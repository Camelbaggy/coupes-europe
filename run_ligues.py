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

import classement_ligue
import journees_ordre
import journees_wiki
import ligues
import ratings

_SAISONS: Dict[str, Any] = {}      # ligue -> matchs de la saison (ligues.saison), lus une fois par processus
_CLUBS: Dict[str, Any] = {}        # ligue -> {id ESPN brut: ligne du classement ESPN actuel} (noms, logos)


def matchs_saison(lg: str, annee: int) -> Optional[List[Dict[str, Any]]]:
    if lg not in _SAISONS:
        rows, _ = ligues.classement(lg)
        _CLUBS[lg] = {r["team_id"].replace("espn-", ""): r for r in rows}
        _SAISONS[lg] = ligues.saison(lg, annee, {c: [] for c in _CLUBS[lg]}) if rows else None
    return _SAISONS[lg]


def classement_calcule(lg: str, annee: int, jour: str) -> List[Dict[str, Any]]:
    """Classement recalculé à l'issue du jour (classement_ligue.py) ; [] si la liste de la saison est illisible (jamais de
    classement calculé sur une liste tronquée)."""
    ms = matchs_saison(lg, annee)
    if not ms:
        return []
    return classement_ligue.calculer(lg, ms, _CLUBS[lg], jour)


DELAI_APRES_COUP_MIN = 120   # un match terminé n'est collecté que 2 h après son coup d'envoi (stats Opta finalisées)
ETAT = "etat_championnats.json"   # racine du dépôt de données ; lu par la veille et par notification_jour.py (dépôt de code)
GARDE_JOURS = 60


def statut_jour(bilan: Dict[str, Any]) -> str:
    st = [b.get("statut") for b in bilan.values()]
    if any(s == "partiel" for s in st):
        return "partiel"
    return "complet" if any(s == "complet" for s in st) else "aucun_match"


def fichier_etat(lgs: List[str]) -> str:
    """etat_championnats.json (championnats principaux, lu par la notification) ; etat_secondaires.json si TOUS les championnats
    demandés sont secondaires (collecte séparée, jamais notifiée ni alertée)."""
    return ligues.FAMILLES["secondaires"]["etat"] if lgs and all(ligues.famille(l) == "secondaires" for l in lgs) else ETAT


def ecrire_saisons(donnees: str, lgs: List[str], jour: str) -> None:
    """championnats/saisons.json {ligue: libellé de la saison en cours} : la page y lit le dossier de chaque championnat (saisons
    sur deux années ou sur l'année civile)."""
    chemin = os.path.join(donnees, "championnats", "saisons.json")
    d = _lire(chemin) or {}
    for lg in lgs:
        d[lg] = libelle_saison(saison_de(jour, lg), lg)
    ecrire_si_change(chemin, dict(sorted(d.items())))


def ecrire_etat(donnees: str, jour: str, bilan: Dict[str, Any], maintenant: datetime) -> Dict[str, Any]:
    """etat_championnats.json : {jour: {statut, ligues: {clé: {statut, matchs, termines}}, maj, alertes?}} (60 jours gardés).
    `matchs` exclut les reportés / annulés ; `termines` = terminés ET collectés en entier."""
    chemin = os.path.join(donnees, fichier_etat(list(bilan)))
    etat = _lire(chemin) or {}
    ancien = etat.get(jour) or {}
    ligues_etat = dict(ancien.get("ligues") or {})
    for lg, b in bilan.items():
        ligues_etat[lg] = {"statut": b.get("statut"), "matchs": b.get("matchs", 0), "termines": b.get("termines", 0)}
    etat[jour] = entree = {"statut": statut_jour(ligues_etat), "ligues": ligues_etat,
                  "maj": maintenant.strftime("%Y-%m-%dT%H:%M:%SZ"),
                  **({"alertes": ancien["alertes"]} if ancien.get("alertes") else {})}
    limite = (maintenant.date() - timedelta(days=GARDE_JOURS)).isoformat()
    etat = {j: v for j, v in sorted(etat.items()) if j >= limite}
    os.makedirs(donnees, exist_ok=True)
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(etat, f, ensure_ascii=False, indent=1)
    # un jour de plus de GARDE_JOURS (collecte d'une plage ancienne) vient d'être retiré de l'état : seul le journal en parle
    print(f"[ÉTAT] {jour} : {entree['statut']}{'' if jour in etat else ' (hors des ' + str(GARDE_JOURS) + ' jours gardés)'} " +
          ", ".join(f"{lg} {v['termines']}/{v['matchs']}" for lg, v in ligues_etat.items() if v.get("matchs")))
    return etat


