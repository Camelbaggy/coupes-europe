#!/usr/bin/env python3
"""Sonde de diagnostic n°2 de l'API uefa.com (requêtes ordinaires, lecture seule)."""
import json, urllib.request, urllib.error, gzip, collections

UA = "coupes-europe-dashboard/1.0 (+https://github.com/Camelbaggy/coupes-europe)"
MID = "2049612"  # Villarreal - Paris (0-6), 04/11/2026

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            b = r.read()
            return r.status, json.loads(gzip.decompress(b) if b[:2] == b"\x1f\x8b" else b)
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read())
        except Exception: return e.code, None
    except Exception as e:
        return -1, str(e)

def tr(o):
    t = (o or {}).get("translations", {}) or {}
    for k in ("name", "shortName", "displayName"):
        if isinstance(t.get(k), dict): return t[k].get("FR") or t[k].get("EN")
    return None

print("=== filtres events : valeurs possibles")
for f in ("XXX", "ALL", "COMMENTARY", "KEY", "HIGHLIGHT", "OTHER", "PLAY", "MAIN", "LINEUP"):
    st, d = get(f"https://match.uefa.com/v5/matches/{MID}/events?offset=0&limit=500&order=ASC&language=FR&filter={f}")
    types = collections.Counter(e.get("type") for e in d) if isinstance(d, list) else None
    print(f, st, types if types is not None else json.dumps(d, ensure_ascii=False)[:400])

print("\n=== events MAIN détaillés")
st, d = get(f"https://match.uefa.com/v5/matches/{MID}/events?offset=0&limit=500&order=ASC&language=FR&filter=MAIN")
for e in d if isinstance(d, list) else []:
    pa = (e.get("primaryActor") or {}); sa = (e.get("secondaryActor") or {})
    print(e.get("type"), e.get("subType"), e.get("phase"), e.get("time"), "|", (pa.get("person") or {}).get("internationalName"),
          (pa.get("team") or {}).get("internationalName"), "|", (sa.get("person") or {}).get("internationalName"),
          "| autres clés:", sorted(set(e) - {"fieldPosition", "fspFieldPosition", "id", "matchId", "phase", "time", "timestamp", "type", "primaryActor", "secondaryActor"}))
print("\n=== events LINEUP")
st, d = get(f"https://match.uefa.com/v5/matches/{MID}/events?offset=0&limit=500&order=ASC&language=FR&filter=LINEUP")
for e in d if isinstance(d, list) else []:
    pa = (e.get("primaryActor") or {}); sa = (e.get("secondaryActor") or {})
    print(e.get("type"), e.get("subType"), e.get("time"), (pa.get("person") or {}).get("internationalName"), "<-", (sa.get("person") or {}).get("internationalName"))

print("\n=== match : champs utiles")
st, m = get(f"https://match.uefa.com/v5/matches/{MID}?language=FR")
print("clés:", sorted(m))
for k in ("score", "status", "phase", "playerEvents", "winner", "lineupStatus", "matchday", "stadium", "behindClosedDoors"):
    print(k, ":", json.dumps(m.get(k), ensure_ascii=False)[:1200])

print("\n=== lineups : un titulaire complet + clés")
st, l = get(f"https://match.uefa.com/v5/matches/{MID}/lineups?language=FR")
print("clés:", sorted(l), "| homeTeam:", sorted(l.get("homeTeam", {})))
f0 = l["homeTeam"]["field"][3]
print(json.dumps({k: v for k, v in f0.items() if k != "player"}, ensure_ascii=False))
print("player:", {k: f0["player"].get(k) for k in ("internationalName", "clubShirtName", "fieldPosition", "detailedFieldPosition")}, "| shortName FR:", tr(f0["player"]))
print("formation ?", {k: l["homeTeam"].get(k) for k in l["homeTeam"] if k not in ("field", "bench", "coaches", "team")})
print("coords:", [(p["jerseyNumber"], p["player"]["clubShirtName"], p.get("fieldCoordinate")) for p in l["homeTeam"]["field"]])

print("\n=== team-statistics : toutes les stats (nom | FR | dom | ext)")
st, ts = get(f"https://matchstats.uefa.com/v1/team-statistics/{MID}")
if isinstance(ts, list) and len(ts) == 2:
    a, b = ({s["name"]: s for s in t["statistics"]} for t in ts)
    print("teamIds:", [t["teamId"] for t in ts])
    for name in a:
        if a[name].get("value") not in ("0", "0.0", None) or b.get(name, {}).get("value") not in ("0", "0.0", None):
            print(f"{name} | {tr(a[name])} | {a[name].get('value')} | {b.get(name, {}).get('value')}")
    print("autres clés d'une stat:", sorted(set(ts[0]["statistics"][0])))
for q in ("?phase=FIRST_HALF", "?period=FIRST_HALF", "?half=1"):
    st, x = get(f"https://matchstats.uefa.com/v1/team-statistics/{MID}{q}")
    v = None
    if isinstance(x, list) and x:
        v = {s["name"]: s["value"] for s in x[0]["statistics"]}.get("attempts")
    print("mi-temps", q, st, "attempts =", v)

print("\n=== player-statistics : stats non nulles d'un joueur")
st, ps = get(f"https://matchstats.uefa.com/v1/player-statistics/{MID}")
if isinstance(ps, list) and ps:
    p = max(ps, key=lambda p: sum(1 for s in p["statistics"] if s.get("value") not in ("0", "0.0")))
    print("playerId", p["playerId"], "team", p["teamId"])
    print([(s["name"], s["value"]) for s in p["statistics"] if s.get("value") not in ("0", "0.0", None)][:200])

print("\n=== autres services")
for u in (f"https://match.uefa.com/v5/matches/{MID}/statistics", f"https://compstats.uefa.com/v1/team-ranking?competitionId=1&seasonYear=2027&limit=5",
          f"https://match.uefa.com/v5/livescore?competitionId=1", f"https://editorial.uefa.com/api/matchreports/{MID}",
          f"https://pss.uefa.com/", f"https://mas.uefa.com/"):
    st, x = get(u)
    print(u, st, json.dumps(x, ensure_ascii=False)[:300] if x else "")
