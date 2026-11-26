#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sonde TEMPORAIRE (26/11/2026) : que publie ESPN PENDANT un match ? (préparation du suivi en direct, à supprimer ensuite)

Toutes les `--pas` secondes, pour chaque match EN COURS des ligues demandées : minute affichée, score, statut (scoreboard) ;
événements clés, compositions, stats d'équipe (summary) ; nombre d'actions Opta et horodatage de la dernière (core plays) ;
xG d'équipe (core statistics). Une ligne JSON par relevé dans --sortie, et un résumé lisible sur la sortie standard.

    python tools/sonde_direct.py --ligues uefa.europa,uefa.europa.conf --minutes 110 --pas 60 --sortie /tmp/direct.jsonl
    python tools/sonde_direct.py --ligues uefa.europa --event 401858000 --une-fois     # un match précis (essai)
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, __file__.rsplit("/tools/", 1)[0])
import ligues  # noqa: E402

SITE, SITE_WEB, CORE = ligues.SITE, ligues.SITE_WEB, ligues.CORE


def releve(slug: str, ev: dict) -> dict:
    eid = ev["id"]
    st = ev.get("status") or {}
    comp = (ev.get("competitions") or [{}])[0]
    cs = comp.get("competitors") or []
    r = {"t": datetime.now(timezone.utc).strftime("%H:%M:%S"), "ligue": slug, "match": ev.get("shortName"), "id": eid,
         "statut": (st.get("type") or {}).get("name"), "horloge": st.get("displayClock"), "periode": st.get("period"),
         "score": "-".join(str(c.get("score")) for c in sorted(cs, key=lambda c: c.get("homeAway") != "home"))}
    sm, s1 = ligues._get(f"{SITE_WEB}/{slug}/summary?event={eid}")
    if s1 == "ok":
        r["evenements_cles"] = len(sm.get("keyEvents") or [])
        r["types_cles"] = sorted({((k.get("type") or {}).get("text") or "") for k in sm.get("keyEvents") or []})
        r["compos"] = [len(x.get("roster") or []) for x in sm.get("rosters") or []]
        eq = (sm.get("boxscore") or {}).get("teams") or []
        r["stats_equipe"] = [len(t.get("statistics") or []) for t in eq]
        r["possession"] = [next((s.get("displayValue") for s in t.get("statistics") or [] if s.get("name") == "possessionPct"), None)
                           for t in eq]
        r["commentaires"] = len(sm.get("commentary") or [])
    pl, s2 = ligues._get(f"{CORE}/{slug}/events/{eid}/competitions/{eid}/plays?limit=1&page=1")
    if s2 == "ok":
        r["actions_opta"] = pl.get("count")
        n = int(pl.get("count") or 0)
        if n:
            der, _ = ligues._get(f"{CORE}/{slug}/events/{eid}/competitions/{eid}/plays?limit=1&page={n}")
            it = ((der or {}).get("items") or [{}])[0]
            r["derniere_action"] = {"type": (it.get("type") or {}).get("text"), "minute": (it.get("clock") or {}).get("displayValue"),
                                    "wallclock": it.get("wallclock")}
    xg = []
    for c in cs:
        s, s3 = ligues._get(f"{CORE}/{slug}/events/{eid}/competitions/{eid}/competitors/{(c.get('team') or {}).get('id')}/statistics")
        noms = {x["name"]: x.get("value") for cat in ((s or {}).get("splits") or {}).get("categories", []) for x in cat.get("stats", [])}
        xg.append(noms.get("expectedGoals"))
        r.setdefault("stats_core", []).append(len(noms))
    r["xg"] = xg
    return r


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ligues", default="uefa.europa,uefa.europa.conf")
    ap.add_argument("--minutes", type=float, default=110)
    ap.add_argument("--pas", type=float, default=60)
    ap.add_argument("--max-matchs", type=int, default=3, help="matchs en cours suivis par ligue (limite les requêtes)")
    ap.add_argument("--sortie", default="/tmp/direct.jsonl")
    ap.add_argument("--event", help="un événement précis (essai)")
    ap.add_argument("--une-fois", action="store_true")
    a = ap.parse_args()
    fin = time.time() + a.minutes * 60
    while True:
        jour = datetime.now(timezone.utc).strftime("%Y%m%d")
        for slug in a.ligues.split(","):
            sb, _ = ligues._get(f"{SITE}/{slug}/scoreboard?dates={jour}")
            evs = (sb or {}).get("events") or []
            if a.event:
                evs = [e for e in evs if e["id"] == a.event] or [{"id": a.event, "shortName": a.event}]
            else:
                evs = [e for e in evs if ((e.get("status") or {}).get("type") or {}).get("state") == "in"][:a.max_matchs]
            for ev in evs:
                r = releve(slug, ev)
                with open(a.sortie, "a", encoding="utf-8") as f:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
                d = r.get("derniere_action") or {}
                print(f"{r['t']} {r['match']} {r['horloge']} {r['score']} | clés {r.get('evenements_cles')} | compos {r.get('compos')} | "
                      f"stats {r.get('stats_equipe')} poss {r.get('possession')} | Opta {r.get('actions_opta')} (dernière {d.get('type')} "
                      f"{d.get('minute')} {d.get('wallclock')}) | xG {r.get('xg')} | comm. {r.get('commentaires')}", flush=True)
        if a.une_fois or time.time() + a.pas > fin:
            break
        time.sleep(a.pas)


if __name__ == "__main__":
    main()
