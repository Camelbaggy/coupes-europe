#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Construit les fixtures de `histoire.py --test` (tools/fixtures/histoire/*.json) à partir de réponses RÉELLES de
`match.uefa.com/v5/matches?teamId=<id>` gardées dans un dossier de cache (`python clubs.py --historique --cache DIR`).

Chaque match est ALLÉGÉ : seuls les champs lus par `histoire.normaliser_match` sont conservés (la structure reste celle de l'API, le
code testé est donc le code de production). Sélection : les matchs des tours « Finale » et « Match d'appui », la Supercoupe, la Coupe
intercontinentale, les matchs de la saison en cours (dont les matchs à venir), plus, selon le club, une édition entière.

Usage : python tools/fixtures_histoire.py <dossier de cache> [dossier de sortie]
"""

import gzip
import json
import os
import sys
from typing import Any, Dict, List, Optional

CLUBS = {   # nom du fichier -> (id UEFA, filtre supplémentaire)
    "liverpool": ("7889", lambda m: False),
    "bayern": ("50037", lambda m: "2020-02-01" <= date(m) <= "2020-09-01" and code(m) == "UCL"),
    "marseille": ("52748", lambda m: code(m) == "UIC"),
    "psg": ("52747", lambda m: False),
    "real_madrid": ("50051", lambda m: False),
    "barcelone": ("50080", lambda m: code(m) == "Fairs Cup" and (date(m) < "1963-01-01" or "1965-09-01" <= date(m) <= "1966-09-30")),
    "petit_club": ("88148", lambda m: True),
}


def date(m: Dict[str, Any]) -> str:
    return ((m.get("kickOffTime") or {}).get("date") or "")[:10]


def code(m: Dict[str, Any]) -> str:
    return (m.get("competition") or {}).get("code") or ""


def garder(m: Dict[str, Any], filtre) -> bool:
    t = ((m.get("round") or {}).get("metaData") or {}).get("type")
    return t in ("FINAL", "REPLAY") or code(m) in ("SCUP", "EUSA") or date(m) >= "2026-06-20" or filtre(m)


def equipe(t: Dict[str, Any]) -> Dict[str, Any]:
    out = {"id": t.get("id"), "internationalName": t.get("internationalName"), "countryCode": t.get("countryCode")}
    tr = t.get("translations") or {}
    if (tr.get("displayName") or {}).get("FR"):
        out["translations"] = {"displayName": {"FR": tr["displayName"]["FR"]}}
    return out


def alleger(m: Dict[str, Any]) -> Dict[str, Any]:
    rd = m.get("round") or {}
    out: Dict[str, Any] = {
        "id": m.get("id"), "status": m.get("status"), "type": m.get("type"), "seasonYear": m.get("seasonYear"),
        "kickOffTime": {"date": date(m)}, "competition": {"code": code(m)},
        "round": {"metaData": rd.get("metaData") or {},
                  "translations": {"name": {"FR": ((rd.get("translations") or {}).get("name") or {}).get("FR")}}},
        "homeTeam": equipe(m.get("homeTeam") or {}), "awayTeam": equipe(m.get("awayTeam") or {}),
    }
    if m.get("score"):
        out["score"] = m["score"]
    w: Dict[str, Any] = {}
    for k, v in (m.get("winner") or {}).items():
        w[k] = {"reason": v.get("reason"), "team": {"id": (v.get("team") or {}).get("id")}} if v.get("team") else {"reason": v.get("reason")}
    if w:
        out["winner"] = w
    st = m.get("stadium") or {}
    nom = ((st.get("translations") or {}).get("name") or {}).get("FR")
    ville = (((st.get("city") or {}).get("translations") or {}).get("name") or {}).get("FR")
    if nom or ville:
        out["stadium"] = {"translations": {"name": {"FR": nom}}, "city": {"translations": {"name": {"FR": ville}}}}
    return out


def main() -> None:
    cache = sys.argv[1]
    sortie = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "histoire")
    os.makedirs(sortie, exist_ok=True)
    for nom, (cid, filtre) in CLUBS.items():
        with gzip.open(os.path.join(cache, f"{cid}.json.gz"), "rt", encoding="utf-8") as f:
            brut: List[Dict[str, Any]] = json.load(f)
        liste = [alleger(m) for m in brut if garder(m, filtre)]
        chemin = os.path.join(sortie, f"{nom}.json")
        with open(chemin, "w", encoding="utf-8") as f:
            json.dump(liste, f, ensure_ascii=False, separators=(",", ":"))
            f.write("\n")
        print(f"{chemin} : {len(liste)} matchs, {os.path.getsize(chemin)} octets")


if __name__ == "__main__":
    main()
