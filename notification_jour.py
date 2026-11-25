#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Notification COMMUNE du jour (décision du propriétaire du 25/11/2026) : UNE notification ntfy par jour où des matchs ont été
joués, toutes compétitions confondues : « Nouveaux résultats disponibles en LDC et Ligue 1 ». Le lien ouvre l'accueil, qui
met en avant les derniers résultats.

Sources de l'état d'un jour J :
- coupes : `etat_soirees.json` (ce dépôt) ; la chaîne des coupes (publication.notifier) vérifie la page publique puis REMET
  sa soirée (`notifie: true` = « remise au notificateur ») au lieu de pousser elle-même ; `soirees/index.json` dit quelles
  coupes ont joué ;
- championnats : `etat_championnats.json` du dépôt Camelbaggy/donnees-football (écrit par run_ligues.py --etat), puis
  vérification de la publication : l'`index.json` publié (GitHub Pages) de chaque championnat doit compter autant de matchs
  terminés que l'état.

Règle (`decider`, fonction pure) : une compétition JOUÉE le jour J est prête si elle est complète (tous ses matchs terminés,
reportés exclus) et publiée, ou, restée partielle, à partir de 12 h UTC le lendemain (comme les soirées, soirees.limite_partiel).
Le push part quand TOUTES les compétitions jouées ce jour-là sont prêtes, une seule fois (`etat_notifications.json`). Tant que
l'état d'une famille n'est pas connu (pas encore de passage) et qu'on est avant 13 h UTC le lendemain, on attend ; au-delà, une
famille sans état est réputée sans match ce jour-là (journal [WARN] si le jour était un jour de coupe).

Commandes :
    python notification_jour.py --veille            # jours à notifier MAINTENANT d'après les fichiers PUBLIÉS (battement) : une date par ligne
    python notification_jour.py --date AAAA-MM-JJ   # décide avec les fichiers locaux + état publié des championnats, pousse, enregistre
    python notification_jour.py --test
