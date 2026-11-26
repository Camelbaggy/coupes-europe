#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Alertes EN DIRECT des clubs français en Coupes d'Europe ET de l'équipe de France (ntfy) : coup d'envoi, chaque but (et but
annulé), fin du match.

Aucune sélection de match : tout match du jour dont une équipe a `countryCode == "FRA"` (Monaco inclus ; l'équipe de France aussi)
est suivi. Compétitions (décision du propriétaire du 26/11/2026) :
- UEFA (liste des matchs du jour : statut + score officiel ; événements `GOAL` pour le buteur, la minute, penalty / csc, comme
  `uefa.build_events`) : LDC `ucl`, Ligue Europa `uel`, Ligue Conférence `uecl`, et les sélections : Euro `euro` (3, éliminatoires
  compris), Ligue des nations `ldn` (2014), Coupe du monde `cdm` (17, éliminatoires ET phase finale) ;
- ESPN (scoreboard du jour + `summary` pour les buts) : Coupe du monde des clubs `cdmc` et Coupe intercontinentale `ci` (finale du
  PSG le 16/12/2026), SANS données UEFA : chaque événement ESPN est converti au format UEFA attendu par `Suivi`
  (`espn_vers_uefa`, `buts_espn` ; id `espn-<id>`) ; le club français est identifié par la liste FIFA de l'édition.
Rien n'est inventé : un but dont l'événement n'est pas encore publié part sans buteur au bout de `ATTENTE_BUTEUR_S` ; un score qui
baisse = « but annulé ».

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

import internationales
import ligues
import notify
import uefa
from netutil import fetch_json, to_number

COUPES = {"ucl": "Ligue des champions", "uel": "Ligue Europa", "uecl": "Ligue Conférence"}   # API UEFA, ids de uefa.COMPETITION_IDS
SELECTIONS_UEFA = {"euro": 3, "ldn": 2014, "cdm": 17}      # API UEFA, requête dédiée (uefa.COMPETITION_IDS n'est PAS modifié)
COMPETITIONS_ESPN = ["cdmc", "ci"]                         # sans données UEFA : ESPN (scoreboard + summary) + liste FIFA
LIBELLES = {**COUPES, "euro": "Euro", "ldn": "Ligue des nations", "cdm": "Coupe du monde",
            "cdmc": "Coupe du monde des clubs", "ci": "Coupe intercontinentale"}   # libellé affiché ET clé du lien `?c=<clé>`
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


def buts_uefa(m: Dict[str, Any], fetch_events: Callable[[str], List[Dict[str, Any]]],
              fetch_resume: Optional[Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]] = None) -> List[Dict[str, Any]]:
    """Buts du match au format de `uefa.build_events(...)[1]` : événements UEFA, ou résumé ESPN (id `espn-…`, voir `buts_espn`)."""
    if str(m.get("id")).startswith("espn-"):
        return buts_espn(m, fetch_resume or resume_espn)
    hid, aid = str((m.get("homeTeam") or {}).get("id")), str((m.get("awayTeam") or {}).get("id"))
    try:
        return uefa.build_events(fetch_events(str(m["id"])), m, hid, aid)[1]
    except Exception as e:  # jamais bloquant : le but part sans buteur
        print(f"[DIRECT] événements illisibles pour {m.get('id')} : {e}")
        return []


# ------------------------------------------------------------------------------
# ESPN -> format UEFA (Coupe du monde des clubs, Coupe intercontinentale)
# ------------------------------------------------------------------------------
def statut_espn(ev: Dict[str, Any]) -> str:
    """Statut UEFA d'un événement ESPN : UPCOMING / FINISHED / POSTPONED / CANCELLED / ABANDONED, sinon LIVE (toute autre valeur
    de l'UEFA hors ces cinq-là est « en direct » pour `Suivi`)."""
    t = (ev.get("status") or {}).get("type") or {}
    nom = t.get("name") or ""
    if nom == "STATUS_POSTPONED":
        return "POSTPONED"
    if nom in ("STATUS_CANCELED", "STATUS_CANCELLED"):
        return "CANCELLED"
    if nom == "STATUS_ABANDONED":
        return "ABANDONED"
    if t.get("completed"):
        return "FINISHED"
    return "UPCOMING" if t.get("state") == "pre" or nom == "STATUS_SCHEDULED" else "LIVE"


