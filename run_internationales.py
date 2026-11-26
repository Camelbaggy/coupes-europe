#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Compétitions internationales -> dépôt de données (donnees-football), dossier `internationales/` :

  internationales/index.json                         {maj, competitions: {cdm: {nom, court, famille, editions: [{edition, libelle,
                                                      jours, matchs, termines, maj}]}}}
  internationales/<comp>/<édition>/<AAAA-MM-JJ>.json  matchs d'un jour (heure de Paris), au schéma des coupes / championnats :
                                                      {last_updated, target_dates, edition, competitions: {<comp>: bloc}}
  internationales/<comp>/<édition>/index.json         liste LÉGÈRE des jours (date, matchs, termines, phases, tours, francais[])
  internationales/<comp>/<édition>/classements.json   classements officiels ACTUELS des groupes {source, maj, groupes[]}
  internationales/<comp>/<édition>/programme.json     matchs à venir {source, maj, matchs[]}

Usage :
  python run_internationales.py --comp cdm --edition 2026 --date 2026-07-19 --donnees DIR     un jour
  python run_internationales.py --comp euro --edition 2024 --reconstituer --budget-min 40     jours joués sans fichier
  python run_internationales.py --reconstituer --budget-min 40                                 toutes les éditions de EDITIONS
  python run_internationales.py --liste                                                        éditions et jours restants
  python run_internationales.py --date 2026-11-14 --donnees DIR [--etat]                       un jour, TOUTES les compétitions :
      éditions qui jouent ce jour-là (étape 3, collecte_internationales.yml) ; --etat écrit etat_internationales.json

