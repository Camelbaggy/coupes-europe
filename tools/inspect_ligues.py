#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Résumé lisible des données de championnats (dossier du dépôt de données) : par championnat et par jour, matchs,
journées, xG, notes, momentum, mi-temps, buts reconstitués, classement. Usage : python tools/inspect_ligues.py <dossier>"""
import glob
import json
import os
import statistics
import sys

racine = sys.argv[1] if len(sys.argv) > 1 else "../donnees-football"
alertes = 0
for f in sorted(glob.glob(os.path.join(racine, "championnats", "*", "*", "20*.json"))):
    d = json.load(open(f, encoding="utf-8"))
    for lg, c in d["competitions"].items():
        ms = c["matches"]
        fins = [m for m in ms if m["finished"]]
        notes = [p["rating"] for m in fins for p in m.get("players", {}).values() if p.get("rating") is not None]
        sans_j = [m for m in ms if not m.get("journee")]
        sans_xg = [m for m in fins if not any(s["key"] == "xg" for s in m["stats"]["all"])]
        faux = [m for m in fins if m.get("buts_incomplets")]
        manq = [m for m in fins if m.get("detail_manquant")]
        print(f"{lg:5} {d['target_dates'][0]} : {len(fins)}/{len(ms)} terminés, journées {sorted({m.get('journee') for m in ms if m.get('journee')})}"
              f" ({len(sans_j)} sans), xG {len(fins) - len(sans_xg)}/{len(fins)}, "
              f"notes {len(notes)} (moy. {statistics.mean(notes):.2f}, é.-t. {statistics.pstdev(notes):.2f})" if notes else "", end="")
        print(f", classement {c['standings_source']} ({len(c['standings'])} lignes)")
        for m in fins:
            h, a = m["home_team"], m["away_team"]
            print(f"      {h['name']} {h['score']}-{a['score']} {a['name']} [{m.get('matchday_short') or '—'}] "
                  f"{len(m['events'])} évén., {len(m['goals'])} buts, {len(m['momentum'])} pts momentum, "
                  f"{len(m['stats']['all'])}/{len(m['stats']['1st'])}/{len(m['stats']['2nd'])} stats, "
                  f"compos {len(m['lineups'].get('home', []))}+{len(m['lineups'].get('away', []))} "
                  f"({h.get('formation', '')} / {a.get('formation', '')}), maillots {h.get('shirt_color', '—')} / {a.get('shirt_color', '—')}")
        for m in faux + manq:
            alertes += 1
            print(f"  [ALERTE] {m['home_team']['name']}-{m['away_team']['name']} : "
                  f"{'buts reconstitués ≠ score' if m.get('buts_incomplets') else 'détail manquant'}")
for f in sorted(glob.glob(os.path.join(racine, "championnats", "*", "*", "journees.json"))):
    j = json.load(open(f, encoding="utf-8"))
    print(f"[JOURNÉES] {f.split(os.sep)[-3]} : {len(j.get('journees', {}))} matchs avec journée, "
          f"{len(j.get('correspondances', {}))} clubs, anomalies : {j.get('anomalies', [])[:4]}")
print(f"[BILAN] {alertes} alerte(s)")