"""

import argparse
import datetime as dt
import json
import os
import sys
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

FICHIER = "etat_notifications.json"
GARDE_JOURS = 60
HEURE_LIMITE_PARTIEL = 12          # comme soirees.HEURE_LIMITE_PARTIEL
HEURE_ETAT_INCONNU = 13            # au-delà (lendemain, UTC), une famille sans état = aucun match ce jour-là
DEPOT_DONNEES = "https://camelbaggy.github.io/donnees-football/"
RAW_DONNEES = "https://raw.githubusercontent.com/Camelbaggy/donnees-football/main/"
RAW_COUPES = "https://raw.githubusercontent.com/Camelbaggy/coupes-europe/main/"
COUPES = ["ucl", "uel", "uecl"]
LIGUES = ["fl1", "pl", "liga", "sa", "bl"]
COURT = {"ucl": "LDC", "uel": "Ligue Europa", "uecl": "Ligue Conférence", "fl1": "Ligue 1", "pl": "Premier League",
         "liga": "Liga", "sa": "Serie A", "bl": "Bundesliga"}


def _limite(jour: str, heure: int) -> dt.datetime:
    d = dt.date.fromisoformat(jour) + dt.timedelta(days=1)
    return dt.datetime(d.year, d.month, d.day, heure, tzinfo=dt.timezone.utc)


def jour_de_coupe(jour: str) -> bool:
    """Jours du calendrier des soirées (veille.sh) : mardi-jeudi, samedi en mai-juin."""
    d = dt.date.fromisoformat(jour)
    return 1 <= d.weekday() <= 3 or (d.weekday() == 5 and d.month in (5, 6))


def titre_message(comps: List[str]) -> str:
    noms = [COURT[c] for c in COUPES + LIGUES if c in comps]
    if not noms:
        return "Nouveaux résultats disponibles"
    liste = noms[0] if len(noms) == 1 else ", ".join(noms[:-1]) + " et " + noms[-1]
    return f"Nouveaux résultats disponibles en {liste}"


# ------------------------------------------------------------------------------
# Règle (pure)
# ------------------------------------------------------------------------------
def decider(jour: str, maintenant: dt.datetime, etat_soirees: Dict[str, Any], index_soirees: List[Dict[str, Any]],
            etat_ch: Dict[str, Any], publies: Optional[Dict[str, int]] = None,
            deja: Optional[Dict[str, Any]] = None) -> Tuple[str, List[str], str]:
    """(action, compétitions jouées, raison) ; action = « notifier » | « attendre » | « rien ».
    `publies` : {ligue: matchs terminés comptés dans l'index PUBLIÉ du jour} (None = vérification non faite : ignorée).
    `deja` : état des notifications ({jour: {notifie: …}})."""
    if (deja or {}).get(jour, {}).get("notifie"):
        return "rien", [], f"{jour} : déjà notifié"
    partiel_ok = maintenant >= _limite(jour, HEURE_LIMITE_PARTIEL)
    inconnu_ok = maintenant >= _limite(jour, HEURE_ETAT_INCONNU)
    comps: List[str] = []
    attente: List[str] = []

    # Coupes
    s = (etat_soirees or {}).get(jour)
    if s is None:
        if jour_de_coupe(jour) and not inconnu_ok:
            attente.append("coupes : soirée pas encore traitée")
    elif s.get("statut") != "aucun_match" and (s.get("matchs") or 0) > 0:
        ligne = next((l for l in index_soirees or [] if l.get("date") == jour), {})
        jouees = [c for c in COUPES if c in (ligne.get("competitions") or {})] or ["ucl"]
        comps += jouees
        if not s.get("notifie"):
            attente.append(f"coupes : soirée {s.get('statut')} pas encore publiée et vérifiée")

    # Championnats
    e = (etat_ch or {}).get(jour)
    if e is None:
        if not inconnu_ok:
            attente.append("championnats : jour pas encore relevé")
    else:
        for lg in LIGUES:
            l = (e.get("ligues") or {}).get(lg) or {}
            if (l.get("matchs") or 0) <= 0:
                continue
            comps.append(lg)
            if l.get("statut") == "complet":
                if publies is not None and (publies.get(lg) or 0) < (l.get("termines") or 0):
                    attente.append(f"{COURT[lg]} : page publique pas encore à jour")
            elif not partiel_ok:
                attente.append(f"{COURT[lg]} : {l.get('termines', 0)}/{l.get('matchs')} terminé(s)")

    if not comps:
        return ("attendre" if attente else "rien"), [], f"{jour} : " + ("; ".join(attente) if attente else "aucun match")
    if attente:
        return "attendre", comps, f"{jour} : " + "; ".join(attente)
    return "notifier", comps, f"{jour} : prêt ({', '.join(COURT[c] for c in comps)})"


def jours_candidats(maintenant: dt.datetime) -> List[str]:
    """Aujourd'hui et les deux jours précédents (UTC)."""
    return [(maintenant.date() - dt.timedelta(days=k)).isoformat() for k in (2, 1, 0)]


# ------------------------------------------------------------------------------
# Entrées / sorties
# ------------------------------------------------------------------------------
def fetch_json(url: str) -> Optional[Any]:
    sep = "&" if "?" in url else "?"
    try:
        req = urllib.request.Request(f"{url}{sep}t={int(dt.datetime.now().timestamp())}",
                                     headers={"User-Agent": "coupes-europe-notification", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"[WARN] lecture impossible : {url} ({e})")
        return None


def _lire(chemin: str, defaut: Any) -> Any:
    try:
        with open(chemin, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return defaut


def saison_de(jour: str) -> str:
    d = dt.date.fromisoformat(jour)
    a = d.year if d.month >= 7 else d.year - 1
    return f"{a}-{str(a + 1)[2:]}"


def publies_ligues(jour: str, etat_ch: Dict[str, Any], fetch: Callable[[str], Any] = fetch_json) -> Dict[str, int]:
    """Matchs terminés du jour dans l'index PUBLIÉ (GitHub Pages) de chaque championnat joué ce jour-là."""
    out: Dict[str, int] = {}
    for lg, l in ((etat_ch.get(jour) or {}).get("ligues") or {}).items():
        if (l.get("matchs") or 0) <= 0:
            continue
        idx = fetch(f"{DEPOT_DONNEES}championnats/{lg}/{saison_de(jour)}/index.json") or []
        out[lg] = next((int(x.get("termines") or 0) for x in idx if x.get("date") == jour), 0)
    return out


def enregistrer(etat: Dict[str, Any], jour: str, comps: List[str], maintenant: dt.datetime, chemin: str = FICHIER) -> None:
    etat[jour] = {"notifie": True, "competitions": comps, "maj": maintenant.strftime("%Y-%m-%dT%H:%M:%SZ")}
    limite = (maintenant.date() - dt.timedelta(days=GARDE_JOURS)).isoformat()
    for j in [j for j in etat if j < limite]:
        del etat[j]
    tmp = chemin + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(etat.items())), f, ensure_ascii=False, indent=1)
    os.replace(tmp, chemin)


def envoyer_push(comps: List[str]) -> bool:
    import notify
    payload = {"topic": notify.NTFY_TOPIC, "title": "Nouveaux résultats disponibles", "message": titre_message(comps),
               "tags": ["soccer"]}
    url = notify.DASHBOARD_URL
    if url:
        payload["click"] = url
        payload["actions"] = [{"action": "view", "label": "Voir les résultats", "url": url, "clear": True}]
    if not notify.NTFY_TOPIC:
        print("[INFO] NTFY_TOPIC non défini. Simulation du push :")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return False
    return notify._poster(payload)


def notifier(jour: str, maintenant: Optional[dt.datetime] = None, fetch: Callable[[str], Any] = fetch_json,
             envoyer: Optional[Callable[[List[str]], bool]] = None, topic: Optional[str] = None,
             etat_soirees: Optional[Dict[str, Any]] = None, chemin: str = FICHIER) -> int:
    """Décide pour le jour `jour` (fichiers locaux des coupes + état publié des championnats), pousse si tout est prêt,
    enregistre. Retourne 0 (notifié, rien à faire ou en attente) ou 1 (push en échec)."""
    import notify
    maintenant = maintenant or dt.datetime.now(dt.timezone.utc)
    envoyer = envoyer or envoyer_push
    topic = notify.NTFY_TOPIC if topic is None else topic
    deja = _lire(chemin, {})
    es = etat_soirees if etat_soirees is not None else _lire("etat_soirees.json", {})
    idx = _lire("soirees/index.json", [])
    ech = fetch(RAW_DONNEES + "etat_championnats.json")
    if ech is None:
        ech = {}
        print("[WARN] etat_championnats.json illisible : championnats réputés sans état")
    action, comps, raison = decider(jour, maintenant, es, idx, ech, publies_ligues(jour, ech, fetch), deja)
    print(f"[NOTIFICATION] {raison}")
    if action != "notifier":
        return 0
    ok = envoyer(comps)
    if not ok and topic:
        print("[ERREUR] Échec de l'envoi ntfy : le jour reste non notifié (le battement retentera).")
        return 1
    enregistrer(deja, jour, comps, maintenant, chemin)
    print(f"[OK] {jour} notifié : « {titre_message(comps)} »")
    return 0


def veille(maintenant: Optional[dt.datetime] = None, fetch: Callable[[str], Any] = fetch_json) -> List[str]:
    """Jours à notifier maintenant d'après les fichiers PUBLIÉS (lecture seule) ; le workflow notification_jour.yml refait
    la décision complète avant de pousser."""
    maintenant = maintenant or dt.datetime.now(dt.timezone.utc)
    es = fetch(RAW_COUPES + "etat_soirees.json")
    deja = fetch(RAW_COUPES + FICHIER) or {}
    idx = fetch(RAW_COUPES + "soirees/index.json") or []
    ech = fetch(RAW_DONNEES + "etat_championnats.json")
    if es is None or ech is None:
        print("[VEILLE-NOTIF] état illisible : rien à faire", file=sys.stderr)
        return []
    out = []
    for j in jours_candidats(maintenant):
        action, comps, raison = decider(j, maintenant, es, idx, ech, None, deja)
        print(f"[VEILLE-NOTIF] {raison}", file=sys.stderr)   # stdout = les seules dates à notifier
        if action == "notifier":
            out.append(j)
    return out


# ------------------------------------------------------------------------------
# Tests (sans réseau)
# ------------------------------------------------------------------------------
def _test() -> None:
    J = "2026-11-24"   # mardi
    soir = dt.datetime(2026, 11, 24, 23, 30, tzinfo=dt.timezone.utc)
    lendemain = dt.datetime(2026, 11, 25, 12, 30, tzinfo=dt.timezone.utc)
    idx = [{"date": J, "competitions": {"ucl": {"matchs": 9}}}]
    coupe_ok = {J: {"statut": "complet", "notifie": True, "matchs": 9, "termines": 9}}
    coupe_att = {J: {"statut": "complet", "notifie": False, "matchs": 9, "termines": 9}}
    ch_vide = {J: {"ligues": {}}}
    ch_l1 = {J: {"ligues": {"fl1": {"statut": "complet", "matchs": 1, "termines": 1}}}}
    ch_l1_part = {J: {"ligues": {"fl1": {"statut": "partiel", "matchs": 2, "termines": 1}}}}
    # coupes seules, remises : notifier
    a, c, _ = decider(J, soir, coupe_ok, idx, ch_vide)
    assert a == "notifier" and c == ["ucl"], (a, c)
    # coupes pas encore remises : attendre
    assert decider(J, soir, coupe_att, idx, ch_vide)[0] == "attendre"
    # coupes + Ligue 1 complète et publiée : un seul push, deux compétitions
    a, c, _ = decider(J, soir, coupe_ok, idx, ch_l1, {"fl1": 1})
    assert a == "notifier" and c == ["ucl", "fl1"], (a, c)
    assert titre_message(c) == "Nouveaux résultats disponibles en LDC et Ligue 1"
    # Ligue 1 pas encore publiée sur la page : attendre
    assert decider(J, soir, coupe_ok, idx, ch_l1, {"fl1": 0})[0] == "attendre"
    # Ligue 1 partielle : attendre le soir, notifier le lendemain à 12 h UTC
    assert decider(J, soir, coupe_ok, idx, ch_l1_part)[0] == "attendre"
    assert decider(J, lendemain, coupe_ok, idx, ch_l1_part)[0] == "notifier"
    # état des championnats inconnu : attendre jusqu'au lendemain 13 h, puis coupes seules
    assert decider(J, soir, coupe_ok, idx, {})[0] == "attendre"
    a, c, _ = decider(J, dt.datetime(2026, 11, 25, 13, 5, tzinfo=dt.timezone.utc), coupe_ok, idx, {})
    assert a == "notifier" and c == ["ucl"]
    # samedi sans coupe : Ligue 1 seule, l'état des coupes absent n'est pas attendu
    S = "2026-11-21"
    a, c, _ = decider(S, dt.datetime(2026, 11, 21, 23, 0, tzinfo=dt.timezone.utc), {}, [],
                      {S: {"ligues": {"fl1": {"statut": "complet", "matchs": 5, "termines": 5},
                                      "pl": {"statut": "complet", "matchs": 7, "termines": 7}}}})
    assert a == "notifier" and c == ["fl1", "pl"], (a, c)
    assert titre_message(["fl1", "pl", "bl"]) == "Nouveaux résultats disponibles en Ligue 1, Premier League et Bundesliga"
    # aucun match nulle part : rien ; déjà notifié : rien
    assert decider(S, dt.datetime(2026, 11, 21, 23, 0, tzinfo=dt.timezone.utc), {}, [], {S: {"ligues": {}}})[0] == "rien"
    assert decider(J, soir, coupe_ok, idx, ch_vide, None, {J: {"notifie": True}})[0] == "rien"
    # soirée sans match + championnat : seulement le championnat
    a, c, _ = decider(J, soir, {J: {"statut": "aucun_match", "matchs": 0}}, [], ch_l1, {"fl1": 1})
    assert a == "notifier" and c == ["fl1"]

    # notifier() : push unique, enregistré ; échec du push = code 1, rien d'enregistré
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        chemin = os.path.join(d, "n.json")
        envois: List[List[str]] = []
        fetch = lambda url: (ch_l1 if url.endswith("etat_championnats.json") else  # noqa: E731
                             [{"date": J, "termines": 1}] if url.endswith("index.json") else None)
        k = dict(maintenant=soir, fetch=fetch, etat_soirees=coupe_ok, chemin=chemin, topic="t")
        cwd = os.getcwd()
        os.chdir(d)
        try:
            os.makedirs("soirees")
            with open("soirees/index.json", "w") as f:
                json.dump(idx, f)
            assert notifier(J, envoyer=lambda c: envois.append(c) or True, **k) == 0
            assert envois == [["ucl", "fl1"]] and _lire(chemin, {})[J]["notifie"] is True
            assert notifier(J, envoyer=lambda c: envois.append(c) or True, **k) == 0 and len(envois) == 1
            os.remove(chemin)
            assert notifier(J, envoyer=lambda c: False, **k) == 1 and not os.path.exists(chemin)
            # simulation (sans topic) : marqué quand même (sinon le battement relancerait sans fin)
            assert notifier(J, envoyer=lambda c: False, **dict(k, topic="")) == 0 and _lire(chemin, {})[J]["notifie"]
        finally:
            os.chdir(cwd)
    print("[OK] notification_jour : tests passés")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Notification commune du jour (coupes + championnats)")
    ap.add_argument("--date")
    ap.add_argument("--veille", action="store_true")
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    if a.test:
        _test()
    elif a.veille:
        for j in veille():
            print(j)
    elif a.date:
        sys.exit(notifier(a.date))
    else:
        ap.print_help()
