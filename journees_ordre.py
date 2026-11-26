"""
Numéro de journée DÉDUIT du calendrier (championnats sans source de journées : Portugal, Pays-Bas, Belgique, Autriche,
Grèce). Idée du propriétaire (26/11/2026) : dans un championnat aller-retour, chaque club joue une fois par journée.
Règles (déterministes ; un match sans preuve reste SANS journée, jamais deviné) :

1. date de référence de la journée k = médiane des dates des k-ièmes matchs de TOUS les clubs (calendrier ESPN de la saison,
   reportés à leur date d'origine) : robuste, presque tous les clubs sont à l'heure ;
2. chaque match est rangé dans la journée de référence la plus proche (à moins de `ECART_JOURS`) ; il en reçoit le numéro
   seulement si CHACUN de ses deux clubs a exactement un match dans cette fenêtre ;
   Match pas encore joué : fenêtre de `ECART_AVENIR_JOURS` seulement (une affiche reprogrammée tombe hors de toute fenêtre) ;
3. complément (matchs JOUÉS et reports en attente seulement) : un match encore sans journée (report rejoué plus tard : ses deux
   clubs ont deux matchs dans la même fenêtre) reçoit la journée manquante commune à ses deux clubs si elle est UNIQUE et antérieure à sa date ; répété tant que ça progresse ;
4. contrôles finaux : au plus un match par club et par journée, au plus clubs / 2 matchs, k <= `max_j` (fin de la phase
   régulière : les poules finales belges, autrichiennes et grecques ne sont pas numérotées) ; une journée qui viole un contrôle
   est entièrement retirée.
"""

import statistics
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

ECART_JOURS = 4.0
ECART_AVENIR_JOURS = 2.0     # match pas encore joué : plus près de la date de la journée (reprogrammations)


def _jours(iso: str) -> Optional[float]:
    try:
        return datetime.fromisoformat((iso or "").replace("Z", "+00:00")).timestamp() / 86400
    except ValueError:
        return None


def calculer(ms: List[Dict[str, Any]], max_j: Optional[int] = None) -> Tuple[Dict[str, int], List[str]]:
    """`ms` = calendrier de la saison (`ligues.saison` : espn_id, home, away, date_utc, statut). Renvoie ({espn_id: journée},
    anomalies). Les matchs annulés ne comptent pas."""
    ms = [m for m in ms if m.get("statut") not in ("STATUS_CANCELED",) and _jours(m.get("date_utc")) is not None]
    ms.sort(key=lambda m: (m["date_utc"], m["espn_id"]))
    clubs = sorted({m["home"] for m in ms} | {m["away"] for m in ms})
    max_j = max_j or 2 * (len(clubs) - 1)
    par_match = {m["espn_id"]: m for m in ms}
    rang: Dict[Tuple[str, str], int] = {}
    vus: Dict[str, int] = {}
    for m in ms:
        for c in (m["home"], m["away"]):
            vus[c] = vus.get(c, 0) + 1
            rang[(m["espn_id"], c)] = vus[c]
    anomalies: List[str] = []
    # 1. dates de référence des journées
    ref: Dict[int, float] = {}
    for k in range(1, max_j + 1):
        ds = [_jours(m["date_utc"]) for m in ms for c in (m["home"], m["away"]) if rang[(m["espn_id"], c)] == k]
        if len(ds) >= len(clubs) // 2:
            ref[k] = statistics.median(ds)
    # 2. fenêtre la plus proche ; un seul match par club dans la fenêtre
    fen: Dict[str, int] = {}
    for m in ms:
        d = _jours(m["date_utc"])
        if m.get("statut") == "STATUS_POSTPONED":
            continue                       # date d'origine : traité par le complément (journée manquante unique)
        k = min(ref, key=lambda v: abs(d - ref[v]), default=None)
        if k is not None and abs(d - ref[k]) <= (ECART_JOURS if m.get("score") is not None else ECART_AVENIR_JOURS):
            fen[m["espn_id"]] = k
    nb: Dict[Tuple[str, int], int] = {}
    for mid, k in fen.items():
        for c in (par_match[mid]["home"], par_match[mid]["away"]):
            nb[(c, k)] = nb.get((c, k), 0) + 1
    j: Dict[str, int] = {mid: k for mid, k in fen.items()
                         if nb[(par_match[mid]["home"], k)] == 1 and nb[(par_match[mid]["away"], k)] == 1}
    # 3. complément : journée manquante commune UNIQUE, antérieure (ou égale) à la date du match
    while True:
        pris: Dict[str, set] = {c: set() for c in clubs}
        for mid, n in j.items():
            pris[par_match[mid]["home"]].add(n)
            pris[par_match[mid]["away"]].add(n)
        ajout = 0
        for m in ms:
            if m["espn_id"] in j or (m.get("score") is None and m.get("statut") != "STATUS_POSTPONED"):
                continue                   # complément réservé aux matchs JOUÉS (et aux reports en attente) : pas d'avenir deviné
            d = _jours(m["date_utc"])
            jusque = [k for k in ref if ref[k] <= d + ECART_JOURS]
            commun = {k for k in jusque if k not in pris[m["home"]] and k not in pris[m["away"]]}
            if len(commun) == 1:
                n = commun.pop()
                j[m["espn_id"]] = n
                pris[m["home"]].add(n)
                pris[m["away"]].add(n)
                ajout += 1
        if not ajout:
            break
    # 4. contrôles finaux par journée
    par_j: Dict[int, List[str]] = {}
    for mid, n in j.items():
        par_j.setdefault(n, []).append(mid)
    for n, mids in sorted(par_j.items()):
        cs = [c for x in mids for c in (par_match[x]["home"], par_match[x]["away"])]
        if len(cs) != len(set(cs)) or len(mids) > len(clubs) // 2:
            anomalies.append(f"J{n} retirée : {len(mids)} match(s), club(s) en double")
            for x in mids:
                del j[x]
    sans = len(ms) - len(j)
    if sans:
        anomalies.append(f"{sans} match(s) sans journée déduite")
    return j, anomalies


