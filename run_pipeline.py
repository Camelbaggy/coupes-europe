#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chef d'Orchestre Principal : run_pipeline.py
--------------------------------------------
Enchaîne automatiquement :
1. La collecte déterministe (soirée du jour à 23h30 OU semaine entière avec `--week`).
2. L'orchestration des 3 Agents Gemini Flash (Rédacteur, Contrôleur, Notification).
3. L'envoi du push mobile `ntfy` si des matchs ont eu lieu.
"""

import argparse
import sys
import importlib.util

# Chargement dynamique de collector-v2.py
spec = importlib.util.spec_from_file_location("collector_v2", "collector-v2.py")
collector_v2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector_v2)

import agents_flash
import notify


def main():
    parser = argparse.ArgumentParser(description="Pipeline Complet Coupes d'Europe")
    parser.add_argument(
        "--week",
        action="store_true",
        help="Test grandeur nature : récupère tous les matchs européens de la semaine (Mardi-Jeudi)",
    )
    parser.add_argument("--date", type=str, help="Tester une date spécifique (YYYY-MM-DD)")
    args = parser.parse_args()

    if args.week:
        dates = collector_v2.get_current_week_european_dates()
        print(f"=== LANCEMENT DU TEST GRANDEUR NATURE SUR LA SEMAINE : {dates} ===")
        raw_data = collector_v2.collect_dates_data(
            dates, label_prefix=f"Semaine du {dates[0]} au {dates[-1]}"
        )
    elif args.date:
        print(f"=== LANCEMENT SUR LA DATE CIBLÉE : {args.date} ===")
        raw_data = collector_v2.collect_dates_data([args.date], label_prefix=f"Soirée du {args.date}")
    else:
        today_str = collector_v2.date.today().isoformat()
        print(f"=== EXÉCUTION AUTOMATIQUE 23H30 ({today_str}) ===")
        raw_data = collector_v2.collect_dates_data([today_str], label_prefix=f"Soirée du {today_str}")

    if not raw_data.get("notification", {}).get("match_night", False):
        print("[FIN] Aucun match européen sur le créneau. Arrêt immédiat.")
        sys.exit(0)

    # Étape 3 : Passage des Agents Gemini Flash
    agents_flash.orchestrate_flash_agents(input_path="data_raw.json", output_path="data.json")

    # Étape 5 : Notification push ntfy
    notify.send_ntfy_notification(data_path="data.json", force_test=args.week)
    print("=== PIPELINE TERMINÉ AVEC SUCCÈS ===")


if __name__ == "__main__":
    main()
