#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Championnats nationaux (Ligue 1, Premier League, Liga, Serie A, Bundesliga, Ligue 2) : collecte ESPN (flux Opta ;
Ligue 2 : actions clés seulement, voir LIGUES["fl2"]).

Étude, mesures et décisions : docs/etude_championnats.md. Produit des matchs AU MÊME FORMAT que les coupes
(collector.build_match) : index.html, ratings.py, couleurs, momentum s'appliquent sans copie.

Endpoints (sans clé, mesurés le 25/11/2026) :
  site.api.espn.com/apis/site/v2/sports/soccer/<ligue>/scoreboard?dates=AAAAMMJJ       matchs d'un jour
  site.web.api.espn.com/apis/site/v2/sports/soccer/<ligue>/summary?event=<id>          compos, maillots, stade, actions clés
  sports.core.api.espn.com/v2/sports/soccer/leagues/<ligue>/events/<id>/competitions/<id>
      /plays?limit=1000&page=N                     toutes les actions Opta (~1 500 par match)
      /competitors/<équipe>/statistics             stats d'équipe Opta (xG compris)
      /competitors/<équipe>/roster/<joueur>/statistics/0   stats Opta d'un joueur dans le match (~110)
  site.api.espn.com/apis/site/v2/sports/soccer/<ligue>/teams/<id>/roster               effectif (poste, âge, nationalité, photo)
  site.api.espn.com/apis/v2/sports/soccer/<ligue>/standings                            classement

Valeurs dérivées (déterministes, documentées) : momentum (uefa.compute_momentum, actions Opta ; « attaque dangereuse »
remplacée par l'entrée dans la surface adverse, décision du 25/11/2026), stats par mi-temps (comptage des actions :
contrôlé égal aux totaux ESPN sur 10 équipes), positions des compos (déduites du poste Opta), notes (ratings.py, clés
ESPN converties en clés UEFA par JOUEUR_CLES, standardisation par championnat). Une valeur absente reste absente.
"""

import argparse
import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import ratings
import uefa
from netutil import FLAG_CODES, fetch_json_ex

SITE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
SITE_WEB = "https://site.web.api.espn.com/apis/site/v2/sports/soccer"
CORE = "https://sports.core.api.espn.com/v2/sports/soccer/leagues"
STANDINGS = "https://site.api.espn.com/apis/v2/sports/soccer"
SOURCE = "ESPN (Opta)"
PAUSE_S = 0.25                  # entre deux requêtes ESPN (politesse ; ~35 requêtes par match)

LIGUES: Dict[str, Dict[str, Any]] = {
    "fl1": {"slug": "fra.1", "name": "Ligue 1", "short_name": "L1", "country": "FRA", "country_name": "France"},
    "pl": {"slug": "eng.1", "name": "Premier League", "short_name": "PL", "country": "ENG", "country_name": "Angleterre"},
    "liga": {"slug": "esp.1", "name": "Liga", "short_name": "Liga", "country": "ESP", "country_name": "Espagne"},
    "sa": {"slug": "ita.1", "name": "Serie A", "short_name": "SA", "country": "ITA", "country_name": "Italie"},
    "bl": {"slug": "ger.1", "name": "Bundesliga", "short_name": "BL", "country": "GER", "country_name": "Allemagne"},
    # Ligue 2 (décision du propriétaire du 26/11/2026) : ESPN ne publie que les actions clés (buts, cartons, remplacements :
    # 15-22 par match, mesuré sur 7 matchs de novembre 2026), ~33 stats d'équipe sans xG et ~12 stats par joueur. `flux` =
    # « reduit » : ni momentum, ni stats par mi-temps, ni notes (des valeurs calculées sur ces données seraient fausses).
    "fl2": {"slug": "fra.2", "name": "Ligue 2", "short_name": "L2", "country": "FRA", "country_name": "France", "flux": "reduit"},
}
# Championnats SECONDAIRES (décision du 26/11/2026 : championnats hors big 5 représentés en LDC 2026-27 ; mesuré le 26/11/2026) :
# Portugal et Pays-Bas = flux Opta complet SANS xG ; Belgique, Turquie, Autriche, Grèce, Norvège = actions clés seulement (« reduit »).
# Pas chez ESPN : Slovaquie, Ukraine, Azerbaïdjan (HTTP 400) ; Tchéquie (`cze.1` vide). Norvège : saison sur l'année civile.
LIGUES.update({
    "por": {"slug": "por.1", "name": "Liga Portugal", "short_name": "POR", "country": "POR", "country_name": "Portugal"},
    "ned": {"slug": "ned.1", "name": "Eredivisie", "short_name": "NED", "country": "NED", "country_name": "Pays-Bas"},
    "bel": {"slug": "bel.1", "name": "Pro League", "short_name": "BEL", "country": "BEL", "country_name": "Belgique", "flux": "reduit"},
    "tur": {"slug": "tur.1", "name": "Süper Lig", "short_name": "TUR", "country": "TUR", "country_name": "Turquie", "flux": "reduit"},
    "aut": {"slug": "aut.1", "name": "Bundesliga autrichienne", "short_name": "AUT", "country": "AUT", "country_name": "Autriche",
            "flux": "reduit"},
    "gre": {"slug": "gre.1", "name": "Super League grecque", "short_name": "GRE", "country": "GRE", "country_name": "Grèce", "flux": "reduit"},
    "nor": {"slug": "nor.1", "name": "Eliteserien", "short_name": "NOR", "country": "NOR", "country_name": "Norvège", "flux": "reduit",
            "annee_civile": True},
})
# Championnats qui entrent dans la notification commune du jour et les alertes d'échec (décision du 26/11/2026 : big 5 +
# Ligue 2 ; tout championnat ajouté ensuite est « secondaire » : collecté et affiché, jamais notifié ni alerté).
PRINCIPAUX = ["fl1", "pl", "liga", "sa", "bl", "fl2"]
SECONDAIRES = [k for k in LIGUES if k not in PRINCIPAUX]
# Familles de collecte : chacune a son workflow (donnees-football) et son fichier d'état ; seuls les principaux ont une alerte d'échec
FAMILLES = {
    "principaux": {"ligues": PRINCIPAUX, "workflow": "collecte_championnats.yml", "etat": "etat_championnats.json"},
    "secondaires": {"ligues": SECONDAIRES, "workflow": "collecte_secondaires.yml", "etat": "etat_secondaires.json"},
}


def famille(ligue: str) -> str:
    return "principaux" if ligue in PRINCIPAUX else "secondaires"


def saison_de(jour: str, ligue: Optional[str] = None) -> int:
    """Année de début de la saison du jour : 1er juillet -> 30 juin ; championnat sur l'année civile (Norvège) : l'année."""
    d = date.fromisoformat(jour)
    if ligue and LIGUES.get(ligue, {}).get("annee_civile"):
        return d.year
    return d.year if d.month >= 7 else d.year - 1


def libelle_saison(annee: int, ligue: Optional[str] = None) -> str:
    """« 2026-27 » ; championnat sur l'année civile : « 2026 »."""
    if ligue and LIGUES.get(ligue, {}).get("annee_civile"):
        return str(annee)
    return f"{annee}-{str(annee + 1)[2:]}"


