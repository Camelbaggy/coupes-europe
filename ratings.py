#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Notation des joueurs sur 10, à partir des statistiques officielles UEFA.

Sources méthodologiques :
  [1] Ball, Huynh & Varley (2025), « Comparing player rating systems as a metric for assessing individual
      performance in soccer », Journal of Sports Sciences 43:7. Table 2 : coefficients des statistiques
      (standardisées) expliquant les notes FotMob, Sofascore et WhoScored ; distribution observée des notes
      (FotMob : moyenne 6,87, écart-type 0,79) ; pas de note sous 10 minutes de jeu.
  [2] Wolf, Schmitt & Schuller (2020), « A football player rating system », Journal of Sports Analytics 6.
      Composante « résultat individuel » : écart de buts pendant le temps de jeu du joueur, comparé au
      résultat attendu, pondéré par la racine cubique de l'écart et les minutes jouées (formules 8 et 9).

Méthode :
  1. Joueurs de champ : chaque statistique est standardisée (score z) sur l'ensemble des joueurs de champ
     de la collecte (≥ 10 min), puis pondérée par le coefficient FotMob de [1] (variables absentes chez
     l'UEFA, comme les xG, les touches et les interceptions, exclues ; variables proches substituées).
  2. Bonus explicites pour les contributions directes (buts, passes décisives), que [1] retire de son modèle.
  3. Gardiens (exclus de [1]) : formule dédiée (arrêts, buts encaissés, clean sheet, jeu au pied).
  4. Composante résultat de [2] pour tous ; bonus clean sheet pour les défenseurs.
  5. Calibrage final pour retrouver la distribution de [1] (moyenne 6,85, écart-type 0,75), bornes 3-10.
  6. Les entrées tardives sont ramenées vers la moyenne (peu de temps de jeu = peu d'information).
"""

from statistics import mean, pstdev
from typing import Any, Dict, List, Tuple

MIN_MINUTES = 10
TARGET_MEAN, TARGET_SD = 6.85, 0.75

# (clé UEFA, poids, libellé du facteur) — poids d'après la colonne FotMob de la Table 2 de [1]
OUTFIELD_WEIGHTS: List[Tuple[str, float, str]] = [
    ("attempts_on_target", 0.17, "tirs cadrés"),
    ("attempts", 0.05, "volume de tirs"),               # substitut partiel des xG (0,15 dans [1])
    ("key_passes", 0.20, "passes clés"),                # passes clés (0,15) + substitut des xA/xAG
    ("recovered_ball", 0.15, "ballons récupérés"),
    ("dribbling_successful", 0.14, "dribbles réussis"),
    ("clearance_completed", 0.12, "dégagements"),
    ("tackles_won", 0.09, "duels gagnés"),
    ("tackles", 0.06, "duels disputés"),
    ("passes_short_completed", 0.08, "passes courtes réussies"),
    ("passes_completed_forward", 0.02, "passes vers l'avant"),
    ("delivery_into_penalty_area", 0.03, "passes dans la surface"),
    ("fouls_suffered", 0.06, "fautes obtenues"),
    ("saves_and_blocks", 0.05, "contres"),
    ("cross_completed", 0.02, "centres réussis"),
    ("lost_balls", -0.10, "pertes de balle"),           # « dispossessed » (-0,14) au sens large
]
GOAL_BONUS = {"FORWARD": 0.85, "MIDFIELDER": 0.95, "DEFENDER": 1.05, "GOALKEEPER": 1.2}
ASSIST_BONUS = 0.6
YELLOW, RED = -0.15, -1.2
RESULT_WEIGHT = 0.3
CLEAN_SHEET_DEF = 0.25


def _z_tables(players: List[Dict[str, Any]]) -> Dict[str, Tuple[float, float]]:
    tables = {}
    for key, _, _ in OUTFIELD_WEIGHTS:
        vals = [float(p["stats"].get(key, 0) or 0) for p in players]
        sd = pstdev(vals) if len(vals) > 1 else 0.0
        tables[key] = (mean(vals) if vals else 0.0, sd if sd > 1e-9 else 1.0)
    return tables


def _on_pitch_goal_diff(p: Dict[str, Any], match: Dict[str, Any]) -> Tuple[int, int]:
    """(buts marqués, buts encaissés) par l'équipe du joueur pendant qu'il était sur le terrain."""
    start = p.get("subbed_in_minute") or 0
    end = p.get("subbed_out_minute") or 999
    side = p["team"]
    scored = conceded = 0
    for g in match.get("goals", []):
        m = g.get("base_minute") or 0
        if g.get("phase") == "SECOND_HALF" and m < 46:
            m = 46
        if start <= m <= end:
            if g["team"] == side:
                scored += 1
            else:
                conceded += 1
    return scored, conceded


def _result_component(p: Dict[str, Any], match: Dict[str, Any]) -> Tuple[float, int]:
    """Formules 8-9 de [2] : (S - E) × ∛|D| (victoire/défaite) ou (S - E) × minutes/90 (nul)."""
    scored, conceded = _on_pitch_goal_diff(p, match)
    d = scored - conceded
    s = 1.0 if d > 0 else 0.5 if d == 0 else 0.0
    e = 0.54 if p["team"] == "home" else 0.46   # léger avantage du terrain, sans hypothèse sur la force des équipes
    share = min(1.0, (p.get("minutes") or 0) / 90)
    if d != 0:
        value = (s - e) * (abs(d) ** (1 / 3)) * share
    else:
        value = (s - e) * share
    return RESULT_WEIGHT * value, conceded


def _goalkeeper_score(p: Dict[str, Any], conceded_on_pitch: int) -> List[Tuple[str, float]]:
    st = p["stats"]
    factors = [
        ("arrêts", 0.35 * float(st.get("saves", 0) or 0)),
        ("buts encaissés", -0.45 * float(st.get("goals_conceded", conceded_on_pitch) or 0)),
    ]
    if conceded_on_pitch == 0 and (p.get("minutes") or 0) >= 60:
        factors.append(("clean sheet", 0.55))
    acc = st.get("passes_accuracy")
    if acc is not None and (st.get("passes_attempted") or 0) >= 10:
        factors.append(("jeu au pied", 0.01 * (float(acc) - 75)))
    return factors


def rate_matches(matches: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calcule note et facteurs de chaque joueur (≥ 10 min) des matchs fournis. Modifie les matchs en place."""
    rated: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for m in matches:
        for p in (m.get("players") or {}).values():
            if (p.get("minutes") or 0) >= MIN_MINUTES:
                rated.append((m, p))
    if not rated:
        return {"players": 0}

    outfield = [p for _, p in rated if p["pos"] != "GOALKEEPER"]
    z = _z_tables(outfield)

    # (score de performance, contributions directes, facteurs [(libellé, valeur, direct ?)])
    raw: Dict[int, Tuple[float, float, List[Tuple[str, float, bool]]]] = {}
    for m, p in rated:
        st = p["stats"]
        res, conceded = _result_component(p, m)
        if p["pos"] == "GOALKEEPER":
            factors = [(lbl, v, False) for lbl, v in _goalkeeper_score(p, conceded)]
        else:
            factors = []
            for key, w, label in OUTFIELD_WEIGHTS:
                mu, sd = z[key]
                factors.append((label, w * (float(st.get(key, 0) or 0) - mu) / sd, False))
            if p["pos"] == "DEFENDER" and conceded == 0 and (p.get("minutes") or 0) >= 60:
                factors.append(("clean sheet", CLEAN_SHEET_DEF, False))
        factors.append(("résultat pendant son temps de jeu", res, False))
        # Contributions directes : comptées en entier, même pour un remplaçant entré tard
        goals = float(st.get("goals", 0) or 0)
        if goals:
            factors.append((f"{int(goals)} but{'s' if goals > 1 else ''}", goals * GOAL_BONUS.get(p["pos"], 0.9), True))
        assists = float(st.get("assists", 0) or 0)
        if assists:
            factors.append((f"{int(assists)} passe{'s' if assists > 1 else ''} décisive{'s' if assists > 1 else ''}",
                            assists * ASSIST_BONUS, True))
        if st.get("yellow_cards"):
            factors.append(("carton jaune", YELLOW, True))
        if st.get("red_cards"):
            factors.append(("carton rouge", RED, True))
        raw[id(p)] = (sum(v for _, v, d in factors if not d), sum(v for _, v, d in factors if d), factors)

    totals = [raw[id(p)][0] + raw[id(p)][1] for _, p in rated]
    sd = pstdev(totals) or 1.0
    scale = TARGET_SD / sd if len(totals) >= 20 else 1.0
    mu_perf = mean(raw[id(p)][0] for _, p in rated)
    mu_direct = mean(raw[id(p)][1] for _, p in rated)
    for m, p in rated:
        perf, direct, factors = raw[id(p)]
        # Temps de jeu court : la partie « statistiques » est ramenée vers la moyenne (peu d'information),
        # les contributions directes (buts, passes décisives, cartons) comptent en entier.
        weight = min(1.0, 0.35 + 0.65 * (p["minutes"] / 60))
        rating = TARGET_MEAN + scale * ((perf - mu_perf) * weight + (direct - mu_direct))
        p["rating"] = round(max(3.0, min(10.0, rating)), 1)
        visible = [(lbl, v * scale * (1 if d else weight)) for lbl, v, d in factors
                   if abs(v * scale * (1 if d else weight)) >= 0.05]
        visible.sort(key=lambda x: -abs(x[1]))
        p["factors"] = [{"label": lbl, "value": round(v, 2)} for lbl, v in visible[:6]]

    # Report des notes dans les compositions
    for m in matches:
        players = m.get("players") or {}
        lu = m.get("lineups") or {}
        for key in ("home", "away", "home_subs", "away_subs"):
            for entry in lu.get(key) or []:
                entry["rating"] = (players.get(entry.get("id")) or {}).get("rating")

    # Validation : le mieux noté de chaque match est-il l'homme du match désigné par l'UEFA ?
    checked = hits = top3 = 0
    for m in matches:
        ps = [p for p in (m.get("players") or {}).values() if p.get("rating") is not None]
        potm = next((p for p in ps if p.get("potm")), None)
        if not potm or not ps:
            continue
        ordered = sorted(ps, key=lambda p: -p["rating"])
        checked += 1
        hits += ordered[0]["id"] == potm["id"] or ordered[0]["rating"] == potm["rating"]
        top3 += potm["id"] in [p["id"] for p in ordered[:3]]
    all_ratings = [p["rating"] for _, p in rated]
    summary = {
        "players": len(rated), "mean": round(mean(all_ratings), 2), "sd": round(pstdev(all_ratings), 2),
        "min": min(all_ratings), "max": max(all_ratings),
        "potm_matches": checked, "potm_top1": hits, "potm_top3": top3,
    }
    print(f"[NOTES] {summary['players']} joueurs notés — moyenne {summary['mean']}, écart-type {summary['sd']}, "
          f"min {summary['min']}, max {summary['max']}")
    if checked:
        print(f"[NOTES] Homme du match UEFA : meilleure note dans {hits}/{checked} matchs "
              f"({100 * hits / checked:.0f} %), dans le top 3 dans {top3}/{checked} ({100 * top3 / checked:.0f} %)")
    return summary
