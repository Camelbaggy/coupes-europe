#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Collecteur Déterministe des Coupes d'Europe (Zéro IA) — v7 (Moteur FOTMOB Sécurisé)
"""

import argparse
import json
import time
import random
from datetime import datetime, date, timedelta
from typing import Dict, List, Any, Optional
import urllib.request
import urllib.error

# Identifiants des tournois sur FotMob
TOURNAMENTS = {
    "ucl": {"id": 42, "name": "Ligue des Champions", "short_name": "LDC"},
    "uel": {"id": 73, "name": "Ligue Europa", "short_name": "EL"},
    "uecl": {"id": 8466, "name": "Ligue Conférence", "short_name": "ECL"},
}

FRENCH_CLUBS_KEYWORDS = [
    "paris", "psg", "monaco", "brest", "lille", "lyon", "nice",
    "marseille", "lens", "rennes", "strasbourg"
]
NON_FRENCH_BLACKLIST = ["lillestrom", "brest (blr)", "dinamo brest", "rukh brest"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
}


def fetch_json(url: str, retries: int = 2) -> Optional[Dict[str, Any]]:
    for attempt in range(retries + 1):
        try:
            time.sleep(random.uniform(0.3, 0.6))
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=12) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            print(f"[WARN] HTTP {e.code} sur {url}")
        except Exception as e:
            print(f"[WARN] Erreur sur {url} : {e}")
        time.sleep(1.0)
    return None


def is_french_team(name: str, ccode: str = "") -> bool:
    """Détecte si une équipe est française via le code pays FotMob (ccode) ou son nom."""
    if ccode and ccode.upper() in ("FRA", "FR"):
        return True
    lower_name = name.lower()
    for bl in NON_FRENCH_BLACKLIST:
        if bl in lower_name:
            return False
    if lower_name in ["lille", "brest"]:
        return True
    return any(kw in lower_name for kw in FRENCH_CLUBS_KEYWORDS)


def compute_spatial_coords(players: List[Dict[str, Any]], is_home: bool) -> List[Dict[str, Any]]:
    lines = {"G": [], "D": [], "M": [], "F": []}
    for p in players:
        pos = (p.get("pos") or "M").upper()
        if pos.startswith("G"):
            lines["G"].append(p)
        elif pos.startswith("D"):
            lines["D"].append(p)
        elif pos.startswith("F") or pos.startswith("A"):
            lines["F"].append(p)
        else:
            lines["M"].append(p)

    y_map = (
        {"G": 8, "D": 22, "M": 36, "F": 46}
        if is_home
        else {"G": 92, "D": 78, "M": 64, "F": 54}
    )

    positioned = []
    for line_key, group in lines.items():
        count = len(group)
        for idx, p in enumerate(group):
            x_val = round(100 * (idx + 1) / (count + 1), 1)
            p_copy = dict(p)
            p_copy["x"] = x_val
            p_copy["y"] = y_map[line_key]
            positioned.append(p_copy)
    return positioned


def fetch_fotmob_standings(league_id: int) -> List[Dict[str, Any]]:
    url = f"https://www.fotmob.com/api/tDetails?id={league_id}"
    data = fetch_json(url)
    rows_out = []
    if not data or "table" not in data or not data["table"]:
        return rows_out

    tables = data["table"]
    target_table = tables[0].get("data", {}) if isinstance(tables[0], dict) and "data" in tables[0] else tables[0]
    
    if "table" in target_table and "all" in target_table["table"]:
        entries = target_table["table"]["all"]
    else:
        entries = target_table.get("all", [])

    for r in entries:
        rank = int(r.get("idx", len(rows_out) + 1))
        if rank <= 8:
            zone = "top8"
        elif rank <= 24:
            zone = "playoff"
        else:
            zone = "eliminated"

        name = r.get("name", "")
        ccode = r.get("ccode", "")
        
        rows_out.append({
            "rank": rank,
            "team": name,
            "short_name": r.get("shortName", name),
            "is_french": is_french_team(name, ccode),
            "played": int(r.get("played", 0)),
            "won": int(r.get("wins", 0)),
            "drawn": int(r.get("draws", 0)),
            "lost": int(r.get("losses", 0)),
            "gf": int(r.get("scoresStr", "0-0").split("-")[0] if "scoresStr" in r else 0),
            "ga": int(r.get("scoresStr", "0-0").split("-")[1] if "scoresStr" in r else 0),
            "gd": r.get("goalConDiff", 0),
            "points": int(r.get("pts", 0)),
            "zone": zone,
        })
    return rows_out


def collect_dates_data(target_dates: List[str], label_prefix: str = "Soirée") -> Dict[str, Any]:
    t_id_to_key = {v["id"]: k for k, v in TOURNAMENTS.items()}
    european_events = {"ucl": [], "uel": [], "uecl": []}

    print(f"[INFO] Interrogation FotMob pour {target_dates}...")
    for d_str in target_dates:
        # L'API FotMob s'attend à la date au format YYYYMMDD
        ymd = d_str.replace("-", "")
        url = f"https://www.fotmob.com/api/matches?date={ymd}"
        
        data = fetch_json(url)
        # Fallback format de date si l'API a changé
        if not data or "leagues" not in data:
            url_fallback = f"https://www.fotmob.com/api/matches?date={d_str}"
            data = fetch_json(url_fallback)
            
        if not data or "leagues" not in data:
            print(f"[WARN] Impossible de charger le calendrier FotMob pour le {d_str}.")
            continue
        
        for league in data["leagues"]:
            l_id = league.get("primaryId") or league.get("id")
            if l_id in t_id_to_key:
                comp_key = t_id_to_key[l_id]
                for match in league.get("matches", []):
                    european_events[comp_key].append(match)

    total_matches = sum(len(v) for v in european_events.values())
    if total_matches == 0:
        print("[INFO] Aucun match de Coupe d'Europe n'a été retourné par FotMob sur ces dates.")
        return {"notification": {"match_night": False}}

    print(f"[INFO] {total_matches} match(s) européen(s) trouvé(s) sur FotMob. Extraction des fiches complètes...")

    output = {
        "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "target_dates": target_dates,
        "notification": {
            "title": "Coupes d'Europe : Résultats et classements à jour",
            "summary": "",
            "match_night": True,
        },
        "competitions": {},
    }

    for comp_key, meta in TOURNAMENTS.items():
        matches_raw = european_events[comp_key]
        standings = fetch_fotmob_standings(meta["id"])
        rank_lookup = {row["team"].lower(): (row["rank"], row["zone"]) for row in standings}
        
        matches_out = []
        french_focus_out = []
        
        for m in matches_raw:
            m_id = m.get("id")
            if not m_id:
                continue
                
            home_name = m.get("home", {}).get("name", "")
            away_name = m.get("away", {}).get("name", "")
            home_ccode = m.get("home", {}).get("ccode", "")
            away_ccode = m.get("away", {}).get("ccode", "")
            
            home_fr = is_french_team(home_name, home_ccode)
            away_fr = is_french_team(away_name, away_ccode)
            is_fr_match = home_fr or away_fr
            
            m_data = fetch_json(f"https://www.fotmob.com/api/matchDetails?matchId={m_id}") or {}
            
            content = m_data.get("content", {})
            header = m_data.get("header", {})
            status_desc = header.get("status", {}).get("reason", {}).get("long", "Terminé")
            
            # Scores
            try:
                h_score = int(header.get("teams", [])[0].get("score", 0))
                a_score = int(header.get("teams", [])[1].get("score", 0))
            except:
                h_score, a_score = 0, 0

            # Goals & Events
            events_list = []
            goals_list = []
            running_h, running_a = 0, 0
            
            mc = content.get("matchFacts", {}).get("events", {}).get("events", [])
            for ev in mc:
                minute = ev.get("time", 0)
                ev_type = ev.get("type", "").lower()
                is_home_ev = ev.get("isHome", True)
                side = "home" if is_home_ev else "away"
                player = ev.get("player", {}).get("name", "Joueur")
                
                if ev_type == "goal":
                    if side == "home": running_h += 1
                    else: running_a += 1
                    assist = ev.get("assist", {}).get("name") if ev.get("assist") else None
                    goals_list.append({
                        "minute": f"{minute}'",
                        "scorer": player,
                        "assist": assist,
                        "team": side,
                        "score_after": f"{running_h}-{running_a}"
                    })
                    events_list.append({
                        "minute": minute,
                        "minute_label": f"{minute}'",
                        "type": "goal",
                        "team": side,
                        "player": player,
                        "detail": f"Passe déc. : {assist}" if assist else "But"
                    })
                elif "card" in ev_type:
                    card_type = "red_card" if "red" in ev_type else "yellow_card"
                    events_list.append({
                        "minute": minute,
                        "minute_label": f"{minute}'",
                        "type": card_type,
                        "team": side,
                        "player": player,
                        "detail": "Faute"
                    })
                elif ev_type == "substitution":
                    p_in = ev.get("swap", [{}])[0].get("name", "Entrant")
                    p_out = player
                    events_list.append({
                        "minute": minute,
                        "minute_label": f"{minute}'",
                        "type": "sub",
                        "team": side,
                        "player": p_in,
                        "detail": f"Remplace {p_out}"
                    })

            # Lineups
            lineup_block = content.get("lineup", {})
            lineups_out = {"home": [], "away": []}
            h_form = lineup_block.get("lineup", [{}])[0].get("formation", "") if lineup_block.get("lineup") else ""
            a_form = lineup_block.get("lineup", [{}, {}])[1].get("formation", "") if len(lineup_block.get("lineup", [])) > 1 else ""
            
            for roster_idx, side in enumerate(["home", "away"]):
                if len(lineup_block.get("lineup", [])) > roster_idx:
                    roster = lineup_block["lineup"][roster_idx]
                    starters = []
                    for row in roster.get("players", []):
                        for p in row:
                            starters.append({
                                "number": p.get("shirt", ""),
                                "name": p.get("name", {}).get("lastName", p.get("name", {}).get("fullName", "")),
                                "pos": p.get("role", "M"),
                                "rating": p.get("rating", {}).get("num"),
                            })
                    lineups_out[side] = compute_spatial_coords(starters, is_home=(side == "home"))

            # Stats (Map FotMob keys to our keys)
            fotmob_stat_map = {
                "Ball possession": ("ballPossession", "Possession (%)"),
                "Total shots": ("totalShotsOnGoal", "Tirs totaux"),
                "Shots on target": ("shotsOnGoal", "Tirs cadrés"),
                "Big chances": ("bigChanceCreated", "Grosses occasions"),
                "Goalkeeper saves": ("goalkeeperSaves", "Arrêts du gardien"),
                "Corners": ("cornerKicks", "Corners"),
                "Fouls": ("fouls", "Fautes"),
                "Accurate passes": ("accuratePasses", "Passes réussies"),
            }
            stats_all = []
            h_poss = 50
            
            stat_periods = content.get("stats", {}).get("Periods", {}).get("All", {})
            if stat_periods and "stats" in stat_periods:
                for group in stat_periods["stats"]:
                    for item in group.get("stats", []):
                        title = item.get("title", "")
                        if title in fotmob_stat_map:
                            our_key, label = fotmob_stat_map[title]
                            try:
                                h_val = int(str(item["stats"][0]).replace("%", "").split(" ")[0])
                                a_val = int(str(item["stats"][1]).replace("%", "").split(" ")[0])
                            except:
                                h_val, a_val = 0, 0
                                
                            if title == "Ball possession": h_poss = h_val
                            stats_all.append({"key": our_key, "label": label, "home": h_val, "away": a_val})

            # Momentum
            momentum_pts = []
            mm_data = content.get("matchFacts", {}).get("momentum", {}).get("main", {})
            if mm_data and "data" in mm_data:
                for pt in mm_data["data"]:
                    m = pt.get("minute", 0)
                    v = pt.get("value", 0)
                    if m > 0:
                        momentum_pts.append({"minute": m, "value": v})

            match_obj = {
                "match_id": str(m_id),
                "kickoff": datetime.fromtimestamp(m.get("status", {}).get("utcTime", time.time()) / 1000 if m.get("status", {}).get("utcTime") else time.time()).strftime("%d/%m %H:%M"),
                "status": status_desc,
                "is_french_match": is_fr_match,
                "home_team": {
                    "name": home_name,
                    "short": m.get("home", {}).get("shortName", home_name[:3]),
                    "is_french": home_fr,
                    "score": h_score,
                    "formation": h_form,
                },
                "away_team": {
                    "name": away_name,
                    "short": m.get("away", {}).get("shortName", away_name[:3]),
                    "is_french": away_fr,
                    "score": a_score,
                    "formation": a_form,
                },
                "events": events_list,
                "momentum": momentum_pts,
                "lineups": lineups_out,
                "stats": {"all": stats_all, "1st": [], "2nd": []},
            }
            matches_out.append(match_obj)

            if is_fr_match:
                raw_comments = []
                for c in content.get("liveticker", {}).get("events", []):
                    c_txt = c.get("text", "")
                    c_min = c.get("minute", "")
                    if c_txt:
                        raw_comments.append(f"[{c_min}'] {c_txt}" if c_min else c_txt)

                for side_team, side_flag in ((match_obj["home_team"], home_fr), (match_obj["away_team"], away_fr)):
                    if side_flag:
                        c_name = side_team["name"]
                        c_rank, c_zone = rank_lookup.get(c_name.lower(), (None, None))
                        french_focus_out.append({
                            "match_id": str(m_id),
                            "club_name": c_name,
                            "club_rank": c_rank,
                            "club_zone": c_zone,
                            "home_team": match_obj["home_team"],
                            "away_team": match_obj["away_team"],
                            "status": match_obj["status"],
                            "goals": goals_list,
                            "raw_comments_for_llm": raw_comments,
                            "ai_summary": "",
                            "ai_verified": False,
                        })

        output["competitions"][comp_key] = {
            "id": comp_key,
            "name": meta["name"],
            "short_name": meta["short_name"],
            "stage_type": "league" if standings else "knockout",
            "matchday_label": f"{label_prefix} ({len(matches_out)} matchs)",
            "french_clubs_focus": french_focus_out,
            "matches": matches_out,
            "standings": standings,
            "bracket": None,
        }

    with open("data_raw.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("[OK] Extraction FotMob terminée -> data_raw.json généré.")
    return output


def get_current_week_european_dates(ref_date: Optional[date] = None) -> List[str]:
    if not ref_date:
        ref_date = date.today()
    monday = ref_date - timedelta(days=ref_date.weekday())
    return [(monday + timedelta(days=offset)).isoformat() for offset in (1, 2, 3)]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collecteur Coupes d'Europe v7 (FotMob)")
    parser.add_argument("--date", type=str, help="Date précise YYYY-MM-DD")
    parser.add_argument("--week", action="store_true", help="Semaine complète (Mardi à Jeudi)")
    args = parser.parse_args()

    if args.week:
        week_dates = get_current_week_european_dates()
        collect_dates_data(week_dates, label_prefix=f"Semaine du {week_dates[0]} au {week_dates[-1]}")
    elif args.date:
        collect_dates_data([args.date], label_prefix=f"Soirée du {args.date}")
    else:
        today_str = date.today().isoformat()
        collect_dates_data([today_str], label_prefix=f"Soirée du {today_str}")