Une reconstitution (`reconstituee: true`) ne touche jamais à un état ni à une notification. Reprenable : un jour écrit et complet
n'est plus demandé ; un jour incomplet (match sans détail) est repris au passage suivant.
"""

import argparse
import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import internationales as I
from run_ligues import GARDE_JOURS, _lire, _sans_horodatage, ecrire_si_change

# Éditions détaillées (décision du propriétaire du 26/11/2026 : fiches complètes pour les éditions récentes seulement), de la plus
# récente à la plus ancienne. Une édition future (éliminatoires de l'Euro 2028…) s'ajoute ici quand l'UEFA la publie.
FORMAT = 3   # 3 : libellés de tour FIFA = ceux de l'UEFA (jours FIFA refaits seulement) ; 2 : `tour_court` / `journee` des matchs, `par_tour` de l'index ; un fichier d'un format plus ancien est refait

EDITIONS: List[Tuple[str, int]] = [("ci", 2026), ("ldn", 2027), ("cdm", 2026), ("cdmc", 2025), ("ldn", 2025), ("euro", 2024)]
ETAT = "etat_internationales.json"   # racine du dépôt de données ; lu par la veille et par notification_jour.py (dépôt de code)
EXCLUS_COMPTE = ("Reporté", "Annulé", "Arrêté", "Abandonné")  # statuts des matchs jamais comptés (comme ligne_index)
ANNEES_SUIVANTES = {"cdm": 4, "euro": 4}   # éliminatoires joués jusqu'à 4 ans avant le tournoi (édition = année du tournoi)


def dossier_edition(donnees: str, comp: str, edition: int) -> str:
    return os.path.join(donnees, "internationales", comp, str(edition))


def _horo(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def ligne_index(jour: str, bloc: Dict[str, Any], maintenant: datetime, reconstituee: bool) -> Dict[str, Any]:
    ms = bloc["matches"]
    comptes = [m for m in ms if m.get("status") not in EXCLUS_COMPTE]
    termines = sum(1 for m in comptes if m.get("finished") and not m.get("en_attente") and not m.get("detail_manquant"))
    tours = []
    for m in ms:
        t = (m.get("round") or {}).get("name") or ""
        if t and t not in tours:
            tours.append(t)
    francais = [{"match_id": m["match_id"], "home": m["home_team"]["name"], "away": m["away_team"]["name"],
                 "score": f"{m['home_team']['score']}-{m['away_team']['score']}" if m.get("finished") else None}
                for m in ms if m.get("is_french_match")]
    par_tour: Dict[str, int] = {}
    for m in comptes:
        t = m.get("tour_court") or (m.get("round") or {}).get("name") or ""
        if t:
            par_tour[t] = par_tour.get(t, 0) + 1
    return {"date": jour, "matchs": len(comptes), "termines": termines, "incomplet": bool(bloc.get("incomplet")),
            "par_tour": par_tour,
            "phases": sorted({m.get("phase") for m in ms if m.get("phase")}), "tours": tours,
            "groupes": sorted({m["groupe"] for m in ms if m.get("groupe")}), "francais": francais,
            "maj": _horo(maintenant), "fichier": f"{jour}.json", **({"reconstituee": True} if reconstituee else {})}


def complet(chemin: str, comp: str) -> bool:
    d = _lire(chemin) or {}
    # format 3 : libellés de tour FIFA ramenés à ceux de l'UEFA ; seuls les jours aux matchs rapprochés de la FIFA sont refaits
    fifa = any(m.get("fifa_id") for m in (((d.get("competitions") or {}).get(comp) or {}).get("matches") or []))
    if (d.get("format") or 1) < (FORMAT if fifa else 2):
        return False
    b = (d.get("competitions") or {}).get(comp) or {}
    ms = b.get("matches") or []
    return bool(ms) and not b.get("incomplet") and all(
        (m.get("finished") or m.get("status") in EXCLUS_COMPTE) and not m.get("detail_manquant")
        and not m.get("en_attente") for m in ms)


def collecter(comp: str, edition: int, jour: str, donnees: str, liste: Optional[List[Dict[str, Any]]] = None,
              maintenant: Optional[datetime] = None, reconstituee: bool = False) -> Dict[str, Any]:
    """Un jour d'une édition -> fichier du jour + ligne d'index. Retourne le bilan {statut, matchs, termines, ecrit}."""
    maintenant = maintenant or datetime.now(timezone.utc)
    dossier = dossier_edition(donnees, comp, edition)
    chemin = os.path.join(dossier, f"{jour}.json")
    precedent = _lire(chemin) or {}
    deja = {m["match_id"]: m for m in (((precedent.get("competitions") or {}).get(comp) or {}).get("matches") or [])
            if (precedent.get("format") or 1) >= 2 and m.get("finished") and not m.get("detail_manquant") and not m.get("en_attente")
            and (m.get("players") or m.get("flux"))}
    bloc = I.collecter_jour(comp, edition, jour, liste, deja=deja, maintenant=maintenant)
    if not bloc["matches"]:
        statut = "partiel" if bloc["incomplet"] else "aucun_match"
        print(f"[OK] {I.COMPETITIONS[comp]['nom']} {jour} : {statut} (aucun fichier)")
        return {"statut": statut, "matchs": 0, "termines": 0, "ecrit": False}
    reconstituee = reconstituee or bool(precedent.get("reconstituee"))
    sortie = {"format": FORMAT, "last_updated": _horo(maintenant), "target_dates": [jour], "edition": edition,
              "edition_libelle": I.libelle_edition(comp, edition),
              "source": "UEFA" if I.COMPETITIONS[comp].get("uefa") and not I.COMPETITIONS[comp].get("fifa")
              else "FIFA (liste) + ESPN (Opta)" if not I.COMPETITIONS[comp].get("uefa") else "UEFA ; phase finale : FIFA + ESPN (Opta)",
              "competitions": {comp: bloc}}
    if reconstituee:
        sortie["reconstituee"] = True
        sortie["reconstituee_le"] = precedent.get("reconstituee_le") or maintenant.date().isoformat()
    ecrit = ecrire_si_change(chemin, sortie)
    ligne = ligne_index(jour, bloc, maintenant, reconstituee)
    chemin_idx = os.path.join(dossier, "index.json")
    idx = [l for l in (_lire(chemin_idx) or []) if l.get("date") != jour] + [ligne]
    idx.sort(key=lambda l: l["date"], reverse=True)
    ecrire_si_change(chemin_idx, idx)
    statut = "complet" if ligne["termines"] == ligne["matchs"] and not ligne["incomplet"] else "partiel"
    print(f"[OK] {I.COMPETITIONS[comp]['nom']} {I.libelle_edition(comp, edition)} {jour} : {statut}, "
          f"{ligne['termines']}/{ligne['matchs']} prêt(s), fichier {'écrit' if ecrit else 'inchangé'}")
    return {"statut": statut, "matchs": ligne["matchs"], "termines": ligne["termines"], "ecrit": ecrit}


def annexes(comp: str, edition: int, donnees: str, liste: List[Dict[str, Any]], maintenant: datetime) -> None:
    """Classements des groupes, programme, index général (une fois par passage et par édition)."""
    dossier = dossier_edition(donnees, comp, edition)
    k = I.classements(comp, edition, liste)
    if k["groupes"]:
        ecrire_si_change(os.path.join(dossier, "classements.json"), {**k, "maj": _horo(maintenant)})
    prog = I.programme(comp, liste, maintenant)
    ecrire_si_change(os.path.join(dossier, "programme.json"),
                     {"source": "UEFA" if I.COMPETITIONS[comp].get("uefa") else "FIFA", "maj": _horo(maintenant), "matchs": prog})
    chemin = os.path.join(donnees, "internationales", "index.json")
    idx = _lire(chemin) or {"competitions": {}}
    cfg = I.COMPETITIONS[comp]
    c = idx["competitions"].setdefault(comp, {})
    c.update({"nom": cfg["nom"], "court": cfg["court"], "famille": cfg["famille"], "majeure": bool(cfg.get("majeure"))})
    jours = _lire(os.path.join(dossier, "index.json")) or []
    eds = [e for e in c.get("editions", []) if e.get("edition") != edition]
    eds.append({"edition": edition, "libelle": I.libelle_edition(comp, edition), "jours": len(jours),
                "matchs": sum(l.get("matchs", 0) for l in jours), "termines": sum(l.get("termines", 0) for l in jours),
                "a_venir": len(prog), "maj": _horo(maintenant)})
    c["editions"] = sorted(eds, key=lambda e: e["edition"], reverse=True)
    idx["maj"] = _horo(maintenant)
    ecrire_si_change(chemin, idx)


def a_faire(comp: str, edition: int, donnees: str, liste: List[Dict[str, Any]], maintenant: datetime) -> List[str]:
    """Jours joués (heure de Paris), antérieurs à aujourd'hui, sans fichier complet ; du plus récent au plus ancien."""
    auj = maintenant.astimezone(I.PARIS).date().isoformat()
    dossier = dossier_edition(donnees, comp, edition)
    return sorted((j for j in I.jours_joues(liste) if j < auj and not complet(os.path.join(dossier, f"{j}.json"), comp)),
                  reverse=True)


