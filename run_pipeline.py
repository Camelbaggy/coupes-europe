#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chef d'orchestre : run_pipeline.py
1. Collecte déterministe ESPN (soirée du jour, date précise, ou semaine avec --week).
2. Rédaction/contrôle des résumés par les agents Gemini Flash (repli déterministe sinon).
3. Push ntfy si au moins un match est terminé.
"""

import argparse
import sys

import agents_flash
import collector
import notify


def main():
    parser = argparse.ArgumentParser(description="Pipeline complet Coupes d'Europe")
    parser.add_argument("--week", action="store_true", help="Tous les matchs européens de la semaine (mardi-jeudi)")
    parser.add_argument("--date", help="Date précise (YYYY-MM-DD)")
    parser.add_argument("--save-raw", help="Dossier où sauvegarder les réponses ESPN brutes (debug)")
    parser.add_argument("--no-notify", action="store_true", help="Ne pas envoyer de push ntfy")
    args = parser.parse_args()

    collector.set_raw_dir(args.save_raw)

    if args.week:
        dates = collector.get_current_week_european_dates()
        label = f"Semaine du {dates[0]} au {dates[-1]}"
    else:
        d = args.date or collector.date.today().isoformat()
        dates, label = [d], f"Soirée du {d}"
    print(f"=== COLLECTE : {dates} ===")
    raw_data = collector.collect_dates_data(dates, label_prefix=label, output_path="data_raw.json")

    if not raw_data.get("notification", {}).get("match_night", False):
        print("[FIN] Aucun match européen terminé sur le créneau. data.json inchangé.")
        sys.exit(0)

    agents_flash.orchestrate_flash_agents(input_path="data_raw.json", output_path="data.json")

    if not args.no_notify:
        notify.send_ntfy_notification(data_path="data.json", force_test=args.week)
    print("=== PIPELINE TERMINÉ ===")


if __name__ == "__main__":
    main()
