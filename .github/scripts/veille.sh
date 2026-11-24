#!/usr/bin/env bash
# Un passage de veille d'update_dashboard.yml : relance le workflow pour une soirée de Coupes d'Europe non terminée.
# Appelé par battement.yml (toutes les 10 min) et par veille_secours.yml (cron horaire, secours). Mêmes règles :
#   - soirées à traiter = jours de match du calendrier du workflow (mardi, mercredi, jeudi ; samedi en mai-juin) dont l'heure
#     UTC actuelle est >= 22 h 15 le jour même, ou < 13 h UTC le lendemain (le passage de 12 h-13 h envoie la notification d'une
#     soirée restée partielle, voir soirees.py) ;
#   - lit etat_soirees.json publié sur main : soirée à relancer si absente, partielle, ou complète non notifiée ;
#     rien si `aucun_match` ou déjà notifiée ;
#   - rien si un passage d'update_dashboard.yml est en file ou en cours, ou si le dernier a démarré il y a moins de 25 min.
# Relance : gh workflow run update_dashboard.yml --ref main -f mode_test_semaine=false -f date_specifique=<soirée>
# Environnement : REPO, GH_TOKEN. Surcharge facultative (essais) : MAINTENANT (tout ce que `date -d` comprend, ex. @1795640400
# ou 2026-11-24T22:20:00Z). Dépend de gh et jq.
set -u
RACINE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
. "$RACINE/commun.sh"
: "${REPO:?REPO manquant}"
wf=update_dashboard.yml
SEUIL_MIN=${SEUIL_MIN:-25}
maintenant=$(date -u -d "${MAINTENANT:-now}" +%s) || { echo "[VEILLE] MAINTENANT illisible"; exit 0; }
heure=$((10#$(date -u -d "@$maintenant" +%H)))
minute=$((10#$(date -u -d "@$maintenant" +%M)))

# Soirée visée à cet instant (vide = aucune)
jour=""
if [ $((heure * 60 + minute)) -ge $((22 * 60 + 15)) ]; then
  jour=$(date -u -d "@$maintenant" +%F)
elif [ "$heure" -lt 13 ]; then
  jour=$(date -u -d "@$((maintenant - 86400))" +%F)
fi
if [ -z "$jour" ]; then echo "[VEILLE] ${heure} h ${minute} UTC : hors créneau des soirées, rien à faire"; exit 0; fi

# Jour de match ? mardi (2), mercredi (3), jeudi (4) ; samedi (6) en mai-juin (finale de la LDC)
jsem=$(date -u -d "$jour" +%u)
mois=$((10#$(date -u -d "$jour" +%m)))
if ! { [ "$jsem" -ge 2 ] && [ "$jsem" -le 4 ]; } && ! { [ "$jsem" = 6 ] && [ "$mois" -ge 5 ] && [ "$mois" -le 6 ]; }; then
  echo "[VEILLE] $jour (jour ${jsem}) : pas de soirée européenne au calendrier, rien à faire"; exit 0
fi

# État publié sur main (404 = pas encore de fichier = aucune soirée connue ; autre erreur = on ne fait rien par prudence)
err=$(mktemp)
if etat=$(gh api "repos/$REPO/contents/etat_soirees.json?ref=main" -H "Accept: application/vnd.github.raw" 2>"$err"); then
  :
elif grep -q "404" "$err"; then
  etat="{}"
else
  echo "[VEILLE] etat_soirees.json illisible ($(head -c 200 "$err")) : rien à faire"; rm -f "$err"; exit 0
fi
rm -f "$err"
statut=$(printf '%s' "$etat" | jq -r --arg j "$jour" '.[$j].statut // "absent"' 2>/dev/null) || { echo "[VEILLE] etat_soirees.json invalide : rien à faire"; exit 0; }
notifie=$(printf '%s' "$etat" | jq -r --arg j "$jour" '.[$j].notifie // false' 2>/dev/null)
if [ "$statut" = "aucun_match" ]; then echo "[VEILLE] soirée $jour : aucun match, rien à faire"; exit 0; fi
if [ "$notifie" = "true" ]; then echo "[VEILLE] soirée $jour : $statut et déjà notifiée, rien à faire"; exit 0; fi

# Garde-fous : passage en file / en cours, puis ancienneté du dernier démarrage
en_cours=$(nb_en_cours "$wf")
if [ "$en_cours" != "0" ]; then echo "[VEILLE] $wf : un passage est en file ou en cours (ou liste illisible : $en_cours), rien à faire"; exit 0; fi
dernier=$(date_dernier_passage "$wf" createdAt)
if [ "$dernier" = "?" ]; then echo "[VEILLE] $wf : liste des passages illisible, rien à faire"; exit 0; fi
if [ -n "$dernier" ]; then age=$(( (maintenant - $(date -u -d "$dernier" +%s)) / 60 )); else age=999999; fi
if [ "$age" -lt "$SEUIL_MIN" ]; then echo "[VEILLE] soirée $jour ($statut) : dernier passage il y a ${age} min (< ${SEUIL_MIN} min), rien à faire"; exit 0; fi
# contrôle « en file ou en cours » refait juste avant la relance
if [ "$(nb_en_cours "$wf")" != "0" ]; then echo "[VEILLE] $wf : un passage vient d'être lancé, rien à faire"; exit 0; fi
echo "[VEILLE] soirée $jour ($statut, notifiée : $notifie) : dernier passage il y a ${age} min : relance pour cette soirée"
gh workflow run "$wf" --repo "$REPO" --ref "$REF_RELANCE" -f mode_test_semaine=false -f "date_specifique=$jour"
