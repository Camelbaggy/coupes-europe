#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chef d'orchestre : run_pipeline.py
1. Collecte déterministe ESPN (soirée du jour, date précise, ou semaine avec --week).
2. Rédaction/contrôle des résumés par les agents Gemini Flash (repli déterministe sinon).
3. État par soirée (etat_soirees.json) et UN SEUL push ntfy par soirée, une fois tous les matchs terminés
   (ou, si elle reste partielle, après 12 h UTC le lendemain). Voir soirees.py.
"""

import argparse
import datetime as dt
import json
import sys

import agents_flash
import collector
import notify
import soirees


def date_soiree_par_defaut(maintenant=None):
    """Date de la soirée de matchs à collecter quand --date n'est pas donné.

    GitHub retarde souvent le cron de 22 h 30 UTC de plusieurs heures (passages réels entre 2 h et 4 h UTC le
    lendemain) : avant 12 h UTC, la soirée visée est donc celle de la VEILLE (sinon on cherche les matchs d'un
    mercredi ou d'un vendredi matin, on n'en trouve aucun et data.json n'est jamais mis à jour)."""
    import datetime as _dt
    maintenant = maintenant or _dt.datetime.now(_dt.timezone.utc)
    jour = maintenant.date()
    if maintenant.hour < 12:
        jour -= _dt.timedelta(days=1)
    return jour.isoformat()


def dates_data_json(chemin="data.json"):
    try:
        with open(chemin, "r", encoding="utf-8") as f:
            return json.load(f).get("target_dates") or []
    except (OSError, ValueError):
        return []


def main():
    parser = argparse.ArgumentParser(description="Pipeline complet Coupes d'Europe")
    parser.add_argument("--week", action="store_true", help="Tous les matchs européens de la semaine (mardi-jeudi)")
    parser.add_argument("--date", help="Date précise (YYYY-MM-DD)")
    parser.add_argument("--save-raw", help="Dossier où sauvegarder les réponses ESPN brutes (debug)")
    parser.add_argument("--no-notify", action="store_true", help="Ne pas envoyer de push ntfy (ni toucher à l'état)")
    parser.add_argument("--forcer", action="store_true",
                        help="Retraiter une soirée déjà complète et notifiée (sinon arrêt anticipé)")
    parser.add_argument("--renotifier", action="store_true", help="Envoyer le push même si la soirée a déjà été notifiée")
    args = parser.parse_args()

    collector.set_raw_dir(args.save_raw)
    maintenant = dt.datetime.now(dt.timezone.utc)
    # --week et --no-notify = essais : comportement historique, l'état des soirées n'est pas touché
    suivre_etat = not args.week and not args.no_notify

    if args.week:
        dates = collector.get_current_week_european_dates()
        label = f"Semaine du {dates[0]} au {dates[-1]}"
        jour = None
    else:
        jour = args.date or date_soiree_par_defaut(maintenant)
        dates, label = [jour], f"Soirée du {jour}"

    etat = soirees.charger() if suivre_etat else {}
    if suivre_etat and not args.forcer and not args.renotifier and soirees.deja_traitee(etat, jour, dates_data_json()):
        print(f"[FIN] Soirée du {jour} déjà complète et notifiée, présente dans data.json : rien à faire "
              "(--forcer pour retraiter).")
        sys.exit(0)

    print(f"=== COLLECTE : {dates} ===")
    raw_data = collector.collect_dates_data(dates, label_prefix=label, output_path="data_raw.json")
    notif = raw_data.get("notification", {})
    matchs, termines = int(notif.get("matchs", 0)), int(notif.get("termines", 0))
    statut = soirees.statut_soiree(matchs, termines, bool(notif.get("incomplet")))
    print(f"[ETAT] {jour or 'semaine'} : {termines}/{matchs} match(s) terminé(s) -> {statut}")

    if not notif.get("match_night", False):
        if suivre_etat:
            soirees.enregistrer(etat, jour, statut, matchs, termines, maintenant)
        print("[FIN] Aucun match européen terminé sur le créneau. data.json inchangé.")
        sys.exit(0)

    agents_flash.orchestrate_flash_agents(input_path="data_raw.json", output_path="data.json")

    if args.week:
        if not args.no_notify:
            notify.send_ntfy_notification(data_path="data.json", force_test=True)
    elif suivre_etat:
        # état écrit APRÈS la réussite de data.json : un plantage de l'IA ne marque jamais la soirée comme faite
        etat = soirees.enregistrer(etat, jour, statut, matchs, termines, maintenant)
        if soirees.doit_notifier(statut, etat[jour]["notifie"], jour, maintenant, args.renotifier):
            envoye = notify.send_ntfy_notification(data_path="data.json")
            # sans NTFY_TOPIC (simulation), on marque quand même : sinon le battement relancerait à vide
            if envoye or not notify.NTFY_TOPIC:
                soirees.enregistrer(etat, jour, statut, matchs, termines, maintenant, notifie=True)
        else:
            print(f"[INFO] Pas de push ntfy pour la soirée {jour} ({statut}, "
                  f"{'déjà notifiée' if etat[jour]['notifie'] else 'en attente'}).")
    print("=== PIPELINE TERMINÉ ===")


if __name__ == "__main__":
    main()