def _calendrier(n_clubs: int = 10) -> List[Dict[str, Any]]:
    """Calendrier fictif aller-retour (méthode du tableau tournant), une journée par semaine ; id = « J-i »."""
    c = [chr(65 + i) for i in range(n_clubs)]
    tours = []
    for _ in range(n_clubs - 1):
        tours.append([(c[i], c[-1 - i]) for i in range(n_clubs // 2)])
        c = [c[0], c[-1]] + c[1:-1]
    tours += [[(b, a) for a, b in t] for t in tours]
    return [{"espn_id": f"{n}-{i}", "home": h, "away": a, "statut": "STATUS_FULL_TIME", "score": (1, 0),
             "date_utc": (datetime(2026, 8, 1) + timedelta(days=7 * n)).strftime("%Y-%m-%dT18:00Z")}
            for n, t in enumerate(tours, 1) for i, (h, a) in enumerate(t)]


def _tests() -> None:
    ms = _calendrier()
    vrai = {m["espn_id"]: int(m["espn_id"].split("-")[0]) for m in ms}
    j, an = calculer(ms)
    assert j == vrai and not an, (len(j), an)
    # report : un match de J3 rejoué entre J6 et J7 -> jamais de journée fausse, et retrouvé par le complément
    ms2 = [dict(m) for m in ms]
    next(m for m in ms2 if m["espn_id"] == "3-1")["date_utc"] = "2026-09-15T18:00Z"
    j2, an2 = calculer(ms2)
    faux = {k: (v, vrai[k]) for k, v in j2.items() if vrai[k] != v}
    assert not faux, faux
    assert j2.get("3-1") == 3 and len(j2) == len(vrai), (len(j2), an2)
    # deux reports qui se croisent
    next(m for m in ms2 if m["espn_id"] == "5-2")["date_utc"] = "2026-10-01T18:00Z"
    j3, _ = calculer(ms2)
    assert all(vrai[k] == v for k, v in j3.items()), "journée fausse avec deux reports"
    # report encore à jouer (statut reporté, date d'origine) : garde sa journée
    ms3 = [dict(m) for m in ms]
    next(m for m in ms3 if m["espn_id"] == "4-0")["statut"] = "STATUS_POSTPONED"
    assert calculer(ms3)[0] == vrai
    # borne de la phase régulière
    assert max(calculer(ms, max_j=12)[0].values()) == 12
    print("[OK] journees_ordre : tests passés")


if __name__ == "__main__":
    _tests()
