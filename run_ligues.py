#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Championnats nationaux : collecte d'un jour et publication dans le dépôt de données (Camelbaggy/donnees-football).

    python run_ligues.py --date 2026-11-22 --donnees ../donnees-football [--ligues fl1,pl] [--sans-journees]

Disposition (dossier `--donnees`, servi par GitHub Pages) :
    championnats/<ligue>/<saison>/<AAAA-MM-JJ>.json   matchs du jour (même schéma que soirees/<date>.json : une seule
                                                       compétition), classement, notes
    championnats/<ligue>/<saison>/journees.json        journées lues sur Wikipédia (journees_wiki.py), cache
    championnats/<ligue>/<saison>/index.json           [{date, journees, matchs, termines, maj, fichier}], date décroissante
`<saison>` = « 2026-27 ». Un match terminé déjà collecté en entier n'est jamais recollecté (plusieurs passages par jour :
seuls les nouveaux matchs terminés coûtent des requêtes). Un fichier n'est réécrit que si son contenu change (hors
horodatage `maj` / `last_updated`).
"""

import argparse
import json
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import journees_wiki
import ligues
import ratings


def saison_de(jour: str) -> int:
    """Année de début de la saison (1er juillet -> 30 juin)."""
    d = date.fromisoformat(jour)
    return d.year if d.month >= 7 else d.year - 1


def libelle_saison(annee: int) -> str:
    return f"{annee}-{str(annee + 1)[2:]}"


def _lire(chemin: str) -> Optional[Any]:
    try:
        with open(chemin, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _sans_horodatage(o: Any) -> Any:
    if isinstance(o, dict):
        return {k: _sans_horodatage(v) for k, v in o.items() if k not in ("maj", "last_updated")}
    if isinstance(o, list):
        return [_sans_horodatage(x) for x in o]
    return o


def ecrire_si_change(chemin: str, obj: Any) -> bool:
    ancien = _lire(chemin)
    if ancien is not None and _sans_horodatage(ancien) == _sans_horodatage(obj):
        return False
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    tmp = chemin + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, chemin)
    return True


def journees_saison(lg: str, annee: int, dossier: str, avec_wiki: bool) -> Dict[str, Any]:
    """Journées de la saison (cache relu ; Wikipédia relu une fois par jour au plus). Jamais bloquant."""
    chemin = os.path.join(dossier, "journees.json")
    cache = _lire(chemin) or {}
    if not avec_wiki or (cache.get("maj") or "")[:10] == datetime.now(timezone.utc).date().isoformat():
        return cache
    try:
        clubs = ligues.equipes(lg)
        ms = ligues.saison(lg, annee, clubs)
        if not ms:
            print(f"[WARN] {lg} : calendrier ESPN de la saison illisible ; journées inchangées")
            return cache
        res = journees_wiki.calculer(lg, annee, ms, clubs, cache)
        if res.get("erreur"):
            print(f"[WARN] {lg} : journées Wikipédia non mises à jour : {res.get('anomalies', [])[:3]}")
            return cache
        res["calendrier"] = {m["espn_id"]: m["date_utc"] for m in ms}
        ecrire_si_change(chemin, res)
        print(f"[JOURNÉES] {lg} : {len(res['journees'])}/{len(ms)} match(s) avec journée ; "
              f"{len(res['anomalies'])} anomalie(s) : {res['anomalies'][:2]}")
        return res
    except Exception as e:   # la journée est un complément : rien ne doit arrêter la collecte
        print(f"[WARN] {lg} : journées Wikipédia en erreur : {e}")
        return cache


def classement_valable(jour: str, calendrier: Dict[str, str], maintenant: datetime) -> bool:
    """Le classement ESPN ACTUEL décrit-il l'état à l'issue du jour `jour` ? Oui tant qu'aucun match du championnat
    postérieur à ce jour n'a commencé (calendrier ESPN de la saison) ; sans calendrier : avant 10 h UTC le lendemain."""
    fin = datetime.fromisoformat(jour + "T00:00:00+00:00") + timedelta(days=1)
    suivants = sorted(d for d in calendrier.values() if d and d >= fin.strftime("%Y-%m-%dT%H:%M"))
    if suivants:
        return maintenant < datetime.fromisoformat(suivants[0].replace("Z", "+00:00"))
    return maintenant < fin + timedelta(hours=10)


