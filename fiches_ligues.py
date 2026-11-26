#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fiches de club et de joueur des CHAMPIONNATS (étape 5 des championnats ; décision du propriétaire du 25/11/2026 : « une fiche par
club et par joueur », coupes et championnats réunis).

Produit, dans le dépôt de données (`--donnees`), `championnats/clubs/<espn-id>.json` AU MÊME SCHÉMA que les fiches UEFA
(`clubs/<id UEFA>.json` du dépôt de code, lues par index.html) + `championnats/clubs/index.json` + `championnats/clubs/correspondances.json`.
La page fusionne la fiche de championnat et la fiche UEFA d'un même club (voir `correspondances`) : une seule fiche.

Contenu d'une fiche (valeurs absentes = absentes, aucune valeur inventée) :
- identité : nom ESPN, logo ESPN, pays du championnat ; `uefa_id` si la correspondance est PROUVÉE ;
- `saison.matchs` : calendrier ESPN de la saison (`ligues.saison`) du point de vue du club (score, V/N/D calculé, journée lue dans
  journees.json, `soiree` = jour si le fichier du jour existe : la page ouvre alors la fiche du match), `forme` (5 derniers), `prochain` ;
- `rang` : classement ESPN actuel ; `stats.<ligue>` : CUMULS calculés sur les matchs collectés (stats d'équipe ESPN / Opta), par match
  (cumul / matchs ; possession et précision = moyennes), moyenne du championnat (moyenne simple des valeurs par match de ses clubs) ;
- `stade` : stade le plus fréquent dans les matchs à domicile collectés ; `couleurs.principale` : couleur de maillot la plus fréquente à
  domicile (maillot porté, ESPN), `secondaire` : la plus fréquente à l'extérieur si différente ;
- `wikidata` / `wikipedia` / `histoire` : fondation, siège, site, surnom, stade (capacité…), extrait Wikipédia FR, historique européen
  (voir encyclo_ligues.py : club -> article Wikipédia du tableau des résultats -> élément Wikidata, jamais par le nom seul) ;
- `effectif` : effectif ESPN (poste, numéro, âge, date de naissance, nationalité, photo) + statistiques de la saison CALCULÉES sur les
  matchs collectés (matchs joués, titularisations, minutes, buts, passes décisives, cartons, xG, xA, note moyenne ; gardiens : arrêts,
  buts encaissés, matchs sans encaisser) et la liste de ses matchs (`matchs`) ; un joueur parti en cours de saison reste listé.

Correspondance ESPN <-> UEFA (`correspondances`) : seulement par PREUVE, un match de coupe du club UEFA dont l'événement ESPN est connu
(`xg_espn_id` des soirées publiées du dépôt de code) : le résumé ESPN de cet événement donne l'id ESPN du club à domicile / à
l'extérieur. Jamais par le nom seul.

    python fiches_ligues.py --donnees ../donnees-football [--ligues fl1,pl] [--sans-effectifs] [--test]
"""

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import classement_ligue
import encyclo_joueurs
import encyclo_ligues
import ligues
from netutil import FLAG_CODES

COUPES_PAGES = "https://camelbaggy.github.io/coupes-europe/"
POURCENTAGES = {"ball_possession", "passes_accuracy", "ppda"}   # moyennes (jamais additionnées)
ESPN_COUPES = {"ucl": "uefa.champions", "uel": "uefa.europa", "uecl": "uefa.europa.conf"}


def _lire(chemin: str) -> Optional[Any]:
    try:
        with open(chemin, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _ecrire(chemin: str, obj: Any) -> bool:
    """Écrit si le contenu change (hors `maj`)."""
    ancien = _lire(chemin)
    sans = lambda o: {k: v for k, v in o.items() if k != "maj"} if isinstance(o, dict) else o  # noqa: E731
    if ancien is not None and sans(ancien) == sans(obj):
        return False
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin + ".tmp", "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(chemin + ".tmp", chemin)
    return True


def resultat(pour: int, contre: int) -> str:
    return "V" if pour > contre else "N" if pour == contre else "D"


# ------------------------------------------------------------------------------
# Agrégats (fonctions pures)
# ------------------------------------------------------------------------------
def stats_club(matchs_detail: List[Dict[str, Any]], club: str) -> Optional[Dict[str, Any]]:
    """Cumuls / moyennes par match d'un club sur ses matchs collectés (`club` = id `espn-…`)."""
    jou = [m for m in matchs_detail if m.get("finished") and not m.get("en_attente")]
    if not jou:
        return None
    cumul: Dict[str, float] = {}
    pct: Dict[str, List[float]] = {}
    v = n = d = cs = 0
    for m in jou:
        cote = "home" if m["home_team"]["id"] == club else "away"
        autre = "away" if cote == "home" else "home"
        pour, contre = m[f"{cote}_team"]["score"], m[f"{autre}_team"]["score"]
        cumul["goals"] = cumul.get("goals", 0) + pour
        cumul["goals_conceded"] = cumul.get("goals_conceded", 0) + contre
        cs += contre == 0
        r = resultat(pour, contre)
        v, n, d = v + (r == "V"), n + (r == "N"), d + (r == "D")
        for s in (m.get("stats") or {}).get("all") or []:
            val = s.get(cote)
            if not isinstance(val, (int, float)):
                continue
            if s["key"] in POURCENTAGES:
                pct.setdefault(s["key"], []).append(val)
            else:
                cumul[s["key"]] = cumul.get(s["key"], 0) + val
    cumul["clean_sheet"] = cs
    nb = len(jou)
    par_match = {k: round(x / nb, 2) for k, x in cumul.items()}
    for k, vals in pct.items():
        cumul[k] = par_match[k] = round(sum(vals) / len(vals), 1)
    cumul = {k: (round(x, 3) if isinstance(x, float) else x) for k, x in cumul.items()}
    return {"matchs": nb, "cumul": cumul, "par_match": par_match, "vnd": {"v": v, "n": n, "d": d}}


def stats_joueurs(matchs_detail: List[Dict[str, Any]], club: str, ligue: str) -> Dict[str, Dict[str, Any]]:
    """{id joueur: {identite (depuis les matchs), stats, matchs[]}} pour les joueurs du club ayant JOUÉ (minutes > 0)."""
    out: Dict[str, Dict[str, Any]] = {}
    for m in sorted(matchs_detail, key=lambda x: x.get("date_utc", "")):
        if not m.get("players"):
            continue
        cote = "home" if m["home_team"]["id"] == club else "away"
        adv = m["away_team" if cote == "home" else "home_team"]
        for pid, p in m["players"].items():
            if p.get("team") != cote or not p.get("minutes"):
                continue
            j = out.setdefault(pid, {"ident": p, "notes": [], "stats": Counter(), "matchs": []})
            st = p.get("stats") or {}
            s = j["stats"]
            s["matches_appearance"] += 1
            s["titulaire"] += 1 if p.get("starter") else 0
            s["minutes_played_official"] += int(p.get("minutes") or 0)
            for cle in ("goals", "assists", "yellow_cards", "red_cards", "saves", "xg", "xa"):
                if st.get(cle):
                    s[cle] += st[cle]
            if p.get("pos") == "GOALKEEPER":
                s["goals_conceded"] += int(st.get("goals_conceded") or 0)
                s["clean_sheet"] += 1 if st.get("clean_sheet") else 0
            if p.get("rating") is not None:
                j["notes"].append(p["rating"])
            j["matchs"].append({"date": m.get("date"), "match_id": m.get("match_id"), "comp": ligue,
                                "adversaire": adv.get("name"), "domicile": cote == "home",
                                "score": f"{m['home_team']['score']}-{m['away_team']['score']}",
                                "minutes": p.get("minutes"), "note": p.get("rating"),
                                **({"buts": st["goals"]} if st.get("goals") else {}),
                                **({"passes": st["assists"]} if st.get("assists") else {})})
    for j in out.values():
        s = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in j["stats"].items() if v}
        if j["notes"]:
            s["note_moyenne"] = round(sum(j["notes"]) / len(j["notes"]), 2)
            s["matchs_notes"] = len(j["notes"])
        j["stats"] = s
    return out


