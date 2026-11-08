#!/usr/bin/env python3
"""Sonde ponctuelle : structure brute des buts et VAR UEFA (Lens-Como 2049623)."""
import json, urllib.request
UA = {"User-Agent": "coupes-europe-dashboard/1.0", "Accept": "application/json"}
def get(u):
    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30) as r:
        return json.loads(r.read())
def strip(o):
    if isinstance(o, dict):
        return {k: strip(v) for k, v in o.items() if k not in ("translations", "imageUrl", "bigLogoUrl", "mediumLogoUrl", "logoUrl", "associationLogoUrl", "fieldPosition", "fspFieldPosition")}
    if isinstance(o, list):
        return [strip(x) for x in o]
    return o
m = get("https://match.uefa.com/v5/matches/2049623?language=FR")
print("score:", m.get("score"))
for s in (m.get("playerEvents") or {}).get("scorers", []):
    s2 = strip(s); s2["player"] = (s.get("player") or {}).get("internationalName")
    print("SCORER", json.dumps(s2, ensure_ascii=False))
ev = get("https://match.uefa.com/v5/matches/2049623/events?filter=ALL&offset=0&limit=500&order=ASC&language=FR")
for e in ev:
    if e.get("type") in ("GOAL", "ASSIST", "VAR", "OWN_GOAL") or "GOAL" in e.get("type", ""):
        e2 = strip(e)
        for k in ("primaryActor", "secondaryActor"):
            if k in e2:
                e2[k] = {"person": ((e.get(k) or {}).get("person") or {}).get("internationalName"),
                         "team": ((e.get(k) or {}).get("team") or {}).get("internationalName"), "type": (e.get(k) or {}).get("type")}
        print(json.dumps(e2, ensure_ascii=False))
print("types:", sorted({e.get("type") for e in ev}))
