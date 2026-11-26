#!/usr/bin/env bash
# Veille du direct des clubs français (appelée par battement.sh toutes les 10 min et par veille_secours.yml) : si un match
# de Coupe d'Europe d'un club français commence dans moins de 20 min ou est en cours (direct_clubs.py --veille, API UEFA)
# et qu'aucun passage de direct_clubs.yml n'est en file ou en cours : gh workflow run direct_clubs.yml --ref main.
# Environnement : REPO, GH_TOKEN. Dépend de gh, python3.
set -u
RACINE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
. "$RACINE/commun.sh"
: "${REPO:?REPO manquant}"
wf=direct_clubs.yml
(cd "$RACINE/../.." && python3 direct_clubs.py --veille); code=$?
if [ "$code" = "10" ]; then exit 0; fi   # rien à suivre
if [ "$code" != "0" ]; then
  # plantage (ex. module absent du checkout partiel, constaté le 26/11/2026) : jamais confondu avec « rien à suivre »
  echo "::error::[DIRECT] direct_clubs.py --veille a échoué (code $code) : suivi en direct NON vérifié"
  exit 1
fi
en_cours=$(nb_en_cours "$wf")
if [ "$en_cours" != "0" ]; then echo "[DIRECT] $wf : un passage est en file ou en cours (ou liste illisible : $en_cours), rien à faire"; exit 0; fi
echo "[DIRECT] relance de $wf"
gh workflow run "$wf" --repo "$REPO" --ref "$REF_RELANCE"
