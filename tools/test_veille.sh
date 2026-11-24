#!/usr/bin/env bash
# Tests locaux de .github/scripts/veille.sh avec un faux `gh` (sans réseau). Usage : bash tools/test_veille.sh
set -u
RAC=$(cd "$(dirname "$0")/.." && pwd)
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
cat > "$T/gh" <<'GH'
#!/usr/bin/env bash
# faux gh : ETAT_JSON (contenu ou "404" ou "ERR"), EN_COURS (nombre), DERNIER (date ISO ou vide), journal des relances dans $JOURNAL
case "$1 $2" in
  "api repos/"*)
    if [ "${ETAT_JSON:-}" = "404" ]; then echo "gh: Not Found (HTTP 404)" >&2; exit 1; fi
    if [ "${ETAT_JSON:-}" = "ERR" ]; then echo "gh: HTTP 502" >&2; exit 1; fi
    printf '%s' "$ETAT_JSON" ;;
  "run list")
    case "$*" in
      *"--jq"*"length"*) echo "${EN_COURS:-0}" ;;
      *) echo "${DERNIER:-}" ;;
    esac ;;
  "workflow run") echo "$*" >> "$JOURNAL" ;;
  *) echo "faux gh : $*" >&2; exit 1 ;;
esac
GH
chmod +x "$T/gh"
export PATH="$T:$PATH" REPO=o/r GH_TOKEN=x JOURNAL="$T/journal"
ech=0
essai() { # nom, attendu (relance|rien), MAINTENANT ; variables d'env déjà posées
  : > "$JOURNAL"
  sortie=$(MAINTENANT="$3" bash "$RAC/.github/scripts/veille.sh" 2>&1)
  if [ -s "$JOURNAL" ]; then r=relance; else r=rien; fi
  if [ "$r" = "$2" ]; then echo "OK   $1 -> $r"; else echo "ECHEC $1 : attendu $2, obtenu $r"; echo "$sortie"; ech=1; fi
  if [ "$2" = relance ] && ! grep -q -- "-f date_specifique=${4:-}" "$JOURNAL"; then echo "ECHEC $1 : mauvaise date ($(cat "$JOURNAL"))"; ech=1; fi
}
# 2026-11-24 = mardi
export ETAT_JSON='{}' EN_COURS=0 DERNIER="2026-11-24T10:00:00Z"
essai "mardi 22h20, soirée non traitée" relance 2026-11-24T22:20:00Z 2026-11-24
ETAT_JSON=404 essai "mardi 22h20, pas de fichier d'état" relance 2026-11-24T22:20:00Z 2026-11-24
ETAT_JSON=ERR essai "état illisible (502)" rien 2026-11-24T22:20:00Z
ETAT_JSON='{"2026-11-24":{"statut":"complet","notifie":true}}' essai "mardi 23h, complet notifiée" rien 2026-11-24T23:00:00Z
ETAT_JSON='{"2026-11-24":{"statut":"complet","notifie":false}}' essai "complet non notifiée" relance 2026-11-24T23:00:00Z 2026-11-24
ETAT_JSON='{"2026-11-24":{"statut":"aucun_match","notifie":false}}' essai "aucun_match" rien 2026-11-24T23:00:00Z
ETAT_JSON='{"2026-11-24":{"statut":"partiel","notifie":false}}' essai "mercredi 3h, soirée de mardi partielle" relance 2026-11-25T03:00:00Z 2026-11-24
ETAT_JSON='{"2026-11-24":{"statut":"partiel","notifie":false}}' essai "mercredi 12h30, partielle (notification forcée)" relance 2026-11-25T12:30:00Z 2026-11-24
ETAT_JSON='{"2026-11-24":{"statut":"partiel","notifie":true}}' essai "mercredi 12h30, partielle déjà notifiée" rien 2026-11-25T12:30:00Z
essai "mercredi 14h (hors créneau)" rien 2026-11-25T14:00:00Z
essai "mercredi 20h (avant 22h15)" rien 2026-11-25T20:00:00Z
essai "mercredi 22h10 (avant 22h15)" rien 2026-11-25T22:10:00Z
essai "mercredi 22h15" relance 2026-11-25T22:15:00Z 2026-11-25
essai "vendredi 22h30" rien 2026-11-27T22:30:00Z
essai "samedi (novembre) 23h" rien 2026-11-28T23:00:00Z
DERNIER="2027-05-29T10:00:00Z" essai "samedi 29 mai 2027 23h (finale)" relance 2027-05-29T23:00:00Z 2027-05-29
essai "dimanche 3h (soirée du samedi de novembre)" rien 2026-11-29T03:00:00Z
essai "vendredi 3h (soirée du jeudi)" relance 2026-11-27T03:00:00Z 2026-11-26
EN_COURS=1 essai "passage en cours" rien 2026-11-24T22:20:00Z
DERNIER="2026-11-24T22:10:00Z" essai "dernier passage il y a 10 min" rien 2026-11-24T22:20:00Z
DERNIER="2026-11-24T21:50:00Z" essai "dernier passage il y a 30 min" relance 2026-11-24T22:20:00Z 2026-11-24
DERNIER="2026-11-24T21:56:00Z" essai "dernier passage il y a 24 min" rien 2026-11-24T22:20:00Z
DERNIER="" essai "aucun passage connu" relance 2026-11-24T22:20:00Z 2026-11-24
[ "$ech" = 0 ] && echo "[OK] veille.sh : tous les tests réussis" || { echo "[ECHEC] veille.sh"; exit 1; }
