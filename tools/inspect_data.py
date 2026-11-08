#!/usr/bin/env python3
"""Affiche un résumé lisible de data.json (contrôle après un test du pipeline)."""
import json, sys

d = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "data.json", encoding="utf-8"))
print("notification:", d["notification"])
for k, c in d["competitions"].items():
    print(f"\n===== {k} — {c['matchday_label']} — {len(c['matches'])} matchs — {len(c['standings'])} au classement — {c['stage_type']}")
    print("Français au classement:", [(r["rank"], r["team"], r["points"]) for r in c["standings"] if r["is_french"]])
    print("Drapeaux manquants:", [(r["team"], r.get("country")) for r in c["standings"] if not r.get("flag")])
    for f in c["french_clubs_focus"]:
        print(f"\n--- {f['club_name']} ({f['club_rank']}e, {f['club_zone']}) {f['home_team']['name']} {f['home_team']['score']}-{f['away_team']['score']} {f['away_team']['name']} [{f.get('summary_source')}]")
        print("buts:", [(g["minute"], g["scorer"], g["assist"], g["kind"], g["score_after"]) for g in f["goals"]])
        print("RÉSUMÉ:", f["ai_summary"])
    if c["matches"]:
        m = next((x for x in c["matches"] if x["is_french_match"]), c["matches"][0])
        print(f"\nfiche {m['home_team']['name']}-{m['away_team']['name']} | {m['kickoff']} | {m['venue']} | {m['attendance']} | potm {m['player_of_match']}")
        print("formations:", m["home_team"].get("formation"), m["away_team"].get("formation"))
        print("events:", [(e["minute_label"], e["type"], e["team"], e["player"], e["detail"]) for e in m["events"]])
        print("stats all:", [(s["label"], s["home"], s["away"]) for s in m["stats"]["all"]])
        print("stats 1st:", [(s["label"], s["home"], s["away"]) for s in m["stats"]["1st"]])
        print("momentum:", [(p["minute"], p["home"], p["away"]) for p in m["momentum"]])
        lu = m["lineups"]
        print("compo dom:", [(p["number"], p["name"], p["x"], p["y"], p.get("subbed_out"), p.get("stats")) for p in lu.get("home", [])][:11])
        print("entrés dom:", lu.get("home_subs"))
