#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Collecteur Déterministe des Coupes d'Europe (Zéro IA) — v5 (SofaScore Natif via Navigateur Réel)
------------------------------------------------------------------------------------------------
Répond aux 2 exigences clés :
1. Extraction 100 % SofaScore même depuis GitHub Actions :
   Utilise Playwright (vrai navigateur Chromium headless) qui ouvre d'abord sofascore.com
   pour valider les cookies/jetons Cloudflare, puis interroge les endpoints JSON internes
   de SofaScore (`/incidents`, `/graph` Momentum, `/lineups` avec notes, `/statistics` par mi-temps,
   `/comments` minute par minute et `/standings/total`).
2. Détection 100 % automatique de la nationalité française (Zéro liste bricolée) :
   Vérifie exclusivement le code pays officiel ISO du club (`country.alpha2 == "FR"` ou
   `country.alpha3 == "FRA"`). Si un endpoint compact omet l'objet `country`, le script
   interroge `/api/v1/team/{id}` (avec cache mémoire) pour récupérer le pays officiel du club.
"""

import argparse
import json
import time
import random
from datetime import datetime, date, timedelta
from typing import Dict, List, Any, Optional

TOURNAMENTS = {
    "ucl": {"id": 7, "name": "Ligue des Champions", "short_name": "LDC"},
    "uel": {"id": 679, "name": "Ligue Europa", "short_name": "EL"},
    "uecl": {"id": 17015, "name": "Ligue Conférence", "short_name": "ECL"},
}

REQUIRED_STAT_KEYS = {
    "ballPossession": "Possession (%)",
    "totalShotsOnGoal": "Tirs totaux",
    "shotsOnGoal": "Tirs cadrés",
    "bigChanceCreated": "Grosses occasions",
    "goalkeeperSaves": "Arrêts du gardien",
    "cornerKicks": "Corners",
    "fouls": "Fautes",
    "totalTackle": "Tacles",
    "accuratePasses": "Passes réussies",
    "yellowCards": "Cartons jaunes",
    "redCards": "Cartons rouges",
}

# Cache mémoire {team_id: bool} pour la nationalité officielle du club
TEAM_IS_FRENCH_CACHE: Dict[int, bool] = {}


class SofaScoreBrowserClient:
    """
    Client SofaScore pilotant un vrai navigateur Chromium (Playwright) pour passer
    les protections Cloudflare des serveurs GitHub Actions sans jamais être bloqué.
    """

    def __init__(self):
        self.pw = None
        self.browser = None
        self.context = None
        self.page = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright

        print("[INFO] Démarrage de la session Chromium anti-Cloudflare pour SofaScore...")
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        self.context = self.browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="fr-FR",
            viewport={"width": 1366, "height": 768},
        )
        self.page = self.context.new_page()
        # Masquer le flag navigator.webdriver
        self.page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        # Initialisation de la session sur la page d'accueil SofaScore pour obtenir les cookies Cloudflare
        try:
            self.page.goto("https://www.sofascore.com/", wait_until="domcontentloaded", timeout=25000)
            time.sleep(2.0)
        except Exception as e:
            print(f"[WARN] Préchauffage SofaScore : {e}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if self.browser:
                self.browser.close()
            if self.pw:
                self.pw.stop()
        except Exception:
            pass

    def fetch_json(self, url: str, retries: int = 2) -> Optional[Dict[str, Any]]:
        """
        Exécute un `fetch()` JavaScript directement depuis l'intérieur de la page
        Chromium authentifiée sur sofascore.com (hérite des cookies et de l'empreinte TLS).
        """
        for attempt in range(retries + 1):
            try:
                time.sleep(random.uniform(0.35, 0.8))
                result = self.page.evaluate(
                    """async (targetUrl) => {
                        try {
                            const r = await fetch(targetUrl, {
                                headers: { 'Accept': 'application/json' }
                            });
                            if (!r.ok) return { __status: r.status };
                            const data = await r.json();
                            return { __status: 200, data: data };
                        } catch (err) {
                            return { __status: 0, error: String(err) };
                        }
                    }""",
                    url,
                )
                status = result.get("__status", 0)
                if status == 200:
                    return result.get("data")
                elif status == 404:
                    return None
                else:
                    print(f"[WARN] SofaScore fetch status={status} sur {url}")
            except Exception as e:
                print(f"[WARN] Exception Chromium sur {url} : {e}")
            time.sleep(1.2 * (attempt + 1))
        return None


def is_french_team_official(client: SofaScoreBrowserClient, team_data: Dict[str, Any]) -> bool:
    """
    Détecte à 100 % via les métadonnées ISO officielles si une équipe est française.
    Aucune liste de noms approximative n'est utilisée :
    1. Si `team_data.country.alpha2` (ou `alpha3`) est présent dans l'objet, on vérifie `== "FR"` / `"FRA"`.
    2. Si l'objet `country` n'est pas inclus dans la réponse partielle, on interroge une seule fois
       `https://api.sofascore.com/api/v1/team/{team_id}` et on met le résultat en cache.
    """
    if not team_data:
        return False

    team_id = team_data.get("id")
    if team_id in TEAM_IS_FRENCH_CACHE:
        return TEAM_IS_FRENCH_CACHE[team_id]

    country = team_data.get("country", {})
    alpha2 = (country.get("alpha2") or "").upper()
    alpha3 = (country.get("alpha3") or "").upper()

    if alpha2 or alpha3:
        is_fr = (alpha2 == "FR") or (alpha3 == "FRA")
        if team_id:
            TEAM_IS_FRENCH_CACHE[team_id] = is_fr
        return is_fr

    # Si `country` est absent de ce sous-objet, on vérifie la fiche officielle de l'équipe sur SofaScore
    if team_id:
        detail = client.fetch_json(f"https://api.sofascore.com/api/v1/team/{team_id}")
        if detail and "team" in detail:
            c_obj = detail["team"].get("country", {})
            a2 = (c_obj.get("alpha2") or "").upper()
            a3 = (c_obj.get("alpha3") or "").upper()
            is_fr = (a2 == "FR") or (a3 == "FRA")
            TEAM_IS_FRENCH_CACHE[team_id] = is_fr
            return is_fr

    return False


def compute_spatial_coords(players: List[Dict[str, Any]], is_home: bool) -> List[Dict[str, Any]]:
    """Calcule les coordonnées visuelles (x, y) sur le terrain pour les 11 titulaires."""
    lines = {"G": [], "D": [], "M": [], "F": []}
    for p in players:
        pos = (p.get("pos") or "M").upper()
        if pos.startswith("G"):
            lines["G"].append(p)
        elif pos.startswith("D"):
            lines["D"].append(p)
        elif pos.startswith("F"):
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


def extract_incidents(client: SofaScoreBrowserClient, event_id: int) -> Dict[str, List[Dict[str, Any]]]:
    """Récupère la chronologie exacte : buts, cartons, remplacements."""
    data = client.fetch_json(f"https://api.sofascore.com/api/v1/event/{event_id}/incidents")
    goals = []
    events = []
    if not data or "incidents" not in data:
        return {"goals": goals, "events": events}

    incidents = sorted(data["incidents"], key=lambda x: (x.get("time", 0), x.get("addedTime", 0)))

    for inc in incidents:
        inc_type = inc.get("incidentType")
        minute = inc.get("time", 0)
        added = inc.get("addedTime")
        min_str = f"{minute}+{added}'" if added else f"{minute}'"
        is_home = inc.get("isHome", True)
        side = "home" if is_home else "away"

        if inc_type == "goal":
            scorer = inc.get("player", {}).get("shortName") or inc.get("player", {}).get("name", "Inconnu")
            assist = inc.get("assist1", {}).get("shortName")
            home_score = inc.get("homeScore", 0)
            away_score = inc.get("awayScore", 0)
            goals.append({
                "minute": min_str,
                "scorer": scorer,
                "assist": assist,
                "team": side,
                "score_after": f"{home_score}-{away_score}",
            })
            events.append({
                "minute": minute,
                "minute_label": min_str,
                "type": "goal",
                "team": side,
                "player": scorer,
                "detail": f"Passe déc. : {assist}" if assist else f"But ({home_score}-{away_score})",
            })
        elif inc_type == "card":
            player = inc.get("player", {}).get("shortName") or inc.get("player", {}).get("name", "Inconnu")
            card_class = inc.get("incidentClass", "yellow")
            events.append({
                "minute": minute,
                "minute_label": min_str,
                "type": "red_card" if "red" in card_class else "yellow_card",
                "team": side,
                "player": player,
                "detail": inc.get("reason", "Faute"),
            })
        elif inc_type == "substitution":
            p_in = inc.get("playerIn", {}).get("shortName", "Entrant")
            p_out = inc.get("playerOut", {}).get("shortName", "Sortant")
            events.append({
                "minute": minute,
                "minute_label": min_str,
                "type": "sub",
                "team": side,
                "player": p_in,
                "detail": f"Remplace {p_out}",
            })

    return {"goals": goals, "events": events}


def extract_momentum(client: SofaScoreBrowserClient, event_id: int) -> List[Dict[str, int]]:
    """Récupère le vrai graphique de pression SofaScore (attackMomentum) minute par minute."""
    data = client.fetch_json(f"https://api.sofascore.com/api/v1/event/{event_id}/graph")
    if not data or "graphPoints" not in data:
        return []
    return [
        {"minute": int(pt.get("minute", 0)), "value": int(pt.get("value", 0))}
        for pt in data["graphPoints"]
    ]


def extract_lineups(client: SofaScoreBrowserClient, event_id: int) -> Dict[str, Any]:
    """Récupère les compositions tactiques, numéros, positions et notes individuelles SofaScore."""
    data = client.fetch_json(f"https://api.sofascore.com/api/v1/event/{event_id}/lineups")
    result = {"home_formation": "", "away_formation": "", "home": [], "away": []}
    if not data:
        return result

    for side in ("home", "away"):
        side_data = data.get(side, {})
        result[f"{side}_formation"] = side_data.get("formation", "")
        raw_starters = []
        for p in side_data.get("players", []):
            if p.get("substitute", False):
                continue
            player_info = p.get("player", {})
            stats = p.get("statistics", {})
            raw_starters.append({
                "number": p.get("shirtNumber") or player_info.get("shirtNumber"),
                "name": player_info.get("shortName") or player_info.get("name", ""),
                "pos": p.get("position") or player_info.get("position", "M"),
                "rating": stats.get("rating"),
                "minutes_played": stats.get("minutesPlayed", 90),
            })
        result[side] = compute_spatial_coords(raw_starters, is_home=(side == "home"))
    return result


def extract_statistics(client: SofaScoreBrowserClient, event_id: int) -> Dict[str, List[Dict[str, Any]]]:
    """Récupère toutes les statistiques détaillées SofaScore (Global, 1re MT, 2e MT)."""
    data = client.fetch_json(f"https://api.sofascore.com/api/v1/event/{event_id}/statistics")
    stats_by_period = {"all": [], "1st": [], "2nd": []}
    if not data or "statistics" not in data:
        return stats_by_period

    period_map = {"ALL": "all", "1ST": "1st", "2ND": "2nd"}
    for period_block in data["statistics"]:
        p_key = period_map.get(period_block.get("period", ""), None)
        if not p_key:
            continue
        for group in period_block.get("groups", []):
            for item in group.get("statisticsItems", []):
                k = item.get("key")
                if k in REQUIRED_STAT_KEYS:
                    stats_by_period[p_key].append({
                        "key": k,
                        "label": REQUIRED_STAT_KEYS[k],
                        "home": item.get("homeValue", item.get("home")),
                        "away": item.get("awayValue", item.get("away")),
                    })
    return stats_by_period


def extract_raw_comments_for_french_club(client: SofaScoreBrowserClient, event_id: int) -> List[str]:
    """Récupère le fil de commentaires texte minute par minute sur SofaScore."""
    data = client.fetch_json(f"https://api.sofascore.com/api/v1/event/{event_id}/comments")
    if not data or "comments" not in data:
        return []
    comments = []
    for c in sorted(data["comments"], key=lambda x: x.get("time", 0)):
        txt = c.get("text", "").strip()
        minute = c.get("time", "")
        if txt:
            comments.append(f"[{minute}'] {txt}")
    return comments


def extract_standings_36(
    client: SofaScoreBrowserClient, tournament_id: int, season_id: int
) -> List[Dict[str, Any]]:
    """Récupère le classement officiel des 36 équipes et vérifie le code pays ISO de chacune."""
    data = client.fetch_json(
        f"https://api.sofascore.com/api/v1/unique-tournament/{tournament_id}/season/{season_id}/standings/total"
    )
    rows_out = []
    if not data or "standings" not in data or not data["standings"]:
        return rows_out

    for row in data["standings"][0].get("rows", []):
        rank = int(row.get("position", 0))
        team = row.get("team", {})
        if rank <= 8:
            zone = "top8"
        elif rank <= 24:
            zone = "playoff"
        else:
            zone = "eliminated"

        gf = int(row.get("scoresFor", 0))
        ga = int(row.get("scoresAgainst", 0))
        diff = gf - ga
        rows_out.append({
            "rank": rank,
            "team": team.get("name", ""),
            "short_name": team.get("shortName", team.get("name", "")),
            "is_french": is_french_team_official(client, team),
            "played": int(row.get("matches", 0)),
            "won": int(row.get("wins", 0)),
            "drawn": int(row.get("draws", 0)),
            "lost": int(row.get("losses", 0)),
            "gf": gf,
            "ga": ga,
            "gd": f"+{diff}" if diff > 0 else str(diff),
            "points": int(row.get("points", 0)),
            "zone": zone,
        })
    return rows_out


def get_current_week_european_dates(ref_date: Optional[date] = None) -> List[str]:
    """Retourne les dates du mardi, mercredi et jeudi de la semaine courante."""
    if not ref_date:
        ref_date = date.today()
    monday = ref_date - timedelta(days=ref_date.weekday())
    return [(monday + timedelta(days=offset)).isoformat() for offset in (1, 2, 3)]


def collect_dates_data(target_dates: List[str], label_prefix: str = "Soirée") -> Dict[str, Any]:
    """Collecte 100 % SofaScore via une vraie instance Chromium (Playwright)."""
    t_id_to_key = {v["id"]: k for k, v in TOURNAMENTS.items()}
    european_events = {"ucl": [], "uel": [], "uecl": []}
    season_ids = {}
    seen_event_ids = set()

    with SofaScoreBrowserClient() as client:
        for d_str in target_dates:
            print(f"[INFO] Interrogation SofaScore (Chromium) pour le {d_str}...")
            schedule = client.fetch_json(
                f"https://api.sofascore.com/api/v1/sport/football/scheduled-events/{d_str}"
            )
            if not schedule or "events" not in schedule:
                continue
            for ev in schedule["events"]:
                ev_id = ev.get("id")
                if ev_id in seen_event_ids:
                    continue
                ut_id = ev.get("tournament", {}).get("uniqueTournament", {}).get("id")
                if ut_id in t_id_to_key:
                    seen_event_ids.add(ev_id)
                    comp_key = t_id_to_key[ut_id]
                    european_events[comp_key].append(ev)
                    season_ids[comp_key] = ev.get("season", {}).get("id")

        total_matches = sum(len(v) for v in european_events.values())
        if total_matches == 0:
            print(f"[INFO] Aucun match de Coupe d'Europe sur {target_dates}. Arrêt propre.")
            return {"notification": {"match_night": False}}

        print(f"[INFO] {total_matches} match(s) européen(s) trouvé(s) sur SofaScore. Extraction complète...")

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
            events = european_events[comp_key]
            standings = []
            if comp_key in season_ids and season_ids[comp_key]:
                standings = extract_standings_36(client, meta["id"], season_ids[comp_key])

            rank_lookup = {row["team"]: (row["rank"], row["zone"]) for row in standings}
            matches_out = []
            french_focus_out = []

            for ev in events:
                ev_id = ev["id"]
                home = ev.get("homeTeam", {})
                away = ev.get("awayTeam", {})
                home_fr = is_french_team_official(client, home)
                away_fr = is_french_team_official(client, away)
                is_fr_match = home_fr or away_fr

                h_score = ev.get("homeScore", {}).get("current", 0)
                a_score = ev.get("awayScore", {}).get("current", 0)

                inc_data = extract_incidents(client, ev_id)
                momentum = extract_momentum(client, ev_id)
                lineups = extract_lineups(client, ev_id)
                stats = extract_statistics(client, ev_id)

                match_obj = {
                    "match_id": str(ev_id),
                    "kickoff": datetime.fromtimestamp(ev.get("startTimestamp", 0)).strftime("%d/%m %H:%M"),
                    "status": ev.get("status", {}).get("description", "Terminé"),
                    "is_french_match": is_fr_match,
                    "home_team": {
                        "name": home.get("name", ""),
                        "short": home.get("shortName", home.get("name", "")),
                        "is_french": home_fr,
                        "score": h_score,
                        "formation": lineups["home_formation"],
                    },
                    "away_team": {
                        "name": away.get("name", ""),
                        "short": away.get("shortName", away.get("name", "")),
                        "is_french": away_fr,
                        "score": a_score,
                        "formation": lineups["away_formation"],
                    },
                    "events": inc_data["events"],
                    "momentum": momentum,
                    "lineups": {"home": lineups["home"], "away": lineups["away"]},
                    "stats": stats,
                }
                matches_out.append(match_obj)

                if is_fr_match:
                    raw_comments = extract_raw_comments_for_french_club(client, ev_id)
                    for side_team, side_flag in ((home, home_fr), (away, away_fr)):
                        if side_flag:
                            c_name = side_team.get("name", "")
                            c_rank, c_zone = rank_lookup.get(c_name, (None, None))
                            french_focus_out.append({
                                "match_id": str(ev_id),
                                "club_name": c_name,
                                "club_rank": c_rank,
                                "club_zone": c_zone,
                                "home_team": match_obj["home_team"],
                                "away_team": match_obj["away_team"],
                                "status": match_obj["status"],
                                "goals": inc_data["goals"],
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

        print("[OK] Extraction 100 % SofaScore terminée -> data_raw.json généré.")
        return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collecteur Coupes d'Europe v5 (SofaScore Chromium)")
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