def flux_reduit(ligue: str) -> bool:
    return LIGUES.get(ligue, {}).get("flux") == "reduit"

REQUETES = {"n": 0, "erreurs": 0}


def _get(url: str) -> Tuple[Optional[Any], str]:
    time.sleep(PAUSE_S)
    REQUETES["n"] += 1
    data, statut = fetch_json_ex(url)
    if statut == "erreur":
        REQUETES["erreurs"] += 1
    return data, statut


def _id_ref(obj: Any, cle: str) -> str:
    """Identifiant final d'un lien `$ref` ESPN (…/teams/176?lang=… -> 176)."""
    ref = ((obj or {}).get("$ref") or "") if isinstance(obj, dict) else ""
    m = re.search(rf"/{cle}/(\d+)", ref)
    return m.group(1) if m else ""


# ------------------------------------------------------------------------------
# Matchs du jour
# ------------------------------------------------------------------------------
def scoreboard(ligue: str, jour: str) -> Tuple[List[Dict[str, Any]], str]:
    """Événements ESPN d'une ligue pour un jour (AAAA-MM-JJ, jour ESPN = heure de l'Est américain) ; statut ok / erreur."""
    data, statut = _get(f"{SITE}/{LIGUES[ligue]['slug']}/scoreboard?dates={jour.replace('-', '')}")
    if statut != "ok":
        return [], statut
    return data.get("events") or [], "ok"


STATUT_FR = {"STATUS_FULL_TIME": "Terminé", "STATUS_FINAL": "Terminé", "STATUS_FINAL_AET": "Terminé",
             "STATUS_FINAL_PEN": "Terminé", "STATUS_SCHEDULED": "À venir", "STATUS_POSTPONED": "Reporté",
             "STATUS_CANCELED": "Annulé", "STATUS_ABANDONED": "Arrêté", "STATUS_SUSPENDED": "Interrompu",
             "STATUS_FIRST_HALF": "En cours", "STATUS_IN_PROGRESS": "En cours", "STATUS_SECOND_HALF": "En cours", "STATUS_HALFTIME": "Mi-temps"}


def _equipe(c: Dict[str, Any], ligue: str) -> Dict[str, Any]:
    t = c.get("team") or {}
    pays = LIGUES[ligue]["country"]
    logo = t.get("logo") or next((l.get("href") for l in t.get("logos") or [] if l.get("href")), "")
    return {
        "flag": FLAG_CODES.get(pays, ""), "country_name": LIGUES[ligue]["country_name"],
        "id": f"espn-{t.get('id', '')}", "espn_id": str(t.get("id", "")),
        "name": (t.get("shortDisplayName") or t.get("displayName") or "").strip(),
        "official_name": (t.get("displayName") or "").strip(), "short": t.get("abbreviation") or "",
        "country": pays, "is_french": pays == "FRA", "logo": logo,
        "score": int(c["score"]) if str(c.get("score", "")).isdigit() else 0,
    }


def match_de_base(ligue: str, ev: Dict[str, Any]) -> Dict[str, Any]:
    comp = (ev.get("competitions") or [{}])[0]
    cs = comp.get("competitors") or []
    home = next((c for c in cs if c.get("homeAway") == "home"), cs[0] if cs else {})
    away = next((c for c in cs if c.get("homeAway") == "away"), cs[1] if len(cs) > 1 else {})
    st = ((ev.get("status") or {}).get("type") or {})
    nom = st.get("name", "")
    return {
        "match_id": f"espn-{ev.get('id')}", "espn_id": str(ev.get("id")), "ligue": ligue,
        "date": _jour_paris(ev.get("date", "")), "date_utc": ev.get("date", ""),
        "kickoff": _kickoff_paris(ev.get("date", "")),
        "status": STATUT_FR.get(nom, st.get("description") or nom), "finished": bool(st.get("completed")) and
        nom not in ("STATUS_CANCELED", "STATUS_POSTPONED", "STATUS_ABANDONED"),
        "matchday": "", "venue": ((comp.get("venue") or {}).get("fullName") or ""), "attendance": None,
        "player_of_match": "", "penalties": "",
        "home_team": _equipe(home, ligue), "away_team": _equipe(away, ligue),
        "events": [], "goals": [], "momentum": [], "lineups": {}, "players": {},
        "stats": {"all": [], "1st": [], "2nd": []}, "stage": "league", "is_french_match": ligue == "fl1",
    }


try:
    from zoneinfo import ZoneInfo
    _PARIS = ZoneInfo("Europe/Paris")
except Exception:  # pragma: no cover
    _PARIS = timezone(timedelta(hours=1))


