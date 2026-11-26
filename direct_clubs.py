#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Alertes EN DIRECT des clubs français en Coupes d'Europe (ntfy) : coup d'envoi, chaque but (et but annulé), fin du match.

Aucune sélection de match : tout match de LDC / LE / LC du jour dont une équipe a `countryCode == "FRA"` (Monaco inclus)
est suivi. Source unique : API UEFA (liste des matchs du jour : statut + score officiel ; événements `GOAL` pour le
buteur, la minute, penalty / csc, comme `uefa.build_events`). Rien n'est inventé : un but dont l'événement UEFA n'est pas
encore publié part sans buteur au bout de `ATTENTE_BUTEUR_S` ; un score qui baisse = « but annulé ».

    python direct_clubs.py --boucle [--duree-min 330] [--pas 30]   # suivi d'une soirée (workflow direct_clubs.yml)
    python direct_clubs.py --veille                                # code 0 si un suivi doit tourner maintenant (battement)
    python direct_clubs.py --test                                  # tests sans réseau

Anti-doublon : chaque notification a un titre unique (il contient le score) ; au démarrage, les titres déjà envoyés sur le
topic depuis 12 h sont relus (`GET <serveur>/<topic>/json?poll=1&since=12h`) : un suivi relancé ne renvoie rien.
Sans NTFY_TOPIC : simulation (affichage).
"""

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Set

import notify
import uefa
from netutil import to_number

COUPES = {"ucl": "Ligue des champions", "uel": "Ligue Europa", "uecl": "Ligue Conférence"}
ATTENTE_BUTEUR_S = 75          # délai max pour attendre l'événement GOAL avant d'envoyer le but sans buteur
AVANCE_VEILLE_MIN = 20         # le suivi démarre 20 min avant le premier coup d'envoi
APRES_COUP_ENVOI_MIN = 200     # au-delà, un match encore « en cours » n'est plus suivi (prolongations + tirs au but compris)
FINAUX = {"FINISHED", "POSTPONED", "CANCELLED", "ABANDONED"}


def nom(t: Dict[str, Any]) -> str:
    return uefa.team_info(t)["name"] or "?"


def francais(m: Dict[str, Any]) -> bool:
    return "FRA" in {((m.get(c) or {}).get("countryCode") or "").upper() for c in ("homeTeam", "awayTeam")}


def score(m: Dict[str, Any]) -> Optional[tuple]:
    t = (m.get("score") or {}).get("total") or {}
    h, a = to_number(t.get("home")), to_number(t.get("away"))
    return None if h is None or a is None else (int(h), int(a))


def coup_envoi(m: Dict[str, Any]) -> Optional[datetime]:
    s = (m.get("kickOffTime") or {}).get("dateTime") or ""
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def ligne_score(m: Dict[str, Any], sc: tuple) -> str:
    return f"{nom(m['homeTeam'])} {sc[0]}-{sc[1]} {nom(m['awayTeam'])}"


def lien(k: str) -> str:
    base = os.environ.get("DASHBOARD_URL", "").strip()
    if not base:
        return ""
    base = base.rsplit("/", 1)[0] + "/" if base.endswith(".html") else base.rstrip("/") + "/"
    return f"{base}?c={k}"


def buts_uefa(m: Dict[str, Any], fetch_events: Callable[[str], List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    hid, aid = str((m.get("homeTeam") or {}).get("id")), str((m.get("awayTeam") or {}).get("id"))
    try:
        return uefa.build_events(fetch_events(str(m["id"])), m, hid, aid)[1]
    except Exception as e:  # jamais bloquant : le but part sans buteur
        print(f"[DIRECT] événements illisibles pour {m.get('id')} : {e}")
        return []


class Suivi:
    """État d'une soirée de suivi (en mémoire) + règles de notification. `envoyer(titre, message, k, prio)` -> bool."""

    def __init__(self, envoyer: Callable[..., bool], deja: Optional[Set[str]] = None):
        self.envoyer = envoyer
        self.deja: Set[str] = set(deja or ())
        self.scores: Dict[str, tuple] = {}        # dernier score notifié (ou constaté au premier relevé d'un match fini)
        self.attente: Dict[str, float] = {}       # but constaté sans événement GOAL : depuis quand
        self.vus: Set[str] = set()

    def _envoi(self, titre: str, message: str, k: str, prio: int = 3) -> None:
        if titre in self.deja:
            return
        if self.envoyer(titre, message, k, prio):
            self.deja.add(titre)

    def passage(self, matchs: Dict[str, List[Dict[str, Any]]], fetch_events, maintenant: float) -> None:
        for k, liste in matchs.items():
            for m in liste:
                if francais(m):
                    self._match(k, m, fetch_events, maintenant)

    def _match(self, k: str, m: Dict[str, Any], fetch_events, maintenant: float) -> None:
        mid, st, sc = str(m.get("id")), (m.get("status") or "").upper(), score(m)
        h, a = nom(m["homeTeam"]), nom(m["awayTeam"])
        comp = COUPES[k]
        premier = mid not in self.vus
        self.vus.add(mid)
        if st in ("UPCOMING", "") or st in ("POSTPONED", "CANCELLED"):
            return
        if premier and st in FINAUX:
            self.scores[mid] = sc or (0, 0)       # déjà fini au premier relevé : rien à annoncer
            return
        if st not in FINAUX:
            self._envoi(f"🟢 Coup d'envoi : {h} - {a}", f"{comp} · c'est parti !", k)
        avant = self.scores.get(mid, (0, 0))
        if sc and sc != avant:
            if sum(sc) < sum(avant):
                self._envoi(f"❌ But annulé : {ligne_score(m, sc)}", f"{comp} · le score revient à {sc[0]}-{sc[1]}", k, 4)
                self.scores[mid] = sc
            else:
                buts = buts_uefa(m, fetch_events)
                depuis = self.attente.setdefault(mid, maintenant)
                if len(buts) < sum(sc) and maintenant - depuis < ATTENTE_BUTEUR_S and st not in FINAUX:
                    return                         # événement GOAL pas encore publié : on attend un peu
                self.attente.pop(mid, None)
                # un message par but nouveau (plusieurs si deux buts entre deux relevés)
                for n in range(sum(avant) + 1, sum(sc) + 1):
                    g = buts[n - 1] if len(buts) >= n else None
                    if g:
                        etape = tuple(int(x) for x in g["score_after"].split("-"))
                        camp = h if g["team"] == "home" else a
                    else:                          # sans événement : seul le dernier score est sûr
                        if n < sum(sc):
                            continue
                        etape, camp = sc, (h if sc[0] > avant[0] else a)
                    fr_marque = ((m["homeTeam"] if camp == h else m["awayTeam"]).get("countryCode") or "").upper() == "FRA"
                    titre = f"⚽ But de {camp} : {h} {etape[0]}-{etape[1]} {a}"
                    if g:
                        detail = f"{g['minute']} {g['scorer']}" + (" (penalty)" if g["kind"] == "pen" else
                                                                   " (contre son camp)" if g["kind"] == "csc" else "")
                        if g.get("assist") and g["kind"] != "csc":
                            detail += f", passe de {g['assist']}"
                    else:
                        detail = "buteur pas encore publié par l'UEFA"
                    self._envoi(titre, f"{detail} · {comp}", k, 4 if fr_marque else 3)
                self.scores[mid] = sc
        if st == "FINISHED":
            sc = sc or (0, 0)
            tab = (m.get("score") or {}).get("penalty") or {}
            ttab = f" (tirs au but {tab.get('home')}-{tab.get('away')})" if tab.get("home") is not None else ""
            self._envoi(f"🏁 Fin du match : {ligne_score(m, sc)}{ttab}", comp, k)
        elif st == "ABANDONED":
            self._envoi(f"⚠️ Match arrêté : {ligne_score(m, sc or (0, 0))}", comp, k)

    def termine(self, matchs: Dict[str, List[Dict[str, Any]]], maintenant: datetime) -> bool:
        """Plus rien à suivre : chaque match français du jour est final ou commencé depuis plus de APRES_COUP_ENVOI_MIN."""
        for liste in matchs.values():
            for m in liste:
                if not francais(m) or (m.get("status") or "").upper() in FINAUX:
                    continue
                ce = coup_envoi(m)
                if ce is None or maintenant < ce + timedelta(minutes=APRES_COUP_ENVOI_MIN):
                    return False
        return True


