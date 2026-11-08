#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Collecteur déterministe des Coupes d'Europe (zéro IA) — source : API publique ESPN.

Pourquoi ESPN :
  - FotMob exige désormais un en-tête signé (`x-mas`) sur /api/matches : les appels
    « nus » sont rejetés.
  - SofaScore est derrière Cloudflare, qui bloque les IP des runners GitHub Actions.
  - `site.api.espn.com` répond sans clé ni blocage depuis GitHub Actions, et fournit
    scores, buteurs, cartons, remplacements, compositions, statistiques, fil de
    commentaires (texte Opta) et classement des 36 équipes.

Toutes les valeurs écrites dans data_raw.json proviennent de l'API. Le seul
calcul dérivé est le « momentum » : un comptage pondéré des actions offensives
(tirs, corners…) lues dans le fil de commentaires, par tranche de 5 minutes.
Si le fil est absent, le momentum reste vide (rien n'est inventé).
"""

import argparse
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
    PARIS_TZ = ZoneInfo("Europe/Paris")
except Exception:  # pragma: no cover
    PARIS_TZ = timezone(timedelta(hours=1))

ESPN_SITE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
ESPN_STANDINGS = "https://site.web.api.espn.com/apis/v2/sports/soccer"

TOURNAMENTS = {
    "ucl": {"slug": "uefa.champions", "name": "Ligue des Champions", "short_name": "LDC"},
    "uel": {"slug": "uefa.europa", "name": "Ligue Europa", "short_name": "EL"},
    "uecl": {"slug": "uefa.europa.conf", "name": "Ligue Conférence", "short_name": "ECL"},
}

# Championnats français dont on récupère la liste des clubs à chaque exécution
# (identification par identifiant ESPN, sans liste de noms codée en dur).
FRENCH_LEAGUES = ("fra.1", "fra.2")

HEADERS = {
    "User-Agent": "coupes-europe-dashboard/1.0 (+https://github.com/Camelbaggy/coupes-europe)",
    "Accept": "application/json",
}

STATUS_FR = {"pre": "À venir", "in": "En cours", "post": "Terminé"}

_RAW_DIR: Optional[str] = None
_FRENCH_IDS: set = set()
_FRENCH_NAMES: set = set()


# ------------------------------------------------------------------------------
# Utilitaires
# ------------------------------------------------------------------------------
def fetch_json(url: str, retries: int = 3, raw_name: str = "") -> Optional[Dict[str, Any]]:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if _RAW_DIR and raw_name:
                    with open(os.path.join(_RAW_DIR, raw_name), "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False)
                return data
        except urllib.error.HTTPError as e:
            print(f"[WARN] HTTP {e.code} sur {url}")
            if e.code in (400, 404):
                return None
        except Exception as e:
            print(f"[WARN] Erreur réseau sur {url} : {e}")
        time.sleep(2 ** attempt)
    return None


def normalize(name: str) -> str:
    txt = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    return " ".join(txt.lower().replace(".", " ").split())


def load_french_clubs() -> int:
    """Charge les clubs des championnats français (Ligue 1, Ligue 2) depuis ESPN."""
    _FRENCH_IDS.clear()
    _FRENCH_NAMES.clear()
    for league in FRENCH_LEAGUES:
        data = fetch_json(f"{ESPN_SITE}/{league}/teams", raw_name=f"teams_{league}.json") or {}
        for sport in data.get("sports", []) or []:
            for lg in sport.get("leagues", []) or []:
                for item in lg.get("teams", []) or []:
                    t = item.get("team", item)
                    if t.get("id"):
                        _FRENCH_IDS.add(str(t["id"]))
                    for k in ("displayName", "shortDisplayName", "name"):
                        if t.get(k):
                            _FRENCH_NAMES.add(normalize(t[k]))
    if not _FRENCH_IDS:
        print("[WARN] Impossible de charger les clubs français (Ligue 1/Ligue 2) depuis ESPN.")
    else:
        print(f"[INFO] {len(_FRENCH_IDS)} clubs français chargés (Ligue 1 + Ligue 2).")
    return len(_FRENCH_IDS)


def is_french_team(team_id: Any, name: str = "") -> bool:
    if team_id and str(team_id) in _FRENCH_IDS:
        return True
    return bool(name) and normalize(name) in _FRENCH_NAMES


def parse_clock(display: str) -> Tuple[int, int]:
    """« 45'+3' » -> (45, 3) ; « 78' » -> (78, 0)."""
    nums = [int(n) for n in re.findall(r"\d+", display or "")]
    if not nums:
        return 0, 0
    return nums[0], (nums[1] if len(nums) > 1 else 0)


def clock_label(display: str) -> str:
    base, extra = parse_clock(display)
    return f"{base}'+{extra}" if extra else f"{base}'"


def sort_key(display: str) -> float:
    base, extra = parse_clock(display)
    return base + extra / 100.0


def kickoff_paris(iso: str) -> str:
    try:
        dt = datetime.strptime(iso, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except Exception:
            return ""
    return dt.astimezone(PARIS_TZ).strftime("%d/%m %H:%M")


def to_number(val: Any) -> Any:
    try:
        f = float(str(val).replace("%", "").strip())
    except (TypeError, ValueError):
        return None
    return int(f) if f.is_integer() else round(f, 1)


# ------------------------------------------------------------------------------
# Classement
# ------------------------------------------------------------------------------
def fetch_standings(slug: str) -> List[Dict[str, Any]]:
    data = fetch_json(f"{ESPN_STANDINGS}/{slug}/standings", raw_name=f"standings_{slug}.json")
    if not data:
        return []
    groups = data.get("children") or [data]
    entries: List[Dict[str, Any]] = []
    for g in groups:
        entries.extend(g.get("standings", {}).get("entries", []))

    rows = []
    for entry in entries:
        team = entry.get("team", {})
        st = {s.get("name"): s.get("value") for s in entry.get("stats", [])}
        rank = int(st.get("rank") or len(rows) + 1)
        gf = int(st.get("pointsFor") or 0)
        ga = int(st.get("pointsAgainst") or 0)
        diff = int(st.get("pointDifferential") if st.get("pointDifferential") is not None else gf - ga)
        name = team.get("displayName") or team.get("name", "")
        rows.append({
            "rank": rank,
            "team_id": str(team.get("id", "")),
            "team": name,
            "short_name": team.get("abbreviation", ""),
            "is_french": is_french_team(team.get("id"), name),
            "played": int(st.get("gamesPlayed") or 0),
            "won": int(st.get("wins") or 0),
            "drawn": int(st.get("ties") or 0),
            "lost": int(st.get("losses") or 0),
            "gf": gf,
            "ga": ga,
            "gd": f"+{diff}" if diff > 0 else str(diff),
            "points": int(st.get("points") or 0),
            "zone": "top8" if rank <= 8 else "playoff" if rank <= 24 else "eliminated",
        })
    rows.sort(key=lambda r: r["rank"])
    return rows


# ------------------------------------------------------------------------------
# Événements (buts, cartons, remplacements)
# ------------------------------------------------------------------------------
ASSIST_RE = re.compile(r"Assisted by ([^.]+?)(?: with | following |\.|$)")
SUB_RE = re.compile(r"Substitution, [^.]+\.\s*(.+?) replaces (.+?)(?: because of an injury)?\.?$")


def build_events(comp_block: Dict[str, Any], summary: Dict[str, Any], home_id: str
                 ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Buts et cartons : `details` du scoreboard (fiable). Passes déc. et remplacements : `keyEvents`."""
    events: List[Dict[str, Any]] = []
    goals: List[Dict[str, Any]] = []

    key_events = summary.get("keyEvents", []) or []
    # Index des textes de but par minute pour retrouver le passeur
    goal_texts: Dict[str, List[str]] = {}
    for ke in key_events:
        if ke.get("scoringPlay"):
            goal_texts.setdefault(clock_label(ke.get("clock", {}).get("displayValue", "")), []).append(ke.get("text", ""))

    for det in comp_block.get("details", []) or []:
        disp = det.get("clock", {}).get("displayValue", "")
        side = "home" if str(det.get("team", {}).get("id")) == home_id else "away"
        athletes = det.get("athletesInvolved", []) or []
        player = athletes[0].get("displayName", "") if athletes else ""
        base = {"minute": parse_clock(disp)[0], "minute_label": clock_label(disp),
                "sort": sort_key(disp), "team": side, "player": player or "—"}

        if det.get("scoringPlay"):
            assist = athletes[1].get("displayName") if len(athletes) > 1 else None
            if not assist:
                for txt in goal_texts.get(base["minute_label"], []):
                    if player and player.split()[-1] in txt:
                        m = ASSIST_RE.search(txt)
                        if m:
                            assist = m.group(1).strip()
                        break
            kind = "csc" if det.get("ownGoal") else "pen" if det.get("penaltyKick") else ""
            goals.append({"minute": base["minute_label"], "sort": base["sort"], "scorer": player or "—",
                          "assist": assist, "team": side, "kind": kind})
            detail = "Contre son camp" if kind == "csc" else "Penalty" if kind == "pen" else (
                f"Passe déc. : {assist}" if assist else "But")
            events.append({**base, "type": "goal", "detail": detail})
        elif det.get("redCard"):
            events.append({**base, "type": "red_card", "detail": "Carton rouge"})
        elif det.get("yellowCard"):
            events.append({**base, "type": "yellow_card", "detail": "Carton jaune"})

    for ke in key_events:
        ktype = (ke.get("type", {}).get("type") or ke.get("type", {}).get("text") or "").lower()
        if "substitution" not in ktype:
            continue
        disp = ke.get("clock", {}).get("displayValue", "")
        side = "home" if str(ke.get("team", {}).get("id")) == home_id else "away"
        text = (ke.get("text") or "").strip()
        m = SUB_RE.search(text)
        if m:
            p_in, p_out = m.group(1).strip(), m.group(2).strip()
        else:
            parts = [p.get("athlete", {}).get("displayName", "") for p in ke.get("participants", []) or []]
            p_in = parts[0] if parts else "Entrant"
            p_out = parts[1] if len(parts) > 1 else ""
        events.append({"minute": parse_clock(disp)[0], "minute_label": clock_label(disp),
                       "sort": sort_key(disp), "type": "sub", "team": side,
                       "player": p_in, "detail": f"Remplace {p_out}" if p_out else "Entrée en jeu"})

    events.sort(key=lambda e: e["sort"])
    goals.sort(key=lambda g: g["sort"])
    h = a = 0
    for g in goals:
        if g["team"] == "home":
            h += 1
        else:
            a += 1
        g["score_after"] = f"{h}-{a}"
    for coll in (events, goals):
        for item in coll:
            item.pop("sort", None)
    return events, goals


# ------------------------------------------------------------------------------
# Fil de commentaires + momentum dérivé
# ------------------------------------------------------------------------------
def extract_commentary(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = summary.get("commentary", []) or []
    out = []
    for idx, c in enumerate(items):
        text = (c.get("text") or "").strip()
        if not text:
            continue
        disp = c.get("time", {}).get("displayValue", "") or ""
        seq = c.get("sequence")
        out.append({"seq": seq if isinstance(seq, (int, float)) else idx,
                    "label": clock_label(disp) if disp else "", "sort": sort_key(disp), "text": text})
    out.sort(key=lambda c: (c["sort"], c["seq"]))
    return out


ACTION_WEIGHTS = [
    (re.compile(r"^(Goal!|Own Goal)", re.I), 5.0),
    (re.compile(r"^Attempt saved", re.I), 3.0),
    (re.compile(r"hits the (bar|left post|right post|post)", re.I), 3.0),
    (re.compile(r"^Penalty .*draws a foul", re.I), 3.0),
    (re.compile(r"^Attempt missed", re.I), 2.0),
    (re.compile(r"^Attempt blocked", re.I), 1.5),
    (re.compile(r"^Corner,", re.I), 1.0),
    (re.compile(r"wins a free kick in the attacking half", re.I), 0.5),
]


def _team_of(text: str, home: str, away: str) -> Optional[str]:
    """Équipe à l'origine de l'action, lue dans le texte Opta."""
    m = re.match(r"^(?:Corner|Offside|Penalty),\s+([^.]+)\.", text)
    cands = [m.group(1)] if m else re.findall(r"\(([^)]+)\)", text)
    nh, na = normalize(home), normalize(away)
    for cand in cands:
        nc = normalize(cand)
        if nc == nh:
            return "home"
        if nc == na:
            return "away"
    return None


def compute_momentum(commentary: List[Dict[str, Any]], home: str, away: str, bucket: int = 5
                     ) -> List[Dict[str, Any]]:
    if not commentary:
        return []
    buckets: Dict[int, List[float]] = {}
    found_any = False
    for c in commentary:
        weight = next((w for rx, w in ACTION_WEIGHTS if rx.search(c["text"])), 0.0)
        if not weight:
            continue
        side = _team_of(c["text"], home, away)
        if not side:
            continue
        found_any = True
        base, _ = parse_clock(c["label"])
        idx = min(max((max(base, 1) - 1) // bucket, 0), 23)  # 0..23 -> jusqu'à 120'
        b = buckets.setdefault(idx, [0.0, 0.0])
        b[0 if side == "home" else 1] += weight
    if not found_any:
        return []
    last = max(max(buckets), 17)  # au moins 90'
    peak = max(abs(h - a) for h, a in buckets.values()) or 1.0
    pts = []
    for i in range(last + 1):
        h, a = buckets.get(i, [0.0, 0.0])
        pts.append({"minute": (i + 1) * bucket, "home": round(h, 1), "away": round(a, 1),
                    "value": round(100 * (h - a) / peak)})
    return pts


# ------------------------------------------------------------------------------
# Compositions
# ------------------------------------------------------------------------------
def _depth(pos: str) -> int:
    p = pos.upper()
    if p in ("G", "GK"):
        return 0
    if p.startswith("DM"):
        return 3
    if p in ("LWB", "RWB"):
        return 2
    if p.startswith(("CD", "LB", "RB", "D", "SW")):
        return 1
    if p.startswith(("CM", "LM", "RM", "M")):
        return 4
    if p.startswith(("AM", "LW", "RW")):
        return 5
    return 6  # F, CF, ST, SS...


def _lateral(pos: str) -> int:
    """0 = couloir gauche, 1 = axe gauche, 2 = axe, 3 = axe droit, 4 = couloir droit."""
    p = pos.upper()
    if p in ("LB", "LWB", "LM", "LW"):
        return 0
    if p in ("RB", "RWB", "RM", "RW"):
        return 4
    if p.endswith("-L"):
        return 1
    if p.endswith("-R"):
        return 3
    return 2


def place_players(starters: List[Dict[str, Any]], formation: str, is_home: bool) -> List[Dict[str, Any]]:
    """Positionne les titulaires sur un demi-terrain selon la formation ESPN (ex. « 4-2-3-1 »)."""
    gks = [p for p in starters if _depth(p["pos"]) == 0][:1]
    outfield = [p for p in starters if p not in gks]
    outfield.sort(key=lambda p: (_depth(p["pos"]), p.get("formation_place") or 99))

    lines_count = [int(x) for x in re.findall(r"\d+", formation or "")]
    if sum(lines_count) != len(outfield) or not lines_count:
        lines: Dict[int, List[Dict[str, Any]]] = {}
        for p in outfield:
            lines.setdefault(_depth(p["pos"]), []).append(p)
        rows = [lines[k] for k in sorted(lines)]
    else:
        rows, i = [], 0
        for n in lines_count:
            rows.append(outfield[i:i + n])
            i += n

    all_rows = ([gks] if gks else []) + rows
    n_rows = len(all_rows)
    out = []
    for r_idx, row in enumerate(all_rows):
        # Domicile en haut (attaque vers le bas), extérieur en bas (attaque vers le haut)
        depth_pct = 6 + (r_idx / max(n_rows - 1, 1)) * 40  # 6 -> 46
        y = depth_pct if is_home else 100 - depth_pct
        row = sorted(row, key=lambda p: _lateral(p["pos"]))
        if is_home:
            row = list(reversed(row))  # vue de face : la gauche de l'équipe du haut est à droite
        for c_idx, p in enumerate(row):
            q = dict(p)
            q["x"] = round(100 * (c_idx + 1) / (len(row) + 1), 1)
            q["y"] = round(y, 1)
            q.pop("formation_place", None)
            out.append(q)
    return out


def build_lineups(summary: Dict[str, Any]) -> Tuple[Dict[str, Any], str, str]:
    lineups: Dict[str, Any] = {"home": [], "away": [], "home_subs": [], "away_subs": []}
    forms = {"home": "", "away": ""}
    for roster in summary.get("rosters", []) or []:
        side = "home" if roster.get("homeAway") == "home" else "away"
        forms[side] = roster.get("formation", "") or ""
        starters, subs = [], []
        for entry in roster.get("roster", []) or []:
            ath = entry.get("athlete", {}) or {}
            player = {
                "number": str(entry.get("jersey", "") or ""),
                "name": ath.get("shortName") or ath.get("displayName", ""),
                "pos": (entry.get("position", {}) or {}).get("abbreviation", "") or "M",
                "rating": None,
                "subbed_out": bool(entry.get("subbedOut")),
                "formation_place": to_number(entry.get("formationPlace")),
            }
            if entry.get("starter"):
                starters.append(player)
            elif entry.get("subbedIn"):
                player.pop("formation_place", None)
                subs.append(player)
        lineups[side] = place_players(starters, forms[side], is_home=(side == "home"))
        lineups[f"{side}_subs"] = subs
    return lineups, forms["home"], forms["away"]


# ------------------------------------------------------------------------------
# Statistiques
# ------------------------------------------------------------------------------
STAT_MAP = [
    ("possessionPct", "ballPossession", "Possession (%)"),
    ("totalShots", "totalShotsOnGoal", "Tirs totaux"),
    ("shotsOnTarget", "shotsOnGoal", "Tirs cadrés"),
    ("saves", "goalkeeperSaves", "Arrêts du gardien"),
    ("wonCorners", "cornerKicks", "Corners"),
    ("foulsCommitted", "fouls", "Fautes"),
    ("effectiveTackles", "totalTackle", "Tacles réussis"),
    ("accuratePasses", "accuratePasses", "Passes réussies"),
    ("totalPasses", "totalPasses", "Passes tentées"),
    ("offsides", "offsides", "Hors-jeu"),
    ("yellowCards", "yellowCards", "Cartons jaunes"),
    ("redCards", "redCards", "Cartons rouges"),
]


def build_stats(summary: Dict[str, Any], home_id: str) -> List[Dict[str, Any]]:
    teams = summary.get("boxscore", {}).get("teams", []) or []
    if len(teams) != 2:
        return []
    by_side = {}
    for t in teams:
        side = "home" if str(t.get("team", {}).get("id")) == home_id else "away"
        by_side[side] = {s.get("name"): s.get("displayValue") for s in t.get("statistics", [])}
    if set(by_side) != {"home", "away"}:  # ids absents : ordre ESPN (domicile en premier)
        by_side = {"home": {s.get("name"): s.get("displayValue") for s in teams[0].get("statistics", [])},
                   "away": {s.get("name"): s.get("displayValue") for s in teams[1].get("statistics", [])}}
    out = []
    for espn_k, key, label in STAT_MAP:
        hv, av = to_number(by_side["home"].get(espn_k)), to_number(by_side["away"].get(espn_k))
        if hv is None or av is None:
            continue
        out.append({"key": key, "label": label, "home": hv, "away": av})
    return out


# ------------------------------------------------------------------------------
# Collecte principale
# ------------------------------------------------------------------------------
def collect_dates_data(target_dates: List[str], label_prefix: str = "Soirée",
                       output_path: str = "data_raw.json") -> Dict[str, Any]:
    print(f"[INFO] Collecte ESPN pour {target_dates}")
    output: Dict[str, Any] = {
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "ESPN",
        "target_dates": target_dates,
        "notification": {
            "title": "Coupes d'Europe : Résultats et classements à jour",
            "summary": "",
            "match_night": False,
        },
        "competitions": {},
    }
    total_finished = 0
    load_french_clubs()

    for comp_key, meta in TOURNAMENTS.items():
        slug = meta["slug"]
        standings = fetch_standings(slug)
        rank_by_id = {r["team_id"]: r for r in standings if r["team_id"]}
        rank_by_name = {normalize(r["team"]): r for r in standings}

        matches_out, focus_out, seen = [], [], set()
        for d_str in target_dates:
            ymd = d_str.replace("-", "")
            sb = fetch_json(f"{ESPN_SITE}/{slug}/scoreboard?dates={ymd}", raw_name=f"scoreboard_{slug}_{ymd}.json")
            for ev in (sb or {}).get("events", []) or []:
                ev_id = str(ev.get("id"))
                if ev_id in seen:
                    continue
                seen.add(ev_id)

                comp_block = (ev.get("competitions") or [{}])[0]
                competitors = comp_block.get("competitors", []) or []
                home_c = next((c for c in competitors if c.get("homeAway") == "home"), {})
                away_c = next((c for c in competitors if c.get("homeAway") == "away"), {})
                home_t, away_t = home_c.get("team", {}), away_c.get("team", {})
                home_id = str(home_t.get("id", ""))
                home_name = home_t.get("displayName", "")
                away_name = away_t.get("displayName", "")

                st_type = ev.get("status", {}).get("type", {}) or {}
                state = st_type.get("state", "post")
                status = STATUS_FR.get(state, st_type.get("description", ""))
                if st_type.get("name") == "STATUS_POSTPONED":
                    status = "Reporté"
                if state == "post" and st_type.get("completed"):
                    total_finished += 1

                summary: Dict[str, Any] = {}
                if state != "pre":
                    summary = fetch_json(f"{ESPN_SITE}/{slug}/summary?event={ev_id}",
                                         raw_name=f"summary_{ev_id}.json") or {}

                events, goals = build_events(comp_block, summary, home_id)
                lineups, h_form, a_form = build_lineups(summary)
                commentary = extract_commentary(summary)
                momentum = compute_momentum(commentary, home_name, away_name)

                h_score = int(to_number(home_c.get("score")) or 0)
                a_score = int(to_number(away_c.get("score")) or 0)
                if goals and goals[-1]["score_after"] != f"{h_score}-{a_score}":
                    print(f"[WARN] Buts incohérents avec le score pour {home_name}-{away_name} "
                          f"({goals[-1]['score_after']} vs {h_score}-{a_score})")

                def team_obj(t: Dict[str, Any], score: int, form: str) -> Dict[str, Any]:
                    name = t.get("displayName", "")
                    return {"id": str(t.get("id", "")), "name": name, "short": t.get("abbreviation", name[:3].upper()),
                            "logo": t.get("logo", ""), "is_french": is_french_team(t.get("id"), name), "score": score,
                            "formation": form}

                match_obj = {
                    "match_id": ev_id,
                    "date": d_str,
                    "kickoff": kickoff_paris(ev.get("date", "")),
                    "status": status,
                    "venue": (comp_block.get("venue") or {}).get("fullName", ""),
                    "home_team": team_obj(home_t, h_score, h_form),
                    "away_team": team_obj(away_t, a_score, a_form),
                    "events": events,
                    "momentum": momentum,
                    "lineups": lineups,
                    "stats": {"all": build_stats(summary, home_id), "1st": [], "2nd": []},
                }
                match_obj["is_french_match"] = match_obj["home_team"]["is_french"] or match_obj["away_team"]["is_french"]
                matches_out.append(match_obj)

                if not match_obj["is_french_match"] or state == "pre":
                    continue
                comments_txt = [f"[{c['label']}] {c['text']}" if c["label"] else c["text"] for c in commentary]
                for side in ("home_team", "away_team"):
                    t = match_obj[side]
                    if not t["is_french"]:
                        continue
                    row = rank_by_id.get(t["id"]) or rank_by_name.get(normalize(t["name"])) or {}
                    focus_out.append({
                        "match_id": ev_id,
                        "club_name": t["name"],
                        "club_rank": row.get("rank"),
                        "club_zone": row.get("zone"),
                        "home_team": match_obj["home_team"],
                        "away_team": match_obj["away_team"],
                        "status": status,
                        "goals": goals,
                        "raw_comments_for_llm": comments_txt,
                        "ai_summary": "",
                        "ai_verified": False,
                    })

        matches_out.sort(key=lambda m: (m["date"], m["kickoff"]))
        output["competitions"][comp_key] = {
            "id": comp_key,
            "name": meta["name"],
            "short_name": meta["short_name"],
            "stage_type": "league" if standings else "knockout",
            "matchday_label": f"{label_prefix} ({len(matches_out)} matchs)",
            "french_clubs_focus": focus_out,
            "matches": matches_out,
            "standings": standings,
            "bracket": None,
        }
        print(f"[INFO] {meta['name']} : {len(matches_out)} match(s), {len(standings)} équipes au classement, "
              f"{len(focus_out)} fiche(s) club français.")

    output["notification"]["match_night"] = total_finished > 0
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"[OK] {total_finished} match(s) terminé(s) -> {output_path}")
    return output


def get_current_week_european_dates(ref_date: Optional[date] = None) -> List[str]:
    ref_date = ref_date or date.today()
    monday = ref_date - timedelta(days=ref_date.weekday())
    return [(monday + timedelta(days=o)).isoformat() for o in (1, 2, 3)]


def set_raw_dir(path: Optional[str]) -> None:
    global _RAW_DIR
    if path:
        os.makedirs(path, exist_ok=True)
    _RAW_DIR = path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collecteur Coupes d'Europe (ESPN)")
    parser.add_argument("--date", help="Date précise YYYY-MM-DD")
    parser.add_argument("--week", action="store_true", help="Mardi à jeudi de la semaine en cours")
    parser.add_argument("--save-raw", help="Dossier où sauvegarder les réponses ESPN brutes (debug)")
    args = parser.parse_args()
    set_raw_dir(args.save_raw)
    if args.week:
        d = get_current_week_european_dates()
        collect_dates_data(d, label_prefix=f"Semaine du {d[0]} au {d[-1]}")
    else:
        d_str = args.date or date.today().isoformat()
        collect_dates_data([d_str], label_prefix=f"Soirée du {d_str}")
