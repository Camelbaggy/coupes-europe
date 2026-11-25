#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Collecteur déterministe des Coupes d'Europe (zéro IA).

- UEFA (source principale, officielle) : matchs, scores, actions, compositions, statistiques
  d'équipe et de joueurs, classement. Les clubs français sont ceux dont le code pays UEFA est FRA.
- ESPN (complément) : fil de commentaires texte des matchs des clubs français, pour le récit de l'IA.

Valeurs dérivées (calculées, jamais inventées) :
- momentum : actions offensives officielles (buts, tirs, corners) pondérées, par tranche de 5 min ;
- statistiques par mi-temps : comptage des actions officielles de chaque période.
"""

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import classement
import espn
import ratings
import uefa
from netutil import fr, set_raw_dir, to_number  # noqa: F401  (set_raw_dir réexporté pour run_pipeline)

try:
    from zoneinfo import ZoneInfo
    PARIS_TZ = ZoneInfo("Europe/Paris")
except Exception:  # pragma: no cover
    PARIS_TZ = timezone(timedelta(hours=1))

TOURNAMENTS = {
    "ucl": {"name": "Ligue des Champions", "short_name": "LDC"},
    "uel": {"name": "Ligue Europa", "short_name": "EL"},
    "uecl": {"name": "Ligue Conférence", "short_name": "ECL"},
}


def kickoff_paris(iso: str) -> str:
    try:
        dt = datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
    except ValueError:
        return ""
    return dt.astimezone(PARIS_TZ).strftime("%d/%m %H:%M")


_MATCHS_LIGUE: Dict[Any, Any] = {}


def matchs_phase_ligue(comp_key: str, season: int) -> List[Dict[str, Any]]:
    """Lignes (date, équipes, score) des matchs de phase de ligue TERMINÉS de la saison, lues une fois par processus.
    Lève RuntimeError si la liste de la saison est illisible (on ne calcule jamais un classement sur une liste tronquée)."""
    cle = (comp_key, season)
    if cle not in _MATCHS_LIGUE:
        brut = uefa.fetch_season_matches(comp_key, season)
        if brut is None:
            raise RuntimeError(f"liste des matchs {comp_key} {season} illisible : classement non calculable")
        _MATCHS_LIGUE[cle] = classement.matchs_depuis_uefa(brut)
    return _MATCHS_LIGUE[cle]


def choisir_classement(comp_key: str, season: int, jour: Optional[str], mode: str, maintenant: datetime
                       ) -> Tuple[List[Dict[str, Any]], str, Optional[str]]:
    """(lignes, source, date de calcul) du classement d'une soirée.

    - officiel : classement UEFA actuel (seul disponible) ; valable tant que la soirée vient d'avoir lieu ;
    - calcule  : recalculé depuis les scores de la phase de ligue jusqu'à `jour` inclus (classement.py) ;
    - absent   : aucun match de phase de ligue terminé à cette date (tours préliminaires) : rien n'est affiché.
    `mode` : "officiel" (forcé, ex. semaine de test), "calcule" (forcé, reconstitution) ou "auto" (officiel si la
    soirée est récente, sinon recalculé)."""
    if mode == "auto":
        mode = "officiel" if jour is None or classement.officiel_valable(jour, maintenant) else "calcule"
    if mode == "officiel" or jour is None:
        return uefa.fetch_standings(comp_key, season), "officiel", None
    rows = classement.calculer_classement(matchs_phase_ligue(comp_key, season), jour)
    return (rows, "calcule", jour) if rows else ([], "absent", None)


def build_match(comp_key: str, m: Dict[str, Any], detailed: bool) -> Dict[str, Any]:
    """Assemble la fiche d'un match. `detailed` = matchs de clubs français (stats joueurs + fil ESPN)."""
    mid = str(m.get("id"))
    home, away = uefa.team_info(m.get("homeTeam") or {}), uefa.team_info(m.get("awayTeam") or {})
    total = (m.get("score") or {}).get("total") or {}
    pens = (m.get("score") or {}).get("penalty") or {}
    home["score"] = int(to_number(total.get("home")) or 0)
    away["score"] = int(to_number(total.get("away")) or 0)
    raw_status = m.get("status", "")
    status = uefa.STATUS_FR.get(raw_status, raw_status.title())
    potm = (m.get("playerOfTheMatch") or {}).get("player") or {}

    match: Dict[str, Any] = {
        "match_id": mid,
        "date": ((m.get("kickOffTime") or {}).get("date") or "")[:10],
        "kickoff": kickoff_paris((m.get("kickOffTime") or {}).get("dateTime", "")),
        "status": status,
        "finished": raw_status == "FINISHED",
        "matchday": fr((m.get("matchday") or {}).get("translations"), "longName"),
        "venue": fr((m.get("stadium") or {}).get("translations"), "name"),
        "attendance": to_number(m.get("matchAttendance")),
        "player_of_match": uefa.person_name(potm) if potm else "",
        "penalties": f"{pens.get('home')}-{pens.get('away')}" if pens else "",
        "home_team": home,
        "away_team": away,
        "events": [], "goals": [], "momentum": [], "actions": [],
        "lineups": {}, "players": {}, "stats": {"all": [], "1st": [], "2nd": []},
    }
    match.update(uefa.stage_info(m))  # stage (league / qualifying / knockout), round, matchday_short, leg
    match["is_french_match"] = home["is_french"] or away["is_french"]
    if raw_status in ("UPCOMING", ""):
        return match

    events = uefa.fetch_events(mid)
    shown, goals, actions = uefa.build_events(events, m, home["id"], away["id"])
    pstats = uefa.fetch_player_stats(mid)  # tous les matchs : nécessaire aux notes et aux fiches joueurs
    lineups_raw = uefa.fetch_lineups(mid)
    kits = uefa.kit_info(lineups_raw)  # maillot réellement porté dans ce match (collecté pour les couleurs, pas encore affiché)
    home.update(kits["home"])
    away.update(kits["away"])
    lineups, players = uefa.build_lineups(lineups_raw, events, str(potm.get("id", "")), pstats)
    home["formation"], away["formation"] = lineups.get("home_formation", ""), lineups.get("away_formation", "")

    match.update({
        "events": shown,
        "goals": goals,
        "momentum": uefa.compute_momentum(actions),
        "lineups": lineups,
        "players": players,
        "stats": {"all": uefa.build_team_stats(uefa.fetch_team_stats(mid), home["id"], away["id"]),
                  "1st": uefa.half_stats(actions, "FIRST_HALF"),
                  "2nd": uefa.half_stats(actions, "SECOND_HALF")},
    })
    if detailed:
        match["actions"] = [{k: v for k, v in a.items() if k != "sort"} for a in actions]
    if goals and goals[-1]["score_after"] != f"{home['score']}-{away['score']}":
        print(f"[WARN] {home['name']}-{away['name']} : buts reconstitués {goals[-1]['score_after']} "
              f"≠ score officiel {home['score']}-{away['score']}")
    return match