# ------------------------------------------------------------------------------
# Correspondance ESPN <-> UEFA (preuve par un match de coupe commun)
# ------------------------------------------------------------------------------
def correspondances(ancien: Dict[str, Any], pays: List[str]) -> Dict[str, Any]:
    """{espn_id brut: {uefa_id, preuve}} pour les clubs UEFA des pays donnés (codes UEFA : FRA, ENG, ESP, ITA, GER). Les
    correspondances déjà prouvées sont gardées ; seuls les clubs UEFA non rapprochés sont cherchés."""
    idx = ligues._get(COUPES_PAGES + "clubs/index.json")[0] or {}
    connus = {v["uefa_id"] for v in ancien.values()}
    out = dict(ancien)
    soirees: Dict[str, Any] = {}
    for c in idx.get("clubs") or []:
        if c.get("code_pays") not in pays or str(c["id"]) in connus:
            continue
        fiche = ligues._get(COUPES_PAGES + "clubs/" + str(c["id"]) + ".json")[0] or {}
        for x in (fiche.get("saison") or {}).get("matchs") or []:
            if not x.get("soiree") or x.get("pour") is None:
                continue
            if x["soiree"] not in soirees:
                soirees[x["soiree"]] = ligues._get(COUPES_PAGES + "soirees/" + x["soiree"] + ".json")[0] or {}
            m = next((mm for comp in (soirees[x["soiree"]].get("competitions") or {}).values()
                      for mm in comp.get("matches") or [] if mm.get("match_id") == x["match_id"]), None)
            if not m or not m.get("xg_espn_id"):
                continue
            slug = m.get("xg_espn_ligue") or ESPN_COUPES.get(x["comp"], "")
            res, st = ligues._get(f"{ligues.SITE}/{slug}/summary?event={m['xg_espn_id']}")
            comps = ((((res or {}).get("header") or {}).get("competitions") or [{}])[0].get("competitors")) or []
            cote = "home" if x.get("domicile") else "away"
            e = next((k for k in comps if k.get("homeAway") == cote), None)
            if e and str((e.get("team") or {}).get("id") or ""):
                out[str(e["team"]["id"])] = {"uefa_id": str(c["id"]), "nom_uefa": c.get("nom"),
                                             "preuve": f"match UEFA {x['match_id']} du {x['date']} = événement ESPN {m['xg_espn_id']}"}
                break
    return out


