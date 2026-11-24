#!/usr/bin/env bash
# Publie data.json et etat_soirees.json (si modifiés) sur la branche courante, avec push robuste.
# Usage : publier.sh [--etat-seul]   (--etat-seul : n'ajoute que etat_soirees.json, pour l'état notifié / les alertes)
# Échec du push après 5 essais : sortie en erreur (le job échoue, aucune notification de résultats).
set -u
git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"
[ "${1:-}" = "--etat-seul" ] || git add data.json
[ -f etat_soirees.json ] && git add etat_soirees.json
if git diff --staged --quiet; then
  if [ -z "$(git log '@{u}..HEAD' --oneline 2>/dev/null)" ]; then
    echo "Aucune modification de data.json ni de etat_soirees.json à publier."
    exit 0
  fi
elif [ "${1:-}" = "--etat-seul" ] || git diff --staged --quiet -- data.json; then
  git commit -m "chore: état des soirées (etat_soirees.json)"
else
  git commit -m "chore: mise à jour automatique des résultats (UEFA)"
fi
# push robuste : main avance (autres passages, commits manuels) ; -X theirs = nos fichiers générés l'emportent
for essai in 1 2 3 4 5; do
  if git push; then exit 0; fi
  echo "Push refusé (essai $essai/5) : rebase sur origin puis nouvelle tentative"
  sleep $(( (RANDOM % 16) + 5 ))
  git pull --rebase -X theirs origin "${GITHUB_REF_NAME}" || { git rebase --abort 2>/dev/null; true; }
done
echo "::error::Échec du push après 5 essais"
exit 1