def espn_vers_uefa(comp: str, ev: Dict[str, Any], liste: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Événement du scoreboard ESPN -> dictionnaire au format de la liste de matchs UEFA lu par `Suivi` : `id` `espn-<id>`,
    `homeTeam` / `awayTeam` (`id` ESPN, `internationalName`, `countryCode` : FRA pour un club français reconnu par la liste FIFA de
    l'édition, `internationales.match_espn`), `status`, `score.total` (+ `score.penalty` si tirs au but), `kickOffTime`."""
    m = internationales.match_espn(comp, ev, liste)
    cs = {c.get("homeAway"): c for c in (ev.get("competitions") or [{}])[0].get("competitors") or []}
    h, a = m["home_team"], m["away_team"]
    tab = {k: (cs.get(c) or {}).get("shootoutScore") for k, c in (("home", "home"), ("away", "away"))}
    debut = ev.get("date") or ""
    out: Dict[str, Any] = {
        "id": f"espn-{m['espn_id']}", "status": statut_espn(ev),
        "kickOffTime": {"date": debut[:10], "dateTime": debut},
        "homeTeam": {"id": h["espn_id"], "internationalName": h["name"], "countryCode": h.get("country") or ""},
        "awayTeam": {"id": a["espn_id"], "internationalName": a["name"], "countryCode": a.get("country") or ""},
        "score": {"total": {"home": h["score"], "away": a["score"]}},
        "_espn": {"comp": comp, "event": m["espn_id"]}}
    if tab["home"] is not None and tab["away"] is not None:
        out["score"]["penalty"] = tab
    return out


def buts_depuis_resume(resume: Dict[str, Any], home_id: str, away_id: str) -> List[Dict[str, Any]]:
    """Buts d'un `summary` ESPN (`keyEvents`) au format de `uefa.build_events(...)[1]` : `minute` (« 45'+2 »), `scorer`, `assist`,
    `team` (home / away ; contre son camp : l'équipe qui BÉNÉFICIE du but, comme ESPN), `kind` (pen / csc / ""), `score_after`.
    Ordre chronologique (période, horloge) ; les tirs au but (`shootout`) ne sont jamais des buts du match."""
    evs = sorted(enumerate(resume.get("keyEvents") or []),
                 key=lambda x: (int((x[1].get("period") or {}).get("number") or 0),
                                float((x[1].get("clock") or {}).get("value") or 0), x[0]))
    buts: List[Dict[str, Any]] = []
    h = a = 0
    for _, k in evs:
        texte = (k.get("type") or {}).get("text") or ""
        if k.get("shootout") or not (texte in ligues.BUTS or (k.get("scoringPlay") and texte.startswith("Goal"))):
            continue
        tid = str((k.get("team") or {}).get("id") or "")
        side = "home" if tid == home_id else "away" if tid == away_id else None
        if side is None:
            continue
        csc = bool(k.get("ownGoal")) or texte == "Own Goal"
        pen = bool(k.get("penaltyKick")) or texte in ("Penalty - Scored", "Goal - Penalty")
        noms = [((p.get("athlete") or {}).get("displayName") or "").strip() for p in k.get("participants") or []]
        h, a = (h + 1, a) if side == "home" else (h, a + 1)
        buts.append({"minute": ligues._minute(k)[0], "scorer": noms[0] if noms and noms[0] else "—",
                     "assist": noms[1] if len(noms) > 1 and noms[1] and not csc else None, "team": side,
                     "kind": "csc" if csc else "pen" if pen else "", "score_after": f"{h}-{a}"})
    return buts


def resume_espn(m: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    comp = (m.get("_espn") or {}).get("comp")
    if comp not in internationales.COMPETITIONS:
        return None
    data, st = ligues._get(f"{ligues.SITE_WEB}/{internationales.COMPETITIONS[comp]['espn']}/summary?event="
                           f"{str(m['id']).replace('espn-', '')}")
    return data if st == "ok" and isinstance(data, dict) else None


def buts_espn(m: Dict[str, Any], fetch_resume: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    try:
        resume = fetch_resume(m)
        if resume is None:
            print(f"[DIRECT] résumé ESPN illisible pour {m.get('id')}")
            return []
        return buts_depuis_resume(resume, str((m.get("homeTeam") or {}).get("id")), str((m.get("awayTeam") or {}).get("id")))
    except Exception as e:  # jamais bloquant : le but part sans buteur
        print(f"[DIRECT] résumé ESPN inutilisable pour {m.get('id')} : {e}")
        return []


class Suivi:
    """État d'une soirée de suivi (en mémoire) + règles de notification. `envoyer(titre, message, k, prio)` -> bool."""

    def __init__(self, envoyer: Callable[..., bool], deja: Optional[Set[str]] = None,
                 fetch_resume: Optional[Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]] = None):
        self.envoyer = envoyer
        self.fetch_resume = fetch_resume          # lecture du summary ESPN (matchs `espn-…`) ; resume_espn par défaut
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
        comp = LIBELLES[k]
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
                buts = buts_uefa(m, fetch_events, self.fetch_resume)
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


def fetch_uefa_jour(cle: str, jour: str, erreurs: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Matchs UEFA d'une compétition de sélections (`SELECTIONS_UEFA`) pour le jour UTC, comme `uefa.fetch_matches` (liste illisible :
    [] et `cle` ajouté à `erreurs`)."""
    d_to = (datetime.fromisoformat(jour) + timedelta(days=1)).date().isoformat()
    data = fetch_json(f"https://match.uefa.com/v5/matches?competitionId={SELECTIONS_UEFA[cle]}&fromDate={jour}&toDate={d_to}"
                      f"&offset=0&limit=200&order=ASC&language=FR")
    if data is None and erreurs is not None:
        erreurs.append(cle)
    return [m for m in (data or []) if ((m.get("kickOffTime") or {}).get("date") or "")[:10] == jour]


_LISTES_FIFA: Dict[tuple, tuple] = {}     # (comp, édition) -> (liste FIFA ou None, instant de la lecture)
RELIRE_LISTE_FIFA_S = 300                 # une liste illisible est relue au plus toutes les 5 min


def liste_fifa(comp: str, edition: int, maintenant: Optional[float] = None) -> Optional[List[Dict[str, Any]]]:
    """Liste FIFA de l'édition (identifie le club français, noms français) : lue une fois par processus si elle est lisible."""
    t = time.time() if maintenant is None else maintenant
    c = _LISTES_FIFA.get((comp, edition))
    if c and (c[0] is not None or t - c[1] < RELIRE_LISTE_FIFA_S):
        return c[0]
    liste = internationales.liste_edition(comp, edition)
    _LISTES_FIFA[(comp, edition)] = (liste, t)
    return liste


def matchs_espn_jour(comp: str, jour: str, maintenant: Optional[datetime] = None, erreurs: Optional[List[str]] = None,
                     scoreboard: Callable[[str, str], Any] = ligues.scoreboard,
                     liste_fn: Callable[[str, int], Optional[List[Dict[str, Any]]]] = liste_fifa) -> List[Dict[str, Any]]:
    """Matchs ESPN d'une compétition de clubs du monde (`COMPETITIONS_ESPN`) dont le coup d'envoi tombe le jour UTC `jour`, au format
    UEFA. Le scoreboard ESPN est rangé par jour de l'Est américain : la veille est lue aussi avant 6 h UTC. La liste FIFA n'est lue
    que s'il y a un match ; illisible : les clubs français ne sont pas reconnus (journal)."""
    maintenant = maintenant or datetime.now(timezone.utc)
    jours = [jour] + ([(datetime.fromisoformat(jour) - timedelta(days=1)).date().isoformat()] if maintenant.hour < 6 else [])
    evs: Dict[str, Dict[str, Any]] = {}
    lecture_ok = False
    for j in jours:
        liste_ev, st = scoreboard(internationales.cle_ligue(comp), j)
        lecture_ok |= st == "ok"
        for ev in liste_ev:
            if (ev.get("date") or "")[:10] == jour:
                evs[str(ev.get("id"))] = ev
    if not lecture_ok and erreurs is not None:
        erreurs.append(comp)
    if not evs:
        return []
    liste = liste_fn(comp, internationales.edition_de(comp, jour))
    if liste is None:
        print(f"[DIRECT] liste FIFA de {comp} illisible : les clubs français ne sont pas reconnus ce passage")
        liste = []
    return [espn_vers_uefa(comp, ev, liste) for ev in evs.values()]


def matchs_du_jour(jour: str, maintenant: Optional[datetime] = None) -> Optional[Dict[str, List[Dict[str, Any]]]]:
    """{clé de compétition: matchs du jour (UTC) au format UEFA} pour les coupes d'Europe, les sélections (UEFA) et les compétitions
    de clubs du monde (ESPN) ; None si TOUTES les sources sont illisibles."""
    erreurs: List[str] = []
    out: Dict[str, List[Dict[str, Any]]] = {k: uefa.fetch_matches(k, [jour], erreurs) for k in COUPES}
    for k in SELECTIONS_UEFA:
        out[k] = fetch_uefa_jour(k, jour, erreurs)
    for k in COMPETITIONS_ESPN:
        try:
            out[k] = matchs_espn_jour(k, jour, maintenant, erreurs)
        except Exception as e:   # jamais bloquant pour les autres compétitions
            print(f"[DIRECT] {k} : lecture ESPN en erreur ({e})")
            out[k] = []
            erreurs.append(k)
    return None if len(erreurs) == len(out) else out


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
        matchs = matchs_du_jour(now.date().isoformat(), now)
        if matchs is None:
            print(f"[DIRECT] {now:%H:%M:%S} liste UEFA illisible")
        else:
            fr = [m for l in matchs.values() for m in l if francais(m)]
            print(f"[DIRECT] {now:%H:%M:%S} " + (" | ".join(
                f"{nom(m['homeTeam'])}-{nom(m['awayTeam'])} {m.get('status')} {score(m)}" for m in fr) or "aucun match français"))
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
    # --- l'équipe de France : compétitions UEFA de sélections (ldn, euro, cdm) ---
    def sel(h, a, st, sc=None, mid="9", ko="2026-11-15T19:45:00Z"):
        m = {"id": mid, "status": st, "kickOffTime": {"dateTime": ko},
             "homeTeam": {"id": "50", "internationalName": h[0], "countryCode": h[1]},
             "awayTeam": {"id": "60", "internationalName": a[0], "countryCode": a[1]}, "playerEvents": {"scorers": []}}
        if sc:
            m["score"] = {"total": {"home": sc[0], "away": sc[1]}}
        return m
    envs: List[tuple] = []
    sn = Suivi(lambda t, msg, k, p: envs.append((t, msg, k, p)) or True)
    sn.passage({"ldn": [sel(("France", "FRA"), ("Turquie", "TUR"), "LIVE", (0, 0)),
                        sel(("Espagne", "ESP"), ("Angleterre", "ENG"), "LIVE", (0, 0), mid="10")]}, fe, 0)
    assert envs == [("🟢 Coup d'envoi : France - Turquie", "Ligue des nations · c'est parti !", "ldn", 3)], envs   # sans la France : ignoré
    evs[:] = [but("n1", "50", 12, "Mbappé")]
    sn.passage({"ldn": [sel(("France", "FRA"), ("Turquie", "TUR"), "LIVE", (1, 0))]}, fe, 10)
    assert envs[-1][0] == "⚽ But de France : France 1-0 Turquie" and envs[-1][2] == "ldn" and envs[-1][3] == 4, envs[-1]
    sn.passage({"euro": [sel(("Portugal", "POR"), ("France", "FRA"), "FINISHED", (0, 2), mid="11")]}, fe, 20)   # fini au 1er relevé : rien
    assert len(envs) == 2
    assert francais(sel(("France", "FRA"), ("Turquie", "TUR"), "LIVE")) and not francais(sel(("Italie", "ITA"), ("Turquie", "TUR"), "LIVE"))

    # --- ESPN (Coupe du monde des clubs / Coupe intercontinentale / sélections sans UEFA) : fixtures RÉELLES allégées ---
    def fixture(nom):
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools", "fixtures", "espn_direct", nom), encoding="utf-8") as f:
            return json.load(f)
    fifa = internationales.entree_fifa("cdmc", fixture("fifa_cdmc_2025_finale.json"))
    liste_cwc = [fifa]
    ev_cwc = fixture("scoreboard_cwc_20250713.json")["events"][0]
    mc = espn_vers_uefa("cdmc", ev_cwc, liste_cwc)
    assert mc["id"] == "espn-735958" and mc["status"] == "FINISHED" and mc["score"]["total"] == {"home": 3, "away": 0}
    assert (nom(mc["homeTeam"]), mc["homeTeam"]["countryCode"], nom(mc["awayTeam"]), mc["awayTeam"]["countryCode"]) == \
        ("Chelsea FC", "ENG", "Paris Saint-Germain", "FRA"), mc
    assert francais(mc) and coup_envoi(mc) == datetime(2025, 7, 13, 19, 0, tzinfo=timezone.utc) and "penalty" not in mc["score"]
    assert mc["kickOffTime"]["date"] == "2025-07-13" and score(mc) == (3, 0)
    # liste FIFA illisible : le club n'est pas reconnu français (jamais deviné)
    assert not francais(espn_vers_uefa("cdmc", ev_cwc, []))
    # statuts ESPN
    st = lambda nom_, etat, fini: statut_espn({"status": {"type": {"name": nom_, "state": etat, "completed": fini}}})  # noqa: E731
    assert [st("STATUS_SCHEDULED", "pre", False), st("STATUS_FIRST_HALF", "in", False), st("STATUS_HALFTIME", "in", False),
            st("STATUS_FULL_TIME", "post", True), st("STATUS_FINAL_PEN", "post", True), st("STATUS_FINAL_AET", "post", True),
            st("STATUS_POSTPONED", "post", False), st("STATUS_CANCELED", "post", False), st("STATUS_ABANDONED", "post", False)] == \
        ["UPCOMING", "LIVE", "LIVE", "FINISHED", "FINISHED", "FINISHED", "POSTPONED", "CANCELLED", "ABANDONED"]
    # buts : résumé de la finale (3 buts de Chelsea, minutes, passeurs, score après chaque but)
    sum_cwc = fixture("summary_cwc_735958.json")
    bs = buts_depuis_resume(sum_cwc, "363", "160")
    assert [(b["minute"], b["scorer"], b["assist"], b["team"], b["kind"], b["score_after"]) for b in bs] == [
        ("22'", "Cole Palmer", "Malo Gusto", "home", "", "1-0"), ("30'", "Cole Palmer", "Levi Colwill", "home", "", "2-0"),
        ("43'", "João Pedro", "Cole Palmer", "home", "", "3-0")], bs
    assert buts_depuis_resume(sum_cwc, "1", "2") == []                                   # équipes inconnues : aucun but attribué
    # contre son camp : l'équipe qui BÉNÉFICIE (Espagne, domicile), pas de passeur (Euro 2024, Espagne-Italie)
    og = buts_depuis_resume(fixture("summary_euro_690588.json"), "164", "162")
    assert [(b["minute"], b["scorer"], b["assist"], b["team"], b["kind"], b["score_after"]) for b in og] == [
        ("55'", "Riccardo Calafiori", None, "home", "csc", "1-0")], og
    # ordre (période, horloge) ; temps additionnel ; tirs au but jamais comptés ; penalty
    def ke(period, valeur, aff, equipe, texte="Goal", **kw):
        return {"type": {"text": texte}, "period": {"number": period}, "clock": {"value": valeur, "displayValue": aff},
                "scoringPlay": True, "team": {"id": equipe}, "participants": [{"athlete": {"displayName": "Buteur " + aff}}], **kw}
    ordre = buts_depuis_resume({"keyEvents": [ke(2, 2700.0, "45'", "2"), ke(1, 2700.0, "45'+3'", "1"),
                                              ke(2, 5400.0, "90'+2'", "1", "Penalty - Scored"),
                                              ke(5, 7200.0, "120'", "1", shootout=True)]}, "1", "2")
    assert [(b["minute"], b["team"], b["kind"], b["score_after"]) for b in ordre] == [
        ("45'+3", "home", "", "1-0"), ("45'", "away", "", "1-1"), ("90'+2", "home", "pen", "2-1")], ordre
    # tirs au but : score.penalty depuis `shootoutScore` (Euro 2024, Portugal-France 0-0, 3-5), France reconnue par le code
    mt = espn_vers_uefa("euro", fixture("scoreboard_euro_20240705.json")["events"][0], [])
    assert mt["score"] == {"total": {"home": 0, "away": 0}, "penalty": {"home": 3, "away": 5}} and francais(mt), mt
    # Suivi de bout en bout sur un match ESPN : coup d'envoi, buts avec buteur / passeur lus dans le résumé, fin ; lien = clé de la compétition
    def live(sc, st="LIVE"):
        return {**mc, "status": st, "score": {"total": {"home": sc[0], "away": sc[1]}}}
    envc: List[tuple] = []
    se = Suivi(lambda t, msg, k, p: envc.append((t, msg, k, p)) or True, fetch_resume=lambda m: sum_cwc)
    se.passage({"cdmc": [live((0, 0))]}, fe, 0)
    assert envc[-1][:3] == ("🟢 Coup d'envoi : Chelsea FC - Paris Saint-Germain", "Coupe du monde des clubs · c'est parti !", "cdmc"), envc[-1]
    se.passage({"cdmc": [live((1, 0))]}, fe, 10)
    assert envc[-1] == ("⚽ But de Chelsea FC : Chelsea FC 1-0 Paris Saint-Germain",
                        "22' Cole Palmer, passe de Malo Gusto · Coupe du monde des clubs", "cdmc", 3), envc[-1]
    se.passage({"cdmc": [live((3, 0))]}, fe, 20)                                          # deux buts entre deux relevés
    assert [e[0] for e in envc[-2:]] == ["⚽ But de Chelsea FC : Chelsea FC 2-0 Paris Saint-Germain",
                                         "⚽ But de Chelsea FC : Chelsea FC 3-0 Paris Saint-Germain"], envc[-2:]
    se.passage({"cdmc": [live((3, 0), "FINISHED")]}, fe, 30)
    assert envc[-1][0] == "🏁 Fin du match : Chelsea FC 3-0 Paris Saint-Germain"
    # résumé ESPN illisible : le but part quand même, sans buteur, après l'attente ; résumé avec un but en retard : on attend
    envr: List[tuple] = []
    sr = Suivi(lambda t, msg, k, p: envr.append((t, msg, k, p)) or True, fetch_resume=lambda m: None)
    sr.passage({"ci": [live((0, 0))]}, fe, 0)
    sr.passage({"ci": [live((0, 1))]}, fe, 10)
    assert len(envr) == 1                                                                 # coup d'envoi seulement : on attend le buteur
    sr.passage({"ci": [live((0, 1))]}, fe, 10 + ATTENTE_BUTEUR_S)
    assert envr[-1][0] == "⚽ But de Paris Saint-Germain : Chelsea FC 0-1 Paris Saint-Germain" and envr[-1][3] == 4 \
        and "pas encore publié" in envr[-1][1] and envr[-1][2] == "ci", envr[-1]
    # lecture des matchs ESPN du jour : filtre sur le jour UTC, veille lue avant 6 h UTC, liste FIFA lue seulement s'il y a un match
    appels: List[tuple] = []
    def sb(lg, j):
        appels.append(("sb", j))
        return ([ev_cwc, {**ev_cwc, "id": "1", "date": "2025-07-14T01:00Z"}], "ok") if j == "2025-07-13" else ([], "ok")
    def lf(comp, ed):
        appels.append(("liste", comp, ed))
        return liste_cwc
    err: List[str] = []
    ms = matchs_espn_jour("cdmc", "2025-07-13", datetime(2025, 7, 13, 12, 0, tzinfo=timezone.utc), err, sb, lf)
    assert [m["id"] for m in ms] == ["espn-735958"] and francais(ms[0]) and appels == [("sb", "2025-07-13"), ("liste", "cdmc", 2025)] and not err
    appels.clear()
    matchs_espn_jour("cdmc", "2025-07-14", datetime(2025, 7, 14, 3, 0, tzinfo=timezone.utc), err, sb, lf)
    assert ("sb", "2025-07-13") in appels and ("sb", "2025-07-14") in appels
    appels.clear()
    assert matchs_espn_jour("ci", "2025-09-01", datetime(2025, 9, 1, 12, tzinfo=timezone.utc), err, lambda lg, j: ([], "ok"), lf) == [] \
        and appels == [] and not err                                                      # aucun match : liste FIFA jamais lue
    assert matchs_espn_jour("ci", "2025-09-01", datetime(2025, 9, 1, 12, tzinfo=timezone.utc), err, lambda lg, j: ([], "erreur"), lf) == []
    assert err == ["ci"]                                                                  # scoreboard illisible : signalé
    ms = matchs_espn_jour("cdmc", "2025-07-13", datetime(2025, 7, 13, 12, tzinfo=timezone.utc), err, sb, lambda c, e: None)
    assert len(ms) == 1 and not francais(ms[0])                                           # liste FIFA illisible : club non reconnu
    # liste FIFA : une lecture réussie est gardée, une panne n'est relue qu'après RELIRE_LISTE_FIFA_S
    _LISTES_FIFA.clear()
    _LISTES_FIFA[("ci", 2026)] = (None, 1000.0)
    assert liste_fifa("ci", 2026, 1000.0 + RELIRE_LISTE_FIFA_S - 1) is None
    _LISTES_FIFA[("ci", 2026)] = ([fifa], 1000.0)
    assert liste_fifa("ci", 2026, 9e9) == [fifa]
    _LISTES_FIFA.clear()
    # veille : un match français en ESPN (Coupe intercontinentale) est à suivre 20 min avant le coup d'envoi
    ko_ci = datetime(2025, 7, 13, 19, 0, tzinfo=timezone.utc)
    prog = {**mc, "status": "UPCOMING"}
    assert a_suivre({"ci": [prog]}, ko_ci - timedelta(minutes=10)) and not a_suivre({"ci": [prog]}, ko_ci - timedelta(minutes=30))
    assert not s.termine({"ci": [prog]}, ko_ci + timedelta(minutes=60)) and s.termine({"ci": [live((3, 0), "FINISHED")]}, ko_ci)
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
        matchs = matchs_du_jour(now.date().isoformat(), now)
        ok = bool(matchs) and a_suivre(matchs, now)
        print(f"[DIRECT] veille {now:%H:%M} UTC : {'suivi à lancer' if ok else 'rien à suivre'}")
        sys.exit(0 if ok else 1)
    elif a.boucle:
        boucle(a.duree_min, a.pas)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
