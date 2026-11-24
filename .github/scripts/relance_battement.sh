#!/usr/bin/env bash
# Secours (appelé par veille_secours.yml, cron) : relance battement.yml s'il n'est ni en file ni en cours.
# Environnement : REPO, GH_TOKEN.
set -u
RACINE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
. "$RACINE/commun.sh"
: "${REPO:?REPO manquant}"
en_cours=$(nb_en_cours battement.yml)
if [ "$en_cours" != "0" ]; then echo "[VEILLE] battement.yml : en file ou en cours (ou liste illisible : $en_cours), rien à faire"; exit 0; fi
echo "[VEILLE] battement.yml : aucun battement en file ou en cours : relance"
gh workflow run battement.yml --repo "$REPO" --ref "$REF_RELANCE"