def _dt(iso: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def _jour_paris(iso: str) -> str:
    d = _dt(iso)
    return d.astimezone(_PARIS).date().isoformat() if d else ""


def _kickoff_paris(iso: str) -> str:
    d = _dt(iso)
    return d.astimezone(_PARIS).strftime("%d/%m %H:%M") if d else ""


# ------------------------------------------------------------------------------
# Actions Opta -> actions au format UEFA (momentum, mi-temps, déroulé)
# ------------------------------------------------------------------------------
PHASES = {1: "FIRST_HALF", 2: "SECOND_HALF", 3: "FIRST_EXTRA_TIME", 4: "SECOND_EXTRA_TIME"}
BUTS = {"Goal", "Goal - Header", "Goal - Free-kick", "Goal - Volley", "Goal - Penalty", "Penalty - Scored", "Own Goal"}
# Type Opta (texte ESPN) -> type UEFA utilisé par uefa.compute_momentum / half_stats
TYPES = {
    "Shot On Target": "SHOT_ON_GOAL", "Penalty - Saved": "SHOT_ON_GOAL",
    "Shot Off Target": "SHOT_WIDE", "Shot Hit Woodwork": "SHOT_WIDE", "Penalty - Missed": "SHOT_WIDE",
    "Shot Blocked": "SHOT_BLOCKED", "Save": "SAVE", "Corner Awarded": "CORNER", "Offside": "OFFSIDE",
    "Yellow Card": "YELLOW_CARD", "Red Card": "RED_CARD", "Substitution": "SUBSTITUTION",
    "Pass": "PASS", "Cross": "CROSS", "Tackle": "TACKLE", "Interception": "INTERCEPTION", "Clear": "CLEARANCE",
    "Take On": "TAKE_ON", "Aerial": "AERIAL", "Dispossessed": "DISPOSSESSED", "Ball recovery": "RECOVERY",
}
# Surface de réparation en coordonnées Opta (0-100, sens d'attaque de l'équipe) : x >= 83, 21,1 <= y <= 78,9
SURFACE_X, SURFACE_Y = 83.0, (21.1, 78.9)
uefa.MOMENTUM_WEIGHTS.setdefault("BOX_ENTRY", 2.0)   # remplace l'« attaque dangereuse » UEFA (absente chez Opta)


def _dans_surface(x: Any, y: Any) -> bool:
    return isinstance(x, (int, float)) and isinstance(y, (int, float)) and x >= SURFACE_X and \
        SURFACE_Y[0] <= y <= SURFACE_Y[1]


def _minute(p: Dict[str, Any]) -> Tuple[str, int, float]:
    """(libellé « 45'+3 », minute de base, clé de tri) depuis l'horloge ESPN (« 45'+3' »)."""
    disp = ((p.get("clock") or {}).get("displayValue") or "").replace(" ", "")
    nums = [int(n) for n in re.findall(r"\d+", disp)]
    if not nums:
        return "", 0, 0.0
    base, add = nums[0], (nums[1] if len(nums) > 1 else 0)
    secs = float((p.get("clock") or {}).get("value") or 0)
    return (f"{base}'+{add}" if add else f"{base}'"), base, base + add / 100 + secs / 1e7


def lire_actions(plays: List[Dict[str, Any]], home_espn: str, away_espn: str, noms: Dict[str, str]
                 ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(déroulé affiché, buts, actions) au format de uefa.build_events. Ids des joueurs = `espn-<id>`."""
    def cote(tid: str) -> Optional[str]:
        return "home" if tid == home_espn else "away" if tid == away_espn else None

    def acteur(p: Dict[str, Any], role: Optional[str] = None, rang: int = 0) -> str:
        parts = p.get("participants") or []
        if role:
            parts = [x for x in parts if x.get("type") == role]
        if len(parts) <= rang:
            return ""
        aid = _id_ref(parts[rang].get("athlete"), "athletes")
        return f"espn-{aid}" if aid else ""

    shown, goals, actions = [], [], []
    for p in sorted(plays, key=lambda x: (int((x.get("period") or {}).get("number") or 0),
                                          float((x.get("clock") or {}).get("value") or 0))):
        texte = (p.get("type") or {}).get("text") or ""
        label, minute, sk = _minute(p)
        phase = PHASES.get(int((p.get("period") or {}).get("number") or 0), "")
        side = cote(_id_ref(p.get("team"), "teams"))
        if not phase or not side:
            continue
        autre = "away" if side == "home" else "home"
        if texte in BUTS or (p.get("scoringPlay") and texte.startswith("Goal")):
            csc = bool(p.get("ownGoal")) or texte == "Own Goal"
            pen = bool(p.get("penaltyKick")) or texte in ("Penalty - Scored", "Goal - Penalty")
            buteur, passeur = acteur(p, "scorer") or acteur(p), acteur(p, "assister")
            # Contre son camp : l'action ESPN porte l'équipe qui BÉNÉFICIE du but (vérifié : Barcelone-Villarreal du
            # 22/11/2026, « Own Goal » rattaché à Barcelone, buteur de Villarreal) ; aucune inversion
            equipe = side
            goals.append({"minute": label, "scorer": noms.get(buteur, "—"), "assist": noms.get(passeur) if passeur else None,
                          "team": equipe, "kind": "csc" if csc else "pen" if pen else "", "scorer_id": buteur,
                          "assist_id": passeur, "base_minute": minute, "phase": phase, "sort": sk})
            detail = "Contre son camp" if csc else "Penalty" if pen else \
                (f"Passe déc. : {noms[passeur]}" if passeur in noms else "But")
            shown.append({"minute": minute, "minute_label": label, "type": "goal", "team": equipe,
                          "player": noms.get(buteur, "—"), "player_id": buteur, "detail": detail, "other_id": passeur})
            actions.append({"minute": label, "phase": phase, "type": "GOAL", "team": equipe, "player": noms.get(buteur, ""),
                            "other": "", "sort": sk})
            continue
        t = TYPES.get(texte)
        if texte == "Foul":
            # Faute : l'action ESPN porte l'équipe FAUTIVE ; le coup franc obtenu revient à l'adversaire
            actions.append({"minute": label, "phase": phase, "type": "FOUL", "team": side,
                            "player": noms.get(acteur(p), ""), "other": "", "sort": sk})
            actions.append({"minute": label, "phase": phase, "type": "FREE_KICK", "team": autre,
                            "player": "", "other": "", "sort": sk})
            continue
        if t in ("YELLOW_CARD", "RED_CARD") or texte in ("Second Yellow Card", "Yellow Red Card"):
            rouge = t == "RED_CARD" or "Red" in texte
            pid = acteur(p)
            shown.append({"minute": minute, "minute_label": label, "type": "red_card" if rouge else "yellow_card",
                          "team": side, "player": noms.get(pid, "—"), "player_id": pid,
                          "detail": "Carton rouge" if rouge else "Carton jaune"})
            t = "RED_CARD" if rouge else "YELLOW_CARD"
        elif t == "SUBSTITUTION":
            entrant, sortant = acteur(p, "subbed-in"), acteur(p, "subbed-out")
            shown.append({"minute": minute, "minute_label": label, "type": "sub", "team": side,
                          "player": noms.get(entrant, "Entrant"), "player_id": entrant, "other_id": sortant,
                          "detail": f"Remplace {noms[sortant]}" if sortant in noms else "Entrée en jeu",
                          "_in": entrant, "_out": sortant})
        elif texte.startswith("VAR") and "cancel" in texte.lower():
            shown.append({"minute": minute, "minute_label": label, "type": "var", "team": "neutral",
                          "player": "Arbitrage vidéo", "detail": "Décision annulée après révision"})
        if t in ("PASS", "CROSS") and _dans_surface(p.get("fieldPosition2X"), p.get("fieldPosition2Y")) and \
                not _dans_surface(p.get("fieldPositionX"), p.get("fieldPositionY")):
            actions.append({"minute": label, "phase": phase, "type": "BOX_ENTRY", "team": side, "player": "",
                            "other": "", "sort": sk})
        if t:
            actions.append({"minute": label, "phase": phase, "type": t, "team": side,
                            "player": noms.get(acteur(p), ""), "other": "", "sort": sk,
                            **({"gardien": True} if t == "SAVE" and acteur(p) in _GARDIENS else {})})
    goals.sort(key=lambda g: g.pop("sort"))
    h = a = 0
    for g in goals:
        h, a = (h + 1, a) if g["team"] == "home" else (h, a + 1)
        g["score_after"] = f"{h}-{a}"
    return shown, goals, actions


_GARDIENS: set = set()   # ids `espn-…` des gardiens du match en cours (arrêts du gardien ≠ contres)

# Stats par mi-temps (décision du 25/11/2026 : on en ajoute) : comptage des actions Opta de la période.
# Contrôlé le 25/11 sur 10 équipes : tirs, cadrés, contrés, corners, fautes, tacles, interceptions, dégagements,
# hors-jeu égaux (à 1 près) aux totaux ESPN du match.
MI_TEMPS = [
    ("attempts", "Tirs", lambda a: a["type"] in uefa.SHOT_TYPES),
    ("attempts_on_target", "Tirs cadrés", lambda a: a["type"] in ("GOAL", "SHOT_ON_GOAL")),
    ("attempts_blocked", "Tirs contrés", lambda a: a["type"] == "SHOT_BLOCKED"),
    ("passes_attempted", "Passes tentées", lambda a: a["type"] == "PASS"),
    ("box_entries", "Passes et centres vers la surface", lambda a: a["type"] == "BOX_ENTRY"),
    ("cross_attempted", "Centres tentés", lambda a: a["type"] == "CROSS"),
    ("corners", "Corners", lambda a: a["type"] == "CORNER"),
    ("offsides", "Hors-jeu", lambda a: a["type"] == "OFFSIDE"),
    ("tackles", "Tacles", lambda a: a["type"] == "TACKLE"),
    ("interceptions", "Interceptions", lambda a: a["type"] == "INTERCEPTION"),
    ("clearances", "Dégagements", lambda a: a["type"] == "CLEARANCE"),
    ("saves", "Arrêts du gardien", lambda a: a["type"] == "SAVE" and a.get("gardien")),
    ("fouls_committed", "Fautes commises", lambda a: a["type"] == "FOUL"),
    ("yellow_cards", "Cartons jaunes", lambda a: a["type"] == "YELLOW_CARD"),
]


def stats_mi_temps(actions: List[Dict[str, Any]], phase: str) -> List[Dict[str, Any]]:
    acts = [a for a in actions if a["phase"] == phase and a["team"] in ("home", "away")]
    if not acts:
        return []
    out = []
    for k, lbl, f in MI_TEMPS:
        h = sum(1 for a in acts if a["team"] == "home" and f(a))
        w = sum(1 for a in acts if a["team"] == "away" and f(a))
        if k == "saves" and not (h or w):
            continue
        out.append({"key": k, "label": lbl, "home": h, "away": w})
    return out


# ------------------------------------------------------------------------------
# Stats d'équipe (core ESPN) : clés UEFA quand elles existent (rubriques d'index.html), sinon clés propres
# ------------------------------------------------------------------------------
STATS_EQUIPE = [
    ("possessionPct", "ball_possession", "Possession (%)", 1),
    ("totalShots", "attempts", "Tirs", 1), ("shotsOnTarget", "attempts_on_target", "Tirs cadrés", 1),
    ("shotsOffTarget", "attempts_off_target", "Tirs non cadrés", 1), ("blockedShotsTaken", "attempts_blocked", "Tirs contrés", 1),
    ("attemptsIbox", "shot_in_penalty_area", "Tirs dans la surface", 1), ("hitWoodwork", "woodwork", "Poteaux / transversales", 1),
    ("bigChanceCreated", "big_chances", "Grosses occasions", 1),
    ("expectedGoals", "xg", "Buts attendus (xG)", 1), ("expectedGoalsOnTarget", "xgot", "xG des tirs cadrés (xGOT)", 1),
    ("expectedGoalsNonPenalty", "xg_sans_penalty", "xG hors penalty", 1), ("expectedAssists", "xa", "Passes décisives attendues (xA)", 1),
    ("accuratePasses", "passes_completed", "Passes réussies", 1), ("passPct", "passes_accuracy", "Précision des passes (%)", 100),
    ("shotAssists", "key_passes", "Passes clés", 1), ("penAreaEntries", "delivery_into_penalty_area", "Entrées dans la surface", 1),
    ("totalCrosses", "cross_attempted", "Centres tentés", 1), ("accurateLongBalls", "long_balls", "Longs ballons réussis", 1),
    ("finalThirdEntries", "final_third_entries", "Entrées dans le dernier tiers", 1),
    ("touchesInOppBox", "touches_opp_box", "Touches dans la surface adverse", 1),
    ("wonCorners", "corners", "Corners", 1), ("offsides", "offsides", "Hors-jeu", 1),
    ("wonContest", "dribbles", "Dribbles réussis", 1),
    ("saves", "saves", "Arrêts du gardien", 1), ("ballRecovery", "recovered_ball", "Ballons récupérés", 1),
    ("effectiveTackles", "tackles_won", "Tacles réussis", 1), ("interceptions", "interceptions", "Interceptions", 1),
    ("totalClearance", "clearances", "Dégagements", 1), ("duelsWon", "duels_won", "Duels gagnés", 1),
    ("aerialsWon", "aerials_won", "Duels aériens gagnés", 1), ("ppda", "ppda", "PPDA (passes adverses par action défensive)", 1),
    ("foulsCommitted", "fouls_committed", "Fautes commises", 1), ("yellowCards", "yellow_cards", "Cartons jaunes", 1),
    ("redCards", "red_cards", "Cartons rouges", 1),
]
XG_CLES = {"xg", "xgot", "xg_sans_penalty", "xa"}


def stats_equipe(ligue: str, event_id: str, team_id: str) -> Tuple[Optional[Dict[str, float]], str]:
    data, statut = _get(f"{CORE}/{LIGUES[ligue]['slug']}/events/{event_id}/competitions/{event_id}"
                        f"/competitors/{team_id}/statistics")
    if statut != "ok":
        return None, statut
    val: Dict[str, float] = {}
    for cat in ((data or {}).get("splits") or {}).get("categories", []) or []:
        for s in cat.get("stats", []) or []:
            v = s.get("value")
            if s.get("name") and isinstance(v, (int, float)) and not isinstance(v, bool) and s["name"] not in val:
                val[s["name"]] = float(v)
    return (val, "ok") if val else (None, "absent")


def construire_stats(h: Dict[str, float], a: Dict[str, float]) -> List[Dict[str, Any]]:
    """Lignes {key, label, home, away} ; une stat n'est gardée que si les DEUX équipes l'ont. Tirs contrés = tirs de
    l'équipe contrés par l'adversaire (= `blockedShots` de l'adversaire : contrôlé égal au comptage des actions)."""
    h, a = dict(h), dict(a)
    if "blockedShots" in a and "blockedShots" in h:
        h["blockedShotsTaken"], a["blockedShotsTaken"] = a["blockedShots"], h["blockedShots"]
    out = []
    for nom, cle, lib, mult in STATS_EQUIPE:
        if nom not in h or nom not in a:
            continue
        hv, av = h[nom] * mult, a[nom] * mult
        if cle == "red_cards" and hv == 0 and av == 0:
            continue
        if cle == "xg_sans_penalty" and abs(h[nom] - h.get("expectedGoals", -1)) < 1e-9 and \
                abs(a[nom] - a.get("expectedGoals", -1)) < 1e-9:
            continue   # aucun penalty : même valeur que l'xG
        dec = 3 if cle in XG_CLES else 1
        hv, av = round(hv, dec), round(av, dec)
        out.append({"key": cle, "label": lib, "home": int(hv) if hv == int(hv) and cle not in XG_CLES else hv,
                    "away": int(av) if av == int(av) and cle not in XG_CLES else av})
    return out


# ------------------------------------------------------------------------------
# Joueurs : stats Opta -> clés UEFA (ratings.py, fiche joueur d'index.html) + clés Opta propres
# ------------------------------------------------------------------------------
# (clé UEFA, fonction des stats ESPN) ; documenté dans docs/etude_championnats.md (§ notes)
JOUEUR_CLES: List[Tuple[str, Any]] = [
    ("minutes_played_official", lambda s: s.get("minutes")),
    ("goals", lambda s: s.get("totalGoals")), ("assists", lambda s: s.get("goalAssists")),
    ("attempts", lambda s: s.get("totalShots")), ("attempts_on_target", lambda s: s.get("shotsOnTarget")),
    ("attempts_off_target", lambda s: s.get("shotsOffTarget")),
    ("key_passes", lambda s: s.get("shotAssists")),                           # Opta : passe menant à un tir
    ("dribbling", lambda s: s.get("totalContest")), ("dribbling_successful", lambda s: s.get("wonContest")),
    ("cross_attempted", lambda s: s.get("totalCrosses")), ("cross_completed", lambda s: s.get("accurateCrosses")),
    ("offsides", lambda s: s.get("offsides")),
    ("passes_attempted", lambda s: s.get("totalPasses")), ("passes_completed", lambda s: s.get("accuratePasses")),
    ("passes_accuracy", lambda s: round(100 * s["passPct"]) if s.get("totalPasses") and "passPct" in s else None),
    # Passes courtes réussies : passes réussies - longs ballons réussis (Opta ne publie pas la valeur ici)
    ("passes_short_completed", lambda s: (s["accuratePasses"] - s.get("accurateLongBalls", 0))
     if "accuratePasses" in s else None),
    ("passes_completed_forward", lambda s: s.get("successfulFinalThirdPasses")),   # substitut : passes réussies dans le dernier tiers
    ("delivery_into_penalty_area", lambda s: s.get("penAreaEntries")),
    ("recovered_ball", lambda s: s.get("ballRecovery")),
    ("tackles", lambda s: s.get("totalTackles")), ("tackles_won", lambda s: s.get("effectiveTackles")),
    ("clearance_attempted", lambda s: s.get("totalClearance")), ("clearance_completed", lambda s: s.get("effectiveClearance")),
    ("saves_and_blocks", lambda s: s.get("outfielderBlock")),
    ("lost_balls", lambda s: s.get("turnover")),
    ("fouls_committed", lambda s: s.get("foulsCommitted")), ("fouls_suffered", lambda s: s.get("foulsSuffered")),
    ("yellow_cards", lambda s: s.get("yellowCards")), ("red_cards", lambda s: s.get("redCards")),
    ("saves", lambda s: s.get("saves")), ("goals_conceded", lambda s: s.get("goalsConceded")),
    ("shots_on_target_suffered", lambda s: s.get("shotsOnGoalAgainst")),
    # Stats Opta sans équivalent UEFA (fiche joueur)
    ("xg", lambda s: s.get("expectedGoals")), ("xgot", lambda s: s.get("expectedGoalsOnTarget")),
    ("xa", lambda s: s.get("expectedAssists")), ("big_chances_created", lambda s: s.get("bigChanceCreated")),
    ("big_chances_missed", lambda s: s.get("bigChanceMissed")), ("touches", lambda s: s.get("touches")),
    ("interceptions", lambda s: s.get("interceptions")), ("duels_won", lambda s: s.get("duelsWon")),
    ("duels", lambda s: s.get("duels")), ("aerials_won", lambda s: s.get("aerialsWon")),
    ("aerials", lambda s: (s["aerialsWon"] + s.get("aerialsLost", 0)) if "aerialsWon" in s else None),
    ("progressive_carries", lambda s: s.get("progressiveCarries")),
    ("goals_prevented", lambda s: s.get("goalsPrevented")),
]


def stats_joueur(brut: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    s: Dict[str, float] = {}
    for cat in ((brut or {}).get("splits") or {}).get("categories", []) or []:
        for st in cat.get("stats", []) or []:
            v = st.get("value")
            if st.get("name") and isinstance(v, (int, float)) and not isinstance(v, bool) and st["name"] not in s:
                s[st["name"]] = float(v)
    out: Dict[str, Any] = {}
    for cle, f in JOUEUR_CLES:
        try:
            v = f(s)
        except (KeyError, TypeError):
            v = None
        if v is None or v == 0:
            continue   # comme l'UEFA : une stat nulle n'est pas stockée (la fiche n'affiche que les valeurs non nulles)
        out[cle] = round(v, 3) if isinstance(v, float) and v != int(v) else int(v)
    if not s.get("goalsConceded") and s.get("minutes", 0) >= 60 and "cleanSheet" in s and s["cleanSheet"]:
        out["clean_sheet"] = 1
    return out


POSTE = {"Goalkeeper": "GOALKEEPER", "Defender": "DEFENDER", "Midfielder": "MIDFIELDER", "Forward": "FORWARD"}
# Poste Opta du match (abréviation ESPN) -> (ligne, côté). Lignes (profondeur) : 0 gardien, 1 défense, 2 milieu
# défensif, 3 milieu, 4 milieu offensif, 5 attaque. Côté : R / C / L (droite, centre, gauche) DU POINT DE VUE DE L'ÉQUIPE.
_LIGNE = [(re.compile(r"^G$"), 0), (re.compile(r"^(SW|CD.*|LB|RB|LWB|RWB|D.*)$"), 1), (re.compile(r"^DM.*$"), 2),
          (re.compile(r"^(CM.*|LM|RM|M)$"), 3), (re.compile(r"^AM.*$"), 4),
          (re.compile(r"^(F|CF.*|LF|RF|RCF|S|LW|RW|ST)$"), 5)]
PROFONDEUR = {0: 6.2, 1: 15.0, 2: 22.0, 3: 29.0, 4: 37.0, 5: 45.0}   # même échelle que les compos UEFA (domicile)


def _ligne_cote(abbr: str) -> Tuple[int, int]:
    """(ligne, largeur) d'un poste Opta. Largeur, du point de vue de l'équipe : 0 couloir droit (RB, RM, RW…), 1 axe
    droit (CD-R, CM-R…), 2 axe, 3 axe gauche, 4 couloir gauche."""
    a = (abbr or "").upper()
    ligne = next((n for rx, n in _LIGNE if rx.match(a)), 3)
    if a in ("RB", "RWB", "RM", "RF", "RW"):
        largeur = 0
    elif a in ("LB", "LWB", "LM", "LF", "LW"):
        largeur = 4
    elif a.endswith("-R"):
        largeur = 1
    elif a.endswith("-L"):
        largeur = 3
    else:
        largeur = 2
    return ligne, largeur


def placer(titulaires: List[Dict[str, Any]], side: str) -> List[Tuple[float, float]]:
    """Positions (x, y) en % au format des compos UEFA : la profondeur vient de la ligne du poste Opta, l'ordre dans la
    ligne de la largeur du poste (droite -> x petit pour l'équipe à domicile, comme les compos UEFA vérifiées : Hakimi 20,
    Nuno Mendes 80), puis répartition régulière. index.html (lineupRows) redécoupe selon la formation."""
    par_ligne: Dict[int, List[Tuple[int, int]]] = {}
    for i, p in enumerate(titulaires):
        ligne, largeur = _ligne_cote(p.get("_abbr", ""))
        par_ligne.setdefault(ligne, []).append((i, largeur))
    pos: Dict[int, Tuple[float, float]] = {}
    for ligne, membres in par_ligne.items():
        membres.sort(key=lambda m: (m[1], m[0]))
        n = len(membres)
        for k, (i, largeur) in enumerate(membres):
            x = 15 + 70 * k / (n - 1) if n > 1 else 15 + 17.5 * largeur
            y = PROFONDEUR[ligne]
            pos[i] = (round(x if side == "home" else 100 - x, 1), round(y if side == "home" else 100 - y, 1))
    return [pos[i] for i in range(len(titulaires))]


_EFFECTIFS: Dict[str, Dict[str, Dict[str, Any]]] = {}


def effectif(ligue: str, team_id: str) -> Dict[str, Dict[str, Any]]:
    """Effectif ESPN d'un club (poste général, âge, nationalité, photo), lu une fois par passage."""
    cle = f"{ligue}/{team_id}"
    if cle not in _EFFECTIFS:
        data, _ = _get(f"{SITE}/{LIGUES[ligue]['slug']}/teams/{team_id}/roster")
        _EFFECTIFS[cle] = {str(a.get("id")): a for a in (data or {}).get("athletes") or []}
    return _EFFECTIFS[cle]


NATIONALITES_FR: Dict[str, str] = {}   # rempli à la demande (nom anglais ESPN conservé si inconnu)


def joueurs_et_compos(ligue: str, summary: Dict[str, Any], match: Dict[str, Any], subs: List[Dict[str, Any]],
                      avec_stats: bool) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]]]:
    slug = LIGUES[ligue]["slug"]
    ev = match["espn_id"]
    entrees = {s["_in"]: s for s in subs if s.get("_in")}
    sorties = {s["_out"]: s for s in subs if s.get("_out")}
    players: Dict[str, Dict[str, Any]] = {}
    out: Dict[str, Any] = {"home": [], "away": [], "home_subs": [], "away_subs": [],
                           "home_formation": "", "away_formation": "", "home_coach": "", "away_coach": ""}
    for ro in summary.get("rosters") or []:
        side = ro.get("homeAway")
        if side not in ("home", "away"):
            continue
        team_id = str((ro.get("team") or {}).get("id", ""))
        out[f"{side}_formation"] = ro.get("formation") or ""
        couleur = ((ro.get("uniform") or {}).get("color") or "").lower()
        if re.fullmatch(r"[0-9a-f]{6}", couleur):
            match[f"{side}_team"]["shirt_color"] = "#" + couleur
        eff = effectif(ligue, team_id)
        titulaires = []
        for r in ro.get("roster") or []:
            ath = r.get("athlete") or {}
            aid = str(ath.get("id", ""))
            pid = f"espn-{aid}"
            joue = bool(r.get("starter")) or bool(r.get("subbedIn"))
            if not joue:
                continue
            fiche = eff.get(aid, {})
            pos = POSTE.get(((fiche.get("position") or {}).get("name")) or "", "")
            abbr = ((r.get("position") or {}).get("abbreviation") or "")
            if not pos and abbr:
                pos = ["GOALKEEPER", "DEFENDER", "DEFENDER", "MIDFIELDER", "MIDFIELDER", "FORWARD"][_ligne_cote(abbr)[0]]
            if pos == "GOALKEEPER":
                _GARDIENS.add(pid)
            stats: Dict[str, Any] = {}
            if avec_stats:
                brut, _ = _get(f"{CORE}/{slug}/events/{ev}/competitions/{ev}/competitors/{team_id}/roster/{aid}/statistics/0")
                stats = stats_joueur(brut)
            e_in, e_out = entrees.get(pid), sorties.get(pid)
            minutes = stats.get("minutes_played_official")
            if minutes is None:
                debut = 0 if r.get("starter") else (e_in["minute"] if e_in else 90)
                minutes = max(0, (e_out["minute"] if e_out else 90) - debut)
            cit = fiche.get("citizenshipCountry") or {}
            code = (cit.get("abbreviation") or "").upper()
            players[pid] = {
                "id": pid, "name": ath.get("displayName") or "", "short": ath.get("lastName") or ath.get("shortName") or "",
                "number": str(r.get("jersey") or ""), "team": side, "pos": pos,
                "pos_fr": uefa.POSITION_FR.get(pos, ""), "poste_opta": abbr,
                "nationality": fiche.get("citizenship") or "", "flag": FLAG_CODES.get(code, ""),
                "age": fiche.get("age"), "photo": ((ath.get("headshot") or {}).get("href") or ""),
                "captain": False, "potm": False, "starter": bool(r.get("starter")),
                "subbed_in": e_in["minute_label"] if e_in else None, "subbed_in_minute": e_in["minute"] if e_in else None,
                "subbed_out": e_out["minute_label"] if e_out else None, "subbed_out_minute": e_out["minute"] if e_out else None,
                "minutes": int(minutes or 0), "stats": stats, "rating": None, "factors": [],
            }
            if r.get("starter"):
                titulaires.append({"_abbr": abbr, "pid": pid})
            else:
                c = players[pid]
                out[f"{side}_subs"].append({"id": pid, "number": c["number"], "name": c["short"],
                                            "minute": c["subbed_in"], "potm": False, "rating": None})
        for t, (x, y) in zip(titulaires, placer(titulaires, side)):
            c = players[t["pid"]]
            out[side].append({"id": c["id"], "number": c["number"], "name": c["short"], "pos": c["pos"],
                              "captain": False, "potm": False, "x": x, "y": y, "rating": None,
                              "subbed_out": c["subbed_out"]})
    return out, players


# ------------------------------------------------------------------------------
# Match complet
# ------------------------------------------------------------------------------
def plays_complets(ligue: str, event_id: str) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    items: List[Dict[str, Any]] = []
    page = 1
    while True:
        data, statut = _get(f"{CORE}/{LIGUES[ligue]['slug']}/events/{event_id}/competitions/{event_id}"
                            f"/plays?limit=1000&page={page}")
        if statut != "ok":
            return None, statut
        items += data.get("items") or []
        if page >= int(data.get("pageCount") or 1):
            return items, "ok"
        page += 1


def completer_match(ligue: str, match: Dict[str, Any], avec_stats_joueurs: bool = True) -> str:
    """Détails d'un match terminé (déroulé, compos, stats, xG, momentum, joueurs). Retourne « ok » ou « erreur »
    (le match reste alors au niveau de base : le passage suivant réessaie)."""
    ev = match["espn_id"]
    summary, st = _get(f"{SITE_WEB}/{LIGUES[ligue]['slug']}/summary?event={ev}")
    if st != "ok":
        return "erreur"
    plays, st = plays_complets(ligue, ev)
    if st != "ok":
        return "erreur"
    h, a = match["home_team"], match["away_team"]
    venue = ((summary.get("gameInfo") or {}).get("venue") or {})
    if venue.get("fullName"):
        match["venue"] = venue["fullName"]
    att = (summary.get("gameInfo") or {}).get("attendance")
    match["attendance"] = att if isinstance(att, int) and att > 0 else None
    # Noms des joueurs (déroulé) depuis les compos du résumé
    noms = {f"espn-{(r.get('athlete') or {}).get('id')}": (r.get("athlete") or {}).get("displayName") or ""
            for ro in summary.get("rosters") or [] for r in ro.get("roster") or []}
    _GARDIENS.clear()
    for ro in summary.get("rosters") or []:
        for r in ro.get("roster") or []:
            if ((r.get("position") or {}).get("abbreviation") or "") == "G":
                _GARDIENS.add(f"espn-{(r.get('athlete') or {}).get('id')}")
    shown, goals, actions = lire_actions(plays, h["espn_id"], a["espn_id"], noms)
    subs = [s for s in shown if s["type"] == "sub"]
    lineups, players = joueurs_et_compos(ligue, summary, match, subs, avec_stats_joueurs)
    for s in shown:
        s.pop("_in", None)
        s.pop("_out", None)
    h["formation"], a["formation"] = lineups.get("home_formation", ""), lineups.get("away_formation", "")
    sh, s1 = stats_equipe(ligue, ev, h["espn_id"])
    sa, s2 = stats_equipe(ligue, ev, a["espn_id"])
    if "erreur" in (s1, s2):
        return "erreur"
    reduit = flux_reduit(ligue)
    match.update({
        "events": shown, "goals": goals, "momentum": [] if reduit else uefa.compute_momentum(actions),
        "lineups": lineups, "players": players,
        "stats": {"all": construire_stats(sh, sa) if sh and sa else [],
                  "1st": [] if reduit else stats_mi_temps(actions, "FIRST_HALF"),
                  "2nd": [] if reduit else stats_mi_temps(actions, "SECOND_HALF")},
        "source": "ESPN" if reduit else SOURCE, "actions_opta": len(plays),
        **({"flux": "reduit"} if reduit else {}),
    })
    if sh and sa and "expectedGoals" in sh and "expectedGoals" in sa:
        match["xg_source"] = SOURCE
    officiel = f"{h['score']}-{a['score']}"
    if (goals[-1]["score_after"] if goals else "0-0") != officiel:
        print(f"[WARN] {h['name']}-{a['name']} : buts reconstitués {goals[-1]['score_after'] if goals else '0-0'} "
              f"≠ score officiel {officiel}")
        match["buts_incomplets"] = True
    return "ok"


# ------------------------------------------------------------------------------
# Classement
# ------------------------------------------------------------------------------
ZONES = [("champions", "ucl"), ("europa league", "uel"), ("conference", "uecl"), ("relegation playoff", "barrage"),
         ("relegation", "relegation"), ("promotion playoff", "barrage_promo"), ("promotion", "promotion")]


def classement(ligue: str) -> Tuple[List[Dict[str, Any]], str]:
    data, statut = _get(f"{STANDINGS}/{LIGUES[ligue]['slug']}/standings")
    if statut != "ok":
        return [], statut
    entries = (((data.get("children") or [{}])[0].get("standings") or {}).get("entries")) or []
    pays = LIGUES[ligue]["country"]
    rows = []
    for e in entries:
        t = e.get("team") or {}
        s = {x.get("name"): x.get("value") for x in e.get("stats") or []}
        if s.get("rank") is None:
            continue
        note = ((e.get("note") or {}).get("description") or "").lower()
        zone = next((z for motif, z in ZONES if motif in note), None)
        gd = int(s.get("pointDifferential") or 0)
        rows.append({
            "rank": int(s["rank"]), "team_id": f"espn-{t.get('id')}", "team": (t.get("shortDisplayName") or t.get("displayName") or "").strip(),
            "short_name": t.get("abbreviation", ""), "country": pays, "country_name": LIGUES[ligue]["country_name"],
            "flag": FLAG_CODES.get(pays, ""), "logo": next((l.get("href") for l in t.get("logos") or []), ""),
            "is_french": pays == "FRA", "played": int(s.get("gamesPlayed") or 0), "won": int(s.get("wins") or 0),
            "drawn": int(s.get("ties") or 0), "lost": int(s.get("losses") or 0), "gf": int(s.get("pointsFor") or 0),
            "ga": int(s.get("pointsAgainst") or 0), "gd": f"+{gd}" if gd > 0 else str(gd), "points": int(s.get("points") or 0),
            **({"zone": zone, "zone_libelle": (e.get("note") or {}).get("description")} if zone else {}),
            **({"penalite": int(s["deductions"])} if str(s.get("deductions") or "").lstrip("-").isdigit() and s.get("deductions") else {}),
        })
    rows.sort(key=lambda r: r["rank"])
    return rows, "ok"


# ------------------------------------------------------------------------------
# Saison complète (journées, reconstitution) : calendrier de chaque club, 2 requêtes par club
# ------------------------------------------------------------------------------
def equipes(ligue: str) -> Dict[str, List[str]]:
    """{id ESPN: [noms]} des clubs du championnat (classement ESPN)."""
    data, statut = _get(f"{STANDINGS}/{LIGUES[ligue]['slug']}/standings")
    out = {}
    for e in ((((data or {}).get("children") or [{}])[0].get("standings") or {}).get("entries")) or []:
        t = e.get("team") or {}
        out[str(t.get("id"))] = [x for x in (t.get("displayName"), t.get("shortDisplayName"), t.get("name"),
                                             t.get("location"), t.get("abbreviation")) if x]
    return out


def saison(ligue: str, annee: int, clubs: Optional[Dict[str, List[str]]] = None) -> Optional[List[Dict[str, Any]]]:
    """Tous les matchs de championnat de la saison (`annee` = année de début, ESPN `season=2026` pour 2026-27) :
    [{espn_id, home, away (ids ESPN), date_utc, score (h, a) si terminé, statut}]. None si une liste est illisible."""
    clubs = clubs or equipes(ligue)
    slug = LIGUES[ligue]["slug"]
    vus: Dict[str, Dict[str, Any]] = {}
    for tid in clubs:
        for suffixe in ("", "&fixture=true"):
            data, statut = _get(f"{SITE}/{slug}/teams/{tid}/schedule?season={annee}{suffixe}")
            if statut != "ok":
                return None
            for ev in data.get("events") or []:
                if ((ev.get("league") or {}).get("slug") or slug) != slug:
                    continue
                comp = (ev.get("competitions") or [{}])[0]
                cs = comp.get("competitors") or []
                h = next((c for c in cs if c.get("homeAway") == "home"), None)
                a = next((c for c in cs if c.get("homeAway") == "away"), None)
                if not h or not a:
                    continue
                st = ((comp.get("status") or ev.get("status") or {}).get("type") or {})
                fini = bool(st.get("completed"))

                def sc(c: Dict[str, Any]) -> Optional[int]:
                    v = c.get("score")
                    v = v.get("value") if isinstance(v, dict) else v
                    try:
                        return int(float(v))
                    except (TypeError, ValueError):
                        return None
                score = (sc(h), sc(a)) if fini and sc(h) is not None and sc(a) is not None else None
                vus[str(ev.get("id"))] = {"espn_id": str(ev.get("id")), "home": str(h["team"]["id"]),
                                          "away": str(a["team"]["id"]), "date_utc": ev.get("date", ""),
                                          "score": score, "statut": st.get("name", ""),
                                          "equipes": [_equipe(h, ligue), _equipe(a, ligue)],
                                          "stade": ((comp.get("venue") or {}).get("fullName") or "").strip()}
    return sorted(vus.values(), key=lambda m: m["date_utc"])


def programme(ligue: str, ms: List[Dict[str, Any]], journees: Dict[str, int], maintenant: datetime) -> Dict[str, Any]:
    """Matchs À VENIR de la saison (calendrier ESPN de `saison`) : non terminés, programmés après `maintenant` - 3 h, ou
    reportés. Journée = celle de Wikipédia (`journees.json`) si connue, sinon absente (jamais devinée)."""
    seuil = (maintenant - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M")
    out = []
    for m in ms:
        if m.get("score") is not None or m.get("statut") in ("STATUS_CANCELED", "STATUS_ABANDONED"):
            continue
        reporte = m.get("statut") == "STATUS_POSTPONED"
        if not reporte and (m.get("date_utc") or "") < seuil:
            continue
        d = _dt(m.get("date_utc") or "")
        eqs = []
        for e in m.get("equipes") or []:
            e = dict(e); e.pop("score", None); eqs.append(e)
        if len(eqs) != 2:
            continue
        x = {"id": f"espn-{m['espn_id']}", "debut": m.get("date_utc") or "",
             "date": d.astimezone(_PARIS).date().isoformat() if d else "",
             "home_team": eqs[0], "away_team": eqs[1], "statut": STATUT_FR.get(m.get("statut") or "", "À venir")}
        if journees.get(m["espn_id"]):
            x["journee"] = int(journees[m["espn_id"]])
        if m.get("stade"):
            x["stade"] = m["stade"]
        out.append(x)
    out.sort(key=lambda x: (x["debut"], x["id"]))
    return {"ligue": ligue, "source": "ESPN", "matchs": out}


# ------------------------------------------------------------------------------
# Collecte d'un jour
# ------------------------------------------------------------------------------
def collecter_jour(jour: str, ligues: Optional[List[str]] = None, avec_stats_joueurs: bool = True,
                   max_matchs: Optional[int] = None) -> Dict[str, Any]:
    """Tous les matchs du jour (heure de Paris) des championnats demandés. Jour ESPN = heure de l'Est : on lit la
    veille et le jour pour couvrir tous les coups d'envoi du jour de Paris."""
    ligues = ligues or list(LIGUES)
    sortie: Dict[str, Any] = {"date": jour, "source": SOURCE, "competitions": {},
                              "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    veille = (date.fromisoformat(jour) - timedelta(days=1)).isoformat()
    n = 0
    for lg in ligues:
        vus, matchs, incomplet = set(), [], False
        for j in (veille, jour):
            evs, st = scoreboard(lg, j)
            incomplet |= st != "ok"
            for ev in evs:
                m = match_de_base(lg, ev)
                if m["date"] != jour or m["espn_id"] in vus:
                    continue
                vus.add(m["espn_id"])
                if m["finished"] and (max_matchs is None or n < max_matchs):
                    n += 1
                    t0 = time.time()
                    r = completer_match(lg, m, avec_stats_joueurs)
                    print(f"[INFO] {LIGUES[lg]['short_name']} {m['home_team']['name']} {m['home_team']['score']}-"
                          f"{m['away_team']['score']} {m['away_team']['name']} : {r}, {m.get('actions_opta', 0)} actions, "
                          f"{len(m['players'])} joueurs, {time.time() - t0:.0f} s")
                    if r != "ok":
                        m["detail_manquant"] = True
                        incomplet = True
                matchs.append(m)
        rows, st = classement(lg)
        rated = [] if flux_reduit(lg) else [m for m in matchs if m.get("players")]
        notes = ratings.rate_matches(rated) if rated else {}
        sortie["competitions"][lg] = {
            "id": lg, "name": LIGUES[lg]["name"], "short_name": LIGUES[lg]["short_name"], "stage_type": "league",
            "matches": sorted(matchs, key=lambda x: (x["date_utc"], x["home_team"]["name"])),
            "standings": rows, "standings_source": "officiel" if rows else "absent",
            "incomplet": incomplet, "notes": notes,
        }
        print(f"[INFO] {LIGUES[lg]['name']} : {len(matchs)} match(s) le {jour}, classement {len(rows)} lignes")
    print(f"[INFO] {REQUETES['n']} requête(s) ESPN, {REQUETES['erreurs']} en erreur")
    return sortie


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Collecte ESPN des championnats (big 5)")
    ap.add_argument("--date", required=True)
    ap.add_argument("--ligues", help="fl1,pl,liga,sa,bl")
    ap.add_argument("--max-matchs", type=int)
    ap.add_argument("--sans-joueurs", action="store_true", help="sans les stats individuelles (~30 requêtes de moins par match)")
    ap.add_argument("--sortie", default="ligues_raw.json")
    args = ap.parse_args()
    res = collecter_jour(args.date, args.ligues.split(",") if args.ligues else None, not args.sans_joueurs, args.max_matchs)
    with open(args.sortie, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(f"[OK] -> {args.sortie}")
