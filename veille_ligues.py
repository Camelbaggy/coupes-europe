#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Veille de la collecte QUOTIDIENNE des championnats (étape 3, décision du 25/11/2026 : tous les jours, pas seulement le week-end).
Tourne dans le dépôt de données Camelbaggy/donnees-football (battement.yml : toutes les 10 min pendant ~330 min, puis se
relance ; veille_secours.yml : un passage par heure + relance du battement), avec le code de ce dépôt.

Décision (`a_lancer`, pure) pour un jour J (heure de Paris) :
  - J n'a encore aucun état publié (etat_championnats.json) et il est >= 9 h UTC : on lance (le passage enregistre les matchs
    du jour ou `aucun_match` ; la notification commune sait alors s'il faut attendre les championnats) ;
  - ESPN compte plus de matchs « prêts » (terminés, coup d'envoi il y a au moins DELAI_APRES_COUP_MIN) que l'état publié : on
    lance (un nouveau match à collecter) ;
  - sinon rien. Garde-fous : aucun passage de collecte en file ou en cours, le dernier a démarré il y a au moins SEUIL_MIN.
Jours examinés : aujourd'hui (Paris) ; hier jusqu'à 12 h UTC (matchs du soir, rattrapage d'une panne).
Coût : 2 requêtes ESPN (scoreboard) par championnat et par jour examiné, toutes les 10 min.

    python veille_ligues.py --une-fois     # un passage (veille_secours.yml)
    python veille_ligues.py --boucle 330   # battement (relance battement.yml à la fin)
    python veille_ligues.py --test
Environnement : GH_TOKEN (jeton du dépôt de données, actions: write), REPO (Camelbaggy/donnees-football), WF (collecte_championnats.yml).
Deux familles (ligues.FAMILLES, 26/11/2026) : principaux (etat_championnats.json -> WF) et secondaires (etat_secondaires.json ->
collecte_secondaires.yml, sans alerte d'échec) ; mêmes règles, passages indépendants.
"""

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

DELAI_APRES_COUP_MIN = 120      # identique à run_ligues.DELAI_APRES_COUP_MIN
SEUIL_MIN = 15                  # au moins 15 min entre deux passages de collecte lancés par la veille
HEURE_PREMIER_RELEVE = 9        # UTC : premier relevé d'un jour sans état
PAUSE_S = 600
API = "https://api.github.com"

try:
    from zoneinfo import ZoneInfo
    PARIS = ZoneInfo("Europe/Paris")
except Exception:  # pragma: no cover
    PARIS = dt.timezone(dt.timedelta(hours=1))


def jours_a_examiner(maintenant: dt.datetime) -> List[str]:
    auj = maintenant.astimezone(PARIS).date()
    jours = [auj.isoformat()]
    if maintenant.hour < 12:
        jours.insert(0, (auj - dt.timedelta(days=1)).isoformat())
    return jours


def prets_espn(matchs: List[Dict[str, Any]], maintenant: dt.datetime) -> int:
    """Matchs terminés dont le coup d'envoi date d'au moins DELAI_APRES_COUP_MIN (reportés / annulés exclus)."""
    n = 0
    for m in matchs:
        if not m.get("finished") or m.get("status") in ("Reporté", "Annulé"):
            continue
        try:
            coup = dt.datetime.fromisoformat((m.get("date_utc") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if maintenant >= coup + dt.timedelta(minutes=DELAI_APRES_COUP_MIN):
            n += 1
    return n


def a_lancer(jour: str, maintenant: dt.datetime, etat: Dict[str, Any], prets: Optional[int]) -> Tuple[bool, str]:
    """(lancer ?, raison). `prets` = matchs prêts selon ESPN (None = ESPN illisible)."""
    e = etat.get(jour)
    if e is None:
        if maintenant.hour >= HEURE_PREMIER_RELEVE or jour < maintenant.astimezone(PARIS).date().isoformat():
            return True, f"{jour} : aucun état publié, premier relevé"
        return False, f"{jour} : aucun état, premier relevé après {HEURE_PREMIER_RELEVE} h UTC"
    connus = sum((l.get("termines") or 0) for l in (e.get("ligues") or {}).values())
    if prets is None:
        return False, f"{jour} : ESPN illisible, rien à faire"
    if prets > connus:
        return True, f"{jour} : {prets} match(s) prêt(s) selon ESPN, {connus} collecté(s)"
    return False, f"{jour} : à jour ({connus} collecté(s), {e.get('statut')})"


# ------------------------------------------------------------------------------
# GitHub (API REST, jeton du dépôt) et ESPN
# ------------------------------------------------------------------------------
def gh(methode: str, chemin: str, corps: Optional[Dict[str, Any]] = None, brut: bool = False) -> Any:
    req = urllib.request.Request(API + chemin, method=methode, data=json.dumps(corps).encode() if corps else None,
                                 headers={"Authorization": f"Bearer {os.environ.get('GH_TOKEN', '')}",
                                          "Accept": "application/vnd.github.raw" if brut else "application/vnd.github+json",
                                          "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "veille-championnats"})
    with urllib.request.urlopen(req, timeout=30) as r:
        txt = r.read().decode("utf-8")
        return json.loads(txt) if txt else None


def etat_publie(repo: str, fichier: str = "etat_championnats.json") -> Optional[Dict[str, Any]]:
    try:
        return gh("GET", f"/repos/{repo}/contents/{fichier}?ref=main", brut=True) or {}
    except urllib.error.HTTPError as e:
        return {} if e.code == 404 else None
    except Exception:
        return None


def passages(repo: str, wf: str) -> Optional[List[Dict[str, Any]]]:
    try:
        return (gh("GET", f"/repos/{repo}/actions/workflows/{wf}/runs?per_page=10") or {}).get("workflow_runs") or []
    except Exception:
        return None


def lancer(repo: str, wf: str, inputs: Dict[str, str]) -> bool:
    try:
        gh("POST", f"/repos/{repo}/actions/workflows/{wf}/dispatches", {"ref": "main", "inputs": inputs})
        return True
    except Exception as e:
        print(f"[VEILLE-LIGUES] relance impossible : {e}")
        return False


def matchs_espn(jour: str, lgs: Optional[List[str]] = None) -> Optional[List[Dict[str, Any]]]:
    import ligues
    out, vus = [], set()
    veille = (dt.date.fromisoformat(jour) - dt.timedelta(days=1)).isoformat()
    for lg in lgs or ligues.PRINCIPAUX:
        for j in (veille, jour):
            evs, st = ligues.scoreboard(lg, j)
            if st != "ok":
                return None
            for ev in evs:
                m = ligues.match_de_base(lg, ev)
                if m["date"] == jour and m["espn_id"] not in vus:
                    vus.add(m["espn_id"])
                    out.append(m)
    return out


def un_passage(repo: str, wf: str, maintenant: Optional[dt.datetime] = None) -> None:
    """Un passage pour chaque famille (principaux : `wf`, alerte d'échec ; secondaires : collecte_secondaires.yml, sans alerte)."""
    import ligues
    for nom, fam in ligues.FAMILLES.items():
        print(f"[VEILLE-LIGUES] — {nom} —")
        try:
            passage_famille(repo, wf if nom == "principaux" else fam["workflow"], fam["etat"], fam["ligues"], maintenant)
        except Exception as e:
            print(f"[VEILLE-LIGUES] {nom} : passage en erreur ({e})")


def passage_famille(repo: str, wf: str, fichier_etat: str, lgs: List[str], maintenant: Optional[dt.datetime] = None) -> None:
    maintenant = maintenant or dt.datetime.now(dt.timezone.utc)
    etat = etat_publie(repo, fichier_etat)
    if etat is None:
        print(f"[VEILLE-LIGUES] {fichier_etat} illisible : rien à faire")
        return
    for jour in jours_a_examiner(maintenant):
        ms = matchs_espn(jour, lgs)
        ok, raison = a_lancer(jour, maintenant, etat, None if ms is None else prets_espn(ms, maintenant))
        print(f"[VEILLE-LIGUES] {raison}")
        if not ok:
            continue
        runs = passages(repo, wf)
        if runs is None:
            print("[VEILLE-LIGUES] liste des passages illisible : rien à faire")
            return
        if any(r.get("status") != "completed" for r in runs):
            print("[VEILLE-LIGUES] un passage de collecte est en file ou en cours : rien à faire")
            return
        if runs:
            age = (maintenant - dt.datetime.fromisoformat(runs[0]["created_at"].replace("Z", "+00:00"))).total_seconds() / 60
            if age < SEUIL_MIN:
                print(f"[VEILLE-LIGUES] dernier passage il y a {age:.0f} min (< {SEUIL_MIN}) : rien à faire")
                return
        if lancer(repo, wf, {"date": jour}):
            print(f"[VEILLE-LIGUES] collecte lancée pour {jour}")
        return   # un jour par passage (la concurrence du workflow sérialise de toute façon)


def boucle(repo: str, wf: str, duree_min: int) -> None:
    debut = time.monotonic()
    n = 0
    while True:
        n += 1
        print(f"[BATTEMENT] passage {n}, {int((time.monotonic() - debut) / 60)} min, {dt.datetime.now(dt.timezone.utc):%H:%M} UTC")
        try:
            un_passage(repo, wf)
        except Exception as e:
            print(f"[BATTEMENT] passage en erreur : {e}")
        if time.monotonic() - debut + PAUSE_S >= duree_min * 60:
            break
        time.sleep(PAUSE_S)
    runs = passages(repo, "battement.yml") or []
    autres = [r for r in runs if r.get("status") != "completed" and str(r.get("id")) != os.environ.get("GITHUB_RUN_ID")]
    if autres:
        print("[BATTEMENT] un autre battement est en file ou en cours : pas de relance")
    elif lancer(repo, "battement.yml", {}):
        print("[BATTEMENT] durée atteinte : battement.yml relancé")


def _test() -> None:
    u = dt.timezone.utc
    t = dt.datetime(2026, 11, 22, 21, 0, tzinfo=u)
    assert jours_a_examiner(t) == ["2026-11-22"]
    assert jours_a_examiner(dt.datetime(2026, 11, 23, 8, 0, tzinfo=u)) == ["2026-11-22", "2026-11-23"]
    ms = [{"finished": True, "date_utc": "2026-11-22T18:00Z", "status": "Terminé"},
          {"finished": True, "date_utc": "2026-11-22T19:30Z", "status": "Terminé"},   # moins de 2 h : pas prêt
          {"finished": False, "date_utc": "2026-11-22T20:00Z", "status": "En cours"},
          {"finished": True, "date_utc": "2026-11-22T14:00Z", "status": "Reporté"}]
    assert prets_espn(ms, t) == 1
    assert a_lancer("2026-11-22", t, {}, 1)[0] is True
    assert a_lancer("2026-11-22", dt.datetime(2026, 11, 22, 6, 0, tzinfo=u), {}, 0)[0] is False
    e = {"2026-11-22": {"statut": "partiel", "ligues": {"fl1": {"termines": 1, "matchs": 3}}}}
    assert a_lancer("2026-11-22", t, e, 1)[0] is False
    assert a_lancer("2026-11-22", t, e, 2)[0] is True
    assert a_lancer("2026-11-22", t, e, None)[0] is False
    print("[OK] veille_ligues : tests passés")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Veille de la collecte quotidienne des championnats")
    ap.add_argument("--une-fois", action="store_true")
    ap.add_argument("--boucle", type=int, metavar="MIN")
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    repo = os.environ.get("REPO", "Camelbaggy/donnees-football")
    wf = os.environ.get("WF", "collecte_championnats.yml")
    if a.test:
        _test()
    elif a.boucle:
        boucle(repo, wf, a.boucle)
    elif a.une_fois:
        un_passage(repo, wf)
    else:
        ap.print_help()
        sys.exit(1)