def alerter(jour: str, cause: str, donnees: str, url_run: str = "") -> int:
    """Alerte ntfy d'échec de la collecte des championnats (une par jour et par cause, mémorisée dans etat_championnats.json ;
    sans NTFY_TOPIC : simulation). Retourne toujours 0."""
    import notify
    chemin = os.path.join(donnees, ETAT)
    etat = _lire(chemin) or {}
    e = etat.setdefault(jour, {"statut": "partiel", "ligues": {}})
    if cause in (e.get("alertes") or {}):
        print(f"[ALERTE] {jour}, cause « {cause} » : déjà alertée")
        return 0
    if notify.send_ntfy_alert("Échec de mise à jour des championnats", f"Jour : {jour}\nÉtape en cause : {cause}\n"
                              f"Lien du run : {url_run or '(inconnu)'}", url_run):
        e.setdefault("alertes", {})[cause] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(chemin, "w", encoding="utf-8") as f:
            json.dump(etat, f, ensure_ascii=False, indent=1)
    return 0


def saison_de(jour: str, ligue: Optional[str] = None) -> int:
    """Année de début de la saison (1er juillet -> 30 juin ; année civile pour les championnats `annee_civile`)."""
    return ligues.saison_de(jour, ligue)


def libelle_saison(annee: int, ligue: Optional[str] = None) -> str:
    return ligues.libelle_saison(annee, ligue)


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


# Championnats sans source de journées (pas de page Wikipédia exploitable, décision du propriétaire du 26/11/2026) : numéro
# déduit du calendrier ESPN (journees_ordre.py ; mesuré : 0 erreur sur 850 matchs joués, 2 sur 1 634 à venir, matchs reportés)
JOURNEES_DEDUITES = {"por", "ned", "bel", "gre"}