# ------------------------------------------------------------------------------
# Construction des fiches
# ------------------------------------------------------------------------------
def construire(donnees: str, ligues_demandees: List[str], avec_effectifs: bool = True, avec_encyclo: bool = True,
               budget_historique_s: float = 480, budget_joueurs_s: float = 240) -> Dict[str, Any]:
    import run_ligues
    maintenant = datetime.now(timezone.utc)
    fin_historique = time.time() + budget_historique_s
    ids_coupes = {str(c["id"]) for c in ((ligues._get(COUPES_PAGES + "clubs/index.json")[0] or {}).get("clubs") or [])}
    jour_paris = maintenant.astimezone(ligues._PARIS).date().isoformat()
    annee = run_ligues.saison_de(jour_paris)
    lib = run_ligues.libelle_saison(annee)        # libellé de l'index commun (saison sur deux années)
    base = os.path.join(donnees, "championnats", "clubs")
    corr_chemin = os.path.join(base, "correspondances.json")
    corr = _lire(corr_chemin) or {}
    try:
        corr = correspondances(corr, [ligues.LIGUES[lg]["country"] for lg in ligues_demandees])
        _ecrire(corr_chemin, corr)
    except Exception as e:   # jamais bloquant
        print(f"[WARN] correspondances UEFA non mises à jour : {e}")
    qid_cache = _lire(os.path.join(base, "wiki_qid.json")) or {}
    liens_hist = _lire(os.path.join(base, "liens_historique.json")) or {}
    index = (_lire(os.path.join(base, "index.json")) or {}).get("clubs") or []
    index = [c for c in index if c.get("ligue") not in ligues_demandees]
    for lg in ligues_demandees:
        meta = ligues.LIGUES[lg]
        annee, lib_lg = run_ligues.saison_de(jour_paris, lg), run_ligues.libelle_saison(run_ligues.saison_de(jour_paris, lg), lg)
        dossier = os.path.join(donnees, "championnats", lg, lib_lg)
        calendrier = run_ligues.matchs_saison(lg, annee)
        clubs = run_ligues._CLUBS.get(lg) or {}
        if not calendrier or not clubs:
            print(f"[WARN] {lg} : calendrier ou classement ESPN illisible, fiches inchangées")
            index += [c for c in ((_lire(os.path.join(base, "index.json")) or {}).get("clubs") or []) if c.get("ligue") == lg]
            continue
        journees_doc = _lire(os.path.join(dossier, "journees.json")) or {}
        journees = journees_doc.get("journees") or {}
        details: Dict[str, Dict[str, Any]] = {}
        jours = set()
        for f in sorted(os.listdir(dossier)) if os.path.isdir(dossier) else []:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", f):
                jours.add(f[:10])
                for m in ((_lire(os.path.join(dossier, f)) or {}).get("competitions") or {}).get(lg, {}).get("matches") or []:
                    details[m["espn_id"]] = m
        rang = {r["team_id"]: r for r in clubs.values()}
        fiches = {}
        for cid, row in clubs.items():
            club = f"espn-{cid}"
            mes = [m for m in calendrier if cid in (m["home"], m["away"])]
            det = [details[m["espn_id"]] for m in mes if m["espn_id"] in details]
            liste = []
            for m in mes:
                dom = m["home"] == cid
                adv_id = m["away"] if dom else m["home"]
                adv = clubs.get(adv_id, {})
                jour = classement_ligue.jour_paris(m["date_utc"])
                x = {"match_id": f"espn-{m['espn_id']}", "date": jour, "heure_utc": m["date_utc"], "comp": lg, "stage": "league",
                     "tour": f"Journée {journees[m['espn_id']]}" if journees.get(m["espn_id"]) else "Journée",
                     "journee": f"J {journees[m['espn_id']]}" if journees.get(m["espn_id"]) else "",
                     "domicile": dom, "adversaire": {"id": f"espn-{adv_id}", "nom": adv.get("team") or "?", "logo": adv.get("logo", ""),
                                                     "pays": meta["country"], "drapeau": FLAG_CODES.get(meta["country"], "")},
                     "statut": "Terminé" if m.get("score") else "À venir"}
                if m.get("score"):
                    p, c = (m["score"][0], m["score"][1]) if dom else (m["score"][1], m["score"][0])
                    x.update(pour=p, contre=c, resultat=resultat(p, c))
                    if jour in jours and m["espn_id"] in details:
                        x["soiree"] = jour
                liste.append(x)
            liste.sort(key=lambda x: x["heure_utc"])
            joues = [x for x in liste if x.get("pour") is not None]
            futurs = [x for x in liste if x.get("pour") is None and x["heure_utc"] >= maintenant.strftime("%Y-%m-%dT%H:%M")]
            r = rang.get(club, {})
            dom_det = [m for m in det if m["home_team"]["id"] == club]
            stades = Counter(m.get("venue") for m in dom_det if m.get("venue"))
            maillots_d = Counter(m["home_team"].get("shirt_color") for m in dom_det if m["home_team"].get("shirt_color"))
            maillots_e = Counter(m["away_team"].get("shirt_color") for m in det if m["away_team"]["id"] == club and m["away_team"].get("shirt_color"))
            st = stats_club(det, club)
            f = {"id": club, "espn_id": cid, "nom": row.get("team"), "nom_officiel": row.get("team"), "nom_court": row.get("short_name"),
                 "pays": meta["country_name"], "code_pays": meta["country"], "drapeau": FLAG_CODES.get(meta["country"], ""),
                 "francais": meta["country"] == "FRA", "ligue": lg, "competitions": [lg], "saison_label": lib_lg,
                 "logos": {"70": row.get("logo", ""), "240": row.get("logo", "")},
                 "saison": {"matchs": liste, "forme": [x["resultat"] for x in joues[-5:]],
                            "prochain": futurs[0]["match_id"] if futurs else None},
                 "rang": [{"comp": lg, "rang": r.get("rank"), "points": r.get("points"), "joues": r.get("played"), "v": r.get("won"),
                           "n": r.get("drawn"), "d": r.get("lost"), "bp": r.get("gf"), "bc": r.get("ga"), "diff": r.get("gd"),
                           "zone_libelle": r.get("zone_libelle"), "source": "ESPN"}] if r else [],
                 "stats": {lg: st} if st else {}, "maj": maintenant.strftime("%Y-%m-%dT%H:%M:%SZ")}
            if stades:
                f["stade"] = {"nom": stades.most_common(1)[0][0], "source": "ESPN",
                              **({"autres_stades": [s for s, _ in stades.most_common()[1:]]} if len(stades) > 1 else {})}
            if maillots_d:
                coul = {"principale": maillots_d.most_common(1)[0][0], "source": "maillots_espn", "nb_matchs": maillots_d.most_common(1)[0][1]}
                sec = [c for c, _ in maillots_e.most_common() if c != coul["principale"]]
                if sec:
                    coul["secondaire"] = sec[0]
                f["couleurs"] = coul
            if cid in corr:
                f["uefa_id"] = corr[cid]["uefa_id"]
            # Effectif : ESPN (identité) + stats calculées sur les matchs collectés
            js = stats_joueurs(det, club, lg)
            eff = []
            roster = ligues.effectif(lg, cid) if avec_effectifs else {}
            vus = set()
            for aid, a in roster.items():
                pid = f"espn-{aid}"
                vus.add(pid)
                cit = a.get("citizenshipCountry") or {}
                code = (cit.get("abbreviation") or "").upper()
                j = js.get(pid)
                eff.append({"id": pid, "nom": a.get("displayName"), "nom_court": a.get("lastName") or a.get("shortName"),
                            "poste": ligues.POSTE.get(((a.get("position") or {}).get("name")) or "", ""),
                            "poste_fr": {"GOALKEEPER": "Gardien", "DEFENDER": "Défenseur", "MIDFIELDER": "Milieu", "FORWARD": "Attaquant"}.get(
                                ligues.POSTE.get(((a.get("position") or {}).get("name")) or "", ""), ""),
                            "numero": str(a.get("jersey") or ""), "age": a.get("age"),
                            "naissance": (a.get("dateOfBirth") or "")[:10] or None, "pays": code, "nationalite": a.get("citizenship"),
                            "drapeau": FLAG_CODES.get(code, ""), "photo": ((a.get("headshot") or {}).get("href")) or "",
                            "joue": bool(j), **({"stats": {lg: j["stats"]}, "matchs": j["matchs"]} if j else {})})
            for pid, j in js.items():
                if pid in vus:
                    continue
                p = j["ident"]
                eff.append({"id": pid, "nom": p.get("name"), "nom_court": p.get("short"), "poste": p.get("pos"),
                            "poste_fr": p.get("pos_fr"), "numero": p.get("number"), "age": p.get("age"), "nationalite": p.get("nationality"),
                            "drapeau": p.get("flag"), "photo": p.get("photo", ""), "joue": True, "parti": True,
                            "stats": {lg: j["stats"]}, "matchs": j["matchs"]})
            f["effectif"] = [{k: v for k, v in e.items() if v not in (None, "")} for e in eff]
            fiches[cid] = f
        # Moyenne du championnat (valeurs par match des clubs ayant joué)
        pms = [f["stats"][lg]["par_match"] for f in fiches.values() if f["stats"]]
        moy = {k: round(sum(p.get(k, 0) for p in pms) / len(pms), 2) for k in {k for p in pms for k in p}} if pms else {}
        # Encyclopédie (Wikidata / Wikipédia) et historique européen : jamais bloquants (encyclo_ligues.py)
        anciens = {cid: _lire(os.path.join(base, f"espn-{cid}.json")) or {} for cid in fiches}
        if avec_encyclo:
            try:
                n = encyclo_ligues.enrichir(fiches, anciens, lg, annee, journees_doc, maintenant.strftime("%Y-%m-%dT%H:%M:%SZ"))
                print(f"[ENCYCLO] {meta['name']} : {n['wikidata']} élément(s) Wikidata, {n['wikipedia']} extrait(s) Wikipédia relus, "
                      f"{n['non_relies']} club(s) non relié(s)")
            except Exception as e:
                print(f"[WARN] {meta['name']} : encyclopédie non mise à jour ({e}), valeurs précédentes conservées")
                for cid, f in fiches.items():
                    for k in ("wikidata", "wikipedia"):
                        if anciens[cid].get(k):
                            f[k] = anciens[cid][k]
                    encyclo_ligues.completer_stade(f)
            try:
                h = encyclo_ligues.historiques(list(fiches.values()), base, ids_coupes, max(0.0, fin_historique - time.time()))
                print(f"[HISTOIRE] {meta['name']} : {sum(1 for f in fiches.values() if f.get('histoire'))} club(s) avec historique européen, "
                      f"{h} fichier(s) produit(s)")
            except Exception as e:
                print(f"[WARN] {meta['name']} : historique européen non mis à jour ({e})")
                for cid, f in fiches.items():
                    if anciens[cid].get("histoire"):
                        f["histoire"] = anciens[cid]["histoire"]
            try:   # classements des saisons passées (championnats/historique/, historique_classements.py)
                hist = _lire(os.path.join(donnees, "championnats", "historique", f"{lg}.json"))
                if hist:
                    liens = encyclo_ligues.parcours_championnat(fiches, hist, qid_cache, maintenant.strftime("%Y-%m-%dT%H:%M:%SZ"))
                    liens_hist[lg] = liens
                    print(f"[HISTORIQUE] {meta['name']} : {sum(1 for f in fiches.values() if f.get('championnat_hist'))} club(s) avec leur "
                          f"parcours, {len(liens)} lien(s) Wikipédia -> club")
            except Exception as e:
                print(f"[WARN] {meta['name']} : parcours en championnat non calculé ({e})")
                for cid, f in fiches.items():
                    if anciens[cid].get("championnat_hist"):
                        f["championnat_hist"] = anciens[cid]["championnat_hist"]
            try:
                n = encyclo_joueurs.enrichir(fiches, anciens, maintenant.strftime("%Y-%m-%dT%H:%M:%SZ"), budget_s=budget_joueurs_s)
                print(f"[JOUEURS] {meta['name']} : {n['demandes']} joueur(s) à relire, {n['relies']} relié(s) à Wikidata, "
                      f"{n['photos']} photo(s), {n['extraits']} extrait(s)")
            except Exception as e:
                print(f"[WARN] {meta['name']} : joueurs non enrichis ({e}), valeurs précédentes conservées")
                prec = {j["id"]: j for a in anciens.values() for j in a.get("effectif") or []}
                for f in fiches.values():
                    for j in f.get("effectif") or []:
                        for k in ("wd", "wp"):
                            if (prec.get(j["id"]) or {}).get(k):
                                j[k] = prec[j["id"]][k]
        for cid, f in fiches.items():
            if f["stats"]:
                f["stats"][lg]["moyenne_competition"] = {"valeurs": moy, "clubs": len(pms), "maj": maintenant.date().isoformat()}
            _ecrire(os.path.join(base, f"espn-{cid}.json"), f)
            index.append({"id": f["id"], "nom": f["nom"], "nom_court": f["nom_court"], "pays": f["pays"], "code_pays": f["code_pays"],
                          "drapeau": f["drapeau"], "francais": f["francais"], "ligue": lg, "logos": f["logos"],
                          "competitions": [lg], "fichier": f"championnats/clubs/espn-{cid}.json",
                          **({"uefa_id": f["uefa_id"]} if f.get("uefa_id") else {}),
                          # id UEFA lu dans Wikidata (P7361 unique, encyclo_ligues) : sert au parcours européen du classement
                          # (clubs/europe.json), jamais à la fusion des fiches (réservée à la correspondance prouvée `uefa_id`)
                          **({"uefa_wd": str((f.get("wikidata") or {}).get("uefa_id"))}
                             if not f.get("uefa_id") and (f.get("wikidata") or {}).get("uefa_id") else {}),
                          **({"couleurs": f["couleurs"]} if f.get("couleurs") else {})})
        print(f"[FICHES] {meta['name']} : {len(fiches)} fiches, {sum(1 for f in fiches.values() if f.get('uefa_id'))} rapprochée(s) d'une fiche UEFA")
    _ecrire(os.path.join(base, "wiki_qid.json"), qid_cache)
    _ecrire(os.path.join(base, "liens_historique.json"), liens_hist)
    _ecrire(os.path.join(base, "index.json"), {"saison": lib, "maj": maintenant.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                                "clubs": sorted(index, key=lambda c: (c["ligue"], c["nom"] or ""))})
    print(f"[FICHES] {ligues.REQUETES['n']} requête(s) ESPN ; {len(corr)} correspondance(s) UEFA")
    return {"clubs": len(index), "correspondances": len(corr)}


