"""Sonde temporaire (projet cyclisme) : joignabilité et forme des sources candidates depuis GitHub Actions.
Une seule requête par URL, User-Agent honnête ; tout challenge anti-robot est seulement constaté, jamais contourné."""
import sys, urllib.request, urllib.error

UA = "courses-velo-sonde/0.1 (projet personnel non commercial; contact via GitHub camelbaggy)"
ROBOTS = [
    "https://www.procyclingstats.com/robots.txt", "https://firstcycling.com/robots.txt",
    "https://www.letour.fr/robots.txt", "https://www.uci.org/robots.txt", "https://dataride.uci.org/robots.txt",
    "https://www.giroditalia.it/robots.txt", "https://www.lavuelta.es/robots.txt",
    "https://www.paris-roubaix.fr/robots.txt", "https://www.lncpro.fr/robots.txt",
    "https://www.directvelo.com/robots.txt", "https://www.cyclingnews.com/robots.txt",
]
PAGES = [
    "https://www.letour.fr/fr/classement-general", "https://www.letour.fr/en/rankings",
    "https://www.letour.fr/en/ajax/ranking/1/itg/",
    "https://firstcycling.com/race.php?r=17&y=2026", "https://firstcycling.com/race.php?r=17&y=2026&k=startlist",
    "https://dataride.uci.org/", "https://www.uci.org/calendar/road/1g4Jt3Q8lxWb6HJpZQ4lLu",
    "https://www.wikidata.org/w/api.php?action=wbsearchentities&search=Tour%20de%20France%202026&language=fr&format=json",
    "https://query.wikidata.org/sparql?format=json&query=SELECT%20%3Fs%20WHERE%20%7B%3Fs%20wdt%3AP31%20wd%3AQ1318941%7D%20LIMIT%203",
    "https://fr.wikipedia.org/api/rest_v1/page/summary/Tour_de_France_2026",
    "https://fr.wikipedia.org/w/api.php?action=parse&page=Tour_de_France_2026&prop=sections&format=json",
    "https://site.api.espn.com/apis/site/v2/sports/cycling/scoreboard",
    "https://api.open-meteo.com/v1/forecast?latitude=48.85&longitude=2.35&hourly=wind_speed_10m,wind_direction_10m,temperature_2m&forecast_days=1",
    "https://archive-api.open-meteo.com/v1/archive?latitude=48.85&longitude=2.35&start_date=2026-07-26&end_date=2026-07-26&hourly=wind_speed_10m,temperature_2m",
    "https://www.directvelo.com/", "https://www.cyclingnews.com/feeds.xml", "https://www.cyclingnews.com/rss",
    "https://www.lequipe.fr/rss/actu_rss_Cyclisme.xml", "https://www.lncpro.fr/",
]

def sonde(url, full=False):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            code, hdrs, body = r.status, r.headers, r.read(400000)
    except urllib.error.HTTPError as e:
        code, hdrs, body = e.code, e.headers, e.read(20000)
    except Exception as e:
        print(f"\n=== {url}\n  ERREUR {type(e).__name__}: {e}")
        return
    txt = body.decode("utf-8", "replace")
    cf = "cf-ray" in {k.lower() for k in hdrs.keys()} or "Just a moment" in txt or "challenge-platform" in txt
    print(f"\n=== {url}\n  HTTP {code} | {hdrs.get('Content-Type')} | {len(body)} o | cloudflare={cf} | server={hdrs.get('Server')}")
    print(txt[:3500] if full else txt[:900].replace("\n", " "))

if __name__ == "__main__":
    for u in ROBOTS:
        sonde(u, full=True)
    for u in PAGES:
        sonde(u)
    sys.exit(0)
