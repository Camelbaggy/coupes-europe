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

Une reconstitution (`reconstituee: true`) ne touche jamais à un état ni à une notification. Reprenable : un jour écrit et complet
n'est plus demandé ; un jour incomplet (match sans détail) est repris au passage suivant.
"""

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import internationales as I
from run_ligues import _lire, ecrire_si_change

# Éditions détaillées (décision du propriétaire du 26/11/2026 : fiches complètes pour les éditions récentes seulement), de la plus
# récente à la plus ancienne. Une édition future (éliminatoires de l'Euro 2028…) s'ajoute ici quand l'UEFA la publie.
FORMAT = 2   # 2 : `tour_court` / `journee` des matchs, `par_tour` de l'index ; un fichier d'un format plus ancien est refait

EDITIONS: List[Tuple[str, int]] = [("ci", 2026), ("ldn", 2027), ("cdm", 2026), ("cdmc", 2025), ("ldn", 2025), ("euro", 2024)]


def dossier_edition(donnees: str, comp: str, edition: int) -> str:
    return os.path.join(donnees, "internationales", comp, str(edition))


def _horo(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def ligne_index(jour: str, bloc: Dict[str, Any], maintenant: datetime, reconstituee: bool) -> Dict[str, Any]:
    ms = bloc["matches"]
    comptes = [m for m in ms if m.get("status") not in ("Reporté", "Annulé")]
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
    if (d.get("format") or 1) < FORMAT:
        return False
    b = (d.get("competitions") or {}).get(comp) or {}
    ms = b.get("matches") or []
    return bool(ms) and not b.get("incomplet") and all(
        (m.get("finished") or m.get("status") in ("Reporté", "Annulé")) and not m.get("detail_manquant")
        and not m.get("en_attente") for m in ms)


def collecter(comp: str, edition: int, jour: str, donnees: str, liste: Optional[List[Dict[str, Any]]] = None,
              maintenant: Optional[datetime] = None, reconstituee: bool = False) -> Dict[str, Any]:
    """Un jour d'une édition -> fichier du jour + ligne d'index. Retourne le bilan {statut, matchs, termines, ecrit}."""
    maintenant = maintenant or datetime.now(timezone.utc)
    dossier = dossier_edition(donnees, comp, edition)
    chemin = os.path.join(dossier, f"{jour}.json")
    precedent = _lire(chemin) or {}
    deja = {m["match_id"]: m for m in (((precedent.get("competitions") or {}).get(comp) or {}).get("matches") or [])
            if (precedent.get("format") or 1) >= FORMAT and m.get("finished") and not m.get("detail_manquant") and not m.get("en_attente")
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
    elif a.date and len(eds) == 1:
        c, e = eds[0]
        L = I.liste_edition(c, e)
        collecter(c, e, a.date, a.donnees, L)
        if L is not None:
            annexes(c, e, a.donnees, L, datetime.now(timezone.utc))
    else:
        ap.print_help()
