#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Compétitions internationales : sélections (Coupe du monde, Euro, Ligue des nations, avec leurs éliminatoires) et compétitions
mondiales de clubs (Coupe du monde des clubs, Coupe intercontinentale). Étude, mesures et décisions : docs/etude_internationales.md.

Sources (mesurées le 26/11/2026, sans clé) :
- UEFA (même API que les coupes d'Europe, `collector.build_match`) : Euro (`3`), Ligue des nations (`2014`), éliminatoires de la
  Coupe du monde zone Europe (`17`, phase QUALIFYING). Données riches : actions, ~200-380 stats d'équipe, stats des joueurs, compos.
- FIFA (`api.fifa.com/api/v3`, accord du propriétaire du 26/11/2026) : liste OFFICIELLE des matchs de la phase finale de la Coupe du
  monde, de la Coupe du monde des clubs et de la Coupe intercontinentale (noms français, tours, groupes, stades, pays des clubs).
- ESPN (`ligues.py`, flux Opta) : détail de ces mêmes matchs (actions, stats, xG en 2026, compos, joueurs). L'UEFA a aussi la phase
  finale de la Coupe du monde 2026 mais sans AUCUNE statistique : on ne l'utilise pas pour elle.

Rapprochement FIFA <-> ESPN (strict, jamais deviné) : sélection = code (abréviation ESPN == code FIFA) ; club = noms concordants
(`espn._noms_concordent`), UN SEUL club FIFA de l'édition ; match = mêmes deux équipes, jour UTC à ±1. Sinon : nom anglais ESPN, pas de
drapeau, tour ESPN traduit (`TOURS_ESPN`).

Flux ESPN réduit (anciens matchs, Coupe intercontinentale : < `SEUIL_FLUX_COMPLET` actions) : ni momentum, ni stats par mi-temps, ni
notes (règle de la Ligue 2) ; le match porte `flux: "reduit"`.

Édition = `seasonYear` UEFA (année de fin : Euro 2024 -> 2024, Ligue des nations 2026-27 -> 2027, Coupe du monde 2026 -> 2026) ; pour
les compétitions FIFA : année du tournoi (Coupe du monde des clubs 2025 -> 2025, Coupe intercontinentale 2026 -> 2026).
"""

import argparse
import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import collector
import espn
import ligues
import ratings
import uefa
from netutil import FLAG_CODES, fetch_json, fr

COMPETITIONS: Dict[str, Dict[str, Any]] = {
    "cdm": {"nom": "Coupe du monde", "court": "CdM", "famille": "selections", "uefa": 17, "fifa": [17],
            "espn": "fifa.world", "uefa_qualif_seulement": True, "majeure": True},
    "euro": {"nom": "Euro", "court": "Euro", "famille": "selections", "uefa": 3, "espn": "uefa.euro", "majeure": True},
    "ldn": {"nom": "Ligue des nations", "court": "LdN", "famille": "selections", "uefa": 2014, "espn": "uefa.nations",
            "edition_saison": True},
    "cdmc": {"nom": "Coupe du monde des clubs", "court": "CdMC", "famille": "clubs", "fifa": [10005, 107],
             "fifa_motif": "Clubs", "espn": "fifa.cwc"},
    "ci": {"nom": "Coupe intercontinentale", "court": "CI", "famille": "clubs", "fifa": [107],
           "fifa_motif": "Intercontinentale", "espn": "fifa.intercontinental_cup"},
}
SEUIL_FLUX_COMPLET = 500       # actions ESPN : au-dessous, ancien flux / actions clés seulement (mesuré : 20-290 contre 1 340-1 970)
FIFA = "https://api.fifa.com/api/v3"
SOURCE_UEFA = "UEFA"
PAUSE_FIFA_S = 0.3

try:
    from zoneinfo import ZoneInfo
    PARIS = ZoneInfo("Europe/Paris")
except Exception:  # pragma: no cover
    PARIS = timezone(timedelta(hours=1))

# Tours ESPN (season.slug) quand le match FIFA n'est pas retrouvé
TOURS_ESPN = {"group-stage": ("Phase de groupes", "groupes"), "round-of-32": ("Seizièmes de finale", "finale"),
              "round-of-16": ("Huitièmes de finale", "finale"), "quarterfinals": ("Quarts de finale", "finale"),
              "semifinals": ("Demi-finales", "finale"), "3rd-place-match": ("Match pour la 3e place", "finale"),
              "final": ("Finale", "finale")}


def cle_ligue(comp: str) -> str:
    """Clé enregistrée dans `ligues.LIGUES` pour réutiliser son collecteur ESPN (dans CE processus seulement)."""
    k = f"int-{comp}"
    if k not in ligues.LIGUES:
        ligues.LIGUES[k] = {"slug": COMPETITIONS[comp]["espn"], "name": COMPETITIONS[comp]["nom"],
                            "short_name": COMPETITIONS[comp]["court"], "country": "", "country_name": ""}
    return k


def libelle_edition(comp: str, edition: int) -> str:
    return f"{edition - 1}-{str(edition)[2:]}" if COMPETITIONS[comp].get("edition_saison") else str(edition)


def edition_de(comp: str, jour: str) -> int:
    """Édition d'une date : saison UEFA (juillet -> juin) pour la Ligue des nations, année civile sinon (éliminatoires de l'Euro
    2028 joués en 2027 : édition donnée explicitement par l'appelant)."""
    d = date.fromisoformat(jour)
    return uefa.season_year_for(d) if COMPETITIONS[comp].get("edition_saison") else d.year


def jour_paris(iso: str) -> str:
    try:
        return datetime.fromisoformat((iso or "").replace("Z", "+00:00")).astimezone(PARIS).date().isoformat()
    except ValueError:
        return ""


def _fr_liste(v: Any) -> str:
    """Texte localisé FIFA ([{Locale, Description}]) : le français, sinon le premier."""
    if isinstance(v, list) and v:
        x = next((t for t in v if str(t.get("Locale", "")).lower().startswith("fr")), v[0])
        return (x.get("Description") or "").replace("\xa0", " ").replace("™", "").strip()
    return ""


# ------------------------------------------------------------------------------
# FIFA : liste officielle des matchs d'une édition
# ------------------------------------------------------------------------------
def fifa_saison(comp: str, edition: int) -> Optional[Tuple[int, str]]:
    """(identifiant de compétition FIFA, identifiant de saison) de l'édition : nom de saison contenant l'année (et le motif de la
    compétition quand l'identifiant FIFA en regroupe plusieurs, ex. 107 = Coupe du monde des clubs ET Coupe intercontinentale)."""
    motif = COMPETITIONS[comp].get("fifa_motif", "")
    for idc in COMPETITIONS[comp].get("fifa") or []:
        d = fetch_json(f"{FIFA}/seasons?idCompetition={idc}&language=fr&count=100")
        for s in (d or {}).get("Results") or []:
            nom = _fr_liste(s.get("Name"))
            if re.search(rf"\b{edition}\b", nom) and (not motif or motif.lower() in nom.lower()):
                return idc, str(s.get("IdSeason"))
    return None


def fifa_matchs(idc: int, ids: str) -> Optional[List[Dict[str, Any]]]:
    time.sleep(PAUSE_FIFA_S)
    d = fetch_json(f"{FIFA}/calendar/matches?language=fr&count=500&idCompetition={idc}&idSeason={ids}")
    if not isinstance(d, dict) or not isinstance(d.get("Results"), list):
        return None
    return d["Results"]


STATUT_FIFA = {0: "Terminé", 1: "À venir", 3: "En cours", 4: "Abandonné", 7: "Reporté", 8: "Annulé", 12: "Programmé"}


def equipe_fifa(t: Optional[Dict[str, Any]], club: bool) -> Optional[Dict[str, Any]]:
    """Équipe FIFA au schéma des équipes de match (flag, country, name…). None pour une place à déterminer."""
    if not t or not t.get("IdTeam"):
        return None
    pays = (t.get("IdCountry") or "").upper()
    nom = _fr_liste(t.get("TeamName"))
    return {"flag": FLAG_CODES.get(pays, ""), "country": pays, "country_name": "" if club else nom,
            "id": f"fifa-{t['IdTeam']}", "fifa_id": str(t["IdTeam"]), "name": nom, "official_name": nom,
            "short": t.get("Abbreviation") or "", "is_french": pays == "FRA", "logo": "",
            "_noms": [x for x in {nom, t.get("ShortClubName") or "", t.get("Abbreviation") or ""} if x]}


def entree_fifa(comp: str, m: Dict[str, Any]) -> Dict[str, Any]:
    club = COMPETITIONS[comp]["famille"] == "clubs"
    # « Finale de la Coupe intercontinentale de la FIFA 2026 » -> « Finale de la Coupe intercontinentale »
    stage = re.sub(r"\s+de la FIFA(\s+\d{4})?$", "", _fr_liste(m.get("StageName")))
    groupe = _fr_liste(m.get("GroupName"))
    ko = not groupe
    statut = m.get("MatchStatus")
    h, a = equipe_fifa(m.get("Home"), club), equipe_fifa(m.get("Away"), club)
    fini = statut == 0 and m.get("HomeTeamScore") is not None and m.get("AwayTeamScore") is not None
    stade = m.get("Stadium") or {}
    return {"source": "fifa", "fifa_id": str(m.get("IdMatch")), "debut": m.get("Date") or "", "jour": jour_paris(m.get("Date") or ""),
            "phase": "finale" if ko else "groupes", "tour": stage, "groupe": groupe or None,
            "home_team": h, "away_team": a,
            "attente": [m.get("PlaceHolderA") or "", m.get("PlaceHolderB") or ""],
            "score": (int(m["HomeTeamScore"]), int(m["AwayTeamScore"])) if fini else None,
            "tab": (m.get("HomeTeamPenaltyScore"), m.get("AwayTeamPenaltyScore"))
            if fini and (m.get("HomeTeamPenaltyScore") or m.get("AwayTeamPenaltyScore")) else None,
            "fini": fini, "statut": STATUT_FIFA.get(statut, "À venir"),
            "stade": _fr_liste(stade.get("Name")), "ville": _fr_liste(stade.get("CityName"))}


# ------------------------------------------------------------------------------
# UEFA : liste de l'édition
# ------------------------------------------------------------------------------
_UEFA: Dict[Tuple[int, int], Optional[List[Dict[str, Any]]]] = {}


def uefa_matchs(cid: int, edition: int) -> Optional[List[Dict[str, Any]]]:
    """Tous les matchs UEFA de l'édition (pagination par 500) ; None si une page est illisible (jamais de liste tronquée)."""
    if (cid, edition) not in _UEFA:
        out: List[Dict[str, Any]] = []
        for off in range(0, 5000, 500):
            data = fetch_json(f"https://match.uefa.com/v5/matches?competitionId={cid}&seasonYear={edition}"
                              f"&offset={off}&limit=500&order=ASC&language=FR")
            if not isinstance(data, list):
                out = None  # type: ignore[assignment]
                break
            out.extend(data)
            if len(data) < 500:
                break
        _UEFA[(cid, edition)] = out
    return _UEFA[(cid, edition)]


def phase_uefa(m: Dict[str, Any]) -> Tuple[str, str]:
    """(phase, tour) d'un match UEFA : qualification (round.phase QUALIFYING : groupes d'éliminatoires et barrages), groupes
    (phase de groupes / de ligue), finale (élimination directe)."""
    r = m.get("round") or {}
    tour = fr(r.get("translations"), "name") or (r.get("metaData") or {}).get("name", "")
    if (r.get("phase") or "") == "QUALIFYING":
        return "qualification", tour
    return ("groupes" if (r.get("mode") or "") == "GROUP" else "finale"), tour


def entree_uefa(m: Dict[str, Any]) -> Dict[str, Any]:
    phase, tour = phase_uefa(m)
    g = m.get("group") or {}
    total = (m.get("score") or {}).get("total") or {}
    pen = (m.get("score") or {}).get("penalty") or {}
    fini = m.get("status") == "FINISHED"
    debut = (m.get("kickOffTime") or {}).get("dateTime") or ""
    h, a = uefa.team_info(m.get("homeTeam") or {}), uefa.team_info(m.get("awayTeam") or {})
    md = m.get("matchday") or {}
    return {"source": "uefa", "uefa_id": str(m.get("id")), "debut": debut, "jour": jour_paris(debut), "phase": phase,
            "tour": tour, "groupe": fr(g.get("translations"), "name") or (g.get("metaData") or {}).get("groupName") or None,
            "journee": fr(md.get("translations"), "name") or None,
            "home_team": h, "away_team": a,
            "score": (int(total.get("home", 0)), int(total.get("away", 0))) if fini and total else None,
            "tab": (pen.get("home"), pen.get("away")) if fini and pen else None,
            "fini": fini, "statut": uefa.STATUS_FR.get(m.get("status", ""), (m.get("status") or "").title()),
            "stade": fr((m.get("stadium") or {}).get("translations"), "name"), "_brut": m}


def liste_edition(comp: str, edition: int) -> Optional[List[Dict[str, Any]]]:
    """Tous les matchs de l'édition (joués et à venir), triés par coup d'envoi ; None si une source est illisible."""
    cfg = COMPETITIONS[comp]
    out: List[Dict[str, Any]] = []
    if cfg.get("uefa"):
        brut = uefa_matchs(cfg["uefa"], edition)
        if brut is None:
            return None
        for m in brut:
            e = entree_uefa(m)
            if cfg.get("uefa_qualif_seulement") and e["phase"] != "qualification":
                continue   # phase finale de la Coupe du monde : FIFA + ESPN (l'UEFA n'en a aucune statistique)
            out.append(e)
    if cfg.get("fifa"):
        s = fifa_saison(comp, edition)
        if s:
            ms = fifa_matchs(*s)
            if ms is None:
                return None
            out += [entree_fifa(comp, m) for m in ms]
    out.sort(key=lambda e: (e["debut"], e.get("uefa_id") or e.get("fifa_id") or ""))
    return out


# ------------------------------------------------------------------------------
# ESPN : détail des matchs FIFA
# ------------------------------------------------------------------------------
def equipe_fifa_de_espn(c: Dict[str, Any], equipes: List[Dict[str, Any]], club: bool) -> Optional[Dict[str, Any]]:
    """Équipe FIFA de l'édition correspondant au participant ESPN `c` : par code pour une sélection, par les noms pour un club ;
    un SEUL candidat, sinon None."""
    t = c.get("team") or {}
    if not club:
        ab = (t.get("abbreviation") or "").upper()
        cand = [e for e in equipes if e["short"].upper() == ab or e["country"] == ab]
    else:
        noms = [x for x in (t.get("displayName"), t.get("shortDisplayName"), t.get("name"), t.get("location")) if x]
        cand = [e for e in equipes if espn._noms_concordent(e["_noms"], noms)]
    ids = {e["fifa_id"] for e in cand}
    return cand[0] if len(ids) == 1 else None


def _sans_prive(e: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in e.items() if not k.startswith("_")}


def match_espn(comp: str, ev: Dict[str, Any], liste: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Match de base ESPN (ligues.match_de_base) complété par la liste FIFA : noms français, pays, tour, groupe, stade."""
    lg = cle_ligue(comp)
    club = COMPETITIONS[comp]["famille"] == "clubs"
    m = ligues.match_de_base(lg, ev)
    m.pop("ligue", None)
    m["is_french_match"] = False
    equipes = {}
    for e in liste:
        for t in (e.get("home_team"), e.get("away_team")):
            if t and e["source"] == "fifa":
                equipes[t["fifa_id"]] = t
    cs = (ev.get("competitions") or [{}])[0].get("competitors") or []
    rap = {}
    for c in cs:
        side = c.get("homeAway")
        f = equipe_fifa_de_espn(c, list(equipes.values()), club)
        t = m.get(f"{side}_team")
        if t is None:
            continue
        if f:
            rap[side] = f["fifa_id"]
            t.update({k: f[k] for k in ("flag", "country", "country_name", "name", "official_name", "is_french", "fifa_id")})
            if not club:
                t["short"] = f["short"] or t["short"]
        else:
            t.update({"flag": "", "country": "", "country_name": "", "is_french": False})
            if not club:   # sélection non rapprochée : le code ESPN reste celui d'un pays (mesuré 48/48 en 2026)
                code = (t.get("short") or "").upper()
                t.update({"flag": FLAG_CODES.get(code, ""), "country": code if code in FLAG_CODES else "",
                          "is_french": code == "FRA"})
    m["is_french_match"] = m["home_team"]["is_french"] or m["away_team"]["is_french"]
    fm = None
    if len(rap) == 2:
        jour = (ev.get("date") or "")[:10]
        cand = [e for e in liste if e["source"] == "fifa" and e.get("home_team") and e.get("away_team")
                and {e["home_team"]["fifa_id"], e["away_team"]["fifa_id"]} == set(rap.values())
                and abs((date.fromisoformat(e["debut"][:10]) - date.fromisoformat(jour)).days) <= 1]
        fm = cand[0] if len(cand) == 1 else None
    if fm:
        m.update({"fifa_id": fm["fifa_id"], "phase": fm["phase"], "groupe": fm["groupe"],
                  "round": {"name": fm["tour"], "type": ""}})
        if fm.get("stade"):
            m["venue"] = m["venue_fifa"] = fm["stade"]   # nom officiel FIFA (en français), prioritaire sur celui d'ESPN
    else:
        tour, phase = TOURS_ESPN.get(((ev.get("season") or {}).get("slug") or ""), ("", "finale"))
        g = ((ev.get("competitions") or [{}])[0].get("group") or {}).get("name") or ""
        m.update({"phase": "groupes" if g else phase, "groupe": g.replace("Group", "Groupe") or None,
                  "round": {"name": tour, "type": ""}})
    m["stage"] = "league" if m["phase"] == "groupes" else "qualifying" if m["phase"] == "qualification" else "knockout"
    return m


def completer_espn(comp: str, m: Dict[str, Any], avec_stats_joueurs: bool = True) -> str:
    r = ligues.completer_match(cle_ligue(comp), m, avec_stats_joueurs)
    if m.get("venue_fifa"):
        m["venue"] = m.pop("venue_fifa")
    if r == "ok" and (m.get("actions_opta") or 0) < SEUIL_FLUX_COMPLET:
        # ancien flux / actions clés : valeurs calculées fausses -> retirées (règle de la Ligue 2)
        m.update({"momentum": [], "flux": "reduit", "source": "ESPN"})
        m["stats"]["1st"], m["stats"]["2nd"] = [], []
        for p in (m.get("players") or {}).values():
            p["rating"], p["factors"] = None, []
    return r


# ------------------------------------------------------------------------------
# Collecte d'un jour
# ------------------------------------------------------------------------------
DELAI_APRES_COUP_MIN = 120   # match terminé collecté 2 h après le coup d'envoi (stats finalisées), comme les championnats


def _trop_tot(debut: str, maintenant: Optional[datetime]) -> bool:
    try:
        d = datetime.fromisoformat((debut or "").replace("Z", "+00:00"))
    except ValueError:
        return False
    return maintenant is not None and maintenant < d + timedelta(minutes=DELAI_APRES_COUP_MIN)


def collecter_jour(comp: str, edition: int, jour: str, liste: Optional[List[Dict[str, Any]]] = None,
                   avec_stats_joueurs: bool = True, max_matchs: Optional[int] = None,
                   deja: Optional[Dict[str, Dict[str, Any]]] = None, maintenant: Optional[datetime] = None) -> Dict[str, Any]:
    """Matchs de l'édition joués le `jour` (heure de Paris), au schéma des coupes, plus `phase`, `groupe`, `tab`.
    `deja` : matchs complets d'un passage précédent ({match_id: match}), repris sans requête. `maintenant` : un match fini depuis
    moins de `DELAI_APRES_COUP_MIN` après son coup d'envoi n'est pas détaillé (`en_attente`).
    Bloc de compétition : {id, name, short_name, famille, edition, matches, incomplet, notes}."""
    deja = deja or {}
    cfg = COMPETITIONS[comp]
    liste = liste if liste is not None else liste_edition(comp, edition)
    incomplet = liste is None
    liste = liste or []
    du_jour = [e for e in liste if e["jour"] == jour]
    matchs: List[Dict[str, Any]] = []
    n = 0
    for e in du_jour:
        if e["source"] != "uefa":
            continue
        if not e["fini"] and e["statut"] in ("À venir", ""):
            continue
        if e["uefa_id"] in deja:
            matchs.append(deja[e["uefa_id"]])
            continue
        if e["fini"] and _trop_tot(e["debut"], maintenant):
            print(f"[INFO] {cfg['court']} {e['home_team']['name']}-{e['away_team']['name']} : fini depuis trop peu, au passage suivant")
            incomplet = True
            continue
        if max_matchs is not None and n >= max_matchs:
            break
        n += 1
        t0 = time.time()
        m = collector.build_match(comp, e["_brut"], detailed=bool(e["home_team"]["is_french"] or e["away_team"]["is_french"]))
        m.update({"phase": e["phase"], "groupe": e["groupe"], "source": SOURCE_UEFA, "date": jour})
        if e.get("tab"):
            m["tab"] = list(e["tab"])
        print(f"[INFO] {cfg['court']} {m['home_team']['name']} {m['home_team']['score']}-{m['away_team']['score']} "
              f"{m['away_team']['name']} (UEFA) : {len(m['events'])} actions, {len(m['players'])} joueurs, {time.time() - t0:.0f} s")
        matchs.append(m)
    if any(e["source"] == "fifa" for e in du_jour) or (not cfg.get("uefa") and cfg.get("espn")):
        veille = (date.fromisoformat(jour) - timedelta(days=1)).isoformat()
        vus = set()
        for j in (veille, jour):
            evs, st = ligues.scoreboard(cle_ligue(comp), j)
            incomplet |= st != "ok"
            for ev in evs:
                m = match_espn(comp, ev, liste)
                if m["date"] != jour or m["espn_id"] in vus:
                    continue
                vus.add(m["espn_id"])
                if m["match_id"] in deja:
                    matchs.append(deja[m["match_id"]])
                    continue
                if m["finished"] and _trop_tot(m.get("date_utc", ""), maintenant):
                    m["en_attente"] = True
                    incomplet = True
                elif m["finished"] and (max_matchs is None or n < max_matchs):
                    n += 1
                    t0 = time.time()
                    r = completer_espn(comp, m, avec_stats_joueurs)
                    print(f"[INFO] {cfg['court']} {m['home_team']['name']} {m['home_team']['score']}-{m['away_team']['score']} "
                          f"{m['away_team']['name']} (ESPN) : {r}, {m.get('actions_opta', 0)} actions, "
                          f"{len(m['players'])} joueurs, {time.time() - t0:.0f} s")
                    if r != "ok":
                        m["detail_manquant"] = True
                        incomplet = True
                    else:
                        espn_tab(m, liste)
                matchs.append(m)
        attendus = [e for e in du_jour if e["source"] == "fifa" and e["fini"]]
        if len([m for m in matchs if m.get("espn_id") and m["finished"]]) < len(attendus):
            print(f"[WARN] {cfg['court']} {jour} : {len(attendus)} match(s) terminé(s) chez la FIFA, "
                  f"{len([m for m in matchs if m.get('espn_id') and m['finished']])} chez ESPN")
            incomplet = True
    # Notes : par source (stats UEFA et ESPN différentes), seulement les matchs au flux complet
    notes: Dict[str, Any] = {}
    for src in ("uefa", "espn"):
        lot = [m for m in matchs if m.get("players") and not m.get("flux") and bool(m.get("espn_id")) == (src == "espn")]
        if lot:
            notes[src] = ratings.rate_matches(lot)
    for m in matchs:
        m.pop("actions", None)   # jamais publiées (comme data.json) : le dossier IA les relit à l'UEFA
    matchs.sort(key=lambda x: (x.get("date_utc") or x.get("kickoff") or "", x["home_team"]["name"]))
    print(f"[INFO] {cfg['nom']} {libelle_edition(comp, edition)} : {len(matchs)} match(s) le {jour}")
    return {"id": comp, "name": cfg["nom"], "short_name": cfg["court"], "famille": cfg["famille"], "edition": edition,
            "edition_libelle": libelle_edition(comp, edition), "stage_type": "international",
            "matches": matchs, "incomplet": incomplet, "notes": notes}


def espn_tab(m: Dict[str, Any], liste: List[Dict[str, Any]]) -> None:
    """Tirs au but : lus dans la liste FIFA du même match (ESPN ne les donne pas dans le score)."""
    fm = next((e for e in liste if e.get("fifa_id") == m.get("fifa_id")), None)
    if fm and fm.get("tab"):
        h, a = fm["tab"]
        # la liste FIFA peut avoir domicile / extérieur inversés par rapport à ESPN (terrain neutre)
        if fm["home_team"] and fm["home_team"]["fifa_id"] != m["home_team"].get("fifa_id"):
            h, a = a, h
        m["tab"] = [h, a]
        m["penalties"] = f"{h}-{a}"


# ------------------------------------------------------------------------------
# Classements par groupe (officiels, état ACTUEL de l'édition)
# ------------------------------------------------------------------------------
def classements_uefa(cid: int, edition: int) -> Optional[List[Dict[str, Any]]]:
    """Groupes UEFA de l'édition : éliminatoires (`phase=QUALIFYING`, à demander à part : mesuré, sans elle seuls les groupes de la
    phase finale reviennent) puis phase de groupes / de ligue."""
    data: List[Dict[str, Any]] = []
    for ph in ("&phase=QUALIFYING", ""):
        d = fetch_json(f"https://standings.uefa.com/v1/standings?competitionId={cid}&seasonYear={edition}{ph}&language=FR")
        if d is None and not ph:
            return None
        if isinstance(d, list):
            for g in d:
                if ph:
                    (g.setdefault("group", {}))["phase"] = "QUALIFYING"
                if all((g.get("group") or {}).get("id") != (x.get("group") or {}).get("id") for x in data):
                    data.append(g)
    out = []
    for g in data:
        gr = g.get("group") or {}
        lignes = []
        for it in g.get("items") or []:
            t = uefa.team_info(it.get("team") or {})
            gd = int(it.get("goalDifference") or 0)
            lignes.append({"rank": int(it.get("rank") or len(lignes) + 1), "team_id": t["id"], "team": t["name"],
                           "short_name": t["short"], "country": t["country"], "flag": t["flag"], "logo": t["logo"],
                           "is_french": t["is_french"], "played": int(it.get("played") or 0), "won": int(it.get("won") or 0),
                           "drawn": int(it.get("drawn") or 0), "lost": int(it.get("lost") or 0),
                           "gf": int(it.get("goalsFor") or 0), "ga": int(it.get("goalsAgainst") or 0),
                           "gd": f"+{gd}" if gd > 0 else str(gd), "points": int(it.get("points") or 0),
                           **({"qualifie": True} if it.get("qualified") else {})})
        lignes.sort(key=lambda r: r["rank"])
        out.append({"id": str(gr.get("id") or ""), "nom": fr(gr.get("translations"), "name") or
                    (gr.get("metaData") or {}).get("groupName", ""),
                    "phase": "qualification" if gr.get("phase") == "QUALIFYING" else "groupes", "lignes": lignes})
    return out


ZONES_ESPN = [("best", "meilleur_troisieme"), ("advance", "qualifie"), ("eliminated", "elimine")]


def classements_espn(comp: str, edition: int, liste: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    data, st = ligues._get(f"{ligues.STANDINGS}/{COMPETITIONS[comp]['espn']}/standings?season={edition}")
    if st != "ok":
        return None
    club = COMPETITIONS[comp]["famille"] == "clubs"
    equipes = {t["fifa_id"]: t for e in liste for t in (e.get("home_team"), e.get("away_team")) if t and e["source"] == "fifa"}
    out = []
    for ch in data.get("children") or []:
        lignes = []
        for x in ((ch.get("standings") or {}).get("entries")) or []:
            s = {y.get("name"): y.get("value") for y in x.get("stats") or []}
            if s.get("rank") is None:
                continue
            f = equipe_fifa_de_espn({"team": x.get("team") or {}}, list(equipes.values()), club)
            t = x.get("team") or {}
            code = (t.get("abbreviation") or "").upper()
            pays = f["country"] if f else (code if not club and code in FLAG_CODES else "")
            note = ((x.get("note") or {}).get("description") or "").lower()
            zone = next((z for motif, z in ZONES_ESPN if motif in note), None)
            gd = int(s.get("pointDifferential") or 0)
            lignes.append({"rank": int(s["rank"]), "team_id": f"espn-{t.get('id')}", "team": f["name"] if f else
                           (t.get("shortDisplayName") or t.get("displayName") or ""), "short_name": code, "country": pays,
                           "flag": FLAG_CODES.get(pays, ""), "is_french": pays == "FRA",
                           "played": int(s.get("gamesPlayed") or 0), "won": int(s.get("wins") or 0),
                           "drawn": int(s.get("ties") or 0), "lost": int(s.get("losses") or 0),
                           "gf": int(s.get("pointsFor") or 0), "ga": int(s.get("pointsAgainst") or 0),
                           "gd": f"+{gd}" if gd > 0 else str(gd), "points": int(s.get("points") or 0),
                           **({"zone": zone} if zone else {})})
        lignes.sort(key=lambda r: r["rank"])
        out.append({"id": ch.get("abbreviation") or ch.get("name") or "",
                    "nom": (ch.get("name") or "").replace("Group", "Groupe"), "phase": "groupes", "lignes": lignes})
    return out


def classements(comp: str, edition: int, liste: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Classements officiels ACTUELS des groupes de l'édition (UEFA, sinon ESPN pour les compétitions FIFA). Pas de classement
    recalculé à une date passée à cette étape (règlements de départage à vérifier par compétition)."""
    cfg = COMPETITIONS[comp]
    groupes: List[Dict[str, Any]] = []
    sources = []
    if cfg.get("uefa"):
        g = classements_uefa(cfg["uefa"], edition)
        if g:
            groupes += [x for x in g if not (cfg.get("uefa_qualif_seulement") and x["phase"] != "qualification")]
            sources.append("UEFA")
    if cfg.get("fifa") and any(e["source"] == "fifa" and e["phase"] == "groupes" for e in liste):
        g = classements_espn(comp, edition, liste)
        if g:
            groupes += g
            sources.append("ESPN")
    return {"source": " + ".join(sources), "groupes": groupes}


# ------------------------------------------------------------------------------
# Programme (matchs à venir)
# ------------------------------------------------------------------------------
def programme(comp: str, liste: List[Dict[str, Any]], maintenant: datetime) -> List[Dict[str, Any]]:
    seuil = (maintenant - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M")
    out = []
    for e in liste:
        if e["fini"] or e["statut"] in ("Annulé", "Abandonné"):
            continue
        if e["statut"] != "Reporté" and (e["debut"] or "") < seuil:
            continue
        x = {"id": e.get("uefa_id") or f"fifa-{e.get('fifa_id')}", "debut": e["debut"], "date": e["jour"],
             "phase": e["phase"], "tour": e["tour"], "statut": e["statut"]}
        for side, att in (("home_team", 0), ("away_team", 1)):
            if e.get(side):
                x[side] = _sans_prive(e[side])
            else:
                x[side] = None
                x.setdefault("a_determiner", []).append(e.get("attente", ["", ""])[att] or "?")
        for k in ("groupe", "journee", "stade", "ville"):
            if e.get(k):
                x[k] = e[k]
        out.append(x)
    return out


def jours_joues(liste: List[Dict[str, Any]]) -> List[str]:
    return sorted({e["jour"] for e in liste if e["fini"] and e["jour"]})


# ------------------------------------------------------------------------------
# Tests sans réseau
# ------------------------------------------------------------------------------
def _test() -> None:
    assert libelle_edition("ldn", 2027) == "2026-27" and libelle_edition("cdm", 2026) == "2026"
    assert edition_de("ldn", "2026-11-17") == 2027 and edition_de("ldn", "2027-03-25") == 2027 and edition_de("cdm", "2026-07-19") == 2026
    assert jour_paris("2026-07-19T22:30:00Z") == "2026-07-20" and jour_paris("2026-07-19T19:00Z") == "2026-07-19"
    assert _fr_liste([{"Locale": "en-GB", "Description": "Spain"}, {"Locale": "fr-FR", "Description": "Espagne\xa0™"}]) == "Espagne"
    # Équipes FIFA (structure réelle allégée, calendrier 2026)
    fra = equipe_fifa({"IdTeam": "43946", "IdCountry": "FRA", "TeamName": [{"Locale": "fr-FR", "Description": "France"}],
                       "Abbreviation": "FRA", "ShortClubName": "France"}, club=False)
    sen = equipe_fifa({"IdTeam": "43879", "IdCountry": "SEN", "TeamName": [{"Locale": "fr-FR", "Description": "Sénégal"}],
                       "Abbreviation": "SEN", "ShortClubName": "Senegal"}, club=False)
    assert fra["is_french"] and fra["flag"] and sen["name"] == "Sénégal"
    assert equipe_fifa({"IdTeam": None}, False) is None
    # Rapprochement ESPN -> FIFA : sélection par code
    assert equipe_fifa_de_espn({"team": {"abbreviation": "SEN", "displayName": "Senegal"}}, [fra, sen], False)["fifa_id"] == "43879"
    assert equipe_fifa_de_espn({"team": {"abbreviation": "XXX"}}, [fra, sen], False) is None
    # Club par les noms, un seul candidat
    psg = equipe_fifa({"IdTeam": "1", "IdCountry": "FRA", "TeamName": [{"Locale": "fr-FR", "Description": "Paris Saint-Germain"}],
                       "ShortClubName": "Paris Saint-Germain", "Abbreviation": "PSG"}, club=True)
    che = equipe_fifa({"IdTeam": "2", "IdCountry": "ENG", "TeamName": [{"Locale": "fr-FR", "Description": "Chelsea FC"}],
                       "ShortClubName": "Chelsea", "Abbreviation": "CHE"}, club=True)
    assert psg["country_name"] == "" and psg["is_french"]
    assert equipe_fifa_de_espn({"team": {"displayName": "Paris Saint-Germain", "abbreviation": "PSG"}}, [psg, che], True)["fifa_id"] == "1"
    assert equipe_fifa_de_espn({"team": {"displayName": "Chelsea", "abbreviation": "CHE"}}, [psg, che], True)["fifa_id"] == "2"
    assert equipe_fifa_de_espn({"team": {"displayName": "Real Madrid"}}, [psg, che], True) is None
    # Entrée FIFA : place à déterminer, programme
    e = entree_fifa("ci", {"IdMatch": "9", "Date": "2026-12-16T17:00:00Z", "MatchStatus": 1,
                           "StageName": [{"Locale": "fr-FR", "Description": "Finale"}], "GroupName": [],
                           "Home": {"IdTeam": "1", "IdCountry": "FRA", "Abbreviation": "PSG",
                                    "TeamName": [{"Locale": "fr-FR", "Description": "Paris Saint-Germain"}]},
                           "Away": None, "PlaceHolderA": "", "PlaceHolderB": "W4", "Stadium": {}})
    assert e["phase"] == "finale" and e["away_team"] is None and not e["fini"] and e["tour"] == "Finale"
    assert entree_fifa("ci", {"StageName": [{"Locale": "fr-FR", "Description": "Derby des Amériques de la FIFA 2026™"}]})["tour"] \
        == "Derby des Amériques"
    p = programme("ci", [e], datetime(2026, 11, 26, tzinfo=timezone.utc))
    assert p[0]["away_team"] is None and p[0]["a_determiner"] == ["W4"] and "_noms" not in p[0]["home_team"]
    assert programme("ci", [e], datetime(2026, 12, 17, tzinfo=timezone.utc)) == []
    # Phase UEFA
    assert phase_uefa({"round": {"phase": "QUALIFYING", "mode": "GROUP"}})[0] == "qualification"
    assert phase_uefa({"round": {"phase": "TOURNAMENT", "mode": "GROUP"}})[0] == "groupes"
    assert phase_uefa({"round": {"phase": "TOURNAMENT", "mode": "KNOCK_OUT"}})[0] == "finale"
    print("[OK] internationales : tests passés")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Compétitions internationales : collecte d'un jour d'une édition")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--comp", choices=list(COMPETITIONS))
    ap.add_argument("--edition", type=int)
    ap.add_argument("--date")
    ap.add_argument("--max-matchs", type=int)
    ap.add_argument("--sans-joueurs", action="store_true")
    ap.add_argument("--liste", action="store_true", help="affiche la liste de l'édition (jours joués, à venir)")
    ap.add_argument("--sortie", default="internationales_raw.json")
    a = ap.parse_args()
    if a.test:
        _test()
    elif a.comp and a.edition and a.liste:
        L = liste_edition(a.comp, a.edition) or []
        print(f"{len(L)} matchs, {len(jours_joues(L))} jours joués ; sources : "
              f"{ {s: sum(1 for e in L if e['source'] == s) for s in ('uefa', 'fifa')} }")
        for e in L[-5:]:
            print(" ", e["jour"], e["phase"], e["tour"], e.get("groupe"), (e["home_team"] or {}).get("name"),
                  e["score"], (e["away_team"] or {}).get("name"), e["statut"])
    elif a.comp and a.edition and a.date:
        res = collecter_jour(a.comp, a.edition, a.date, None, not a.sans_joueurs, a.max_matchs)
        with open(a.sortie, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        print(f"[OK] -> {a.sortie}")
    else:
        ap.print_help()