def reconstituer(editions: List[Tuple[str, int]], donnees: str, budget_min: float) -> Dict[str, int]:
    debut = datetime.now(timezone.utc)
    faits, restants = 0, 0
    for comp, ed in editions:
        liste = I.liste_edition(comp, ed)
        if liste is None:
            print(f"[WARN] {comp} {ed} : liste de l'édition illisible ; rien ce passage")
            restants += 1
            continue
        todo = a_faire(comp, ed, donnees, liste, debut)
        print(f"[RECONSTITUTION] {I.COMPETITIONS[comp]['nom']} {I.libelle_edition(comp, ed)} : {len(todo)} jour(s) à faire")
        for j in todo:
            if (datetime.now(timezone.utc) - debut).total_seconds() > budget_min * 60:
                restants += 1
                continue
            collecter(comp, ed, j, donnees, liste, maintenant=datetime.now(timezone.utc), reconstituee=True)
            faits += 1
        annexes(comp, ed, donnees, liste, datetime.now(timezone.utc))
    print(f"[RECONSTITUTION] {faits} jour(s) fait(s), {restants} restant(s)")
    sortie = os.environ.get("GITHUB_OUTPUT")
    if sortie:
        with open(sortie, "a", encoding="utf-8") as f:
            f.write(f"traites={faits}\nrestants={restants}\n")
    return {"traites": faits, "restants": restants}


# ------------------------------------------------------------------------------
# Étape 3 : un jour, toutes les compétitions
# ------------------------------------------------------------------------------
def editions_candidates(comp: str, jour: str) -> List[int]:
    """Éditions qui PEUVENT avoir des matchs le `jour` : celle de la date et, pour la Coupe du monde et l'Euro (édition = année
    du tournoi), les 1 à 4 suivantes (éliminatoires de l'Euro 2028 joués en 2027, de la Coupe du monde 2030 en 2027-2029)."""
    base = I.edition_de(comp, jour)
    return [base + k for k in range(0, ANNEES_SUIVANTES.get(comp, 0) + 1)]


_SANS_MATCH: Dict[Tuple[str, int, str], float] = {}   # (comp, édition, jour) -> instant du dernier constat « aucun match »
TTL_SANS_MATCH_S = 3600       # l'absence de match un jour donné est retenue 1 h par processus (la veille tourne toutes les 10 min)