def collecter(jour: str, donnees: str, ligues_demandees: List[str], avec_wiki: bool = True,
              maintenant: Optional[datetime] = None) -> Dict[str, Any]:
    maintenant = maintenant or datetime.now(timezone.utc)
    annee = saison_de(jour)
    bilan: Dict[str, Any] = {}
    for lg in ligues_demandees:
        dossier = os.path.join(donnees, "championnats", lg, libelle_saison(annee))
        chemin = os.path.join(dossier, f"{jour}.json")
        precedent = _lire(chemin) or {}
        deja = {m["espn_id"]: m for m in ((precedent.get("competitions") or {}).get(lg) or {}).get("matches", [])
                if m.get("finished") and m.get("players") and not m.get("detail_manquant")}
        jr = journees_saison(lg, annee, dossier, avec_wiki)
        journees = jr.get("journees") or {}

        # Matchs du jour (heure de Paris) : jours ESPN de la veille et du jour
        veille = (date.fromisoformat(jour) - timedelta(days=1)).isoformat()
        vus, matchs, incomplet, nouveaux = set(), [], False, 0
        for j in (veille, jour):
            evs, st = ligues.scoreboard(lg, j)
            incomplet |= st != "ok"
            for ev in evs:
                m = ligues.match_de_base(lg, ev)
                if m["date"] != jour or m["espn_id"] in vus:
                    continue
                vus.add(m["espn_id"])
                if m["espn_id"] in deja:
                    m = deja[m["espn_id"]]
                elif m["finished"]:
                    r = ligues.completer_match(lg, m)
                    nouveaux += 1
                    print(f"[INFO] {ligues.LIGUES[lg]['short_name']} {m['home_team']['name']} {m['home_team']['score']}-"
                          f"{m['away_team']['score']} {m['away_team']['name']} : {r}")
                    if r != "ok":
                        m["detail_manquant"] = True
                        incomplet = True
                n = journees.get(m["espn_id"])
                m.pop("matchday", None)
                m.update({"matchday": f"Journée {n}" if n else "", "matchday_short": f"J{n}" if n else "",
                          "journee": n, "round": {"name": f"Journée {n}" if n else "", "type": "LEAGUE"}})
                matchs.append(m)
        if incomplet and not matchs and precedent:
            print(f"[WARN] {lg} {jour} : ESPN illisible ; fichier précédent conservé")
            bilan[lg] = {"statut": "erreur"}
            continue
        if not matchs and not precedent:
            bilan[lg] = {"statut": "aucun_match"}
            continue
        # Notes : recalculées sur TOUS les matchs notés du jour (standardisation par championnat et par jour, comme les
        # coupes par soirée) ; un match déjà noté peut donc voir ses notes bouger légèrement quand un autre s'ajoute
        notes = ratings.rate_matches([m for m in matchs if m.get("players")]) if any(m.get("players") for m in matchs) else {}
        rows, source = [], "absent"
        if classement_valable(jour, jr.get("calendrier") or {}, maintenant):
            rows, st = ligues.classement(lg)
            source = "officiel" if rows else "absent"
        else:
            ancien = (precedent.get("competitions") or {}).get(lg) or {}
            rows, source = ancien.get("standings") or [], ancien.get("standings_source") or "absent"
        termines = sum(1 for m in matchs if m["finished"])
        comp = {
            "id": lg, "name": ligues.LIGUES[lg]["name"], "short_name": ligues.LIGUES[lg]["short_name"],
            "stage_type": "league", "type": "championnat", "pays": ligues.LIGUES[lg]["country"],
            "matches": sorted(matchs, key=lambda x: (x.get("date_utc", ""), x["home_team"]["name"])),
            "standings": rows, "standings_source": source, "french_clubs_focus": [], "notes": notes,
            "incomplet": incomplet,
        }
        sortie = {"last_updated": maintenant.strftime("%Y-%m-%dT%H:%M:%SZ"), "target_dates": [jour],
                  "source": ligues.SOURCE + " ; journées : Wikipédia", "saison": libelle_saison(annee),
                  "competitions": {lg: comp}}
        ecrit = ecrire_si_change(chemin, sortie)
        # Index de la saison
        chemin_idx = os.path.join(dossier, "index.json")
        idx = [l for l in (_lire(chemin_idx) or []) if l.get("date") != jour]
        idx.append({"date": jour, "journees": sorted({m["journee"] for m in matchs if m.get("journee")}),
                    "matchs": len(matchs), "termines": termines, "incomplet": incomplet,
                    "maj": maintenant.strftime("%Y-%m-%dT%H:%M:%SZ"), "fichier": f"{jour}.json"})
        idx.sort(key=lambda l: l["date"], reverse=True)
        ecrire_si_change(chemin_idx, idx)
        statut = "aucun_match" if not matchs else "complet" if termines == len(matchs) and not incomplet else "partiel"
        bilan[lg] = {"statut": statut, "matchs": len(matchs), "termines": termines, "nouveaux": nouveaux, "ecrit": ecrit}
        print(f"[OK] {ligues.LIGUES[lg]['name']} {jour} : {statut}, {termines}/{len(matchs)} terminé(s), "
              f"{nouveaux} nouveau(x), classement {source}, fichier {'écrit' if ecrit else 'inchangé'}")
    print(f"[INFO] {ligues.REQUETES['n']} requête(s) ESPN, {ligues.REQUETES['erreurs']} en erreur")
    return bilan


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Championnats : collecte d'un jour -> dépôt de données")
    ap.add_argument("--date", help="AAAA-MM-JJ (défaut : aujourd'hui, heure UTC)")
    ap.add_argument("--du", help="première date d'une plage (avec --au)")
    ap.add_argument("--au")
    ap.add_argument("--donnees", default="../donnees-football")
    ap.add_argument("--ligues", default=",".join(ligues.LIGUES))
    ap.add_argument("--sans-journees", action="store_true", help="ne pas relire Wikipédia (cache seul)")
    a = ap.parse_args()
    if a.du:
        d, fin = date.fromisoformat(a.du), date.fromisoformat(a.au or a.du)
        jours = []
        while d <= fin:
            jours.append(d.isoformat())
            d += timedelta(days=1)
    else:
        jours = [a.date or datetime.now(timezone.utc).date().isoformat()]
    for j in jours:
        collecter(j, a.donnees, a.ligues.split(","), not a.sans_journees)
