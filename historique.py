#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Historique des soirées : `soirees/<AAAA-MM-JJ>.json` + `soirees/index.json` (jamais purgés).

  soirees/<date>.json   même contenu que data.json pour cette soirée (une seule soirée), écrit en JSON compact ;
                        `reconstituee: true` + `reconstituee_le` pour une soirée rejouée a posteriori ;
  soirees/index.json    liste LÉGÈRE triée par date décroissante, une ligne par soirée (voir `ligne_index`) ;
  data.json             copie de la soirée la plus RÉCENTE de l'index (compatibilité : index.html sans index, notify,
                        publication.py, battement) : jamais remplacé par une soirée plus ancienne.

L'index se dérive entièrement des fichiers : `reindexer` le reconstruit (utilisé par publier.sh après un rebase, où
deux passages concurrents ont pu perdre la ligne de l'autre). Fonctions pures + lecture / écriture JSON ;
tests : `python historique.py --test`.
"""

import datetime as dt
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

import soirees

DOSSIER = "soirees"
INDEX = "index.json"
# Une carte de résumé qui échoue au contrôle trois fois n'est plus retentée par le rattrapage IA (quota gratuit).
MAX_TENTATIVES_IA = 3
FICHIER_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")
TOURS_QUALIF = {"FIRST_QUALIFYING": "T1", "SECOND_QUALIFYING": "T2", "THIRD_QUALIFYING": "T3", "PLAY_OFF": "Barrages"}


# ------------------------------------------------------------------------------
# Libellés
# ------------------------------------------------------------------------------
def stage_du_match(match: Dict[str, Any], comp: Optional[Dict[str, Any]] = None) -> str:
    """league / qualifying / knockout / '' (inconnu). Les anciens fichiers (sans `stage`) : « Journée N » d'une
    compétition de type league = phase de ligue ; rien d'autre n'est deviné."""
    if match.get("stage"):
        return match["stage"]
    if (comp or {}).get("stage_type") == "league" and re.match(r"^Journée \d+$", match.get("matchday") or ""):
        return "league"
    return ""


def tour_court(match: Dict[str, Any], comp: Optional[Dict[str, Any]] = None) -> str:
    """Sigle court du tour d'un match : J5 (phase de ligue), T2 aller / T1 retour / Barrages aller (préliminaires)."""
    stage = stage_du_match(match, comp)
    if stage == "league":
        m = re.match(r"^Journée (\d+)$", match.get("matchday") or "")
        return (f"J{m.group(1)}" if m else (match.get("matchday_short") or "").replace(" ", "")) or "Phase de ligue"
    rnd = match.get("round") or {}
    if stage == "qualifying":
        tour = TOURS_QUALIF.get(rnd.get("type")) or rnd.get("name") or "Préliminaires"
        return tour + {"FIRST_LEG": " aller", "SECOND_LEG": " retour"}.get(match.get("leg"), "")
    return rnd.get("name") or match.get("matchday") or ""


def _tours(matchs: List[Dict[str, Any]], comp: Dict[str, Any]) -> str:
    vus: List[str] = []
    for m in matchs:
        t = tour_court(m, comp)
        if t and t not in vus:
            vus.append(t)
    return " / ".join(vus)