def matchs_du_jour(jour: str) -> Optional[Dict[str, List[Dict[str, Any]]]]:
    erreurs: List[str] = []
    out = {k: uefa.fetch_matches(k, [jour], erreurs) for k in COUPES}
    return None if len(erreurs) == len(COUPES) else out


def envoyer_ntfy(titre: str, message: str, k: str, prio: int = 3) -> bool:
    payload = {"topic": notify.NTFY_TOPIC, "title": titre, "message": message, "priority": prio, "tags": ["soccer"]}
    if lien(k):
        payload["click"] = lien(k)
    if not notify.NTFY_TOPIC:
        print("[DIRECT] simulation : " + json.dumps(payload, ensure_ascii=False))
        return True
    return notify._poster(payload)


def titres_deja_envoyes() -> Set[str]:
    if not notify.NTFY_TOPIC:
        return set()
    try:
        with urllib.request.urlopen(f"{notify.NTFY_SERVER}/{notify.NTFY_TOPIC}/json?poll=1&since=12h", timeout=20) as r:
            lignes = r.read().decode("utf-8").splitlines()
        return {json.loads(x).get("title", "") for x in lignes if x.strip()}
    except Exception as e:
        print(f"[DIRECT] relecture du topic impossible ({e}) : doublons possibles après une relance")
        return set()


