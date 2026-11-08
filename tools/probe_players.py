#!/usr/bin/env python3
"""Sonde ponctuelle : noms des statistiques individuelles UEFA (Monaco-Nordsjælland 2050346)."""
import collections
import json
import urllib.request

UA = {"User-Agent": "coupes-europe-dashboard/1.0", "Accept": "application/json"}


def get(u):
    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60) as r:
        return json.loads(r.read())


ps = get("https://matchstats.uefa.com/v1/player-statistics/2050346")
lu = get("https://match.uefa.com/v5/matches/2050346/lineups?language=FR")
info = {}
for side in ("homeTeam", "awayTeam"):
    for p in (lu.get(side) or {}).get("field", []) + (lu.get(side) or {}).get("bench", []):
        info[str(p["player"]["id"])] = p["player"]

nonzero = collections.Counter()
labels = {}
for p in ps:
    for s in p["statistics"]:
        labels[s["name"]] = ((s.get("translations") or {}).get("name") or {}).get("FR")
        if s.get("value") not in ("0", "0.0", "", None, "0.000"):
            nonzero[s["name"]] += 1
print("joueurs:", len(ps), "| stats distinctes:", len(labels))
for name, n in sorted(nonzero.items()):
    print(f"{name} | {labels.get(name)} | non nul chez {n} joueurs")

gk = next(p for p in ps if (info.get(str(p["playerId"])) or {}).get("fieldPosition") == "GOALKEEPER")
print("\nGARDIEN", (info.get(str(gk["playerId"])) or {}).get("internationalName"))
print({s["name"]: s["value"] for s in gk["statistics"] if s.get("value") not in ("0", "0.0", "", None)})
pl = next(iter(info.values()))
print("\nCHAMPS JOUEUR:", sorted(pl), "| translations:", sorted((pl.get("translations") or {})))
print("shortName:", (pl.get("translations") or {}).get("shortName"), "| countryCode:", pl.get("countryCode"),
      "| image:", pl.get("imageUrl"))
print("pays des joueurs:", sorted({p.get("countryCode") for p in info.values()}))
