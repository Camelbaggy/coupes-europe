#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chef d'orchestre : run_pipeline.py
1. Collecte déterministe ESPN (soirée du jour, date précise, ou semaine avec --week).
2. Rédaction/contrôle des résumés par les agents Gemini Flash (repli déterministe sinon).
3. Historique : la soirée est rangée dans soirees/<date>.json + soirees/index.json ; data.json en est la copie de la
   soirée la plus récente (jamais remplacé par une plus ancienne) : voir historique.py.
   `--reconstituer` / `--rattraper-ia` / `--completer-xg` : reconstitution des soirées passées et rattrapage des résumés IA (reconstitution.py).
4. Fiches de club : `clubs.apres_soiree` met à jour `clubs/<id>.json` des clubs qui ont joué (sans bloquer la notification).
5. État par soirée (etat_soirees.json). Ce script NE NOTIFIE PLUS (sauf --week) : le push ntfy est envoyé par
   `--notifier` (publication.py), appelé par le workflow après un push réussi, une fois la page publique vérifiée
   à jour (un seul push par soirée, règles de soirees.py).
"""

import argparse
import datetime as dt
import json
import sys

import agents_flash
import clubs
import collector
import historique
import notify
import publication
import reconstitution
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


def dates_connues(dossier=historique.DOSSIER, chemin="data.json"):
    """Soirées déjà publiées : celles de data.json + celles de l'historique (une soirée plus ancienne que data.json
    n'y figure plus, mais son fichier soirees/<date>.json existe)."""
    return list(dict.fromkeys(dates_data_json(chemin) + [l["date"] for l in historique.lire_index(dossier)]))


def main():
    parser = argparse.ArgumentParser(description="Pipeline complet Coupes d'Europe")
    parser.add_argument("--week", action="store_true", help="Tous les matchs européens de la semaine (mardi-jeudi)")
    parser.add_argument("--date", help="Date précise (YYYY-MM-DD)")
    parser.add_argument("--save-raw", help="Dossier où sauvegarder les réponses ESPN brutes (debug)")
    parser.add_argument("--no-notify", action="store_true", help="Ne pas envoyer de push ntfy (ni toucher à l'état)")
    parser.add_argument("--forcer", action="store_true",
                        help="Retraiter une soirée déjà complète et notifiée (sinon arrêt anticipé)")
    parser.add_argument("--renotifier", action="store_true",
                        help="Notifier même si la soirée l'a déjà été (avec --notifier ; passe par la vérification de publication)")
    parser.add_argument("--notifier", nargs="?", const="auto", metavar="SOIREE",
                        help="Pas de collecte : vérifie que la page publiée est à jour puis envoie le push ntfy de la "
                             "soirée (AAAA-MM-JJ, défaut : soirée par défaut) et la marque notifiée")
    parser.add_argument("--dossier-soirees", default=historique.DOSSIER,
                        help="Dossier de l'historique des soirées (défaut : soirees)")
    parser.add_argument("--reconstituer", action="store_true",
                        help="Pas de passage normal : reconstitue les soirées passées manquantes (jamais de ntfy ni d'état)")
    parser.add_argument("--du", help="Avec --reconstituer ou --completer-xg : première date (AAAA-MM-JJ)")
    parser.add_argument("--au", help="Avec --reconstituer ou --completer-xg : dernière date (AAAA-MM-JJ)")
    parser.add_argument("--budget-min", type=float, default=40, help="Avec --reconstituer : durée maximale (minutes)")
    parser.add_argument("--max-soirees", type=int, default=0, help="Avec --reconstituer : nombre maximal de soirées (0 = sans limite)")
    parser.add_argument("--publier-tous", type=int, default=0,
                        help="Avec --reconstituer : publie (publier.sh --soirees) toutes les N soirées reconstituées")
    parser.add_argument("--rattraper-ia", action="store_true",
                        help="Pas de passage normal : remplace par Gemini des résumés déterministes de la PHASE DE LIGUE")
    parser.add_argument("--max-cartes", type=int, default=10, help="Avec --rattraper-ia : cartes par passage")
    parser.add_argument("--completer-xg", action="store_true",
                        help="Pas de passage normal : ajoute les xG (ESPN / Opta) aux matchs des soirées existantes (--du / --au, "
                             "--budget-min, --publier-tous)")
    parser.add_argument("--alerte", metavar="SOIREE",
                        help="Pas de collecte : envoie l'alerte ntfy d'échec de publication de la soirée (avec --cause)")
    parser.add_argument("--cause", default="inconnue", help="Cause de l'alerte : collecte, push, page_non_a_jour")
    args = parser.parse_args()

    if args.alerte:
        sys.exit(publication.alerter(args.alerte, args.cause, publication.url_run_actions()))
    if args.reconstituer:
        sys.exit(reconstitution.reconstituer(args.dossier_soirees, args.du, args.au, args.budget_min,
                                             args.max_soirees, args.publier_tous))
    if args.completer_xg:
        sys.exit(reconstitution.completer_xg(args.dossier_soirees, args.du, args.au, args.budget_min, args.publier_tous))
    if args.rattraper_ia:
        sys.exit(reconstitution.rattraper_ia(args.dossier_soirees, args.max_cartes))
    if args.notifier:
        jour = date_soiree_par_defaut() if args.notifier == "auto" else args.notifier
        sys.exit(publication.notifier(jour, renotifier=args.renotifier))

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
    if suivre_etat and not args.forcer and not args.renotifier and soirees.deja_traitee(etat, jour, dates_connues(args.dossier_soirees)):
        print(f"[FIN] Soirée du {jour} déjà complète et notifiée, présente dans data.json : rien à faire "
              "(--forcer pour retraiter).")
        sys.exit(0)

    if suivre_etat and not args.forcer and not args.renotifier and soirees.a_notifier_sans_collecte(
            etat, jour, dates_data_json()):
        print(f"[FIN] Soirée du {jour} complète et déjà dans data.json mais non notifiée : collecte sautée, "
              "la vérification de publication + la notification suivent (--notifier).")
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

    if args.week:
        # semaine de test : comportement historique (data.json seul, pas d'historique des soirées)
        agents_flash.orchestrate_flash_agents(input_path="data_raw.json", output_path="data.json")
        if not args.no_notify:
            notify.send_ntfy_notification(data_path="data.json", force_test=True)
    else:
        # une soirée = soirees/<jour>.json + index ; data.json seulement si c'est la plus récente (historique.py)
        data = agents_flash.orchestrate_flash_agents(input_path="data_raw.json", output_path=None)
        historique.publier_soiree(data, jour, args.dossier_soirees)
        # fiches des clubs qui ont joué (jamais bloquant : un échec est journalisé et repris au passage suivant)
        clubs.apres_soiree(data, jour)
    if suivre_etat and not args.week:
        # état écrit APRÈS la réussite de data.json : un plantage de l'IA ne marque jamais la soirée comme faite.
        # `notifie` reste inchangé (faux pour une nouvelle soirée) : le push part de `--notifier`, après publication.
        soirees.enregistrer(etat, jour, statut, matchs, termines, maintenant)
        print(f"[INFO] Soirée {jour} ({statut}) : push ntfy différé, envoyé par --notifier une fois la page publiée à jour.")
    print("=== PIPELINE TERMINÉ ===")


if __name__ == "__main__":
    main()