def a_suivre(matchs: Dict[str, List[Dict[str, Any]]], maintenant: datetime) -> bool:
    """Un match français du jour commence dans moins de AVANCE_VEILLE_MIN, ou a commencé et n'est pas final."""
    for liste in matchs.values():
        for m in liste:
            ce = coup_envoi(m)
            if not francais(m) or ce is None or (m.get("status") or "").upper() in FINAUX:
                continue
            if ce - timedelta(minutes=AVANCE_VEILLE_MIN) <= maintenant < ce + timedelta(minutes=APRES_COUP_ENVOI_MIN):
                return True
    return False


def boucle(duree_min: float, pas: float) -> None:
    suivi = Suivi(envoyer_ntfy, titres_deja_envoyes())
    print(f"[DIRECT] {len(suivi.deja)} titre(s) déjà envoyés sur le topic depuis 12 h")
    fin = time.time() + duree_min * 60
    while time.time() < fin:
        now = datetime.now(timezone.utc)
        matchs = matchs_du_jour(now.date().isoformat())
        if matchs is None:
            print(f"[DIRECT] {now:%H:%M:%S} liste UEFA illisible")
        else:
            fr = [m for l in matchs.values() for m in l if francais(m)]
            print(f"[DIRECT] {now:%H:%M:%S} " + " | ".join(
                f"{nom(m['homeTeam'])}-{nom(m['awayTeam'])} {m.get('status')} {score(m)}" for m in fr) or "aucun match français")
            suivi.passage(matchs, uefa.fetch_events, time.time())
            if suivi.termine(matchs, now):
                print("[DIRECT] tous les matchs français du jour sont terminés : fin du suivi")
                return
            if not a_suivre(matchs, now):
                print("[DIRECT] aucun match français en cours ni imminent : fin (la veille relancera avant le prochain)")
                return
        time.sleep(pas)
    print("[DIRECT] durée atteinte : fin (la veille relance un suivi si un match est encore en cours)")