def _test() -> None:
    def m(h, a, sh, sa, stats, players=None):
        return {"finished": True, "home_team": {"id": h, "score": sh, "name": h}, "away_team": {"id": a, "score": sa, "name": a},
                "stats": {"all": stats}, "players": players or {}, "date": "2026-11-01", "date_utc": "2026-11-01T20:00Z", "match_id": "x"}
    s1 = [{"key": "attempts", "home": 10, "away": 4}, {"key": "ball_possession", "home": 60, "away": 40}, {"key": "xg", "home": 1.5, "away": 0.4}]
    s2 = [{"key": "attempts", "home": 6, "away": 12}, {"key": "ball_possession", "home": 45, "away": 55}, {"key": "xg", "home": 0.8, "away": 2.1}]
    st = stats_club([m("A", "B", 2, 0, s1), m("C", "A", 1, 1, s2)], "A")
    assert st["matchs"] == 2 and st["cumul"]["attempts"] == 22 and st["par_match"]["attempts"] == 11.0, st
    assert st["cumul"]["ball_possession"] == 57.5 and st["vnd"] == {"v": 1, "n": 1, "d": 0} and st["cumul"]["clean_sheet"] == 1
    assert st["cumul"]["goals"] == 3 and st["cumul"]["goals_conceded"] == 1 and st["cumul"]["xg"] == 3.6, st
    pl = {"p1": {"team": "home", "minutes": 90, "starter": True, "pos": "FORWARD", "rating": 7.5, "stats": {"goals": 2, "xg": 1.2}},
          "p2": {"team": "away", "minutes": 90, "pos": "GOALKEEPER", "rating": 5.9, "stats": {"goals_conceded": 2}},
          "p3": {"team": "home", "minutes": 0, "pos": "DEFENDER", "stats": {}}}
    js = stats_joueurs([m("A", "B", 2, 0, s1, pl)], "A", "fl1")
    assert set(js) == {"p1"} and js["p1"]["stats"]["goals"] == 2 and js["p1"]["stats"]["note_moyenne"] == 7.5, js
    assert js["p1"]["matchs"][0]["buts"] == 2 and js["p1"]["matchs"][0]["score"] == "2-0"
    jb = stats_joueurs([m("A", "B", 2, 0, s1, pl)], "B", "fl1")
    assert jb["p2"]["stats"]["goals_conceded"] == 2 and "clean_sheet" not in jb["p2"]["stats"]
    assert resultat(1, 1) == "N" and resultat(0, 2) == "D"
    print("[OK] fiches_ligues : tests passés")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Fiches de club et de joueur des championnats")
    ap.add_argument("--donnees", default="../donnees-football")
    ap.add_argument("--ligues", default=",".join(ligues.LIGUES))
    ap.add_argument("--sans-effectifs", action="store_true")
    ap.add_argument("--sans-encyclo", action="store_true", help="ni Wikidata / Wikipédia ni historique européen")
    ap.add_argument("--budget-historique", type=float, default=8, help="minutes au plus pour l'historique européen (reprenable)")
    ap.add_argument("--budget-joueurs", type=float, default=4, help="minutes au plus, par championnat, pour les photos et extraits des joueurs")
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    if a.test:
        _test()
        sys.exit(0)
    construire(a.donnees, a.ligues.split(","), not a.sans_effectifs, not a.sans_encyclo, a.budget_historique * 60, a.budget_joueurs * 60)