def entrees_du_jour(liste: List[Dict[str, Any]], jour: str) -> List[Dict[str, Any]]:
    """Entrées de la liste d'une édition jouées le `jour` (heure de Paris), reportés / annulés exclus."""
    return [e for e in liste if e["jour"] == jour and e["statut"] not in EXCLUS_COMPTE]


def editions_du_jour(jour: str, liste_fn: Optional[Callable[[str, int], Optional[List[Dict[str, Any]]]]] = None,
                     comps: Optional[List[str]] = None, cache_negatif: bool = False
                     ) -> Tuple[List[Tuple[str, int, List[Dict[str, Any]]]], List[Tuple[str, int]]]:
    """((comp, édition, liste) des éditions ayant au moins un match le `jour`, (comp, édition) des listes ILLISIBLES).
    `liste_fn(comp, édition)` : `internationales.liste_edition` par défaut. `cache_negatif` : n'interroge plus une édition
    sans match ce jour-là pendant TTL_SANS_MATCH_S (veille)."""
    liste_fn = liste_fn or I.liste_edition
    trouvees: List[Tuple[str, int, List[Dict[str, Any]]]] = []
    illisibles: List[Tuple[str, int]] = []
    for comp in comps or list(I.COMPETITIONS):
        for ed in editions_candidates(comp, jour):
            cle = (comp, ed, jour)
            if cache_negatif and time.time() - _SANS_MATCH.get(cle, 0) < TTL_SANS_MATCH_S:
                continue
            liste = liste_fn(comp, ed)
            if liste is None:
                illisibles.append((comp, ed))
            elif any(e["jour"] == jour for e in liste):
                trouvees.append((comp, ed, liste))
            else:
                _SANS_MATCH[cle] = time.time()
    return trouvees, illisibles


def resume_comp(comp: str, edition: int, jour: str, liste: List[Dict[str, Any]], bilan: Dict[str, Any]) -> Dict[str, Any]:
    """Entrée d'état d'une compétition pour le jour : {edition, statut, matchs, termines, france, phase_finale}.
    `matchs` = matchs de la LISTE du jour (reportés / annulés exclus : un match pas encore commencé compte, donc le jour est
    « partiel » dès le matin) ; `termines` = terminés ET collectés en entier ; `france` = une équipe française joue ce jour-là ;
    `phase_finale` = match de groupes / à élimination directe d'une compétition `majeure` (Coupe du monde, Euro)."""
    jour_l = entrees_du_jour(liste, jour)
    n = len(jour_l)
    termines = min(int(bilan.get("termines") or 0), n)
    complet = n > 0 and bilan.get("statut") == "complet" and termines == n
    return {"edition": edition, "statut": "complet" if complet else "partiel" if n else "aucun_match", "matchs": n,
            "termines": termines,
            "france": any(bool((e.get("home_team") or {}).get("is_french") or (e.get("away_team") or {}).get("is_french"))
                          for e in jour_l),
            "phase_finale": bool(I.COMPETITIONS[comp].get("majeure")) and any(e["phase"] in ("groupes", "finale") for e in jour_l)}


def statut_jour(comps: Dict[str, Dict[str, Any]], incomplet: bool = False) -> str:
    st = [c.get("statut") for c in comps.values()]
    if incomplet or any(s == "partiel" for s in st):
        return "partiel"
    return "complet" if any(s == "complet" for s in st) else "aucun_match"


def ecrire_etat(donnees: str, jour: str, comps: Dict[str, Dict[str, Any]], maintenant: datetime,
                incomplet: bool = False) -> Dict[str, Any]:
    """etat_internationales.json : {jour: {statut, matchs, termines, comps: {comp: résumé}, maj, alertes?}} (60 jours gardés ;
    écrit aussi un jour `aucun_match`, pour que la veille sache que le jour est relevé). `maj` ne change que si le reste change."""
    chemin = os.path.join(donnees, ETAT)
    etat = _lire(chemin) or {}
    ancien = etat.get(jour) or {}
    entree = {"statut": statut_jour(comps, incomplet), "matchs": sum(c["matchs"] for c in comps.values()),
              "termines": sum(c["termines"] for c in comps.values()), "comps": comps,
              "maj": _horo(maintenant), **({"alertes": ancien["alertes"]} if ancien.get("alertes") else {})}
    if _sans_horodatage(entree) == _sans_horodatage(ancien) and ancien.get("maj"):
        entree["maj"] = ancien["maj"]
    etat[jour] = entree
    limite = (maintenant.date() - timedelta(days=GARDE_JOURS)).isoformat()
    etat = {j: v for j, v in sorted(etat.items()) if j >= limite}
    os.makedirs(donnees, exist_ok=True)
    tmp = chemin + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(etat, f, ensure_ascii=False, indent=1)
    os.replace(tmp, chemin)
    print(f"[ÉTAT] {jour} : {entree['statut']}{'' if jour in etat else ' (hors des ' + str(GARDE_JOURS) + ' jours gardés)'} " +
          (", ".join(f"{k} {v['edition']} {v['termines']}/{v['matchs']}" + (" FRA" if v["france"] else "") +
                     (" phase finale" if v["phase_finale"] else "") for k, v in comps.items()) or "aucun match"))
    return etat