# ------------------------------------------------------------------------------
# Ligne d'index
# ------------------------------------------------------------------------------
def ligne_index(data: Dict[str, Any], jour: str, dossier: str = DOSSIER) -> Dict[str, Any]:
    """Ligne légère de l'index pour la soirée `jour` (dérivée du contenu du fichier, rien d'autre)."""
    notif = data.get("notification") or {}
    comps: Dict[str, Any] = {}
    francais: List[Dict[str, Any]] = []
    gemini = deterministe = a_rattraper = 0
    matchs = termines = 0
    for key, comp in (data.get("competitions") or {}).items():
        ms = comp.get("matches") or []
        if not ms:
            continue
        stages = sorted({stage_du_match(m, comp) for m in ms} - {""})
        comps[key] = {"matchs": len(ms), "stage": stages[0] if len(stages) == 1 else ("mixte" if stages else ""),
                      "tour": _tours(ms, comp)}
        matchs += len(ms)
        termines += sum(1 for m in ms if m.get("finished"))
        by_id = {m.get("match_id"): m for m in ms}
        for m in ms:
            if m.get("is_french_match") or m["home_team"].get("is_french") or m["away_team"].get("is_french"):
                francais.append({"comp": key, "match_id": m.get("match_id"), "home": m["home_team"]["name"],
                                 "away": m["away_team"]["name"], "home_fr": bool(m["home_team"].get("is_french")),
                                 "away_fr": bool(m["away_team"].get("is_french")),
                                 "score": f"{m['home_team']['score']}-{m['away_team']['score']}" if m.get("finished") else "",
                                 "statut": m.get("status", "")})
        for card in comp.get("french_clubs_focus") or []:
            if card.get("summary_source") == "gemini":
                gemini += 1
            else:
                deterministe += 1
                if (stage_du_match(by_id.get(card.get("match_id")) or {}, comp) == "league"
                        and int(card.get("ia_tentatives") or 0) < MAX_TENTATIVES_IA):
                    a_rattraper += 1
    statut = soirees.statut_soiree(int(notif.get("matchs", matchs)), int(notif.get("termines", termines)),
                                   bool(notif.get("incomplet")))
    ligne = {"date": jour, "statut": statut, "matchs": matchs, "termines": termines, "competitions": comps,
             "francais": francais, "resumes": {"gemini": gemini, "deterministe": deterministe, "a_rattraper": a_rattraper},
             "reconstituee": bool(data.get("reconstituee")), "maj": data.get("last_updated", ""),
             "fichier": f"{DOSSIER}/{jour}.json"}
    return ligne


# ------------------------------------------------------------------------------
# Fichiers
# ------------------------------------------------------------------------------
def chemin_soiree(dossier: str, jour: str) -> str:
    return os.path.join(dossier, f"{jour}.json")


def _ecrire_json(chemin: str, obj: Any, **kw) -> None:
    os.makedirs(os.path.dirname(chemin) or ".", exist_ok=True)
    tmp = chemin + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, **kw)
        f.write("\n")
    os.replace(tmp, chemin)


