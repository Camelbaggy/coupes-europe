#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Classement de la phase de ligue RECALCULÉ à une date donnée, uniquement à partir des scores des matchs terminés.

Pourquoi : l'API de classement de l'UEFA ne donne que l'état ACTUEL (les paramètres matchday / date sont ignorés).
Pour une soirée passée (reconstitution, ou soirée plus ancienne que la plus récente), on ne recopie jamais le
classement d'aujourd'hui : on le recalcule ici, déterministe, et on le marque `standings_source: "calcule"`.

Données d'entrée : liste de matchs normalisés (voir `matchs_depuis_uefa`) ; seuls les matchs de PHASE DE LIGUE
(`round.mode == "GROUP"`), TERMINÉS (`FINISHED`) et datés au plus tard de `jusqu_a` (AAAA-MM-JJ, inclus) comptent.
Les tours préliminaires (`QUALIFYING`) n'ont pas de classement : `calculer_classement` ne les voit jamais.

Critères de départage appliqués, dans l'ordre (règlement UEFA de la phase de ligue ; les noms des champs
`opponentsPoints` / `opponentsGoalDifference` / `opponentsGoalScored` du classement officiel UEFA confirment la
définition des critères g à i, vérifiée sur les données réelles : voir `python classement.py --test`) :
  a. points ;
  b. différence de buts ;
  c. buts marqués ;
  d. buts marqués à l'extérieur ;
  e. victoires ;
  f. victoires à l'extérieur ;
  g. total des points de TOUS les adversaires affrontés (un adversaire compte autant de fois qu'il a été rencontré) ;
  h. différence de buts totale de tous les adversaires ;
  i. buts marqués au total par tous les adversaires.
NON appliqués faute de données à la date voulue : j. points disciplinaires (cartons de TOUS les matchs de la
phase de ligue, non collectés) et k. coefficient de club. Une égalité qui survit à g-i est donc laissée en
ex æquo : les clubs concernés portent le MÊME rang (1, 2, 2, 4…), `ex_aequo: true`, ordre interne alphabétique
(présentation seulement, aucune valeur n'est inventée).
Aucune zone (`top8` / `playoff` / `eliminated`) : elle n'a de sens qu'à l'issue de la dernière journée.

Fonctions pures, bibliothèque standard seule ; tests : `python classement.py --test`.
"""

import datetime as dt
import sys
from typing import Any, Dict, List, Optional

CRITERES = ("points", "gd", "gf", "gf_ext", "victoires", "victoires_ext", "adv_points", "adv_gd", "adv_gf")


def officiel_valable(jour: str, maintenant: dt.datetime) -> bool:
    """Le classement OFFICIEL actuel de l'UEFA décrit-il encore l'état à l'issue de la soirée `jour` ?

    Oui tant qu'on est avant 13 h UTC le lendemain (fin du créneau du battement : aucun match du lendemain n'a commencé,
    leur coup d'envoi le plus précoce est vers 16 h 45 UTC). Au-delà, l'UEFA a pu intégrer des matchs plus récents :
    on recalcule (`calculer_classement`) au lieu de recopier un classement d'une autre date."""
    d = dt.date.fromisoformat(jour) + dt.timedelta(days=1)
    return maintenant < dt.datetime(d.year, d.month, d.day, 13, tzinfo=dt.timezone.utc)


def matchs_depuis_uefa(raw_matches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Matchs UEFA bruts (`match.uefa.com/v5/matches`) -> lignes minimales de phase de ligue TERMINÉS.

    Un match sans score total lisible est ignoré (jamais un 0-0 inventé)."""
    import uefa  # import local : ce module reste pur / testable sans réseau
    from netutil import to_number
    out = []
    for m in raw_matches:
        if ((m.get("round") or {}).get("mode") or "") != "GROUP" or m.get("status") != "FINISHED":
            continue
        total = (m.get("score") or {}).get("total") or {}
        hg, ag = to_number(total.get("home")), to_number(total.get("away"))
        date = ((m.get("kickOffTime") or {}).get("date") or "")[:10]
        if hg is None or ag is None or not date:
            continue
        out.append({"date": date, "home": uefa.team_info(m.get("homeTeam") or {}),
                    "away": uefa.team_info(m.get("awayTeam") or {}), "hg": int(hg), "ag": int(ag)})
    return out


def _cumul(matchs: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    t: Dict[str, Dict[str, Any]] = {}

    def ligne(info):
        return t.setdefault(info["id"], {"info": info, "played": 0, "won": 0, "drawn": 0, "lost": 0, "gf": 0, "ga": 0,
                                         "gf_ext": 0, "victoires_ext": 0, "points": 0, "adversaires": []})
    for m in matchs:
        h, a = ligne(m["home"]), ligne(m["away"])
        for x, y, gf, ga, ext in ((h, a, m["hg"], m["ag"], False), (a, h, m["ag"], m["hg"], True)):
            x["played"] += 1
            x["gf"] += gf
            x["ga"] += ga
            x["adversaires"].append(y["info"]["id"])
            if ext:
                x["gf_ext"] += gf
            if gf > ga:
                x["won"] += 1
                x["points"] += 3
                if ext:
                    x["victoires_ext"] += 1
            elif gf == ga:
                x["drawn"] += 1
                x["points"] += 1
            else:
                x["lost"] += 1
    for x in t.values():
        x["gd"] = x["gf"] - x["ga"]
        x["victoires"] = x["won"]
    for x in t.values():
        adv = [t[i] for i in x["adversaires"]]
        x["adv_points"] = sum(o["points"] for o in adv)
        x["adv_gd"] = sum(o["gd"] for o in adv)
        x["adv_gf"] = sum(o["gf"] for o in adv)
    return t


def calculer_classement(matchs: List[Dict[str, Any]], jusqu_a: Optional[str] = None) -> List[Dict[str, Any]]:
    """Classement de la phase de ligue après les matchs datés au plus tard de `jusqu_a` (None = tous).

    Lignes au format de `uefa.fetch_standings` (rank, team_id, team, short_name, country, country_name, flag, logo,
    is_french, played, won, drawn, lost, gf, ga, gd, points) SANS `zone` ni `trend`, plus `ex_aequo` (bool)."""
    retenus = [m for m in matchs if not jusqu_a or m["date"] <= jusqu_a]
    t = _cumul(retenus)
    cle = lambda x: tuple(x[c] for c in CRITERES)
    ordre = sorted(t.values(), key=lambda x: (tuple(-v for v in cle(x)), x["info"]["name"].lower()))
    rows: List[Dict[str, Any]] = []
    for i, x in enumerate(ordre):
        if i and cle(ordre[i - 1]) == cle(x):
            rang = rows[-1]["rank"]
            rows[-1]["ex_aequo"] = True
            ex = True
        else:
            rang, ex = i + 1, False
        info = x["info"]
        rows.append({
            "rank": rang, "team_id": info["id"], "team": info["name"], "short_name": info["short"],
            "country": info["country"], "country_name": info["country_name"], "flag": info["flag"],
            "logo": info["logo"], "is_french": info["is_french"],
            "played": x["played"], "won": x["won"], "drawn": x["drawn"], "lost": x["lost"],
            "gf": x["gf"], "ga": x["ga"], "gd": f"+{x['gd']}" if x["gd"] > 0 else str(x["gd"]),
            "points": x["points"], "ex_aequo": ex,
        })
    return rows


def _eq(i, nom, pays="FRA"):
    return {"id": str(i), "name": nom, "short": nom[:3].upper(), "country": pays, "country_name": pays,
            "flag": "", "logo": "", "is_french": pays == "FRA"}


def _test():
    import json
    import os
    U = dt.timezone.utc
    assert officiel_valable("2026-11-24", dt.datetime(2026, 11, 25, 3, 0, tzinfo=U)) is True      # passage de 3 h : officiel
    assert officiel_valable("2026-11-24", dt.datetime(2026, 11, 25, 12, 59, tzinfo=U)) is True
    assert officiel_valable("2026-11-24", dt.datetime(2026, 11, 25, 13, 0, tzinfo=U)) is False    # plus tard : recalculé
    # 1. cas fait main : 4 clubs, tout est vérifiable à la main
    A, B, C, D = _eq(1, "A"), _eq(2, "B"), _eq(3, "C", "ESP"), _eq(4, "D", "ESP")
    ms = [
        {"date": "2026-09-01", "home": A, "away": B, "hg": 2, "ag": 0},   # A 3 pts
        {"date": "2026-09-01", "home": C, "away": D, "hg": 1, "ag": 1},   # C, D 1 pt
        {"date": "2026-09-15", "home": B, "away": C, "hg": 3, "ag": 1},   # B 3 pts
        {"date": "2026-09-15", "home": D, "away": A, "hg": 0, "ag": 1},   # A 3 pts (à l'extérieur)
    ]
    r = calculer_classement(ms)
    assert [x["team"] for x in r][:2] == ["A", "B"], r
    a = r[0]
    assert (a["team"], a["rank"], a["points"], a["played"], a["won"], a["gd"]) == ("A", 1, 6, 2, 2, "+3")
    b = r[1]
    assert (b["team"], b["points"], b["gd"]) == ("B", 3, "0")
    # après la 1re soirée seulement : A 3 pts, B 0 ; C et D 1 pt chacun, D devant C (buts marqués à l'extérieur : critère d)
    r1 = calculer_classement(ms, "2026-09-01")
    assert [(x["team"], x["points"]) for x in r1] == [("A", 3), ("D", 1), ("C", 1), ("B", 0)], r1
    assert [x["rank"] for x in r1] == [1, 2, 3, 4] and not any(x["ex_aequo"] for x in r1)
    assert calculer_classement(ms, "2026-08-31") == []
    # égalité parfaite : mêmes rangs partagés (1, 1, 3, 3), ex æquo signalé, ordre alphabétique à l'intérieur
    P, Q, R, S = _eq(11, "P"), _eq(12, "Q"), _eq(13, "R"), _eq(14, "S")
    r4 = calculer_classement([{"date": "d", "home": P, "away": Q, "hg": 1, "ag": 1}, {"date": "d", "home": R, "away": S, "hg": 1, "ag": 1}])
    assert [(x["team"], x["rank"], x["ex_aequo"]) for x in r4] == [("Q", 1, True), ("S", 1, True), ("P", 3, True), ("R", 3, True)], r4
    # départage : buts à l'extérieur (d) avant les victoires (e)
    X, Y, Z = _eq(5, "X"), _eq(6, "Y"), _eq(7, "Z")
    ms2 = [{"date": "d", "home": X, "away": Z, "hg": 1, "ag": 1}, {"date": "d", "home": Z, "away": Y, "hg": 1, "ag": 1}]
    r2 = calculer_classement(ms2)
    # X : 1 pt, 1 but ; Y : 1 pt, 1 but à l'extérieur ; Z : 2 pts -> Z, puis Y (buts ext. 1) devant X (0)
    assert [x["team"] for x in r2] == ["Z", "Y", "X"], r2
    # 2. cas réel : classement de la LDC 2026-27 au 24/11/2026 (fixture) comparé au classement officiel UEFA
    chemin = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools", "fixtures", "classement_ldc_2027.json")
    with open(chemin, "r", encoding="utf-8") as f:
        fx = json.load(f)
    ids = {e["id"]: e for e in fx["equipes"]}
    ms3 = [{"date": m[0], "home": _eq(m[1], ids[str(m[1])]["nom"], ids[str(m[1])]["pays"]),
            "away": _eq(m[2], ids[str(m[2])]["nom"], ids[str(m[2])]["pays"]), "hg": m[3], "ag": m[4]}
           for m in fx["matchs"]]
    r3 = calculer_classement(ms3, fx["jusqu_a"])
    off = {o["id"]: o for o in fx["officiel"]}
    assert len(r3) == len(off) == 36
    for x in r3:
        o = off[x["team_id"]]
        assert (x["points"], x["played"], x["gf"], x["ga"]) == (o["points"], o["played"], o["gf"], o["ga"]), (x, o)
        # rang : celui de l'UEFA, sauf pour les clubs encore à égalité après g-i (UEFA : fair-play / coefficient)
        if not x["ex_aequo"]:
            assert x["rank"] == o["rank"], (x["team"], x["rank"], o["rank"])
    ecart = sum(1 for x in r3 if x["rank"] != off[x["team_id"]]["rank"])
    print(f"[INFO] LDC 24/11/2026 : {sum(1 for x in r3 if x['ex_aequo'])} club(s) en ex æquo, {ecart} rang(s) différent(s) de l'UEFA")
    print("[OK] classement.py : tests réussis")


if __name__ == "__main__":
    if "--test" in sys.argv:
        _test()
