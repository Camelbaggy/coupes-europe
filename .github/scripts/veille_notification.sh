#!/usr/bin/env bash
# Un passage de veille de la NOTIFICATION COMMUNE du jour (coupes + championnats, notification_jour.py) : appelé par battement.sh
# (toutes les 10 min) et par veille_secours.yml (cron horaire). Lit les états PUBLIÉS (etat_soirees.json, etat_notifications.json,
# soirees/index.json de ce dépôt ; etat_championnats.json de Camelbaggy/donnees-football) ; pour chaque jour prêt et non notifié
# (hier, avant-hier, aujourd'hui), relance notification_jour.yml, qui refait la décision sur une copie fraîche de main avant
# de pousser (une seule notification par jour). Rien si un passage de notification_jour.yml est en file ou en cours, ou si le
# dernier a démarré il y a moins de 10 min.
# Environnement : REPO, GH_TOKEN. Dépend de gh, python3 (notification_jour.py à la racine du dépôt).
set -u
RACINE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
. "$RACINE/commun.sh"
: "${REPO:?REPO manquant}"
wf=notification_jour.yml
SEUIL_MIN=${SEUIL_NOTIF_MIN:-10}
py=$(command -v python3 || command -v python) || { echo "[VEILLE-NOTIF] python introuvable : rien à faire"; exit 0; }
jours=$("$py" "$RACINE/../../notification_jour.py" --veille | grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' || true)
if [ -z "$jours" ]; then echo "[VEILLE-NOTIF] aucun jour prêt à notifier"; exit 0; fi
en_cours=$(nb_en_cours "$wf")
if [ "$en_cours" != "0" ]; then echo "[VEILLE-NOTIF] $wf en file ou en cours ($en_cours) : rien à faire"; exit 0; fi
dernier=$(date_dernier_passage "$wf" createdAt)
if [ "$dernier" = "?" ]; then echo "[VEILLE-NOTIF] liste des passages illisible : rien à faire"; exit 0; fi
if [ -n "$dernier" ]; then age=$(( ($(date -u +%s) - $(date -u -d "$dernier" +%s)) / 60 )); else age=999999; fi
if [ "$age" -lt "$SEUIL_MIN" ]; then echo "[VEILLE-NOTIF] dernier passage il y a ${age} min (< ${SEUIL_MIN}) : rien à faire"; exit 0; fi
jour=$(printf '%s\n' "$jours" | head -1)
echo "[VEILLE-NOTIF] jour $jour prêt : relance de $wf"
gh workflow run "$wf" --repo "$REPO" --ref "$REF_RELANCE" -f "date=$jour"