def collecter_jour_toutes(jour: str, donnees: str, avec_etat: bool = False, maintenant: Optional[datetime] = None,
                          liste_fn: Optional[Callable[[str, int], Optional[List[Dict[str, Any]]]]] = None
                          ) -> Dict[str, Dict[str, Any]]:
    """Toutes les compétitions qui jouent le `jour` (heure de Paris) : pour chaque édition retenue, `collecter` (match fini depuis
    moins de 2 h = `en_attente`, repris au passage suivant) puis `annexes`. Retourne {comp: résumé} ; `avec_etat` écrit
    etat_internationales.json (même quand aucun match). Une liste illisible n'empêche pas les autres compétitions : le jour est alors
    « partiel » et l'entrée précédente de la compétition est conservée."""
    maintenant = maintenant or datetime.now(timezone.utc)
    trouvees, illisibles = editions_du_jour(jour, liste_fn)
    for comp, ed in illisibles:
        print(f"[WARN] {comp} {ed} : liste de l'édition illisible ; rien pour cette édition ce passage")
    comps: Dict[str, Dict[str, Any]] = {}
    for comp, ed, liste in trouvees:
        print(f"[JOUR] {I.COMPETITIONS[comp]['nom']} {I.libelle_edition(comp, ed)} : "
              f"{len(entrees_du_jour(liste, jour))} match(s) le {jour}")
        try:
            bilan = collecter(comp, ed, jour, donnees, liste, maintenant=maintenant)
            annexes(comp, ed, donnees, liste, datetime.now(timezone.utc))
        except Exception as e:   # une compétition en erreur ne bloque pas les autres : elle reste « partiel »
            print(f"[WARN] {comp} {ed} {jour} : erreur de collecte ({type(e).__name__}: {e})")
            bilan = {"statut": "partiel", "termines": 0}
        r = resume_comp(comp, ed, jour, liste, bilan)
        if comp not in comps or r["termines"] >= comps[comp]["termines"]:   # deux éditions le même jour : cas non attendu
            comps[comp] = r
    if avec_etat:
        ancien = (_lire(os.path.join(donnees, ETAT)) or {}).get(jour) or {}
        for comp, ed in illisibles:   # édition illisible : on garde ce qu'on savait d'elle
            if comp not in comps and comp in (ancien.get("comps") or {}):
                comps[comp] = ancien["comps"][comp]
        ecrire_etat(donnees, jour, comps, maintenant, incomplet=bool(illisibles))
    return comps


