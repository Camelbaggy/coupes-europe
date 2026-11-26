#!/usr/bin/env bash
# Battement auto-entretenu (appelé par battement.yml) : toutes les 10 min, un passage de veille.sh (relance d'update_dashboard.yml)
# puis de veille_notification.sh (notification commune du jour, coupes + championnats) et de veille_direct.sh (direct des clubs français).
# Environnement : REPO, GH_TOKEN. Surcharges facultatives : DUREE_MIN (330) ou DUREE_S, PAUSE_S (600).
set -u
RACINE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
. "$RACINE/commun.sh"
: "${REPO:?REPO manquant}"
duree=${DUREE_S:-$(( ${DUREE_MIN:-330} * 60 ))}
pause=${PAUSE_S:-600}

# Garde-fou : un autre battement déjà en cours = on sort aussitôt (la concurrence du workflow sérialise de toute façon)
autres=$(gh run list --repo "$REPO" --workflow battement.yml --status in_progress --json databaseId \
           --jq "[.[] | select(.databaseId != ${GITHUB_RUN_ID:-0})] | length" 2>/dev/null) || autres="?"
if [ "$autres" != "0" ] && [ "$autres" != "?" ]; then
  echo "[BATTEMENT] un autre battement est déjà en cours ($autres) : sortie"; exit 0
fi
[ "$autres" = "?" ] && echo "[BATTEMENT] liste des battements illisible : on continue"

debut=$SECONDS
n=0
while :; do
  n=$((n + 1))
  echo "[BATTEMENT] passage $n, $(( (SECONDS - debut) / 60 )) min écoulées, $(date -u +%H:%M) UTC"
  bash "$RACINE/veille.sh" || echo "[BATTEMENT] veille.sh a échoué (code $?)"
  bash "$RACINE/veille_notification.sh" || echo "[BATTEMENT] veille_notification.sh a échoué (code $?)"
  bash "$RACINE/veille_direct.sh" || echo "[BATTEMENT] veille_direct.sh a échoué (code $?)"
  if [ $(( SECONDS - debut + pause )) -ge "$duree" ]; then break; fi
  sleep "$pause"
done

autres=$(autres_battements)
if [ "$autres" = "0" ]; then
  echo "[BATTEMENT] durée atteinte ($(( (SECONDS - debut) / 60 )) min) : relance de battement.yml puis fin"
  gh workflow run battement.yml --repo "$REPO" --ref "$REF_RELANCE"
else
  echo "[BATTEMENT] durée atteinte : un autre battement est déjà en file ou en cours ($autres), pas de relance, fin"
fi
