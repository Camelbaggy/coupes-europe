# Fonctions communes des scripts de veille / battement (à « sourcer », pas à exécuter). Variables : REPO (owner/nom), GH_TOKEN.
# REF_RELANCE : branche sur laquelle on relance les workflows (main ; ne jamais relancer sur une branche d'essai : les
# workflows de collecte y commiteraient des données).
REF_RELANCE=${REF_RELANCE:-main}

# Nombre de passages d'un workflow en file ou en cours (hors « completed »), « ? » si la liste est illisible (par prudence,
# l'appelant ne relance alors rien).
nb_en_cours() {
  local n
  n=$(gh run list --repo "$REPO" --workflow "$1" --limit 20 --json status \
        --jq '[.[] | select(.status != "completed")] | length' 2>/dev/null) || { echo "?"; return; }
  echo "${n:-?}"
}

# Champ de date (createdAt / updatedAt) du dernier passage d'un workflow, vide s'il n'y en a aucun ; « ? » si illisible.
date_dernier_passage() {
  local d
  d=$(gh run list --repo "$REPO" --workflow "$1" --limit 1 --json "$2" --jq ".[0].$2 // \"\"" 2>/dev/null) || { echo "?"; return; }
  echo "$d"
}

# Autres exécutions (hors celle-ci) de battement.yml en file ou en cours.
autres_battements() {
  local n
  n=$(gh run list --repo "$REPO" --workflow battement.yml --limit 20 --json status,databaseId \
        --jq "[.[] | select(.status != \"completed\" and .databaseId != ${GITHUB_RUN_ID:-0})] | length" 2>/dev/null) || { echo "?"; return; }
  echo "${n:-?}"
}