def journees_saison(lg: str, annee: int, dossier: str, avec_wiki: bool) -> Dict[str, Any]:
    """Journées de la saison (cache relu ; Wikipédia relu une fois par jour au plus) et programme des matchs à venir
    (`programme.json`, une fois par jour au plus, indépendamment des journées). Jamais bloquant."""
    chemin = os.path.join(dossier, "journees.json")
    cache = _lire(chemin) or {}
    auj = datetime.now(timezone.utc).date().isoformat()
    besoin_jr = (cache.get("maj") or "")[:10] != auj or (lg in JOURNEES_DEDUITES and "deduites" not in cache)
    besoin_prog = ((_lire(os.path.join(dossier, "programme.json")) or {}).get("maj") or "")[:10] != auj
    if not avec_wiki or not (besoin_jr or besoin_prog):
        return cache
    try:
        clubs = ligues.equipes(lg)
        ms = ligues.saison(lg, annee, clubs)
        if not ms:
            print(f"[WARN] {lg} : calendrier ESPN de la saison illisible ; journées et programme inchangés")
            return cache
        res = journees_wiki.calculer(lg, annee, ms, clubs, cache) if besoin_jr else {"erreur": True, "deja_lues": True}
        if lg in JOURNEES_DEDUITES and not res.get("erreur"):
            # pas de source de journées : numéro déduit du calendrier (journees_ordre.py) ; Wikipédia garde la priorité
            ded, an_d = journees_ordre.calculer(ms)
            wiki_n = len(res.get("journees") or {})
            res["journees"] = {**ded, **(res.get("journees") or {})}
            res["deduites"] = len(res["journees"]) - wiki_n
            res["source"] = (res.get("source") or "") + " ; journées déduites du calendrier ESPN (journees_ordre.py)"
            res["anomalies"] = list(res.get("anomalies") or []) + [f"déduction : {a}" for a in an_d]
            print(f"[JOURNÉES] {lg} : {res['deduites']} journée(s) déduite(s) du calendrier")
        jr = cache.get("journees") or {} if res.get("erreur") else res.get("journees") or {}
        prog = ligues.programme(lg, ms, jr, datetime.now(timezone.utc))
        prog["maj"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        ecrire_si_change(os.path.join(dossier, "programme.json"), prog)
        print(f"[PROGRAMME] {lg} : {len(prog['matchs'])} match(s) à venir, "
              f"{sum(1 for x in prog['matchs'] if x.get('journee'))} avec journée")
        if res.get("deja_lues"):
            return cache
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
              maintenant: Optional[datetime] = None, reconstituee: bool = False,
              forcer_calcul: bool = False) -> Dict[str, Any]:
    maintenant = maintenant or datetime.now(timezone.utc)
    bilan: Dict[str, Any] = {}
    for lg in ligues_demandees:
        annee = saison_de(jour, lg)
        dossier = os.path.join(donnees, "championnats", lg, libelle_saison(annee, lg))
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
                coup = ligues._dt(m.get("date_utc", ""))
                if m["espn_id"] in deja:
                    m = deja[m["espn_id"]]
                elif m["finished"] and coup and maintenant < coup + timedelta(minutes=DELAI_APRES_COUP_MIN):
                    # Fini depuis trop peu : Opta complète encore ses statistiques ; collecté au passage suivant
                    m["en_attente"] = True
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
            ancien = next((l for l in (_lire(os.path.join(dossier, "index.json")) or []) if l.get("date") == jour), {})
            bilan[lg] = {"statut": "partiel", "matchs": ancien.get("matchs", 0), "termines": ancien.get("termines", 0)}
            continue
        if not matchs and not precedent:
            bilan[lg] = {"statut": "partiel" if incomplet else "aucun_match", "matchs": 0, "termines": 0}
            continue
        # Notes : recalculées sur TOUS les matchs notés du jour (standardisation par championnat et par jour, comme les
        # coupes par soirée) ; un match déjà noté peut donc voir ses notes bouger légèrement quand un autre s'ajoute
        notes = ratings.rate_matches([m for m in matchs if m.get("players")]) \
            if any(m.get("players") for m in matchs) and not ligues.flux_reduit(lg) else {}
        rows, source, calc_at = [], "absent", None
        if not reconstituee and not forcer_calcul and classement_valable(jour, jr.get("calendrier") or {}, maintenant):
            rows, st = ligues.classement(lg)
            source = "officiel" if rows else "absent"
        else:
            ancien = (precedent.get("competitions") or {}).get(lg) or {}
            if ancien.get("standings_source") == "officiel" and not reconstituee and not forcer_calcul:
                rows, source = ancien["standings"], "officiel"     # relevé à temps lors d'un passage précédent : gardé
            else:
                rows = classement_calcule(lg, annee, jour)
                source, calc_at = ("calcule", jour) if rows else ("absent", None)
        # Matchs comptés pour l'état : les reportés / annulés ne bloquent pas un jour ; un match « prêt » = terminé ET collecté
        comptes = [m for m in matchs if m.get("status") not in ("Reporté", "Annulé")]
        termines = sum(1 for m in comptes if m["finished"] and not m.get("en_attente") and not m.get("detail_manquant"))
        comp = {
            "id": lg, "name": ligues.LIGUES[lg]["name"], "short_name": ligues.LIGUES[lg]["short_name"],
            "stage_type": "league", "type": "championnat", "pays": ligues.LIGUES[lg]["country"],
            "matches": sorted(matchs, key=lambda x: (x.get("date_utc", ""), x["home_team"]["name"])),
            "standings": rows, "standings_source": source, "french_clubs_focus": [], "notes": notes,
            "incomplet": incomplet, **({"standings_at": calc_at} if calc_at else {}),
        }
        sortie = {"last_updated": maintenant.strftime("%Y-%m-%dT%H:%M:%SZ"), "target_dates": [jour],
                  "source": ligues.SOURCE + " ; journées : Wikipédia", "saison": libelle_saison(annee, lg),
                  "competitions": {lg: comp}}
        if reconstituee or precedent.get("reconstituee"):
            sortie["reconstituee"] = True
            sortie["reconstituee_le"] = precedent.get("reconstituee_le") or maintenant.date().isoformat()
        ecrit = ecrire_si_change(chemin, sortie)
        # Index de la saison
        chemin_idx = os.path.join(dossier, "index.json")
        idx = [l for l in (_lire(chemin_idx) or []) if l.get("date") != jour]
        idx.append({"date": jour, "journees": sorted({m["journee"] for m in matchs if m.get("journee")}),
                    "matchs": len(matchs), "termines": termines, "incomplet": incomplet,
                    "par_journee": {str(n): sum(1 for m in matchs if m.get("journee") == n)
                                    for n in sorted({m["journee"] for m in matchs if m.get("journee")})},
                    "sans_journee": sum(1 for m in matchs if not m.get("journee")),
                    "maj": maintenant.strftime("%Y-%m-%dT%H:%M:%SZ"), "fichier": f"{jour}.json",
                    **({"reconstituee": True} if sortie.get("reconstituee") else {})})
        idx.sort(key=lambda l: l["date"], reverse=True)
        ecrire_si_change(chemin_idx, idx)
        statut = "aucun_match" if not comptes else "complet" if termines == len(comptes) and not incomplet else "partiel"
        bilan[lg] = {"statut": statut, "matchs": len(comptes), "termines": termines, "nouveaux": nouveaux, "ecrit": ecrit}
        print(f"[OK] {ligues.LIGUES[lg]['name']} {jour} : {statut}, {termines}/{len(comptes)} prêt(s), "
              f"{nouveaux} nouveau(x), classement {source}, fichier {'écrit' if ecrit else 'inchangé'}")
    print(f"[INFO] {ligues.REQUETES['n']} requête(s) ESPN, {ligues.REQUETES['erreurs']} en erreur")
    return bilan