def lire_json(chemin: str) -> Any:
    try:
        with open(chemin, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def lire_index(dossier: str = DOSSIER) -> List[Dict[str, Any]]:
    data = lire_json(os.path.join(dossier, INDEX))
    return [l for l in data if isinstance(l, dict) and l.get("date")] if isinstance(data, list) else []


def ecrire_index(lignes: List[Dict[str, Any]], dossier: str = DOSSIER) -> List[Dict[str, Any]]:
    """Index trié par date décroissante, réécrit seulement s'il change (pas de commit vide)."""
    lignes = sorted(lignes, key=lambda l: l["date"], reverse=True)
    chemin = os.path.join(dossier, INDEX)
    if lire_json(chemin) != lignes:
        _ecrire_json(chemin, lignes, indent=1)
    return lignes


def ecrire_soiree(data: Dict[str, Any], jour: str, dossier: str = DOSSIER, reconstituee: bool = False,
                  maintenant: Optional[dt.datetime] = None, **marques: Any) -> Dict[str, Any]:
    """Écrit `soirees/<jour>.json` (JSON compact, `last_updated` / `target_dates` en tête) et sa ligne d'index.
    `reconstituee` ajoute `reconstituee: true` + `reconstituee_le` ; `marques` : autres champs de tête (ex. amorcee)."""
    maintenant = maintenant or dt.datetime.now(dt.timezone.utc)
    tete = {"last_updated": data.get("last_updated"), "target_dates": data.get("target_dates") or [jour]}
    if reconstituee:
        tete["reconstituee"] = True
        tete["reconstituee_le"] = maintenant.strftime("%Y-%m-%dT%H:%M:%SZ")
    for k in ("reconstituee", "reconstituee_le", "amorcee"):  # marques d'origine conservées lors d'une réécriture
        if k in data and k not in tete:
            tete[k] = data[k]
    tete.update(marques)
    doc = dict(tete, **{k: v for k, v in data.items() if k not in tete})
    _ecrire_json(chemin_soiree(dossier, jour), doc, separators=(",", ":"))
    ligne = ligne_index(doc, jour, dossier)
    lignes = [l for l in lire_index(dossier) if l["date"] != jour] + [ligne]
    ecrire_index(lignes, dossier)
    return ligne


def reindexer(dossier: str = DOSSIER, complet: bool = False) -> List[Dict[str, Any]]:
    """Reconstruit l'index depuis les fichiers : lignes manquantes recalculées (toutes si `complet`), lignes sans
    fichier supprimées. Idempotent (aucune écriture si rien ne change)."""
    if not os.path.isdir(dossier):
        return []
    fichiers = sorted(m.group(1) for n in os.listdir(dossier) for m in [FICHIER_RE.match(n)] if m)
    anciennes = {l["date"]: l for l in lire_index(dossier)}
    lignes = []
    for jour in fichiers:
        if jour in anciennes and not complet:
            lignes.append(anciennes[jour])
            continue
        doc = lire_json(chemin_soiree(dossier, jour))
        if isinstance(doc, dict):
            lignes.append(ligne_index(doc, jour, dossier))
        else:
            print(f"[WARN] {chemin_soiree(dossier, jour)} illisible : ignoré dans l'index")
    return ecrire_index(lignes, dossier)


# ------------------------------------------------------------------------------
# data.json = soirée la plus récente
# ------------------------------------------------------------------------------
def doit_remplacer_data_json(jour: str, index: List[Dict[str, Any]], data_actuel: Optional[Dict[str, Any]],
                             strict: bool = False) -> bool:
    """data.json prend la soirée `jour` seulement si elle est au moins aussi récente que toute soirée de l'index ET que
    ce que data.json contient déjà : une soirée plus ancienne (relance manuelle, reconstitution) ne le remplace jamais.
    `strict` (reconstitution) : une soirée de la MÊME date ne le remplace pas non plus (data.json vient d'un vrai
    passage, avec ses résumés IA ; la version reconstituée est moins riche)."""
    if any(l["date"] > jour for l in index):
        return False
    dates = (data_actuel or {}).get("target_dates") or []
    return not (dates and (jour < max(dates) or (strict and jour == max(dates))))


def synchroniser_data_json(doc: Dict[str, Any], jour: str, data_path: str = "data.json") -> bool:
    """Si data.json est déjà la soirée `jour`, il en suit les mises à jour (ex. un résumé rattrapé) : copie fidèle."""
    actuel = lire_json(data_path)
    if isinstance(actuel, dict) and (actuel.get("target_dates") or []) == [jour]:
        _ecrire_json(data_path, doc, indent=2)
        return True
    return False


def restaurer_data_json(dossier: str = DOSSIER, data_path: str = "data.json") -> bool:
    """Rétablit l'invariant « data.json = soirée la plus récente de l'index » si un rebase concurrent l'a rompu
    (un data.json plus ancien que l'index est remplacé par la copie du fichier de la soirée la plus récente)."""
    index = lire_index(dossier)
    if not index:
        return False
    actuel = lire_json(data_path)
    dates = (actuel.get("target_dates") or []) if isinstance(actuel, dict) else []
    doc = lire_json(chemin_soiree(dossier, index[0]["date"]))
    if (dates and max(dates) >= index[0]["date"]) or not isinstance(doc, dict):
        return False
    _ecrire_json(data_path, doc, indent=2)
    return True


def amorcer(data_actuel: Optional[Dict[str, Any]], dossier: str = DOSSIER) -> Optional[str]:
    """Avant de remplacer data.json : si c'est UNE soirée sans fichier dans `soirees/`, on la conserve (amorçage ;
    la première fois, data.json est la seule trace de la soirée précédente, résumés IA compris)."""
    dates = (data_actuel or {}).get("target_dates") or []
    if not data_actuel or len(dates) != 1 or not data_actuel.get("competitions"):
        return None
    jour = dates[0]
    if os.path.exists(chemin_soiree(dossier, jour)):
        return None
    ecrire_soiree(data_actuel, jour, dossier, amorcee=True)
    print(f"[SOIREES] Soirée {jour} conservée depuis data.json (amorçage de l'historique).")
    return jour


def publier_soiree(data: Dict[str, Any], jour: str, dossier: str = DOSSIER, data_path: str = "data.json",
                   reconstituee: bool = False, maintenant: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """Range une soirée : amorçage éventuel, `soirees/<jour>.json`, index, puis data.json SI la soirée est la plus récente.
    Retourne {"ligne": ligne d'index, "data_json": bool}."""
    actuel = lire_json(data_path)
    amorcer(actuel if isinstance(actuel, dict) else None, dossier)
    ligne = ecrire_soiree(data, jour, dossier, reconstituee=reconstituee, maintenant=maintenant)
    remplace = doit_remplacer_data_json(jour, lire_index(dossier), actuel if isinstance(actuel, dict) else None,
                                        strict=reconstituee)
    if remplace:
        _ecrire_json(data_path, data, indent=2)
        print(f"[SOIREES] Soirée {jour} -> {dossier}/{jour}.json + {data_path} (la plus récente).")
    else:
        print(f"[SOIREES] Soirée {jour} -> {dossier}/{jour}.json ; {data_path} inchangé (une soirée plus récente existe).")
    return {"ligne": ligne, "data_json": remplace}


# ------------------------------------------------------------------------------
# Reconstitution : quelles soirées rejouer ?
# ------------------------------------------------------------------------------
def soirees_de_saison(par_comp: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Dict[str, int]]:
    """{date: {"matchs": n, "termines": k}} d'après les listes de matchs UEFA de la saison (toutes compétitions)."""
    out: Dict[str, Dict[str, int]] = {}
    for matchs in par_comp.values():
        for m in matchs or []:
            jour = ((m.get("kickOffTime") or {}).get("date") or "")[:10]
            if not jour:
                continue
            c = out.setdefault(jour, {"matchs": 0, "termines": 0})
            c["matchs"] += 1
            c["termines"] += 1 if m.get("status") == "FINISHED" else 0
    return out


def creneau_normal_passe(jour: str, maintenant: dt.datetime) -> bool:
    """Le créneau du passage normal (+ battement) de la soirée est-il fini ? 13 h UTC le lendemain, comme veille.sh :
    avant, la soirée appartient au workflow update_dashboard (et à sa notification), jamais à la reconstitution."""
    d = dt.date.fromisoformat(jour) + dt.timedelta(days=1)
    return maintenant >= dt.datetime(d.year, d.month, d.day, 13, tzinfo=dt.timezone.utc)


def dates_a_reconstituer(par_comp: Dict[str, List[Dict[str, Any]]], maintenant: dt.datetime, dossier: str = DOSSIER,
                         du: Optional[str] = None, au: Optional[str] = None) -> List[str]:
    """Dates sans fichier dans `soirees/`, avec au moins un match terminé, au créneau normal passé, de la plus
    récente à la plus ancienne (les soirées les plus utiles d'abord)."""
    out = []
    for jour, c in sorted(soirees_de_saison(par_comp).items(), reverse=True):
        if c["termines"] <= 0 or (du and jour < du) or (au and jour > au):
            continue
        if not creneau_normal_passe(jour, maintenant) or os.path.exists(chemin_soiree(dossier, jour)):
            continue
        out.append(jour)
    return out


# ------------------------------------------------------------------------------
# Rattrapage IA : quelles cartes ?
# ------------------------------------------------------------------------------
def cartes_a_rattraper(dossier: str = DOSSIER) -> List[Dict[str, Any]]:
    """Cartes de clubs français de PHASE DE LIGUE encore en résumé déterministe, de la soirée la plus récente à la plus
    ancienne : [{date, comp, match_id, club}]. Jamais les tours préliminaires (décision du 25/11/2026 : seule la phase
    de ligue est rattrapée ; aux saisons suivantes les préliminaires sont traités en direct). Une carte déjà essayée
    MAX_TENTATIVES_IA fois est écartée. N'ouvre que les fichiers dont la ligne d'index annonce des cartes à rattraper."""
    out = []
    for l in lire_index(dossier):
        if int((l.get("resumes") or {}).get("a_rattraper", 0)) <= 0:
            continue
        doc = lire_json(chemin_soiree(dossier, l["date"]))
        if not isinstance(doc, dict):
            continue
        for key, comp in (doc.get("competitions") or {}).items():
            by_id = {m.get("match_id"): m for m in comp.get("matches") or []}
            for card in comp.get("french_clubs_focus") or []:
                if (card.get("summary_source") != "gemini"
                        and stage_du_match(by_id.get(card.get("match_id")) or {}, comp) == "league"
                        and int(card.get("ia_tentatives") or 0) < MAX_TENTATIVES_IA):
                    out.append({"date": l["date"], "comp": key, "match_id": card.get("match_id"),
                                "club": card.get("club_name")})
    return out


# ------------------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------------------
def _carte(mid, club, source="deterministe", tent=0):
    return {"match_id": mid, "club_name": club, "summary_source": source, "ia_tentatives": tent, "ai_summary": "x"}


def _match(mid, home, away, hs, as_, stage="league", mday="Journée 5", fr_home=True, finished=True, **extra):
    m = {"match_id": mid, "date": "2026-11-24", "finished": finished, "status": "Terminé" if finished else "À venir",
         "matchday": mday, "is_french_match": True,
         "home_team": {"name": home, "score": hs, "is_french": fr_home},
         "away_team": {"name": away, "score": as_, "is_french": not fr_home}}
    if stage:
        m["stage"] = stage
    m.update(extra)
    return m


def _soiree(jour, last, comps):
    n = sum(len(c["matches"]) for c in comps.values())
    t = sum(1 for c in comps.values() for m in c["matches"] if m["finished"])
    return {"last_updated": last, "target_dates": [jour], "notification": {"matchs": n, "termines": t, "incomplet": False},
            "competitions": comps}


def _test():
    import tempfile
    U = dt.timezone.utc
    J1, J2, J3 = "2026-11-04", "2026-11-24", "2026-08-26"
    # libellés
    assert tour_court(_match("1", "A", "B", 1, 0)) == "J5"
    assert tour_court(_match("1", "A", "B", 1, 0, stage="", mday="Journée 3"), {"stage_type": "league"}) == "J3"
    assert tour_court(_match("1", "A", "B", 1, 0, stage="qualifying", mday="Journée 1",
                             round={"type": "SECOND_QUALIFYING", "name": "Deuxième tour de qualification"},
                             leg="FIRST_LEG")) == "T2 aller"
    assert tour_court(_match("1", "A", "B", 1, 0, stage="qualifying", round={"type": "PLAY_OFF"}, leg="SECOND_LEG")) == "Barrages retour"
    # écriture, index, remplacement de data.json
    with tempfile.TemporaryDirectory() as d:
        dos, dj = os.path.join(d, "soirees"), os.path.join(d, "data.json")
        ucl = {"name": "LDC", "stage_type": "league", "matches": [_match("1", "Lens", "PSG", 2, 1), _match("2", "X", "Y", 0, 0, fr_home=False)],
               "french_clubs_focus": [_carte("1", "Lens", "gemini"), _carte("1", "PSG")], "standings": []}
        s24 = _soiree(J2, "2026-11-25T00:13:00Z", {"ucl": ucl})
        # 1. data.json absent : la soirée devient data.json
        r = publier_soiree(s24, J2, dos, dj, maintenant=dt.datetime(2026, 11, 25, 1, 0, tzinfo=U))
        assert r["data_json"] is True and lire_json(dj)["target_dates"] == [J2]
        idx = lire_index(dos)
        assert [l["date"] for l in idx] == [J2] and idx[0]["matchs"] == 2 and idx[0]["statut"] == "complet"
        assert idx[0]["competitions"]["ucl"] == {"matchs": 2, "stage": "league", "tour": "J5"}
        assert [f["home"] for f in idx[0]["francais"]] == ["Lens", "X"] and idx[0]["francais"][0]["score"] == "2-1"
        assert idx[0]["resumes"] == {"gemini": 1, "deterministe": 1, "a_rattraper": 1} and idx[0]["reconstituee"] is False
        # 2. soirée PLUS ANCIENNE (reconstituée) : data.json inchangé, index trié par date décroissante
        s04 = _soiree(J1, "2026-11-25T02:00:00Z", {"ucl": dict(ucl, matches=[_match("9", "Nice", "Z", 1, 1)],
                                                              french_clubs_focus=[_carte("9", "Nice", "deterministe", 3)])})
        avant = open(dj, encoding="utf-8").read()
        r = publier_soiree(s04, J1, dos, dj, reconstituee=True, maintenant=dt.datetime(2026, 11, 25, 2, 0, tzinfo=U))
        assert r["data_json"] is False and open(dj, encoding="utf-8").read() == avant
        assert [l["date"] for l in lire_index(dos)] == [J2, J1]
        assert lire_index(dos)[1]["reconstituee"] is True and lire_index(dos)[1]["resumes"]["a_rattraper"] == 0  # 3 essais : écartée
        doc = lire_json(chemin_soiree(dos, J1))
        assert list(doc)[:3] == ["last_updated", "target_dates", "reconstituee"] and doc["reconstituee_le"] == "2026-11-25T02:00:00Z"
        # 3. soirée plus récente : remplace data.json ; la précédente a un fichier (amorçage inutile)
        s25 = _soiree("2026-11-25", "2026-11-26T01:00:00Z", {"ucl": ucl})
        assert publier_soiree(s25, "2026-11-25", dos, dj)["data_json"] is True and lire_json(dj)["target_dates"] == ["2026-11-25"]
        assert [l["date"] for l in lire_index(dos)] == ["2026-11-25", J2, J1]
        # 4. relance d'une soirée ancienne (J2 < 25/11) : data.json inchangé, son fichier est mis à jour
        s24b = _soiree(J2, "2026-11-26T09:00:00Z", {"ucl": ucl})
        assert publier_soiree(s24b, J2, dos, dj)["data_json"] is False and lire_json(dj)["target_dates"] == ["2026-11-25"]
        assert lire_json(chemin_soiree(dos, J2))["last_updated"] == "2026-11-26T09:00:00Z"
        # 5. amorçage : data.json d'une soirée sans fichier est conservé avant d'être remplacé
        os.remove(chemin_soiree(dos, "2026-11-25"))
        reindexer(dos)
        assert [l["date"] for l in lire_index(dos)] == [J2, J1]
        assert publier_soiree(_soiree("2026-12-01", "2026-12-02T01:00:00Z", {"ucl": ucl}), "2026-12-01", dos, dj)["data_json"] is True
        assert os.path.exists(chemin_soiree(dos, "2026-11-25")) and lire_json(chemin_soiree(dos, "2026-11-25"))["amorcee"] is True
        # data.json multi-dates (semaine de test) : jamais amorcé
        assert amorcer({"target_dates": ["a", "b"], "competitions": {"x": {}}}, dos) is None
        # 6. reindexer : ligne perdue (rebase -X theirs) recalculée, ligne sans fichier supprimée, idempotent
        lignes = [l for l in lire_index(dos) if l["date"] != J1]
        ecrire_index(lignes + [{"date": "2020-01-01", "statut": "complet"}], dos)
        assert {l["date"] for l in reindexer(dos)} == {J1, J2, "2026-11-25", "2026-12-01"}
        m1 = os.path.getmtime(os.path.join(dos, INDEX))
        reindexer(dos)
        assert os.path.getmtime(os.path.join(dos, INDEX)) == m1
        assert reindexer(os.path.join(d, "absent")) == []
        # 6 bis. data.json plus ancien que l'index (rebase concurrent) : rétabli depuis la soirée la plus récente
        _ecrire_json(dj, {"target_dates": [J2], "last_updated": "x"}, indent=2)
        assert restaurer_data_json(dos, dj) is True and lire_json(dj)["target_dates"] == ["2026-12-01"]
        assert restaurer_data_json(dos, dj) is False   # déjà à jour
        # 7. cartes à rattraper : phase de ligue seulement, essais épuisés écartés, plus récente d'abord
        pre = _soiree(J3, "2026-11-25T03:00:00Z", {"uecl": {"name": "LC", "stage_type": "knockout", "french_clubs_focus": [_carte("5", "Brest")],
                      "matches": [_match("5", "Brest", "Q", 1, 0, stage="qualifying", round={"type": "THIRD_QUALIFYING"}, leg="FIRST_LEG")]}})
        publier_soiree(pre, J3, dos, dj, reconstituee=True)
        cartes = cartes_a_rattraper(dos)
        assert [(c["date"], c["comp"], c["match_id"], c["club"]) for c in cartes] == [
            ("2026-12-01", "ucl", "1", "PSG"), ("2026-11-25", "ucl", "1", "PSG"), (J2, "ucl", "1", "PSG")], cartes
        assert all(c["date"] != J3 for c in cartes)  # préliminaires jamais rattrapés
    # data.json plus récent que la soirée (semaine de test) : pas de remplacement
    assert doit_remplacer_data_json("2026-11-04", [{"date": "2026-11-04"}], {"target_dates": ["2026-11-24"]}) is False
    assert doit_remplacer_data_json("2026-11-24", [{"date": "2026-11-24"}], {"target_dates": ["2026-11-03", "2026-11-04", "2026-11-05"]}) is True
    assert doit_remplacer_data_json("2026-11-24", [{"date": "2026-11-25"}, {"date": "2026-11-24"}], None) is False
    assert doit_remplacer_data_json("2026-11-24", [{"date": "2026-11-24"}], {"target_dates": ["2026-11-24"]}) is True
    assert doit_remplacer_data_json("2026-11-24", [{"date": "2026-11-24"}], {"target_dates": ["2026-11-24"]}, strict=True) is False
    assert doit_remplacer_data_json("2026-11-25", [{"date": "2026-11-25"}], {"target_dates": ["2026-11-24"]}, strict=True) is True
    # dates à reconstituer
    def raw(jour, statut="FINISHED"):
        return {"kickOffTime": {"date": jour}, "status": statut}
    par = {"ucl": [raw("2026-11-03"), raw("2026-11-03"), raw("2026-11-24"), raw("2026-11-25", "UPCOMING")],
           "uel": [raw("2026-11-03", "UPCOMING"), raw("2026-08-04"), raw("2026-08-05", "CANCELLED")]}
    assert soirees_de_saison(par)["2026-11-03"] == {"matchs": 3, "termines": 2}
    now = dt.datetime(2026, 11, 25, 12, 59, tzinfo=U)
    with tempfile.TemporaryDirectory() as d:
        assert dates_a_reconstituer(par, now, d) == ["2026-11-03", "2026-08-04"]   # 24/11 : créneau normal pas fini ; 25/11 à venir ; 05/08 aucun terminé
        assert dates_a_reconstituer(par, now.replace(hour=13, minute=0), d) == ["2026-11-24", "2026-11-03", "2026-08-04"]
        assert dates_a_reconstituer(par, now, d, du="2026-09-01") == ["2026-11-03"]
        assert dates_a_reconstituer(par, now, d, au="2026-09-01") == ["2026-08-04"]
        os.makedirs(os.path.join(d, "s"))
        open(chemin_soiree(os.path.join(d, "s"), "2026-11-03"), "w").write("{}")
        assert dates_a_reconstituer(par, now, os.path.join(d, "s")) == ["2026-08-04"]
    print("[OK] historique.py : tests réussis")


if __name__ == "__main__":
    if "--test" in sys.argv:
        _test()
    elif "--reindexer" in sys.argv:
        dossier = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--dossier=")), DOSSIER)
        lignes = reindexer(dossier, complet="--complet" in sys.argv)
        rest = restaurer_data_json(dossier)
        print(f"[SOIREES] index de {dossier} : {len(lignes)} soirée(s)" + (" ; data.json rétabli" if rest else ""))