def collect_dates_data(target_dates: List[str], label_prefix: str = "Soirée",
                       output_path: str = "data_raw.json", classement_mode: str = "auto",
                       avec_espn: bool = True, maintenant: Optional[datetime] = None,
                       avec_xg: bool = True) -> Dict[str, Any]:
    """`classement_mode` : voir `choisir_classement` (une soirée = une date ; plusieurs dates = officiel).
    `avec_espn=False` : pas de fil de commentaires (reconstitution : résumés déterministes, ESPN inutile).
    `avec_xg` : xG (ESPN / Opta) des matchs terminés de TOUTES les coupes, y compris en reconstitution ; jamais bloquant."""
    maintenant = maintenant or datetime.now(timezone.utc)
    jour = target_dates[0] if len(target_dates) == 1 else None
    print("[INFO] Collecte UEFA" + (" (+ fil ESPN)" if avec_espn else "") + f" pour {target_dates}")
    output: Dict[str, Any] = {
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "UEFA (données officielles) + ESPN (fil de commentaires)",
        "target_dates": target_dates,
        "notification": {"title": "Coupes d'Europe : Résultats et classements à jour", "summary": "",
                         "match_night": False, "matchs": 0, "termines": 0, "incomplet": False},
        "competitions": {},
    }
    finished_total = 0
    matches_total = 0
    erreurs_uefa: List[str] = []
    bilan_xg: Dict[str, int] = {"ok": 0, "non_trouve": 0, "absent": 0, "erreur": 0, "non_termine": 0}
    espn.REQUETES.update(scoreboard=0, stats=0)

    for comp_key, meta in TOURNAMENTS.items():
        raw_matches = uefa.fetch_matches(comp_key, target_dates, erreurs_uefa)
        season = next((int(to_number(m.get("seasonYear"))) for m in raw_matches if m.get("seasonYear")),
                      uefa.season_year_for(date.fromisoformat(target_dates[0])))
        standings, standings_source, standings_at = choisir_classement(comp_key, season, jour, classement_mode, maintenant)
        by_team = {r["team_id"]: r for r in standings}
        is_league = any(((m.get("round") or {}).get("mode") or "") == "GROUP" for m in raw_matches) or \
            (not raw_matches and bool(standings))

        matches, focus = [], []
        for m in raw_matches:
            fr_match = any((m.get(k) or {}).get("countryCode") == "FRA" for k in ("homeTeam", "awayTeam"))
            match = build_match(comp_key, m, detailed=fr_match)
            matches.append(match)
            matches_total += 1
            if match["finished"]:
                finished_total += 1
                if avec_xg:
                    try:
                        bilan_xg[espn.ajouter_xg(comp_key, match)] += 1
                    except Exception as e:   # l'xG est un bonus : rien ne doit arrêter la collecte
                        bilan_xg["erreur"] += 1
                        print(f"[WARN] xG ignoré pour {match['home_team']['name']}-{match['away_team']['name']} : {e}")
            if not match["is_french_match"] or not match["finished"]:
                continue

            h, a = match["home_team"], match["away_team"]
            comments: List[str] = []
            espn_id = avec_espn and espn.find_espn_event(comp_key, match["date"], [h["name"], h["official_name"]],
                                                         [a["name"], a["official_name"]], h["score"], a["score"])
            if espn_id:
                comments = espn.fetch_commentary(comp_key, espn_id)
            print(f"[INFO] {h['name']}-{a['name']} : {len(match['actions'])} actions UEFA, "
                  f"{len(comments)} lignes de fil ESPN" + ("" if espn_id or not avec_espn else " (match ESPN introuvable)"))

            for t in (h, a):
                if not t["is_french"]:
                    continue
                row = by_team.get(t["id"], {})
                focus.append({
                    "match_id": match["match_id"], "club_name": t["name"], "club_id": t["id"],
                    "club_rank": row.get("rank"), "club_zone": row.get("zone"),
                    "home_team": h, "away_team": a, "status": match["status"], "goals": match["goals"],
                    "raw_comments_for_llm": comments, "ai_summary": "", "ai_verified": False,
                })

        labels = sorted({m["matchday"] for m in matches if m["matchday"]})
        output["competitions"][comp_key] = {
            "id": comp_key, "name": meta["name"], "short_name": meta["short_name"],
            "stage_type": "league" if is_league else "knockout",
            "matchday_label": (" / ".join(labels) + " — " if labels else "") + label_prefix,
            "french_clubs_focus": focus,
            "matches": sorted(matches, key=lambda x: (x["date"], x["kickoff"])),
            "standings": standings,
            "standings_source": standings_source,
            **({"standings_at": standings_at} if standings_at else {}),
            "bracket": None,
        }
        print(f"[INFO] {meta['name']} : {len(matches)} match(s), {len(standings)} équipes au classement ({standings_source}), "
              f"{len(focus)} fiche(s) club français.")

    if avec_xg:
        print(f"[xG] {bilan_xg['ok']}/{finished_total} match(s) terminé(s) avec xG (ESPN / Opta) ; "
              f"{bilan_xg['non_trouve']} non rapproché(s), {bilan_xg['absent']} sans xG, {bilan_xg['erreur']} en erreur ; "
              f"{espn.REQUETES['scoreboard']} + {espn.REQUETES['stats']} requête(s) ESPN (scoreboard + statistiques d'équipe).")
    # Notes : standardisation et calibrage par compétition (niveaux différents entre LDC, EL et ECL)
    output["ratings"] = {}
    for comp_key, comp in output["competitions"].items():
        rated = [m for m in comp["matches"] if m.get("players")]
        if rated:
            print(f"[NOTES] {comp['name']} :")
            output["ratings"][comp_key] = ratings.rate_matches(rated)
    output["notification"]["match_night"] = finished_total > 0
    # Compteurs pour l'état par soirée (soirees.py) ; incomplet = liste UEFA illisible pour une compétition
    output["notification"].update({"matchs": matches_total, "termines": finished_total,
                                   "incomplet": bool(erreurs_uefa)})
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"[OK] {finished_total} match(s) terminé(s) -> {output_path}")
    return output


def get_current_week_european_dates(ref_date: Optional[date] = None) -> List[str]:
    ref_date = ref_date or date.today()
    monday = ref_date - timedelta(days=ref_date.weekday())
    return [(monday + timedelta(days=o)).isoformat() for o in (1, 2, 3)]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collecteur Coupes d'Europe (UEFA + ESPN)")
    parser.add_argument("--date", help="Date précise YYYY-MM-DD")
    parser.add_argument("--week", action="store_true", help="Mardi à jeudi de la semaine en cours")
    parser.add_argument("--save-raw", help="Dossier où sauvegarder les réponses brutes (debug)")
    args = parser.parse_args()
    set_raw_dir(args.save_raw)
    if args.week:
        d = get_current_week_european_dates()
        collect_dates_data(d, label_prefix=f"semaine du {d[0]} au {d[-1]}")
    else:
        d_str = args.date or date.today().isoformat()
        collect_dates_data([d_str], label_prefix=f"soirée du {d_str}")