def _test() -> None:
    import tempfile
    bloc = {"incomplet": False, "matches": [
        {"match_id": "1", "finished": True, "tour_court": "Phase de groupes · J1", "status": "Terminé", "phase": "groupes", "groupe": "Groupe D",
         "round": {"name": "Phase de groupes"}, "is_french_match": True, "players": {"a": {}},
         "home_team": {"name": "France", "score": 3}, "away_team": {"name": "Sénégal", "score": 1}},
        {"match_id": "2", "finished": True, "status": "Terminé", "phase": "groupes", "groupe": "Groupe D",
         "round": {"name": "Phase de groupes"}, "is_french_match": False, "players": {"a": {}},
         "home_team": {"name": "Irak", "score": 0}, "away_team": {"name": "Norvège", "score": 2}}]}
    l = ligne_index("2026-06-16", bloc, datetime(2026, 6, 17, tzinfo=timezone.utc), True)
    assert l["matchs"] == 2 and l["termines"] == 2 and l["francais"][0]["score"] == "3-1" and l["groupes"] == ["Groupe D"]
    assert l["reconstituee"] and l["tours"] == ["Phase de groupes"]
    assert l["par_tour"] == {"Phase de groupes · J1": 1, "Phase de groupes": 1}
    with tempfile.TemporaryDirectory() as d:
        ch = os.path.join(d, "j.json")
        ecrire_si_change(ch, {"competitions": {"cdm": bloc}})
        assert not complet(ch, "cdm")   # format ancien : refait
        ecrire_si_change(ch, {"format": FORMAT, "competitions": {"cdm": bloc}})
        assert complet(ch, "cdm")
        bloc["matches"][1]["detail_manquant"] = True
        ecrire_si_change(ch, {"format": FORMAT, "competitions": {"cdm": bloc}})
        assert not complet(ch, "cdm")
        liste = [{"jour": "2026-06-16", "fini": True}, {"jour": "2026-06-17", "fini": True}, {"jour": "2026-12-16", "fini": False}]
        os.makedirs(dossier_edition(d, "cdm", 2026))
        os.replace(ch, os.path.join(dossier_edition(d, "cdm", 2026), "2026-06-16.json"))
        assert a_faire("cdm", 2026, d, liste, datetime(2026, 11, 26, tzinfo=timezone.utc)) == ["2026-06-17", "2026-06-16"]

    # --- étape 3 : un jour, toutes les compétitions ---
    assert editions_candidates("cdm", "2027-03-25") == [2027, 2028, 2029, 2030, 2031]
    assert editions_candidates("euro", "2026-11-14") == [2026, 2027, 2028, 2029, 2030]
    assert editions_candidates("ldn", "2026-11-14") == [2027] and editions_candidates("ci", "2026-12-16") == [2026]
    assert editions_candidates("cdmc", "2025-07-13") == [2025]

    def ent(jour, h, a, fini, phase="groupes", statut="Terminé"):
        eq = lambda c: {"is_french": c == "FRA", "country": c} if c else None  # noqa: E731
        return {"jour": jour, "home_team": eq(h), "away_team": eq(a), "fini": fini, "statut": statut, "phase": phase}
    L = [ent("2026-11-14", "FRA", "ITA", True), ent("2026-11-14", "ESP", "DEN", False, statut="À venir"),
         ent("2026-11-14", "BEL", "SUI", False, statut="Reporté"), ent("2026-11-15", "POR", "CRO", False, statut="À venir")]
    assert len(entrees_du_jour(L, "2026-11-14")) == 2
    r = resume_comp("ldn", 2027, "2026-11-14", L, {"statut": "partiel", "termines": 1})
    assert (r["statut"], r["matchs"], r["termines"], r["france"], r["phase_finale"]) == ("partiel", 2, 1, True, False), r
    assert resume_comp("ldn", 2027, "2026-11-14", L[:1], {"statut": "complet", "termines": 1})["statut"] == "complet"
    # collecte « complète » du fichier mais un match de la liste manque (ex. FIFA sans ESPN) : partiel
    assert resume_comp("ldn", 2027, "2026-11-14", L, {"statut": "complet", "termines": 1})["statut"] == "partiel"
    # phase finale d'une compétition majeure sans la France ; éliminatoires ; ldn n'est jamais « phase finale »
    G = [ent("2026-06-20", "BRA", "MAR", True)]
    assert resume_comp("cdm", 2026, "2026-06-20", G, {"statut": "complet", "termines": 1}) | {} == \
        {"edition": 2026, "statut": "complet", "matchs": 1, "termines": 1, "france": False, "phase_finale": True}
    assert not resume_comp("cdm", 2030, "2027-03-25", [ent("2027-03-25", "SWE", "POL", False, "qualification", "À venir")],
                           {"statut": "partiel", "termines": 0})["phase_finale"]
    assert not resume_comp("ldn", 2027, "2026-11-14", [ent("2026-11-14", "ESP", "DEN", True, "groupes")],
                           {"statut": "complet", "termines": 1})["phase_finale"]
    # club : france = club français
    assert resume_comp("ci", 2026, "2026-12-16", [ent("2026-12-16", "FRA", None, False, "finale", "À venir")],
                       {"statut": "partiel", "termines": 0})["france"]
    # éditions retenues : seulement celles qui jouent ce jour-là ; liste illisible signalée à part
    listes = {("ldn", 2027): L, ("cdm", 2030): None, ("euro", 2028): [ent("2026-11-15", "ESP", "DEN", False)]}
    trouvees, illis = editions_du_jour("2026-11-14", lambda c, e: listes.get((c, e), []), ["ldn", "cdm", "euro"])
    assert [(c, e) for c, e, _ in trouvees] == [("ldn", 2027)] and illis == [("cdm", 2030)], (trouvees, illis)
    # état : jour sans match, jour partiel, jour complet ; conservation de `maj` si rien ne change ; alertes conservées
    with tempfile.TemporaryDirectory() as d:
        t1 = datetime(2026, 11, 14, 9, 0, tzinfo=timezone.utc)
        etat = ecrire_etat(d, "2026-11-13", {}, t1)
        assert etat["2026-11-13"]["statut"] == "aucun_match" and etat["2026-11-13"]["comps"] == {}
        comps = {"ldn": resume_comp("ldn", 2027, "2026-11-14", L, {"statut": "partiel", "termines": 1})}
        etat = ecrire_etat(d, "2026-11-14", comps, t1)
        e = etat["2026-11-14"]
        assert e["statut"] == "partiel" and e["matchs"] == 2 and e["termines"] == 1 and e["comps"]["ldn"]["france"] is True
        assert ecrire_etat(d, "2026-11-14", comps, t1 + timedelta(minutes=30))["2026-11-14"]["maj"] == _horo(t1)
        brut = _lire(os.path.join(d, ETAT))
        brut["2026-11-14"]["alertes"] = {"workflow": "x"}
        with open(os.path.join(d, ETAT), "w", encoding="utf-8") as f:
            json.dump(brut, f)
        comps2 = {"ldn": resume_comp("ldn", 2027, "2026-11-14", L[:1], {"statut": "complet", "termines": 1})}
        e = ecrire_etat(d, "2026-11-14", comps2, t1 + timedelta(hours=5))["2026-11-14"]
        assert e["statut"] == "complet" and e["alertes"] == {"workflow": "x"} and e["maj"] != _horo(t1)
        assert ecrire_etat(d, "2026-11-14", comps2, t1, incomplet=True)["2026-11-14"]["statut"] == "partiel"
        # purge au-delà de 60 jours
        assert "2026-11-13" not in ecrire_etat(d, "2027-02-01", {}, datetime(2027, 2, 1, tzinfo=timezone.utc))
        # collecter_jour_toutes sans réseau : listes injectées, aucun match -> état aucun_match, rien d'écrit dans internationales/
        assert collecter_jour_toutes("2026-11-20", d, True, t1, lambda c, e: []) == {}
        assert _lire(os.path.join(d, ETAT))["2026-11-20"]["statut"] == "aucun_match"
        assert not os.path.exists(os.path.join(d, "internationales"))
    print("[OK] run_internationales : tests passés")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Compétitions internationales -> dépôt de données")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--comp", choices=list(I.COMPETITIONS))
    ap.add_argument("--edition", type=int)
    ap.add_argument("--date")
    ap.add_argument("--donnees", default="../donnees-football")
    ap.add_argument("--reconstituer", action="store_true")
    ap.add_argument("--budget-min", type=float, default=40)
    ap.add_argument("--liste", action="store_true", help="jours restants par édition (sans écriture)")
    ap.add_argument("--etat", action="store_true", help="avec --date seul : écrit aussi etat_internationales.json")
    a = ap.parse_args()
    eds = [(a.comp, a.edition)] if a.comp and a.edition else [e for e in EDITIONS if not a.comp or e[0] == a.comp]
    if a.test:
        _test()
    elif a.liste:
        maint = datetime.now(timezone.utc)
        for c, e in eds:
            L = I.liste_edition(c, e)
            print(f"{c} {I.libelle_edition(c, e)} : " + ("illisible" if L is None else
                  f"{len(L)} matchs, {len(I.jours_joues(L))} jours joués, {len(a_faire(c, e, a.donnees, L, maint))} à faire"))
    elif a.reconstituer:
        reconstituer(eds, a.donnees, a.budget_min)
    elif a.date and not a.comp:
        collecter_jour_toutes(a.date, a.donnees, a.etat)
    elif a.date and len(eds) == 1:
        c, e = eds[0]
        L = I.liste_edition(c, e)
        collecter(c, e, a.date, a.donnees, L)
        if L is not None:
            annexes(c, e, a.donnees, L, datetime.now(timezone.utc))
    else:
        ap.print_help()
