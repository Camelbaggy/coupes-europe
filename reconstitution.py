#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Reconstitution de l'historique des soirées et rattrapage des résumés IA (décisions du propriétaire, 25/11/2026).

`reconstituer` : rejoue le pipeline sur chaque soirée passée de la saison (phase de ligue ET tours préliminaires) :
  collecte UEFA, notes, momentum, statistiques, classement RECALCULÉ depuis les scores (phase de ligue seulement),
  résumés DÉTERMINISTES (aucun Gemini, aucun ESPN). La liste des dates vient de l'API UEFA (listes de saison), pas
  d'un code en dur ; une soirée dont `soirees/<date>.json` existe est sautée (reprenable). Ne touche JAMAIS à
  etat_soirees.json ni à ntfy ; data.json n'est remplacé que par une soirée plus récente (normalement jamais).

`rattraper_ia` : remplace, par lots, les résumés déterministes des matchs de clubs français de PHASE DE LIGUE par un
  résumé Gemini contrôlé (rédacteur + contrôleur, comme en direct). Jamais les tours préliminaires de cette saison.
  Chaque carte est enregistrée dès qu'elle est réussie (reprenable) ; quota Gemini épuisé (HTTP 429) = arrêt propre.
"""

import datetime as dt
import os
import subprocess
import tempfile
import time
from typing import Any, Dict, List, Optional

import agents_flash
import collector
import espn
import historique
import uefa


def _sortie_github(**valeurs: Any) -> None:
    chemin = os.environ.get("GITHUB_OUTPUT")
    if chemin:
        with open(chemin, "a", encoding="utf-8") as f:
            for k, v in valeurs.items():
                f.write(f"{k}={v}\n")


def publier_git() -> bool:
    """Commit + push robuste des soirées (publier.sh --soirees). Faux = le push a échoué (travail non publié)."""
    r = subprocess.run(["bash", ".github/scripts/publier.sh", "--soirees"])
    return r.returncode == 0


def reconstituer(dossier: str = historique.DOSSIER, du: Optional[str] = None, au: Optional[str] = None,
                 budget_min: float = 40, max_soirees: int = 0, publier_tous: int = 0,
                 maintenant: Optional[dt.datetime] = None, saison: Optional[int] = None,
                 data_path: str = "data.json") -> int:
    """Retourne le code de sortie (0 = ok, même s'il reste des soirées ; 1 = liste UEFA illisible ou push en échec)."""
    debut = time.monotonic()
    maintenant = maintenant or dt.datetime.now(dt.timezone.utc)
    saison = saison or uefa.season_year_for(maintenant.date())
    agents_flash.GEMINI_API_KEY = ""   # reconstitution = repli déterministe d'abord (rattrapage IA ensuite, par lots)
    par_comp: Dict[str, List[Dict[str, Any]]] = {}
    for comp_key in collector.TOURNAMENTS:
        brut = uefa.fetch_season_matches(comp_key, saison)
        if brut is None:
            print(f"[ERREUR] Liste des matchs {comp_key} {saison} illisible : reconstitution impossible (aucune liste tronquée).")
            return 1
        par_comp[comp_key] = brut
    historique.amorcer(historique.lire_json(data_path), dossier)   # data.json = seule trace de la soirée précédente
    dates = historique.dates_a_reconstituer(par_comp, maintenant, dossier, du, au)
    print(f"[RECONSTITUTION] {len(dates)} soirée(s) à reconstituer : {dates}")
    traitees = 0
    echecs: List[str] = []
    depuis_publication = 0
    with tempfile.TemporaryDirectory() as tmp:
        brut_path = os.path.join(tmp, "data_raw.json")
        for jour in dates:
            if max_soirees and traitees >= max_soirees:
                break
            if time.monotonic() - debut > budget_min * 60:
                print(f"[RECONSTITUTION] budget de {budget_min} min atteint : arrêt propre, reprise au passage suivant.")
                break
            print(f"\n=== RECONSTITUTION {jour} ===")
            try:
                raw = collector.collect_dates_data([jour], label_prefix=f"Soirée du {jour}", output_path=brut_path,
                                                   classement_mode="calcule", avec_espn=False, maintenant=maintenant)
                if not raw.get("notification", {}).get("match_night"):
                    raise RuntimeError("aucun match terminé collecté")
                data = agents_flash.orchestrate_flash_agents(input_path=brut_path, output_path=None)
                historique.publier_soiree(data, jour, dossier, data_path, reconstituee=True, maintenant=maintenant)
            except Exception as e:  # une soirée en échec n'arrête pas les autres ; elle reste « à reconstituer »
                print(f"[ERREUR] Soirée {jour} non reconstituée : {e}")
                echecs.append(jour)
                continue
            traitees += 1
            depuis_publication += 1
            if publier_tous and depuis_publication >= publier_tous:
                depuis_publication = 0
                if not publier_git():
                    return 1
    if depuis_publication and publier_tous and not publier_git():
        return 1
    restantes = len(dates) - traitees
    print(f"[RECONSTITUTION] restantes={restantes} traitees={traitees} echecs={len(echecs)}")
    _sortie_github(restantes=restantes, traitees=traitees)
    return 0


def _contexte_ia(comp_key: str, comp: Dict[str, Any], match: Dict[str, Any], card: Dict[str, Any]):
    """Reconstitue ce que data.json ne garde pas (actions UEFA détaillées, fil ESPN) pour le dossier du rédacteur."""
    brut = next((m for m in uefa.fetch_matches(comp_key, [match["date"]]) if str(m.get("id")) == match["match_id"]), None)
    if brut is None:
        return None
    events = uefa.fetch_events(match["match_id"])
    _, _, actions = uefa.build_events(events, brut, match["home_team"]["id"], match["away_team"]["id"])
    match_ctx = dict(match, actions=[{k: v for k, v in a.items() if k != "sort"} for a in actions])
    h, a = match["home_team"], match["away_team"]
    comments: List[str] = []
    espn_id = espn.find_espn_event(comp_key, match["date"], [h["name"], h["official_name"]],
                                   [a["name"], a["official_name"]], h["score"], a["score"])
    if espn_id:
        comments = espn.fetch_commentary(comp_key, espn_id)
    return match_ctx, dict(card, raw_comments_for_llm=comments)


def rattraper_ia(dossier: str = historique.DOSSIER, max_cartes: int = 10, data_path: str = "data.json",
                 maintenant: Optional[dt.datetime] = None) -> int:
    """Rattrape jusqu'à `max_cartes` résumés de phase de ligue par Gemini. Imprime `restantes=N` ; code 0."""
    maintenant = maintenant or dt.datetime.now(dt.timezone.utc)
    cartes = historique.cartes_a_rattraper(dossier)
    print(f"[RATTRAPAGE IA] {len(cartes)} carte(s) de phase de ligue en résumé déterministe.")
    if not cartes or not agents_flash.GEMINI_API_KEY:
        if cartes:
            print("[RATTRAPAGE IA] GEMINI_API_KEY absente : rien à faire.")
        print(f"[RATTRAPAGE IA] restantes={len(cartes)} traitees=0")
        _sortie_github(restantes=len(cartes), traitees=0)
        return 0
    agents_flash._DEADLINE = time.monotonic() + agents_flash.AI_BUDGET_SECONDS
    traitees = 0
    docs: Dict[str, Dict[str, Any]] = {}
    for c in cartes[:max_cartes]:
        doc = docs.setdefault(c["date"], historique.lire_json(historique.chemin_soiree(dossier, c["date"])))
        comp = doc["competitions"][c["comp"]]
        match = next((m for m in comp["matches"] if m["match_id"] == c["match_id"]), None)
        card = next((x for x in comp["french_clubs_focus"] if x["match_id"] == c["match_id"] and x["club_name"] == c["club"]), None)
        if not match or not card:
            continue
        print(f"\n=== RATTRAPAGE {c['date']} {c['club']} ({c['comp']}) ===")
        try:
            ctx = _contexte_ia(c["comp"], comp, match, card)
            if ctx is None:
                print("[WARN] Match introuvable dans la liste UEFA du jour : carte ignorée pour ce passage.")
                continue
            row = next((r for r in comp.get("standings") or [] if r.get("team_id") == card.get("club_id")), {})
            texte = agents_flash.summarize_card(comp.get("name", ""), ctx[1], ctx[0], row)
        except Exception as e:
            print(f"[WARN] Rattrapage impossible pour {c['club']} : {e}")
            if "429" in str(e) or "budget de temps IA épuisé" in str(e):
                print("[RATTRAPAGE IA] quota ou budget Gemini épuisé : arrêt propre, reprise au prochain passage.")
                break
            continue
        if texte:
            card["ai_summary"] = " ".join(texte.split())
            card["summary_source"] = "gemini"
            card["ai_verified"] = True
            card.pop("ia_tentatives", None)
            traitees += 1
        else:  # trois rejets du contrôleur : on retentera deux fois au plus (MAX_TENTATIVES_IA)
            card["ia_tentatives"] = int(card.get("ia_tentatives") or 0) + 1
            print(f"[REPLI] Résumé déterministe conservé pour {c['club']} (essai {card['ia_tentatives']}).")
        historique.ecrire_soiree(doc, c["date"], dossier)
        historique.synchroniser_data_json(doc, c["date"], data_path)
    restantes = len(historique.cartes_a_rattraper(dossier))
    print(f"[RATTRAPAGE IA] restantes={restantes} traitees={traitees}")
    _sortie_github(restantes=restantes, traitees=traitees)
    return 0


def _test():
    """Tests hors réseau : réseau, collecte et Gemini remplacés par des doublures."""
    import json
    import sys
    U = dt.timezone.utc
    maintenant = dt.datetime(2026, 11, 25, 14, 0, tzinfo=U)

    with tempfile.TemporaryDirectory() as d:
        os.chdir(d)
        dos = "soirees"
        # --- reconstitution : 3 dates (2 passées, 1 dans le créneau normal), data.json plus récent intact, aucune notification
        def raw(jour, statut="FINISHED"):
            return {"kickOffTime": {"date": jour}, "status": statut}
        listes = {"ucl": [raw("2026-11-03"), raw("2026-11-24"), raw("2026-11-25", "UPCOMING")], "uel": [raw("2026-09-16")], "uecl": []}
        uefa_fetch, coll, orch = uefa.fetch_season_matches, collector.collect_dates_data, agents_flash.orchestrate_flash_agents
        appels = []
        uefa.fetch_season_matches = lambda comp, saison: listes[comp]

        def faux_collect(dates, label_prefix, output_path, classement_mode, avec_espn, maintenant):
            appels.append((dates[0], classement_mode, avec_espn))
            if dates[0] == "2026-09-16":
                raise RuntimeError("UEFA indisponible")
            with open(output_path, "w") as f:
                f.write("{}")
            return {"notification": {"match_night": True}}
        collector.collect_dates_data = faux_collect
        agents_flash.orchestrate_flash_agents = lambda input_path, output_path: historique._soiree(
            appels[-1][0], "2026-11-25T14:00:00Z", {"ucl": {"name": "LDC", "stage_type": "league", "french_clubs_focus": [],
                                                           "matches": [historique._match("1", "A", "B", 1, 0)]}})
        try:
            reel = historique._soiree("2026-11-24", "Z", {"ucl": {"name": "LDC", "stage_type": "league", "french_clubs_focus": [],
                                                                  "matches": [historique._match("7", "P", "Q", 3, 0)]}})
            with open("data.json", "w") as f:
                json.dump(reel, f)   # data.json = vrai passage du 24/11 : amorcé dans soirees/, jamais écrasé par une reconstitution
            assert reconstituer(dos, maintenant=maintenant, saison=2027) == 0
            # ordre : la plus récente d'abord ; le 24/11 existe déjà (amorçage), 16/09 en échec reste à faire
            assert [a[0] for a in appels] == ["2026-11-03", "2026-09-16"], appels
            assert all(a[1] == "calcule" and a[2] is False for a in appels)
            assert [l["date"] for l in historique.lire_index(dos)] == ["2026-11-24", "2026-11-03"]
            assert historique.lire_json(historique.chemin_soiree(dos, "2026-11-24"))["amorcee"] is True
            assert json.load(open("data.json"))["last_updated"] == "Z"   # data.json intact
            assert not os.path.exists("etat_soirees.json")               # ni état, ni notification
            appels.clear()
            assert reconstituer(dos, maintenant=maintenant, saison=2027, max_soirees=1) == 0 and [a[0] for a in appels] == ["2026-09-16"]
            # liste de saison illisible : aucune soirée écrite, code 1
            uefa.fetch_season_matches = lambda comp, saison: None
            assert reconstituer(dos, maintenant=maintenant, saison=2027) == 1
        finally:
            uefa.fetch_season_matches, collector.collect_dates_data, agents_flash.orchestrate_flash_agents = uefa_fetch, coll, orch

        # --- rattrapage IA : phase de ligue seulement, par lots, marque summary_source, 429 = arrêt, essais comptés
        mk = historique._match
        ucl = {"name": "LDC", "stage_type": "league", "standings": [], "matches": [mk("1", "A", "B", 1, 0), mk("2", "C", "D", 0, 0), mk("3", "E", "F", 2, 2)],
               "french_clubs_focus": [dict(historique._carte("1", "A"), club_id="1"), historique._carte("2", "C"), historique._carte("3", "E")]}
        pre = {"name": "LC", "stage_type": "knockout", "standings": [], "matches": [mk("9", "Z", "Y", 1, 0, stage="qualifying")],
               "french_clubs_focus": [historique._carte("9", "Z")]}
        historique.ecrire_soiree(historique._soiree("2026-11-24", "2026-11-25T00:00:00Z", {"ucl": ucl, "uecl": pre}), "2026-11-24", dos, reconstituee=True)
        with open("data.json", "w") as f:
            json.dump({"target_dates": ["2026-11-24"], "marque": "ancienne"}, f)
        gem, ctx, summ = agents_flash.GEMINI_API_KEY, _contexte_ia, agents_flash.summarize_card
        agents_flash.GEMINI_API_KEY = "x"
        globals()["_contexte_ia"] = lambda *a: ({}, {})
        reponses = iter(["Résumé IA contrôlé.", None, RuntimeError("Échec Gemini (gemini HTTP 429 : quota)"), "Résumé 3"])

        def faux_summ(*a, **k):
            r = next(reponses)
            if isinstance(r, Exception):
                raise r
            return r
        agents_flash.summarize_card = faux_summ
        try:
            assert len(historique.cartes_a_rattraper(dos)) == 3          # les préliminaires ne comptent pas
            assert rattraper_ia(dos, max_cartes=3) == 0
            doc = historique.lire_json(historique.chemin_soiree(dos, "2026-11-24"))
            cartes = {c["club_name"]: c for c in doc["competitions"]["ucl"]["french_clubs_focus"]}
            assert cartes["A"]["summary_source"] == "gemini" and cartes["A"]["ai_summary"] == "Résumé IA contrôlé."
            assert cartes["C"]["summary_source"] == "deterministe" and cartes["C"]["ia_tentatives"] == 1   # 3 rejets : essai compté
            assert cartes["E"]["summary_source"] == "deterministe" and not cartes["E"].get("ia_tentatives")  # 429 : arrêt, pas d'essai compté
            assert doc["competitions"]["uecl"]["french_clubs_focus"][0]["summary_source"] == "deterministe"  # préliminaires intacts
            assert doc["reconstituee"] is True and historique.lire_json("data.json")["competitions"]["ucl"]["french_clubs_focus"][0]["summary_source"] == "gemini"
            assert [c["club"] for c in historique.cartes_a_rattraper(dos)] == ["C", "E"]
            assert historique.lire_index(dos)[0]["resumes"]["gemini"] == 1
            # lot suivant : seules les cartes restantes
            reponses = iter(["Résumé C", "Résumé E"])
            assert rattraper_ia(dos, max_cartes=1) == 0 and [c["club"] for c in historique.cartes_a_rattraper(dos)] == ["E"]
            # sans clé : rien n'est modifié
            agents_flash.GEMINI_API_KEY = ""
            assert rattraper_ia(dos, max_cartes=5) == 0 and [c["club"] for c in historique.cartes_a_rattraper(dos)] == ["E"]
        finally:
            agents_flash.GEMINI_API_KEY, agents_flash.summarize_card = gem, summ
            globals()["_contexte_ia"] = ctx
        os.chdir("/")
    print("[OK] reconstitution.py : tests réussis")


if __name__ == "__main__":
    import sys
    if "--test" in sys.argv:
        _test()