def a_reconstituer(donnees: str, ligues_demandees: List[str], maintenant: datetime) -> List[tuple]:
    """(jour, ligue) à reconstituer : jours (heure de Paris) avec au moins un match terminé, antérieurs à aujourd'hui, sans
    fichier publié ; du plus récent au plus ancien."""
    auj = maintenant.astimezone(ligues._PARIS).date().isoformat()
    out = []
    for lg in ligues_demandees:
        annee = saison_de(auj, lg)
        ms = matchs_saison(lg, annee)
        if ms is None:
            print(f"[WARN] {lg} : calendrier de la saison illisible ; rien à reconstituer ce passage")
            continue
        dossier = os.path.join(donnees, "championnats", lg, libelle_saison(annee, lg))
        jours = {classement_ligue.jour_paris(m["date_utc"]) for m in ms if m.get("score") is not None}
        for j in jours:
            if not j or j >= auj:
                continue
            chemin = os.path.join(dossier, f"{j}.json")
            if not os.path.exists(chemin):
                out.append((j, lg, True))
            elif ((_lire(chemin) or {}).get("competitions") or {}).get(lg, {}).get("standings_source") == "absent":
                out.append((j, lg, False))   # jour collecté en direct sans classement valable : classement recalculé seul
    return sorted(out, reverse=True)


def reconstituer(donnees: str, ligues_demandees: List[str], budget_min: float) -> Dict[str, int]:
    """Rejoue les jours passés de la saison (même collecte, classement RECALCULÉ, `reconstituee: true`) dans la limite du
    budget ; jamais d'état du jour ni de notification. Reprenable : un jour déjà écrit n'est plus demandé."""
    debut = datetime.now(timezone.utc)
    todo = a_reconstituer(donnees, ligues_demandees, debut)
    print(f"[RECONSTITUTION] {len(todo)} jour(s) x championnat à reconstituer")
    faits = 0
    for jour, lg, nouveau in todo:
        if (datetime.now(timezone.utc) - debut).total_seconds() > budget_min * 60:
            print(f"[RECONSTITUTION] budget de {budget_min} min atteint")
            break
        collecter(jour, donnees, [lg], True, reconstituee=nouveau, forcer_calcul=not nouveau)
        faits += 1
    restants = len(todo) - faits
    ecrire_saisons(donnees, ligues_demandees, debut.astimezone(ligues._PARIS).date().isoformat())
    print(f"[RECONSTITUTION] {faits} fait(s), {restants} restant(s)")
    sortie = os.environ.get("GITHUB_OUTPUT")
    if sortie:
        with open(sortie, "a", encoding="utf-8") as f:
            f.write(f"traites={faits}\nrestants={restants}\n")
    return {"traites": faits, "restants": restants}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Championnats : collecte d'un jour -> dépôt de données")
    ap.add_argument("--date", help="AAAA-MM-JJ (défaut : aujourd'hui, heure UTC)")
    ap.add_argument("--du", help="première date d'une plage (avec --au)")
    ap.add_argument("--au")
    ap.add_argument("--donnees", default="../donnees-football")
    ap.add_argument("--ligues", default=",".join(ligues.LIGUES))
    ap.add_argument("--sans-journees", action="store_true", help="ne pas relire Wikipédia (cache seul)")
    ap.add_argument("--etat", action="store_true", help="écrire etat_championnats.json (collecte quotidienne)")
    ap.add_argument("--alerte", metavar="JOUR", help="alerte ntfy d'échec pour ce jour (avec --cause), sans collecte")
    ap.add_argument("--cause", default="workflow")
    ap.add_argument("--reconstituer", action="store_true", help="rejouer les jours passés de la saison sans fichier")
    ap.add_argument("--budget-min", type=float, default=40)
    a = ap.parse_args()
    if a.reconstituer:
        reconstituer(a.donnees, a.ligues.split(","), a.budget_min)
        raise SystemExit(0)
    if a.alerte:
        e = os.environ
        url = f"{e.get('GITHUB_SERVER_URL', '')}/{e.get('GITHUB_REPOSITORY', '')}/actions/runs/{e.get('GITHUB_RUN_ID', '')}" \
            if e.get("GITHUB_RUN_ID") else ""
        raise SystemExit(alerter(a.alerte, a.cause, a.donnees, url))
    if a.du:
        d, fin = date.fromisoformat(a.du), date.fromisoformat(a.au or a.du)
        jours = []
        while d <= fin:
            jours.append(d.isoformat())
            d += timedelta(days=1)
    else:
        jours = [a.date or datetime.now(timezone.utc).date().isoformat()]
    for j in jours:
        b = collecter(j, a.donnees, a.ligues.split(","), not a.sans_journees)
        ecrire_saisons(a.donnees, a.ligues.split(","), j)
        if a.etat:
            ecrire_etat(a.donnees, j, b, datetime.now(timezone.utc))
