#!/usr/bin/env python3
"""Sonde de diagnostic : que renvoie l'API publique d'uefa.com ? (requêtes ordinaires, lecture seule)"""
import json, re, sys, urllib.request, urllib.error, gzip

UA = "coupes-europe-dashboard/1.0 (+https://github.com/Camelbaggy/coupes-europe)"
COMPS = {"ucl": 1, "uel": 14, "uecl": 2019}

def get(url, accept="application/json"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept, "Accept-Language": "fr-FR,fr;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            b = r.read()
            if b[:2] == b"\x1f\x8b": b = gzip.decompress(b)
            return r.status, b
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:300]
    except Exception as e:
        return -1, str(e).encode()[:300]

def shape(o, d=0, maxd=3):
    if d > maxd: return "…"
    if isinstance(o, dict): return {k: shape(v, d + 1, maxd) for k, v in list(o.items())[:30]}
    if isinstance(o, list): return [f"list[{len(o)}]", shape(o[0], d + 1, maxd)] if o else "list[0]"
    return str(o)[:70]

def show(tag, url, n=3000, maxd=3):
    st, b = get(url)
    print(f"\n### {tag}\n{url}\nHTTP {st} — {len(b)} octets")
    try:
        d = json.loads(b)
    except Exception:
        print("non-JSON:", b[:200]); return st, None
    print(json.dumps(shape(d, maxd=maxd), ensure_ascii=False)[:n])
    return st, d

# 1. Liste des matchs
matches = {}
for key, cid in COMPS.items():
    st, d = show(f"matches {key}", f"https://match.uefa.com/v5/matches?competitionId={cid}&fromDate=2026-11-03&toDate=2026-11-06&offset=0&limit=60&order=ASC&language=FR", n=4000 if key == "ucl" else 600)
    if isinstance(d, list):
        matches[key] = d
        print("matchs:", [(m.get("id"), m.get("homeTeam", {}).get("internationalName"), m.get("homeTeam", {}).get("countryCode"),
                           m.get("awayTeam", {}).get("internationalName"), m.get("awayTeam", {}).get("countryCode"),
                           (m.get("score") or {}).get("total")) for m in d][:40])

# 2. Détails d'un match avec un club français
ucl = matches.get("ucl") or []
fr = [m for m in ucl if "FRA" in (m.get("homeTeam", {}).get("countryCode"), m.get("awayTeam", {}).get("countryCode"))]
mid = (fr or ucl or [{}])[0].get("id")
print("\nMATCH ÉTUDIÉ :", mid)
if mid:
    show("match", f"https://match.uefa.com/v5/matches/{mid}?language=FR", n=5000, maxd=4)
    show("lineups", f"https://match.uefa.com/v5/matches/{mid}/lineups?language=FR", n=4000, maxd=5)
    for f in ("", "&filter=LINEUP", "&filter=MAIN"):
        show(f"events{f}", f"https://match.uefa.com/v5/matches/{mid}/events?offset=0&limit=300&order=ASC&language=FR{f}", n=3000, maxd=4)
    show("team-statistics", f"https://matchstats.uefa.com/v1/team-statistics/{mid}", n=5000, maxd=5)
    show("player-statistics", f"https://matchstats.uefa.com/v1/player-statistics/{mid}", n=2500, maxd=5)
    for path in ("commentary", "livecommentary", "live-commentary", "minute-by-minute", "timeline"):
        show(f"devinette {path}", f"https://match.uefa.com/v5/matches/{mid}/{path}?language=FR", n=1500)

    # 3. Découverte des endpoints utilisés par la page publique du match et ses scripts
    st, html = get(f"https://www.uefa.com/uefachampionsleague/match/{mid}/", accept="text/html")
    print(f"\n### page HTML HTTP {st} — {len(html)} octets")
    found = set(re.findall(rb"https?://[a-z0-9.-]+\.uefa\.com/[A-Za-z0-9/_{}.?=&-]*", html))
    scripts = re.findall(rb'<script[^>]+src="([^"]+\.js[^"]*)"', html)
    print("scripts:", len(scripts))
    for s in scripts[:25]:
        u = s.decode()
        u = u if u.startswith("http") else "https://www.uefa.com" + (u if u.startswith("/") else "/" + u)
        st2, js = get(u, accept="*/*")
        found |= set(re.findall(rb"https?://[a-z0-9.-]+\.uefa\.com/v\d+[A-Za-z0-9/_{}.-]*", js))
        for kw in (rb"commentary", rb"liveblog", rb"minute"):
            for m in re.finditer(rb".{0,80}" + kw + rb".{0,80}", js):
                frag = m.group(0)
                if b"uefa.com" in frag or b"/v" in frag:
                    print("  indice", kw.decode(), ":", frag[:160])
                    break
    api = sorted(x.decode() for x in found if not x.endswith((b".js", b".css", b".png", b".jpg", b".svg")))
    print("endpoints découverts:", json.dumps(api[:120], indent=0))

# 4. Classements
for y in (2027, 2026):
    show(f"standings UCL seasonYear={y}", f"https://standings.uefa.com/v1/standings?competitionId=1&seasonYear={y}&language=FR", n=2000, maxd=5)
