#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Classement d'un championnat RECALCULÉ à une date, uniquement depuis les scores des matchs terminés (étape 4 des championnats).

ESPN, comme l'UEFA, ne donne que le classement ACTUEL : pour une journée passée (reconstitution, relance tardive) on le
recalcule ici, de façon déterministe, et on le marque `standings_source: "calcule"` + `standings_at`.

Entrées : matchs de la saison (`ligues.saison` : {espn_id, home, away, date_utc, score (h, a) si terminé}) ; seuls les matchs
TERMINÉS dont la date (heure de Paris) est <= `jusqu_a` comptent. Clubs : ceux du classement ESPN (ids `espn-<id>`).

Critères appliqués (`CRITERES`, documentés dans docs/etude_championnats.md § 14), dans l'ordre :
  - Premier League, Bundesliga, Ligue 1 : points, différence de buts, buts marqués ;
  - Liga, Serie A : points, puis CONFRONTATIONS DIRECTES (points puis différence de buts des seuls matchs entre les clubs à
    égalité) SEULEMENT si tous ces matchs (aller et retour) ont été joués à la date, puis différence de buts, buts marqués.
Les critères suivants des règlements (fair-play, autres confrontations…) ne sont pas appliqués : une égalité qui leur survit
est laissée en EX ÆQUO (même rang, `ex_aequo: true`, ordre interne alphabétique, présentation seulement). Pas de zone (elle ne
décrit que la fin de saison) ni de pénalité de points (aucune connue cette saison ; une pénalité future serait signalée par
l'écart avec le classement ESPN, voir `comparer`).

Validation (`python classement_ligue.py --valider`, réseau) : calcul jusqu'à aujourd'hui comparé au classement ESPN actuel des
5 championnats. Tests : `python classement_ligue.py --test`.
"""

import argparse
import datetime as dt
import sys
from typing import Any, Dict, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
    PARIS = ZoneInfo("Europe/Paris")
except Exception:  # pragma: no cover
    PARIS = dt.timezone(dt.timedelta(hours=1))

CRITERES = {
    "pl": ["points", "gd", "gf"],
    "bl": ["points", "gd", "gf"],
    "fl1": ["points", "gd", "gf"],
    "fl2": ["points", "gd", "gf"],         # règlement LFP, mêmes premiers critères que la Ligue 1
    # Championnats secondaires (26/11/2026) : critères appliqués seulement quand ils sont sûrs ; sinon les points seuls (deux clubs à
    # égalité de points = même rang, suivi de « = » : jamais de départage deviné)
    "ned": ["points", "gd", "gf"], "nor": ["points", "gd", "gf"], "aut": ["points", "gd", "gf"],
    "por": ["points"], "bel": ["points"], "tur": ["points"], "gre": ["points"],
    "liga": ["points", "h2h", "gd", "gf"],
    "sa": ["points", "h2h", "gd", "gf"],
}
LIBELLES = {"points": "points", "gd": "différence de buts", "gf": "buts marqués",
            "h2h": "confrontations directes (points puis différence de buts, seulement si tous ces matchs ont été joués)"}


def jour_paris(iso: str) -> str:
    try:
        return dt.datetime.fromisoformat((iso or "").replace("Z", "+00:00")).astimezone(PARIS).date().isoformat()
    except ValueError:
        return ""


def _table(matchs: List[Tuple[str, str, int, int]], clubs: List[str]) -> Dict[str, Dict[str, int]]:
    t = {c: {"j": 0, "g": 0, "n": 0, "p": 0, "bp": 0, "bc": 0, "points": 0} for c in clubs}
    for h, a, sh, sa in matchs:
        if h not in t or a not in t:
            continue
        for c, pour, contre in ((h, sh, sa), (a, sa, sh)):
            x = t[c]
            x["j"] += 1
            x["bp"] += pour
            x["bc"] += contre
            if pour > contre:
                x["g"] += 1
                x["points"] += 3
            elif pour == contre:
                x["n"] += 1
                x["points"] += 1
            else:
                x["p"] += 1
    for x in t.values():
        x["gd"] = x["bp"] - x["bc"]
        x["gf"] = x["bp"]
    return t


def _departager(groupe: List[str], criteres: List[str], table: Dict[str, Dict[str, int]],
                matchs: List[Tuple[str, str, int, int]]) -> List[List[str]]:
    """Ordonne `groupe` (clubs à égalité jusqu'ici) ; retourne une liste de sous-groupes (un sous-groupe de plusieurs clubs =
    égalité résiduelle)."""
    if len(groupe) == 1 or not criteres:
        return [sorted(groupe)] if len(groupe) > 1 else [groupe]
    c, reste = criteres[0], criteres[1:]
    if c == "h2h":
        membres = set(groupe)
        entre = [m for m in matchs if m[0] in membres and m[1] in membres]
        paires = {(h, a) for h, a, _, _ in entre}
        complet = all((x, y) in paires for x in groupe for y in groupe if x != y)
        if not complet:
            return _departager(groupe, reste, table, matchs)
        mini = _table(entre, groupe)
        cle = lambda x: (mini[x]["points"], mini[x]["gd"])  # noqa: E731
    else:
        cle = lambda x: table[x][c]  # noqa: E731
    valeurs = sorted({cle(x) for x in groupe}, reverse=True)
    out: List[List[str]] = []
    for v in valeurs:
        sous = [x for x in groupe if cle(x) == v]
        out += _departager(sous, reste, table, matchs)
    return out


def calculer(ligue: str, matchs_saison: List[Dict[str, Any]], clubs: Dict[str, Dict[str, Any]],
             jusqu_a: str) -> List[Dict[str, Any]]:
    """Lignes de classement au format de `ligues.classement` (sans zone) + `ex_aequo`. `clubs` : {id ESPN brut: ligne de
    classement ESPN (nom, logo…)} ; un club sans match terminé à la date figure avec 0 point."""
    joues = [(m["home"], m["away"], int(m["score"][0]), int(m["score"][1])) for m in matchs_saison
             if m.get("score") is not None and jour_paris(m.get("date_utc", "")) <= jusqu_a]
    if not joues:
        return []
    ids = list(clubs)
    table = _table(joues, ids)
    groupes = _departager(ids, CRITERES[ligue], table, joues)
    rows, rang = [], 1
    for g in groupes:
        for c in g:
            meta = clubs[c]
            x = table[c]
            rows.append({**{k: meta[k] for k in ("team_id", "team", "short_name", "country", "country_name", "flag", "logo",
                                                  "is_french") if k in meta},
                         "rank": rang, "played": x["j"], "won": x["g"], "drawn": x["n"], "lost": x["p"], "gf": x["bp"],
                         "ga": x["bc"], "gd": f"+{x['gd']}" if x["gd"] > 0 else str(x["gd"]), "points": x["points"],
                         **({"ex_aequo": True} if len(g) > 1 else {})})
        rang += len(g)
    return rows


def comparer(calcule: List[Dict[str, Any]], officiel: List[Dict[str, Any]]) -> List[str]:
    """Écarts (rang, points, matchs joués) entre un classement calculé et le classement officiel."""
    off = {r["team_id"]: r for r in officiel}
    ecarts = []
    for r in calcule:
        o = off.get(r["team_id"])
        if not o:
            ecarts.append(f"{r['team']} absent du classement officiel")
            continue
        for k in ("points", "played", "gd"):
            if str(r[k]) != str(o[k]):
                ecarts.append(f"{r['team']} : {k} {r[k]} calculé, {o[k]} officiel")
        if r["rank"] != o["rank"] and not (r.get("ex_aequo") and abs(r["rank"] - o["rank"]) < 5):
            ecarts.append(f"{r['team']} : rang {r['rank']} calculé, {o['rank']} officiel")
    return ecarts


def _test() -> None:
    clubs = {c: {"team_id": f"espn-{c}", "team": c.upper()} for c in "abcd"}
    m = lambda h, a, sh, sa, d="2026-09-01T18:00Z": {"home": h, "away": a, "score": (sh, sa), "date_utc": d}  # noqa: E731
    saison = [m("a", "b", 2, 0), m("c", "d", 1, 1), m("b", "c", 3, 0), m("d", "a", 0, 0),
              m("a", "c", 0, 1, "2026-10-01T18:00Z"), {"home": "b", "away": "d", "score": None, "date_utc": "2026-10-01T18:00Z"}]
    r = calculer("pl", saison, clubs, "2026-09-30")
    assert [(x["team"], x["points"], x["rank"]) for x in r] == [("A", 4, 1), ("B", 3, 2), ("D", 2, 3), ("C", 1, 4)], r
    # date : le match du 1er octobre ne compte qu'à partir de cette date
    assert {x["team"]: x["played"] for x in calculer("pl", saison, clubs, "2026-10-01")}["C"] == 3
    # égalité parfaite : ex æquo, même rang
    eg = [m("a", "b", 1, 1), m("c", "d", 1, 1)]
    r = calculer("pl", eg, clubs, "2026-12-31")
    assert all(x["rank"] == 1 and x["ex_aequo"] for x in r), r
    # Liga : confrontations directes appliquées seulement si aller ET retour joués
    deux = {c: clubs[c] for c in "ab"}
    s = [m("a", "b", 0, 1), m("b", "a", 0, 3)]             # a : 3 pts, +2 ; b : 3 pts, -2 ; h2h a gagne (diff +2)
    r = calculer("liga", s, deux, "2026-12-31")
    assert [x["team"] for x in r] == ["A", "B"] and not r[0].get("ex_aequo")
    trois = {c: clubs[c] for c in "abc"}
    deux_b = {c: clubs[c] for c in "ab"}
    s2 = [m("a", "b", 1, 0), m("b", "x", 4, 0), m("a", "y", 0, 3)]   # x, y hors classement : ignorés
    s2 = [m("a", "b", 1, 0), m("b", "a", 3, 0, "2026-11-01T18:00Z")]  # aller-retour : 3 pts chacun, h2h b (+2)
    r = calculer("liga", s2, deux_b, "2026-12-31")
    assert [x["team"] for x in r] == ["B", "A"], r
    # trois clubs à 3 points, a-b aller seulement : pas de confrontations directes, différence de buts b +3, c -1, a -2
    s3 = [m("a", "b", 1, 0), m("a", "c", 0, 3), m("b", "c", 4, 0)]
    r = calculer("liga", s3, trois, "2026-12-31")
    assert [x["team"] for x in r] == ["B", "C", "A"], r
    assert comparer([{"team_id": "1", "team": "A", "rank": 1, "points": 3, "played": 1, "gd": "+1"}],
                    [{"team_id": "1", "rank": 1, "points": 3, "played": 1, "gd": "+1"}]) == []
    print("[OK] classement_ligue : tests passés")


def valider() -> int:
    import ligues
    total = 0
    auj = dt.datetime.now(PARIS).date().isoformat()
    for lg in ligues.LIGUES:
        officiel, _ = ligues.classement(lg)
        clubs = {r["team_id"].replace("espn-", ""): r for r in officiel}
        ms = ligues.saison(lg, int(auj[:4]) if auj[5:7] >= "07" else int(auj[:4]) - 1, {c: [] for c in clubs})
        calc = calculer(lg, ms or [], clubs, auj)
        ec = comparer(calc, officiel)
        total += len(ec)
        print(f"[VALIDATION] {lg} : {len(calc)} clubs, {len(ec)} écart(s) ; ex æquo : "
              f"{sum(1 for r in calc if r.get('ex_aequo'))}" + (f" ; {ec[:6]}" if ec else ""))
    return 1 if total else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--valider", action="store_true")
    a = ap.parse_args()
    if a.test:
        _test()
    elif a.valider:
        sys.exit(valider())
