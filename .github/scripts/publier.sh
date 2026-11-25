#!/usr/bin/env bash
# Publie les fichiers générés sur la branche courante, avec push robuste.
# Usage : publier.sh [--etat-seul | --soirees | --clubs]
#   (sans option) data.json + soirees/ + clubs/ + etat_soirees.json  (passage d'une soirée, update_dashboard.yml)
#   --etat-seul   etat_soirees.json seul (état « notifié », alertes)
#   --soirees     soirees/ + data.json (modifié seulement par une soirée plus récente), JAMAIS etat_soirees.json
#                 (reconstitution historique_soirees.yml, rattrapage IA rattrapage_ia.yml : aucune notification)
#   --clubs       clubs/ seul (fiches de club, clubs.yml) : jamais data.json, soirees/ ni etat_soirees.json
# Échec du push après 5 essais : sortie en erreur (le job échoue, aucune notification de résultats).
set -u
mode=${1:-}
git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"

# Après un rebase `-X theirs`, nos fichiers l'emportent en bloc : si un autre passage a ajouté sa ligne à
# soirees/index.json, elle a pu être perdue, et data.json a pu redevenir une soirée plus ancienne. L'index se dérive des
# fichiers, data.json = soirée la plus récente de l'index : on rétablit les deux (idempotent).
reindexer() {
  [ -d soirees ] && [ -f historique.py ] || return 0
  local py
  py=$(command -v python3 || command -v python) || return 0
  "$py" historique.py --reindexer > /dev/null 2>&1 || return 0
  if ! git diff --quiet -- soirees/index.json data.json; then
    git add soirees/index.json data.json && git commit -q --amend --no-edit
  fi
}

case "$mode" in
  --etat-seul) ;;
  --soirees) git add data.json; [ -d soirees ] && git add soirees ;;
  --clubs) [ -d clubs ] && git add clubs ;;
  *) git add data.json; [ -d soirees ] && git add soirees; [ -d clubs ] && git add clubs ;;
esac
if [ "$mode" != "--soirees" ] && [ "$mode" != "--clubs" ]; then [ -f etat_soirees.json ] && git add etat_soirees.json; fi

if git diff --staged --quiet; then
  if [ -z "$(git log '@{u}..HEAD' --oneline 2>/dev/null)" ]; then
    echo "Aucune modification de data.json, soirees/, clubs/ ni etat_soirees.json à publier."
    exit 0
  fi
else
  fichiers=$(git diff --staged --name-only)
  if [ "$mode" = "--clubs" ]; then
    git commit -m "chore: fiches de club (mise à jour hebdomadaire)"
  elif [ "$mode" = "--soirees" ]; then
    git commit -m "chore: historique des soirées (reconstitution ou rattrapage des résumés IA)"
  elif echo "$fichiers" | grep -qx "data.json"; then
    git commit -m "chore: mise à jour automatique des résultats (UEFA)"
  elif echo "$fichiers" | grep -q "^soirees/"; then
    git commit -m "chore: soirée passée mise à jour (soirees/)"
  elif echo "$fichiers" | grep -q "^clubs/"; then
    git commit -m "chore: fiches de club (clubs/)"
  else
    git commit -m "chore: état des soirées (etat_soirees.json)"
  fi
fi
# push robuste : main avance (autres passages, commits manuels) ; -X theirs = nos fichiers générés l'emportent
for essai in 1 2 3 4 5; do
  if git push; then exit 0; fi
  echo "Push refusé (essai $essai/5) : rebase sur origin puis nouvelle tentative"
  sleep $(( (RANDOM % 16) + 5 ))
  if git pull --rebase -X theirs origin "${GITHUB_REF_NAME}"; then reindexer; else git rebase --abort 2>/dev/null; true; fi
done
echo "::error::Échec du push après 5 essais"
exit 1