# ------------------------------------------------------------------------------------------------------------------
def _tests() -> None:
    def eq(t, st, sc=None, ko="2026-11-26T17:45:00Z", mid="1", pays=("FRA", "BUL"), tab=None):
        m = {"id": mid, "status": st, "kickOffTime": {"dateTime": ko},
             "homeTeam": {"id": "10", "internationalName": "Marseille", "countryCode": pays[0]},
             "awayTeam": {"id": "20", "internationalName": "Levski Sofia", "countryCode": pays[1]},
             "playerEvents": {"scorers": []}}
        if sc:
            m["score"] = {"total": {"home": sc[0], "away": sc[1]}}
            if tab:
                m["score"]["penalty"] = {"home": tab[0], "away": tab[1]}
        return m

    def but(eid, team, minute, joueur, gtype="SCORED"):
        return {"id": eid, "type": "GOAL", "phase": "FIRST_HALF", "time": {"minute": minute},
                "primaryActor": {"team": {"id": team}, "person": {"internationalName": joueur}}}

    envois: List[tuple] = []
    s = Suivi(lambda t, msg, k, p: envois.append((t, msg, p)) or True)
    evs: List[Dict[str, Any]] = []
    fe = lambda mid: evs
    s.passage({"uel": [eq(0, "UPCOMING")]}, fe, 0)
    assert envois == []
    s.passage({"uel": [eq(0, "LIVE", (0, 0))]}, fe, 10)
    assert envois[-1][0] == "🟢 Coup d'envoi : Marseille - Levski Sofia", envois
    s.passage({"uel": [eq(0, "LIVE", (0, 0))]}, fe, 20)
    assert len(envois) == 1                                   # pas de doublon
    # but sans événement : on attend, puis l'événement arrive
    s.passage({"uel": [eq(0, "LIVE", (1, 0))]}, fe, 30)
    assert len(envois) == 1
    evs.append(but("g1", "10", 23, "Greenwood"))
    s.passage({"uel": [eq(0, "LIVE", (1, 0))]}, fe, 60)
    assert envois[-1][0] == "⚽ But de Marseille : Marseille 1-0 Levski Sofia" and "23' Greenwood" in envois[-1][1] \
        and envois[-1][2] == 4, envois[-1]
    # but adverse, événement jamais publié : envoyé sans buteur après l'attente
    s.passage({"uel": [eq(0, "LIVE", (1, 1))]}, fe, 100)
    assert len(envois) == 2
    s.passage({"uel": [eq(0, "LIVE", (1, 1))]}, fe, 100 + ATTENTE_BUTEUR_S)
    assert envois[-1][0] == "⚽ But de Levski Sofia : Marseille 1-1 Levski Sofia" and "pas encore publié" in envois[-1][1]
    # but annulé
    s.passage({"uel": [eq(0, "LIVE", (1, 0))]}, fe, 400)
    assert envois[-1][0] == "❌ But annulé : Marseille 1-0 Levski Sofia"
    # deux buts d'un coup avec événements -> deux messages, scores intermédiaires justes
    evs[:] = [but("g1", "10", 23, "Greenwood"), but("g2", "10", 70, "Gouiri"), but("g3", "20", 75, "Tsonev")]
    s.passage({"uel": [eq(0, "LIVE", (2, 1))]}, fe, 500)
    assert [e[0] for e in envois[-2:]] == ["⚽ But de Marseille : Marseille 2-0 Levski Sofia",
                                           "⚽ But de Levski Sofia : Marseille 2-1 Levski Sofia"], envois[-2:]
    s.passage({"uel": [eq(0, "FINISHED", (2, 1))]}, fe, 600)
    assert envois[-1][0] == "🏁 Fin du match : Marseille 2-1 Levski Sofia"
    n = len(envois)
    s.passage({"uel": [eq(0, "FINISHED", (2, 1))]}, fe, 700)
    assert len(envois) == n
    # match sans club français : ignoré ; match déjà fini au premier relevé : rien
    s2 = Suivi(lambda *a: envois.append(a) or True)
    s2.passage({"ucl": [eq(0, "LIVE", (1, 0), pays=("ITA", "GER"), mid="2"), eq(0, "FINISHED", (3, 0), mid="3")]}, fe, 0)
    assert len(envois) == n
    # relance : titres déjà envoyés relus -> rien
    s3 = Suivi(lambda *a: envois.append(a) or True, {"🟢 Coup d'envoi : Marseille - Levski Sofia"})
    s3.passage({"uel": [eq(0, "LIVE", (0, 0), mid="4")]}, fe, 0)
    assert len(envois) == n
    # tirs au but dans le titre de fin
    s4 = Suivi(lambda t, msg, k, p: envois.append((t, msg, p)) or True)
    s4.passage({"uel": [eq(0, "LIVE", (1, 1), mid="5")]}, lambda mid: [but("a", "10", 10, "X"), but("b", "20", 20, "Y")], 0)
    s4.passage({"uel": [eq(0, "FINISHED", (1, 1), mid="5", tab=(4, 3))]}, fe, 10)
    assert envois[-1][0] == "🏁 Fin du match : Marseille 1-1 Levski Sofia (tirs au but 4-3)", envois[-1]
    # veille / fin du suivi
    ko = datetime(2026, 11, 26, 17, 45, tzinfo=timezone.utc)
    j = {"uel": [eq(0, "UPCOMING")]}
    assert not a_suivre(j, ko - timedelta(minutes=30)) and a_suivre(j, ko - timedelta(minutes=10))
    assert not s.termine(j, ko + timedelta(minutes=60)) and s.termine({"uel": [eq(0, "FINISHED", (1, 0))]}, ko)
    assert s.termine(j, ko + timedelta(minutes=APRES_COUP_ENVOI_MIN + 1))
    assert not a_suivre({"uel": [eq(0, "UPCOMING", pays=("ITA", "GER"))]}, ko)
    print("[TEST] direct_clubs : OK")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--boucle", action="store_true")
    ap.add_argument("--veille", action="store_true")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--duree-min", type=float, default=330)
    ap.add_argument("--pas", type=float, default=30)
    a = ap.parse_args()
    if a.test:
        _tests()
    elif a.veille:
        now = datetime.now(timezone.utc)
        matchs = matchs_du_jour(now.date().isoformat())
        ok = bool(matchs) and a_suivre(matchs, now)
        print(f"[DIRECT] veille {now:%H:%M} UTC : {'suivi à lancer' if ok else 'rien à suivre'}")
        sys.exit(0 if ok else 1)
    elif a.boucle:
        boucle(a.duree_min, a.pas)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
