#!/usr/bin/env python3
"""Sonde ponctuelle : acteurs et positions des actions UEFA (Monaco-Nordsjælland 2050346)."""
import collections
import json
import urllib.request

UA = {"User-Agent": "coupes-europe-dashboard/1.0", "Accept": "application/json"}


def get(u):
    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30) as r:
        return json.loads(r.read())


ev = get("https://match.uefa.com/v5/matches/2050346/events?filter=ALL&offset=0&limit=500&order=ASC&language=FR")
lu = get("https://match.uefa.com/v5/matches/2050346/lineups?language=FR")
pos = {}
for side in ("homeTeam", "awayTeam"):
    for p in (lu.get(side) or {}).get("field", []) + (lu.get(side) or {}).get("bench", []):
        pos[str(p["player"]["id"])] = p["player"].get("fieldPosition")


def who(a):
    return ((a.get("person") or {}).get("internationalName"), (a.get("team") or {}).get("internationalName"),
            pos.get(str((a.get("person") or {}).get("id"))))


seen = collections.Counter()
for e in ev:
    t = e.get("type")
    if t in ("SAVE", "FOUL", "FREE_KICK", "OFFSIDE", "SHOT_ON_GOAL", "SHOT_WIDE", "CORNER", "GOAL") and seen[t] < 5:
        seen[t] += 1
        print(t, e.get("phase"), e.get("time"), "| P:", who(e.get("primaryActor") or {}),
              "| S:", who(e.get("secondaryActor") or {}), "| pos:", e.get("fieldPosition"), "| detail:", e.get("detail"))
print("types:", collections.Counter(e.get("type") for e in ev))
