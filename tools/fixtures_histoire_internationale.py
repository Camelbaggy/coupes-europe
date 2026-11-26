#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fixtures RÉELLES allégées de `histoire_internationale.py --test` (tools/fixtures/histoire_internationale/).

Lit le cache brut de `python histoire_internationale.py --donnees DIR --cache CACHE` (jamais commité) et en extrait quelques matchs
par édition, réduits aux seuls champs lus par le code (réponses UEFA : traductions FR / EN seulement).

Usage : python tools/fixtures_histoire_internationale.py <CACHE> [<dossier de sortie>]
"""

import gzip
import json
import os
import sys

# (fichier de fixture, cache, [ids de match FIFA / UEFA à garder ; vide = tous], filtre facultatif)
SPECS = [
    ("cdm_2022.json", "fifa_cdm_2022", {"finale", "3e", "ouverture"}),
    ("cdm_2018.json", "fifa_cdm_2018", {"finale"}),
    ("cdm_2010.json", "fifa_cdm_2010", {"finale"}),
    ("cdm_2006.json", "fifa_cdm_2006", {"finale"}),
    ("cdm_1998.json", "fifa_cdm_1998", {"finale", "but_en_or"}),
    ("cdm_1930.json", "fifa_cdm_1930", None),
    ("cdm_1950.json", "fifa_cdm_1950", {"tour_final", "groupe"}),
    ("euro_2016.json", "uefa_euro_2016", {"finale"}),
    ("euro_2000.json", "uefa_euro_2000", {"finale"}),
    ("euro_1984.json", "uefa_euro_1984", {"finale"}),
    ("euro_1988.json", "uefa_euro_1988", {"tournoi"}),                  # hôte : stades en Allemagne de l'Ouest (HOTES_EPOQUE)
    ("euro_2020.json", "uefa_euro_2020", {"tournoi"}),                  # 11 pays hôtes, « Russie* »
    ("euro_1976.json", "uefa_euro_1976", {"finale", "3e"}),
    ("euro_1968.json", "uefa_euro_1968", {"finale", "3e"}),
    ("euro_1960.json", "uefa_euro_1960", {"phase_finale", "finale", "3e", "deux_manches", "annule"}),
    ("ldn_2025.json", "uefa_ldn_2025", {"finale", "3e", "quart"}),
    ("ldn_2021.json", "uefa_ldn_2021", {"finale", "3e"}),
    ("cdmc_2000.json", "fifa_cdmc_2000", {"finale", "3e"}),
    ("cdmc_2019.json", "fifa_cdmc_2019", None),                         # 8 matchs : corrections sourcées (ESPN)
    ("cdmc_2020.json", "fifa_cdmc_2020", {"forfait"}),
    ("ci_2025.json", "fifa_ci_2025", None),
    ("ci_2026.json", "fifa_ci_2026", None),
]
GARDE_FIFA = ("IdMatch", "StageName", "GroupName", "Date", "HomeTeamScore", "AwayTeamScore", "HomeTeamPenaltyScore",
              "AwayTeamPenaltyScore", "Winner", "MatchStatus", "ResultType")
GARDE_EQUIPE_FIFA = ("IdTeam", "IdCountry", "TeamName", "Abbreviation")


def fr_en(o):
    """Réduit récursivement les traductions UEFA aux langues FR et EN."""
    if isinstance(o, dict):
        if set(o) >= {"EN", "FR"} and len(o) > 2:
            return {k: o[k] for k in ("EN", "FR")}
        return {k: fr_en(v) for k, v in o.items()}
    if isinstance(o, list):
        return [fr_en(x) for x in o]
    return o


def garde_uefa(m):
    eq = lambda t: {k: v for k, v in fr_en(t).items() if k in ("countryCode", "id", "teamCode", "internationalName", "isPlaceHolder", "translations")}
    r = fr_en(m["round"])
    r = {k: r.get(k) for k in ("metaData", "mode", "modeDetail", "phase", "translations") if k in r}
    r["translations"] = {"name": r.get("translations", {}).get("name")}
    out = {"id": m["id"], "status": m["status"], "type": m.get("type"), "round": r, "homeTeam": eq(m["homeTeam"]), "awayTeam": eq(m["awayTeam"]),
           "kickOffTime": m["kickOffTime"], "score": m.get("score"),
           "stadium": {"countryCode": (m.get("stadium") or {}).get("countryCode")}, "group": m.get("group") and {"metaData": m["group"].get("metaData")}}
    w = (m.get("winner") or {}).get("match")
    if w:
        out["winner"] = {"match": {"reason": w.get("reason"), "team": w.get("team") and {"countryCode": w["team"].get("countryCode"),
                                                                                       "id": w["team"].get("id")}}}
    return out


def libelle(v):
    return (v[0]["Description"] if v else "").replace("\xa0", " ")


def choisir_fifa(ms, tags):
    if tags is None:
        return ms
    out = []
    for m in ms:
        st = libelle(m["StageName"])
        h = libelle((m.get("Home") or {}).get("TeamName") or [])
        a = libelle((m.get("Away") or {}).get("TeamName") or [])
        ok = (("finale" in tags and st in ("Finale", "FIFA Intercontinental Cup 2025 Final")) or
              ("3e" in tags and st in ("Match pour la 3e place", "Match pour la troisième place", "Bronze final")) or
              ("ouverture" in tags and {h, a} == {"Qatar", "Équateur"}) or
              ("but_en_or" in tags and {h, a} == {"France", "Paraguay"} and st == "Huitième de finale") or
              ("tour_final" in tags and st == "Tour final") or
              ("groupe" in tags and st == "Matches de groupes" and "Brésil" in (h, a) and len(out) < 40 and
               libelle(m["GroupName"]) == "Groupe 1" and m["Date"].startswith("1950-06-24")) or
              ("forfait" in tags and m.get("MatchStatus") == 9))
        if ok:
            out.append(m)
    return out


def choisir_uefa(ms, tags):
    out = []
    for m in ms:
        t = m["round"]["metaData"].get("type")
        ok = (("tournoi" in tags and m["round"].get("phase") == "TOURNAMENT" and m["round"].get("modeDetail") != "KNOCK_OUT_TWO_LEGS") or
              ("finale" in tags and t == "FINAL") or ("3e" in tags and t == "THIRD_PLAY_OFF") or
              ("phase_finale" in tags and t in ("SEMIFINAL",)) or
              ("quart" in tags and t == "QUARTER_FINALS" and len(out) < 3 and m["homeTeam"]["teamCode"] in ("POR", "ESP", "DEN", "GER", "FRA", "ITA", "CRO", "NED")
               and m["kickOffTime"]["date"] < "2025-03-25") or
              ("deux_manches" in tags and t == "ROUND_OF_16" and m["homeTeam"]["teamCode"] in ("FRA", "GRE") ) or
              ("annule" in tags and m["status"] == "CANCELED" and t == "QUARTER_FINALS"))
        if ok:
            out.append(m)
    return out


def main():
    cache = sys.argv[1]
    sortie = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "histoire_internationale")
    os.makedirs(sortie, exist_ok=True)
    for fichier, nom, tags in SPECS:
        with gzip.open(os.path.join(cache, nom + ".json.gz"), "rt", encoding="utf-8") as f:
            brut = json.load(f)
        if nom.startswith("fifa"):
            ms = choisir_fifa(brut["matchs"], tags)
            ids = {str((m.get(c) or {}).get("IdTeam")) for m in ms for c in ("Home", "Away")}
            gardes = []
            for m in ms:
                g = {k: m.get(k) for k in GARDE_FIFA}
                for c in ("Home", "Away"):
                    g[c] = {k: m[c].get(k) for k in GARDE_EQUIPE_FIFA} if m.get(c) else None
                gardes.append(g)
            doc = {"matchs": gardes, "hotes": [h for h in brut.get("hotes", []) if h in ids]}
        else:
            ms = choisir_uefa(brut["matchs"], tags)
            doc = {"matchs": [garde_uefa(m) for m in ms]}
        with open(os.path.join(sortie, fichier), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
        print(f"{fichier}: {len(doc['matchs'])} match(s)")


if __name__ == "__main__":
    main()
