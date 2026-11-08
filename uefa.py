#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Source principale : API publique d'uefa.com (données officielles, en français).

Endpoints utilisés (vérifiés depuis GitHub Actions le 08/11/2026) :
  match.uefa.com/v5/matches?competitionId=..&fromDate=..&toDate=..   liste des matchs
  match.uefa.com/v5/matches/{id}/lineups                              compositions + coordonnées
  match.uefa.com/v5/matches/{id}/events?filter=ALL                    toutes les actions (tirs, arrêts...)
  matchstats.uefa.com/v1/team-statistics/{id}                         ~430 stats par équipe
  matchstats.uefa.com/v1/player-statistics/{id}                       ~380 stats par joueur
  standings.uefa.com/v1/standings?competitionId=..&seasonYear=..       classement

Pièges connus :
  - team-statistics n'est PAS ordonné domicile/extérieur : on associe par teamId.
  - SUBSTITUTION : primaryActor = joueur qui SORT, secondaryActor = joueur qui ENTRE.
  - GOAL : secondaryActor = gardien battu (le passeur est dans un événement ASSIST).
"""

from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from netutil import fetch_json, fr, to_number

COMPETITION_IDS = {"ucl": 1, "uel": 14, "uecl": 2019}
STATUS_FR = {"FINISHED": "Terminé", "LIVE": "En cours", "UPCOMING": "À venir", "POSTPONED": "Reporté",
             "CANCELLED": "Annulé", "ABANDONED": "Arrêté"}

# Statistiques d'équipe retenues pour l'affichage (clé UEFA, libellé)
TEAM_STATS = [
    ("ball_possession", "Possession (%)"),
    ("attempts", "Tirs"),
    ("attempts_on_target", "Tirs cadrés"),
    ("attempts_off_target", "Tirs non cadrés"),
    ("attempts_blocked", "Tirs contrés"),
    ("shot_in_penalty_area", "Tirs dans la surface"),
    ("saves", "Arrêts du gardien"),
    ("attacks", "Attaques"),
    ("counterattack", "Contre-attaques"),
    ("key_passes", "Passes clés"),
    ("delivery_into_penalty_area", "Passes dans la surface"),
    ("corners", "Corners"),
    ("cross_attempted", "Centres tentés"),
    ("passes_completed", "Passes réussies"),
    ("passes_accuracy", "Précision des passes (%)"),
    ("recovered_ball", "Ballons récupérés"),
    ("fouls_committed", "Fautes commises"),
    ("offsides", "Hors-jeu"),
    ("yellow_cards", "Cartons jaunes"),
    ("red_cards", "Cartons rouges"),
    ("distance_covered", "Distance parcourue (km)"),
    ("top_speed", "Vitesse max. (km/h)"),
    ("sprints", "Sprints"),
]

# Statistiques individuelles conservées (pour les compos et le dossier de l'IA)
PLAYER_STATS = {
    "minutes_played_official": "minutes", "goals": "buts", "assists": "passes_dec", "attempts": "tirs",
    "attempts_on_target": "tirs_cadres", "key_passes": "passes_cles", "passes_accuracy": "precision_passes",
    "recovered_ball": "ballons_recuperes", "saves": "arrets", "distance_covered": "distance_km",
    "top_speed": "vitesse_max", "dribbling_successful": "dribbles_reussis",
}

SHOT_TYPES = {"GOAL", "SHOT_ON_GOAL", "SHOT_WIDE", "SHOT_BLOCKED"}
MOMENTUM_WEIGHTS = {"GOAL": 5.0, "SHOT_ON_GOAL": 3.0, "SHOT_WIDE": 2.0, "SHOT_BLOCKED": 1.5, "CORNER": 1.0}


# ------------------------------------------------------------------------------
# Utilitaires
# ------------------------------------------------------------------------------
def person_name(person: Optional[Dict[str, Any]], short: bool = False) -> str:
    if not person:
        return ""
    if short:
        return fr(person.get("translations"), "shortName") or person.get("internationalName", "")
    return person.get("internationalName") or fr(person.get("translations"), "name")


def time_of(ev: Dict[str, Any]) -> Tuple[str, int, float]:
    """(libellé « 45'+3 », minute de base, clé de tri)."""
    t = ev.get("time") or {}
    minute = int(to_number(t.get("minute")) or 0)
    inj = int(to_number(t.get("injuryMinute")) or 0)
    sec = int(to_number(t.get("second")) or 0)
    label = f"{minute}'+{inj}" if inj else (f"{minute}'" if minute else "")
    return label, minute, minute + inj / 100 + sec / 10000


def season_year_for(d: date) -> int:
    return d.year + 1 if d.month >= 7 else d.year


def team_info(t: Dict[str, Any]) -> Dict[str, Any]:
    tr = t.get("translations")
    return {
        "id": str(t.get("id", "")),
        "name": fr(tr, "displayName", t.get("internationalName", "")),
        "official_name": fr(tr, "displayOfficialName", t.get("internationalName", "")),
        "short": t.get("teamCode") or fr(tr, "displayTeamCode"),
        "country": t.get("countryCode", ""),
        "is_french": (t.get("countryCode") or "").upper() == "FRA",
        "logo": t.get("mediumLogoUrl") or t.get("logoUrl", ""),
    }


# ------------------------------------------------------------------------------
# Appels API
# ------------------------------------------------------------------------------
def fetch_matches(comp_key: str, dates: List[str]) -> List[Dict[str, Any]]:
    cid = COMPETITION_IDS[comp_key]
    d_from = min(dates)
    d_to = (date.fromisoformat(max(dates)) + timedelta(days=1)).isoformat()
    data = fetch_json(f"https://match.uefa.com/v5/matches?competitionId={cid}&fromDate={d_from}&toDate={d_to}"
                      f"&offset=0&limit=200&order=ASC&language=FR", raw_name=f"uefa_matches_{comp_key}.json")
    wanted = set(dates)
    return [m for m in (data or []) if ((m.get("kickOffTime") or {}).get("date") or "")[:10] in wanted]


def fetch_events(match_id: str) -> List[Dict[str, Any]]:
    data = fetch_json(f"https://match.uefa.com/v5/matches/{match_id}/events?filter=ALL&offset=0&limit=1000"
                      f"&order=ASC&language=FR", raw_name=f"uefa_events_{match_id}.json")
    evs = data if isinstance(data, list) else []
    evs.sort(key=lambda e: (0 if e.get("phase") == "FIRST_HALF" else 1, time_of(e)[2]))
    return evs


def fetch_lineups(match_id: str) -> Dict[str, Any]:
    return fetch_json(f"https://match.uefa.com/v5/matches/{match_id}/lineups?language=FR",
                      raw_name=f"uefa_lineups_{match_id}.json") or {}


def fetch_team_stats(match_id: str) -> Dict[str, Dict[str, Any]]:
    data = fetch_json(f"https://matchstats.uefa.com/v1/team-statistics/{match_id}",
                      raw_name=f"uefa_teamstats_{match_id}.json") or []
    return {str(t.get("teamId")): {s.get("name"): s.get("value") for s in t.get("statistics", [])}
            for t in data if isinstance(t, dict)}


def fetch_player_stats(match_id: str) -> Dict[str, Dict[str, Any]]:
    data = fetch_json(f"https://matchstats.uefa.com/v1/player-statistics/{match_id}") or []
    out = {}
    for p in data if isinstance(data, list) else []:
        raw = {s.get("name"): s.get("value") for s in p.get("statistics", [])}
        kept = {label: to_number(raw.get(k)) for k, label in PLAYER_STATS.items() if to_number(raw.get(k))}
        out[str(p.get("playerId"))] = kept
    return out


def fetch_standings(comp_key: str, season_year: int) -> List[Dict[str, Any]]:
    data = fetch_json(f"https://standings.uefa.com/v1/standings?competitionId={COMPETITION_IDS[comp_key]}"
                      f"&seasonYear={season_year}&language=FR", raw_name=f"uefa_standings_{comp_key}.json") or []
    groups = [g for g in data if isinstance(g, dict) and (g.get("group") or {}).get("phase") == "TOURNAMENT"] or data
    if not groups:
        return []
    items = max(groups, key=lambda g: len(g.get("items", []))).get("items", [])
    rows = []
    for it in items:
        t = team_info(it.get("team") or {})
        rank = int(to_number(it.get("rank")) or len(rows) + 1)
        gd = int(to_number(it.get("goalDifference")) or 0)
        rows.append({
            "rank": rank, "team_id": t["id"], "team": t["name"], "short_name": t["short"],
            "logo": t["logo"], "is_french": t["is_french"],
            "played": int(to_number(it.get("played")) or 0), "won": int(to_number(it.get("won")) or 0),
            "drawn": int(to_number(it.get("drawn")) or 0), "lost": int(to_number(it.get("lost")) or 0),
            "gf": int(to_number(it.get("goalsFor")) or 0), "ga": int(to_number(it.get("goalsAgainst")) or 0),
            "gd": f"+{gd}" if gd > 0 else str(gd), "points": int(to_number(it.get("points")) or 0),
            "trend": it.get("rankTrend", ""),
            "zone": "top8" if rank <= 8 else "playoff" if rank <= 24 else "eliminated",
        })
    rows.sort(key=lambda r: r["rank"])
    return rows


# ------------------------------------------------------------------------------
# Transformation des événements
# ------------------------------------------------------------------------------
def build_events(events: List[Dict[str, Any]], match: Dict[str, Any], home_id: str, away_id: str
                 ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Retourne (événements affichés, buts, actions détaillées pour l'IA)."""
    def side_of(team: Dict[str, Any]) -> Optional[str]:
        tid = str((team or {}).get("id", ""))
        return "home" if tid == home_id else "away" if tid == away_id else None

    # Types de buts (penalty, csc) depuis playerEvents.scorers, consommés dans l'ordre
    goal_types: Dict[str, List[str]] = {}
    for s in (match.get("playerEvents") or {}).get("scorers", []) or []:
        goal_types.setdefault(str((s.get("player") or {}).get("id")), []).append(s.get("goalType", ""))

    assists = [e for e in events if e.get("type") == "ASSIST"]
    shown, goals, actions = [], [], []
    prev_score = {"home": 0, "away": 0}
    for e in events:
        etype = e.get("type", "")
        label, minute, sk = time_of(e)
        pa, sa = e.get("primaryActor") or {}, e.get("secondaryActor") or {}
        p1, p2 = person_name(pa.get("person")), person_name(sa.get("person"))
        side = side_of(pa.get("team"))

        if etype == "GOAL":
            total = e.get("totalScore") or {}
            new = {"home": to_number(total.get("home")), "away": to_number(total.get("away"))}
            if new["home"] is not None and new["away"] is not None:
                if new["home"] > prev_score["home"]:
                    side = "home"
                elif new["away"] > prev_score["away"]:
                    side = "away"
                prev_score = {"home": int(new["home"]), "away": int(new["away"])}
            pending = goal_types.get(str((pa.get("person") or {}).get("id"))) or []
            gtype = pending.pop(0) if pending else ""
            kind = "csc" if "OWN" in gtype.upper() or (side and side_of(pa.get("team")) not in (None, side)) \
                else "pen" if "PENALTY" in gtype.upper() else ""
            assist = None
            for a in assists:
                if abs(time_of(a)[2] - sk) < 0.02 and side_of((a.get("primaryActor") or {}).get("team")) == side:
                    assist = person_name((a.get("primaryActor") or {}).get("person"))
                    break
            goals.append({"minute": label, "scorer": p1 or "—", "assist": assist, "team": side or "home", "kind": kind})
            detail = "Contre son camp" if kind == "csc" else "Penalty" if kind == "pen" else \
                (f"Passe déc. : {assist}" if assist else "But")
            shown.append({"minute": minute, "minute_label": label, "type": "goal", "team": side or "home",
                          "player": p1 or "—", "detail": detail})
        elif etype in ("YELLOW_CARD", "RED_CARD") or "RED" in etype:
            ctype = "yellow_card" if etype == "YELLOW_CARD" else "red_card"
            shown.append({"minute": minute, "minute_label": label, "type": ctype, "team": side or "home",
                          "player": p1 or "—", "detail": "Carton jaune" if ctype == "yellow_card" else "Carton rouge"})
        elif etype == "SUBSTITUTION":
            shown.append({"minute": minute, "minute_label": label, "type": "sub", "team": side or "home",
                          "player": p2 or "Entrant", "detail": f"Remplace {p1}" if p1 else "Entrée en jeu"})
        elif etype == "VAR":
            shown.append({"minute": minute, "minute_label": label, "type": "var", "team": side or "home",
                          "player": p1 or "Arbitrage vidéo", "detail": "Intervention de la VAR"})

        if etype not in ("START_PHASE", "END_PHASE", "CHANGE_PHASE", "INJURY_TIME", "FULL_TIME", "ASSIST"):
            actions.append({"minute": label, "phase": e.get("phase", ""), "type": etype, "team": side,
                            "player": p1, "other": p2, "sort": sk})

    h = a = 0
    for g in goals:
        if g["team"] == "home":
            h += 1
        else:
            a += 1
        g["score_after"] = f"{h}-{a}"
    return shown, goals, actions


def compute_momentum(actions: List[Dict[str, Any]], bucket: int = 5) -> List[Dict[str, Any]]:
    buckets: Dict[int, List[float]] = {}
    for act in actions:
        w = MOMENTUM_WEIGHTS.get(act["type"])
        if not w or act["team"] not in ("home", "away"):
            continue
        base = int(str(act["minute"]).split("'")[0] or 0) if act["minute"] else 0
        idx = min(max((max(base, 1) - 1) // bucket, 0), 23)
        b = buckets.setdefault(idx, [0.0, 0.0])
        b[0 if act["team"] == "home" else 1] += w
    if not buckets:
        return []
    last = max(max(buckets), 17)
    peak = max(abs(x - y) for x, y in buckets.values()) or 1.0
    return [{"minute": (i + 1) * bucket, "home": round(buckets.get(i, [0, 0])[0], 1),
             "away": round(buckets.get(i, [0, 0])[1], 1),
             "value": round(100 * (buckets.get(i, [0, 0])[0] - buckets.get(i, [0, 0])[1]) / peak)}
            for i in range(last + 1)]


def half_stats(actions: List[Dict[str, Any]], phase: str) -> List[Dict[str, Any]]:
    """Statistiques par mi-temps, comptées à partir des actions officielles."""
    acts = [a for a in actions if a["phase"] == phase and a["team"] in ("home", "away")]
    defs = [
        ("attempts", "Tirs", lambda a: a["type"] in SHOT_TYPES),
        ("attempts_on_target", "Tirs cadrés", lambda a: a["type"] in ("GOAL", "SHOT_ON_GOAL")),
        ("corners", "Corners", lambda a: a["type"] == "CORNER"),
        ("yellow_cards", "Cartons jaunes", lambda a: a["type"] == "YELLOW_CARD"),
    ]
    if not acts:
        return []
    return [{"key": k, "label": lbl, "home": sum(1 for a in acts if a["team"] == "home" and f(a)),
             "away": sum(1 for a in acts if a["team"] == "away" and f(a))} for k, lbl, f in defs]


def build_team_stats(stats_by_team: Dict[str, Dict[str, Any]], home_id: str, away_id: str) -> List[Dict[str, Any]]:
    h, a = stats_by_team.get(home_id), stats_by_team.get(away_id)
    if not h or not a:
        return []
    out = []
    for key, label in TEAM_STATS:
        hv, av = to_number(h.get(key)), to_number(a.get(key))
        if hv is None or av is None:
            continue
        if key == "red_cards" and hv == 0 and av == 0:
            continue
        out.append({"key": key, "label": label, "home": hv, "away": av})
    return out


# ------------------------------------------------------------------------------
# Compositions
# ------------------------------------------------------------------------------
def build_lineups(lineups: Dict[str, Any], events: List[Dict[str, Any]], potm_id: str,
                  player_stats: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    subs_out, subs_in = {}, {}
    for e in events:
        if e.get("type") == "SUBSTITUTION":
            label = time_of(e)[0]
            subs_out[str(((e.get("primaryActor") or {}).get("person") or {}).get("id"))] = label
            subs_in[str(((e.get("secondaryActor") or {}).get("person") or {}).get("id"))] = label

    out: Dict[str, Any] = {"home": [], "away": [], "home_subs": [], "away_subs": [],
                           "home_formation": "", "away_formation": "", "home_coach": "", "away_coach": ""}
    for side, key in (("home", "homeTeam"), ("away", "awayTeam")):
        block = lineups.get(key) or {}
        field = block.get("field") or []
        ys = sorted({int(to_number((p.get("fieldCoordinate") or {}).get("y")) or 0)
                     for p in field if p.get("type") != "GOALKEEPER" and (p.get("player") or {}).get("fieldPosition") != "GOALKEEPER"})
        rows = [sum(1 for p in field if int(to_number((p.get("fieldCoordinate") or {}).get("y")) or 0) == y
                    and (p.get("player") or {}).get("fieldPosition") != "GOALKEEPER") for y in ys]
        out[f"{side}_formation"] = "-".join(str(r) for r in rows if r) if field else ""
        coaches = block.get("coaches") or []
        if coaches:
            out[f"{side}_coach"] = fr((coaches[0].get("person") or {}).get("translations"), "name")
        for p in field:
            pl = p.get("player") or {}
            pid = str(pl.get("id", ""))
            c = p.get("fieldCoordinate") or {}
            x, y = (to_number(c.get("x")) or 500) / 10, (to_number(c.get("y")) or 500) / 10
            depth = 4 + y * 0.44  # 0..100 -> 4..48 (demi-terrain)
            out[side].append({
                "number": str(p.get("jerseyNumber", "")), "name": person_name(pl, short=True),
                "pos": pl.get("fieldPosition", ""), "captain": p.get("type") == "CAPTAIN",
                "x": round(x if side == "home" else 100 - x, 1),
                "y": round(depth if side == "home" else 100 - depth, 1),
                "rating": None, "potm": pid == potm_id,
                "subbed_out": subs_out.get(pid), "stats": player_stats.get(pid, {}),
            })
        for p in block.get("bench") or []:
            pl = p.get("player") or {}
            pid = str(pl.get("id", ""))
            if pid in subs_in:
                out[f"{side}_subs"].append({"number": str(p.get("jerseyNumber", "")), "name": person_name(pl, short=True),
                                            "minute": subs_in[pid], "potm": pid == potm_id,
                                            "stats": player_stats.get(pid, {})})
    return out
