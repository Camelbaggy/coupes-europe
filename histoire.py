#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Historique européen complet d'un club : `clubs/historique/<id UEFA>.json` (un fichier par club, chargé à la demande par l'onglet
« Histoire » de la fiche ; la fiche `clubs/<id>.json` ne grossit pas).

Source unique : `match.uefa.com/v5/matches?teamId=<id>` SANS `competitionId` (tous les matchs UEFA du club depuis l'origine,
pagination par 500, langue FR). Aucune valeur n'est devinée : un champ que l'UEFA ne donne pas reste absent, un résultat que les
données ne tranchent pas reste « non déterminé ».

Compétitions (clé = code UEFA de l'API) :
  C1 = UCL (Coupe des clubs champions / Ligue des champions)   C2 = ECWC (Coupe des vainqueurs de coupe)
  C3 = UEL (Coupe UEFA / Ligue Europa)                          LC = UECL (Ligue Conférence)
  SE = SCUP (Supercoupe d'Europe)                               VF = Fairs Cup (Coupe des villes de foires, non UEFA)
  IT = UIC (Coupe Intertoto)                                    IC = EUSA (Coupe intercontinentale, Europe / Amérique du Sud)
Titres « européens » comptés : C1, C2, C3, LC, SE. VF, IT et IC sont listés à part (« autres coupes »).

Règles de calcul (versionnées par `REGLE`, voir `docs/histoire_europeenne.md`) :
  - SAISON : saison européenne = 20 juin -> 19 juin (la Coupe Intertoto, jouée de juin à août, prend l'année du match) (une finale ne tombe jamais après le 19 juin, les premiers tours de qualification
    commencent après le 20 juin). `seasonYear` de l'API n'est PAS utilisé (convention « année de début » jusqu'en 2007, « année de fin »
    ensuite). Deux exceptions documentées : (1) une finale de C1 / C2 / C3 / LC jouée en juillet-septembre (rejouée en septembre 1962,
    août 2020) appartient à la saison précédente ; (2) depuis 2008, un match dont `seasonYear` vaut l'année de DÉBUT de la saison
    calculée par la date appartient à la saison précédente (août 2020, COVID : 8es, quarts, demies de LDC / LE). La Coupe des villes de
    foires (éditions pluriannuelles et finales en septembre) est groupée par `seasonYear`, son libellé vient des dates des matchs.
  - SCORE : `score.total` (prolongation comprise) du point de vue du club ; tirs au but = `score.penalty`. V / N / D sont calculés sur
    le score hors tirs au but (tirs au but : un nul, comme `clubs.vnd`). Un match ni terminé ni neutre (annulé, arrêté, forfait) est
    listé mais exclu du bilan.
  - FINALE ET TITRE : une finale = les matchs du tour « Finale » de l'édition (1 match, 2 manches, ou match rejoué) ; Supercoupe et
    Coupe intercontinentale : tous les matchs de l'édition. Match rejoué : seul le match rejoué décide. Match unique : score, puis tirs
    au but. Deux manches : CUMUL des scores des deux manches (prolongation comprise) ; en cas d'égalité, tirs au but de la 2e manche, puis
    seulement le vainqueur que l'UEFA indique (`winner.aggregate`, avec sa raison : buts à l'extérieur, prolongation, tirs au but,
    tirage au sort), sinon « non déterminé » (`?`). Tout désaccord entre ce calcul et le vainqueur UEFA est consigné dans `ecarts`.
  - PARCOURS : tour atteint = tour le plus avancé (`NIVEAUX`) joué dans l'édition ; meilleur parcours d'une compétition = édition la plus
    haut placée (vainqueur > finaliste > demi-finale > quart > ...) ; l'ordre entre tours numérotés d'autrefois et phases de groupes est
    indicatif (documenté).

Usage :
  python histoire.py --test                     tests purs (fixtures réelles allégées de tools/fixtures/histoire/)
Collecte : `python clubs.py --historique [--clubs id,…] [--depuis AAAA-MM-JJ] [--cache DIR] [--refaire]`.
"""

import argparse
import datetime as dt
import gzip
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import uefa
from netutil import FLAG_CODES, fetch_json, fr, to_number

REGLE = 1                               # version de la règle de calcul (une valeur plus ancienne dans un fichier = à recalculer)
DOSSIER_HISTO = os.path.join("clubs", "historique")
PAUSE_HISTORIQUE = 1.0                  # secondes entre deux requêtes UEFA (politesse ; ~12 Mo pour les plus gros clubs)
JOUR_COUPURE_JUIN = 20                  # début de saison : 20 juin

COMPETITIONS = {"UCL": "C1", "ECWC": "C2", "UEL": "C3", "UECL": "LC", "SCUP": "SE", "Fairs Cup": "VF", "UIC": "IT", "EUSA": "IC"}
# clé -> (nom générique, sigle, titre européen compté ?)
COMP_META = {
    "C1": ("Ligue des champions (Coupe des clubs champions)", "C1", True),
    "C2": ("Coupe des vainqueurs de coupe", "C2", True),
    "C3": ("Ligue Europa (Coupe UEFA)", "C3", True),
    "LC": ("Ligue Conférence", "LC", True),
    "SE": ("Supercoupe d'Europe", "SE", True),
    "VF": ("Coupe des villes de foires", "VF", False),
    "IT": ("Coupe Intertoto", "IT", False),
    "IC": ("Coupe intercontinentale", "IC", False),
}
ORDRE_COMP = ["C1", "C2", "C3", "LC", "SE", "VF", "IT", "IC"]
COMP_FINALE_SEULE_TIE = ("SE", "IC")    # une édition = un seul duel : tous ses matchs forment « la finale »
COMP_CLASSIQUES = ("C1", "C2", "C3", "LC")

# Niveau d'un tour (comparaison entre éditions de formats différents ; indicatif en dessous des quarts de finale).
NIVEAUX = {
    "PRELIMINARY": 1, "FIRST_QUALIFYING": 2, "SECOND_QUALIFYING": 3, "THIRD_QUALIFYING": 4, "QUALIFYING": 4, "PLAY_OFF": 5,
    "FIRST": 10, "SECOND": 20, "THIRD": 30, "FOURTH": 40, "INTERMEDIATE": 42, "REPLAY": 12,
    "FIRST_GROUP_MATCH_STAGE": 35, "GROUP_STANDINGS": 35, "FINAL_TOURNAMENT_PLAY_OFF": 43, "ROUND_OF_32": 45,
    "SECOND_GROUP_MATCH_STAGE": 55, "ROUND_OF_16": 60, "QUARTER_FINALS": 70, "SEMIFINAL": 80, "FINAL": 90,
}
RAISONS_UEFA = {"WIN_ON_AWAY_GOAL": "buts à l'extérieur", "WIN_ON_EXTRA_TIME": "prolongation", "WIN_ON_SILVER_GOAL": "but en argent",
                "WIN_ON_PENALTIES": "tirs au but", "WIN_ON_TOSS_OF_COIN": "tirage au sort", "WIN_BY_FORFEIT": "forfait"}


# ------------------------------------------------------------------------------
# Saison, noms d'époque
# ------------------------------------------------------------------------------
def debut_saison_date(jour: str) -> int:
    """Année de début de la saison européenne d'une date AAAA-MM-JJ (20 juin -> 19 juin)."""
    y, m, d = int(jour[:4]), int(jour[5:7]), int(jour[8:10])
    return y if (m >= 7 or (m == 6 and d >= JOUR_COUPURE_JUIN)) else y - 1


def libelle_saison(debut: int, fin: Optional[int] = None) -> str:
    """1964 -> « 1964-65 » ; (1955, 1958) -> « 1955-58 » (édition pluriannuelle)."""
    return f"{debut}-{(fin if fin is not None else debut + 1) % 100:02d}"


def debut_saison_match(jour: str, comp: str, tour_type: str, season_year: Optional[int]) -> int:
    """Année de début de la saison d'un match (voir l'en-tête : coupure du 20 juin et deux exceptions documentées)."""
    d = debut_saison_date(jour)
    mois = int(jour[5:7])
    if comp == "IT":
        return int(jour[:4])                           # Coupe Intertoto : jouée de juin à août, qualificative pour la saison qui commence
    if comp in COMP_CLASSIQUES and tour_type == "FINAL" and 7 <= mois <= 9:
        return d - 1                                   # finale rejouée en septembre 1962, finales d'août 2020
    if jour >= "2008-01-01" and comp in COMP_CLASSIQUES and season_year is not None and season_year == d:
        return d - 1                                   # août 2020 : `seasonYear` (année de fin) = année de début de la date
    return d


def nom_epoque(comp: str, debut: int) -> str:
    """Nom que portait la compétition cette saison-là (dérivé de la saison, jamais de l'API qui ne donne que le nom actuel)."""
    if comp == "C1":
        return "Coupe des clubs champions" if debut < 1992 else "Ligue des champions"
    if comp == "C3":
        return "Coupe UEFA" if debut < 2009 else "Ligue Europa"
    return COMP_META[comp][0]


# ------------------------------------------------------------------------------
# Normalisation d'un match brut UEFA
# ------------------------------------------------------------------------------
def _gagnant(bloc: Any) -> Optional[Tuple[str, Optional[str]]]:
    if not isinstance(bloc, dict):
        return None
    return (str(bloc.get("reason") or ""), str(((bloc.get("team") or {}).get("id")) or "") or None)


def _lieu(m: Dict[str, Any]) -> str:
    st = m.get("stadium") or {}
    nom = fr(st.get("translations"), "name")
    ville = fr((st.get("city") or {}).get("translations"), "name")
    return ", ".join(x for x in (nom, ville) if x)


def normaliser_match(m: Dict[str, Any], club_id: str) -> Optional[Dict[str, Any]]:
    """Un match brut -> enregistrement du point de vue du club, ou None (club absent, match à venir / en cours)."""
    h, a = m.get("homeTeam") or {}, m.get("awayTeam") or {}
    dom = str(h.get("id")) == str(club_id)
    if not dom and str(a.get("id")) != str(club_id):
        return None
    statut = m.get("status") or ""
    if statut not in ("FINISHED", "CANCELED", "ABANDONED"):
        return None                                    # UPCOMING / LIVE / POSTPONED : pas encore de résultat
    comp = COMPETITIONS.get(((m.get("competition") or {}).get("code")) or "")
    jour = ((m.get("kickOffTime") or {}).get("date") or "")[:10]
    if not comp or len(jour) != 10:
        return None
    rd = m.get("round") or {}
    meta = rd.get("metaData") or {}
    tour_type = meta.get("type") or ""
    adv_t = a if dom else h
    adv = uefa.team_info(adv_t)
    sy = to_number(m.get("seasonYear"))
    out: Dict[str, Any] = {
        "id": str(m.get("id") or ""), "date": jour, "comp": comp, "sy": int(sy) if sy is not None else None,
        "tour": fr(rd.get("translations"), "name") or meta.get("name") or "", "tour_type": tour_type,
        "type": m.get("type") or "",
        "adv": {"id": adv["id"], "nom": adv["name"], "dr": adv["flag"], "pays": adv["country"]},
        "dom": dom,
    }
    out["neutre"] = (tour_type == "FINAL" and out["type"] in ("SINGLE", "REPLAY")) or tour_type == "REPLAY"   # lieu non précisé par l'UEFA
    if statut != "FINISHED":
        out["statut"] = "annule" if statut == "CANCELED" else "arrete"
        return out
    sc = m.get("score") or {}
    total = sc.get("total") or {}
    if total.get("home") is None or total.get("away") is None:
        out["statut"] = "sans_score"
        return out
    th, ta = int(to_number(total["home"]) or 0), int(to_number(total["away"]) or 0)
    out["pour"], out["contre"] = (th, ta) if dom else (ta, th)
    reg = sc.get("regular") or {}
    if reg.get("home") is not None and reg.get("away") is not None and (to_number(reg["home"]), to_number(reg["away"])) != (th, ta):
        out["ap"] = True                               # prolongation : le score total diffère du temps réglementaire
    pen = sc.get("penalty") or {}
    if pen.get("home") is not None and pen.get("away") is not None:
        ph, pa = int(to_number(pen["home"]) or 0), int(to_number(pen["away"]) or 0)
        out["tab"] = (ph, pa) if dom else (pa, ph)
    w = m.get("winner") or {}
    out["w_match"], out["w_agg"] = _gagnant(w.get("match")), _gagnant(w.get("aggregate"))
    if (out["w_match"] or ("", None))[0] == "WIN_BY_FORFEIT":
        out["statut"] = "forfait"                      # score attribué par l'UEFA : affiché, jamais compté
        out.pop("ap", None)
    if out["tour_type"] == "FINAL" or out["comp"] in COMP_FINALE_SEULE_TIE:
        out["lieu"] = _lieu(m)
    return out


def jouable(r: Dict[str, Any]) -> bool:
    """Match terminé normalement, avec score : compte dans le bilan."""
    return r.get("pour") is not None and not r.get("statut")


# ------------------------------------------------------------------------------
# Finales et titres
# ------------------------------------------------------------------------------
def resoudre_finale(legs: List[Dict[str, Any]], club_id: str) -> Dict[str, Any]:
    """Issue d'une finale (liste de ses matchs, chronologique) du point de vue du club.

    Renvoie {r: V / D / ?, dep (départage), cumul, tab, ecarts[]}. Voir l'en-tête du module pour la règle."""
    legs = sorted(legs, key=lambda x: (x["date"], x["id"]))
    ecarts: List[str] = []
    res: Dict[str, Any] = {"r": "?"}
    if not legs or not all(jouable(x) for x in legs):
        res["pourquoi"] = "match non joué ou sans score"
        return res
    rejoues = [x for x in legs if x.get("type") == "REPLAY" or x.get("tour_type") == "REPLAY"]   # match rejoué / d'appui
    # --- match unique (ou match rejoué : seul lui décide)
    if rejoues or len(legs) == 1:
        dec = rejoues[-1] if rejoues else legs[0]
        if dec["pour"] != dec["contre"]:
            res["r"] = "V" if dec["pour"] > dec["contre"] else "D"
        elif dec.get("tab") and dec["tab"][0] != dec["tab"][1]:
            res["r"], res["dep"] = ("V" if dec["tab"][0] > dec["tab"][1] else "D"), "tirs au but"
        else:
            res["pourquoi"] = "égalité sans tirs au but dans les données"
        w = dec.get("w_match")
        if w and w[1] and res["r"] != "?" and (w[0].startswith("WIN") or w[0] == "DRAW"):
            uefa_r = "V" if w[1] == str(club_id) else "D"
            if uefa_r != res["r"]:
                ecarts.append(f"{dec['date']} : calcul {res['r']} / UEFA {uefa_r}")
        if rejoues:
            res["rejoue"] = True
    # --- deux manches : cumul, puis tirs au but de la 2e manche, puis vainqueur donné par l'UEFA
    elif len(legs) == 2:
        p, c = legs[0]["pour"] + legs[1]["pour"], legs[0]["contre"] + legs[1]["contre"]
        res["cumul"] = [p, c]
        if p != c:
            res["r"] = "V" if p > c else "D"
        else:
            t = legs[1].get("tab")
            w = legs[1].get("w_agg") or legs[0].get("w_agg")
            if t and t[0] != t[1]:
                res["r"], res["dep"] = ("V" if t[0] > t[1] else "D"), "tirs au but"
            elif w and w[1]:
                res["r"] = "V" if w[1] == str(club_id) else "D"
                res["dep"] = RAISONS_UEFA.get(w[0], "règle UEFA")
            else:
                res["pourquoi"] = "égalité au cumul sans départage dans les données"
        w = legs[1].get("w_agg") or legs[0].get("w_agg")
        if w and w[1] and res["r"] != "?":
            uefa_r = "V" if w[1] == str(club_id) else "D"
            if uefa_r != res["r"]:
                ecarts.append(f"{legs[1]['date']} : calcul {res['r']} / UEFA {uefa_r}")
    else:
        res["pourquoi"] = f"{len(legs)} matchs dans la finale (cas non prévu)"
    if ecarts:
        res["ecarts"] = ecarts
    return res


def _manche(x: Dict[str, Any]) -> List[Any]:
    """[date, lieu (0 ext, 1 dom, 2 non précisé), pour, contre, tab pour, tab contre, prolongation]"""
    sortie: List[Any] = [x["date"], 2 if x["neutre"] else (1 if x["dom"] else 0), x["pour"], x["contre"]]
    if x.get("tab"):
        sortie += [x["tab"][0], x["tab"][1]]
    elif x.get("ap"):
        sortie += [None, None]
    if x.get("ap"):
        sortie.append(1)
    return sortie


# ------------------------------------------------------------------------------
# Éditions
# ------------------------------------------------------------------------------
def niveau_tour(tour_type: str) -> int:
    return NIVEAUX.get(tour_type, 0)


def construire_editions(recs: List[Dict[str, Any]], club_id: str, noms: Optional[List[str]] = None, tours: Optional[List[str]] = None,
                        adv: Optional[Dict[str, List[str]]] = None) -> Tuple[List[Dict[str, Any]], List[str], List[str], Dict[str, Any]]:
    """Regroupe les matchs en éditions (saison × compétition) et résout les finales.
    `noms` / `tours` / `adv` : index déjà existants d'un fichier (mise à jour : on n'y ajoute que ce qui manque).

    Renvoie (éditions, noms d'époque, noms de tours, adversaires). Chaque match d'une édition = [date, tour, adv, lieu, pour, contre, extra]
    (`tour` = index dans `tours`, `adv` = identifiant, `lieu` 0 ext / 1 dom / 2 non précisé ; `extra` seulement s'il y a des tirs au but,
    une prolongation, un statut spécial)."""
    groupes: Dict[Tuple[str, Any], List[Dict[str, Any]]] = {}
    for r in recs:
        if r["comp"] == "VF":
            cle = ("VF", r["sy"])
        else:
            cle = (r["comp"], debut_saison_match(r["date"], r["comp"], r["tour_type"], r["sy"]))
        groupes.setdefault(cle, []).append(r)
    noms = noms if noms is not None else []
    tours = tours if tours is not None else []
    adv = adv if adv is not None else {}

    def idx(liste: List[str], v: str) -> int:
        if v not in liste:
            liste.append(v)
        return liste.index(v)

    editions: List[Dict[str, Any]] = []
    for (comp, deb), ms in groupes.items():
        ms.sort(key=lambda x: (x["date"], x["id"]))
        if comp == "VF":
            # édition pluriannuelle : début = saison du 1er match ; fin = `seasonYear` (année de la finale) ou année d'un match de fin de saison
            d0 = debut_saison_date(ms[0]["date"])
            fin = max([int(deb or 0)] + [int(x["date"][:4]) for x in ms if int(x["date"][5:7]) <= 6])
            etiquette = libelle_saison(d0, fin if fin > d0 + 1 else None)
            debut = d0
        else:
            debut = int(deb)
            etiquette = libelle_saison(debut)
        ed: Dict[str, Any] = {"s": etiquette, "c": comp, "n": idx(noms, nom_epoque(comp, debut))}
        # finale
        if comp in COMP_FINALE_SEULE_TIE:
            legs = list(ms)
        else:
            legs = [x for x in ms if x["tour_type"] == "FINAL"]
        if legs:
            f = resoudre_finale(legs, club_id)
            dernier = legs[-1]
            fin_d: Dict[str, Any] = {"r": f["r"], "adv": dernier["adv"]["id"], "m": [_manche(x) for x in legs]}
            for k in ("dep", "cumul", "pourquoi", "rejoue"):
                if k in f:
                    fin_d[k] = f[k]
            lieu = dernier.get("lieu")
            if lieu:
                fin_d["lieu"] = lieu
            if f.get("ecarts"):
                fin_d["ecarts"] = f["ecarts"]
            ed["f"] = fin_d
        # tour atteint : le plus avancé joué (match terminé), à défaut le dernier match
        joues = [x for x in ms if x.get("statut") not in ("annule",)] or ms
        haut = max(joues, key=lambda x: (niveau_tour(x["tour_type"]), x["date"]))
        ed["t"] = idx(tours, haut["tour"])
        ed["nv"] = niveau_tour(haut["tour_type"])
        if "f" in ed and ed["f"]["r"] in ("V", "D"):
            ed["i"] = ed["f"]["r"]
        elif "f" in ed:
            ed["i"] = "?"
        matchs = []
        for x in ms:
            adv.setdefault(x["adv"]["id"], [x["adv"]["nom"], x["adv"]["dr"], x["adv"]["pays"]])
            ligne: List[Any] = [x["date"], idx(tours, x["tour"]), x["adv"]["id"],
                                2 if x["neutre"] else (1 if x["dom"] else 0), x.get("pour"), x.get("contre")]
            extra: Dict[str, Any] = {}
            if x.get("tab"):
                extra["tab"] = list(x["tab"])
            if x.get("ap"):
                extra["ap"] = 1
            if x.get("statut"):
                extra["st"] = x["statut"]
            if extra:
                ligne.append(extra)
            matchs.append(ligne)
        ed["m"] = matchs
        editions.append(ed)
    editions.sort(key=lambda e: (e["m"][0][0], ORDRE_COMP.index(e["c"])))
    return editions, noms, tours, adv


# ------------------------------------------------------------------------------
# Dérivés : bilan, meilleurs parcours, palmarès
# ------------------------------------------------------------------------------
def bilan_par_competition(editions: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    """J / V / N / D / buts pour / contre par compétition (matchs terminés normalement : ni annulé, ni arrêté, ni forfait) + nombre
    d'éditions jouées. Calculé sur les lignes de matchs des éditions (tirs au but : un nul)."""
    out: Dict[str, Dict[str, int]] = {}
    for e in editions:
        b = out.setdefault(e["c"], {"ed": 0, "j": 0, "v": 0, "n": 0, "d": 0, "bp": 0, "bc": 0})
        b["ed"] += 1
        for m in e["m"]:
            if m[4] is None or (len(m) > 6 and m[6].get("st")):
                continue
            b["j"] += 1
            b["bp"] += m[4]
            b["bc"] += m[5]
            b["v" if m[4] > m[5] else "d" if m[4] < m[5] else "n"] += 1
    return out


def issue_edition(e: Dict[str, Any]) -> Tuple[int, str]:
    """(niveau comparable, code) : 100 = vainqueur, 90 = finaliste, sinon niveau du tour atteint."""
    if e.get("i") == "V":
        return 100, "V"
    if e.get("i") == "D":
        return 90, "F"
    return e.get("nv", 0), "T"


def meilleurs_parcours(editions: List[Dict[str, Any]], tours: List[str]) -> Dict[str, Dict[str, Any]]:
    """Par compétition : {lib, niv, s: [saisons à ce niveau]}. Les éditions en cours comptent (tour atteint à ce jour)."""
    out: Dict[str, Dict[str, Any]] = {}
    for e in editions:
        niv, code = issue_edition(e)
        cur = out.get(e["c"])
        if cur is None or niv > cur["niv"]:
            lib = "Vainqueur" if code == "V" else "Finaliste" if code == "F" else tours[e["t"]]
            out[e["c"]] = {"lib": lib, "niv": niv, "s": [e["s"]]}
        elif niv == cur["niv"]:
            cur["s"].append(e["s"])
    return out


def palmares(editions: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    """Finales jouées par compétition : {V, D, ?} (V = titres)."""
    out: Dict[str, Dict[str, int]] = {}
    for e in editions:
        f = e.get("f")
        if not f:
            continue
        p = out.setdefault(e["c"], {"V": 0, "D": 0, "?": 0})
        p[f["r"]] += 1
    return out


# ------------------------------------------------------------------------------
# Fichier d'un club
# ------------------------------------------------------------------------------
def maintenant_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def debut_saison_courante(aujourdhui: Optional[dt.date] = None) -> int:
    return debut_saison_date((aujourdhui or dt.date.today()).isoformat())


def enregistrements(matchs_bruts: List[Dict[str, Any]], club_id: str) -> List[Dict[str, Any]]:
    """Matchs bruts UEFA -> enregistrements normalisés du club, sans doublon, chronologiques."""
    recs: Dict[str, Dict[str, Any]] = {}
    for m in matchs_bruts:
        r = normaliser_match(m, club_id)
        if r and r["id"] not in recs:
            recs[r["id"]] = r
    return sorted(recs.values(), key=lambda x: (x["date"], x["id"]))


def construire_historique(club_id: str, matchs_bruts: List[Dict[str, Any]], aujourdhui: Optional[dt.date] = None,
                          maintenant: Optional[str] = None) -> Dict[str, Any]:
    """Fichier compact d'un club à partir de TOUS ses matchs bruts UEFA."""
    liste = enregistrements(matchs_bruts, club_id)
    editions, noms, tours, adv = construire_editions(liste, club_id)
    return assembler(club_id, editions, noms, tours, adv, liste[0]["date"] if liste else None, debut_saison_courante(aujourdhui), maintenant)


def assembler(club_id: str, editions: List[Dict[str, Any]], noms: List[str], tours: List[str], adv: Dict[str, List[str]],
              depuis: Optional[str], debut_courant: Optional[int], maintenant: Optional[str] = None) -> Dict[str, Any]:
    """Document final : éditions triées, édition en cours signalée (`ec`), dérivés (bilan, meilleurs parcours, palmarès)."""
    editions.sort(key=lambda e: (e["m"][0][0], ORDRE_COMP.index(e["c"])))
    for e in editions:
        e.pop("ec", None)
        if debut_courant is not None and int(e["s"][:4]) == debut_courant:
            e["ec"] = 1
    doc: Dict[str, Any] = {
        "id": str(club_id), "regle": REGLE, "maj": maintenant or maintenant_iso(),
        "source": "UEFA (match.uefa.com, matchs du club toutes compétitions)",
        "depuis": depuis,
        "comp": {c: {"nom": COMP_META[c][0], "court": COMP_META[c][1], "titre": COMP_META[c][2]}
                 for c in ORDRE_COMP if any(e["c"] == c for e in editions)},
        "noms": noms, "tours": tours, "adv": adv, "ed": editions,
        "bilan": bilan_par_competition(editions),
        "meilleurs": meilleurs_parcours(editions, tours),
        "pal": palmares(editions),
    }
    ecarts = [f"{e['s']} {e['c']} : {x}" for e in editions for x in (e.get("f") or {}).get("ecarts", [])]
    if ecarts:
        doc["ecarts"] = ecarts
    return doc


# ------------------------------------------------------------------------------
# Lecture / écriture, collecte
# ------------------------------------------------------------------------------
def chemin_club(club_id: str, dossier: str = DOSSIER_HISTO) -> str:
    return os.path.join(dossier, f"{club_id}.json")


def lire(chemin: str) -> Any:
    try:
        with open(chemin, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def ecrire(chemin: str, doc: Dict[str, Any]) -> bool:
    """JSON compact ; n'écrit que si le contenu (hors `maj`) change. Vrai si le fichier a été (ré)écrit."""
    ancien = lire(chemin)
    if ancien is not None and {k: v for k, v in ancien.items() if k != "maj"} == {k: v for k, v in doc.items() if k != "maj"}:
        return False
    os.makedirs(os.path.dirname(chemin) or ".", exist_ok=True)
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n")
    return True


def telecharger_matchs(club_id: str, depuis: Optional[str] = None, cache: Optional[str] = None,
                       pause: float = PAUSE_HISTORIQUE) -> Optional[List[Dict[str, Any]]]:
    """Tous les matchs UEFA d'un club (pagination par 500) ; `depuis` = date AAAA-MM-JJ (mise à jour de la saison courante).
    `cache` : dossier où le JSON brut (gzip) est gardé HORS du dépôt et relu s'il existe. None = page illisible (jamais une liste tronquée)."""
    chemin = os.path.join(cache, f"{club_id}{'_' + depuis if depuis else ''}.json.gz") if cache else None
    if chemin and os.path.exists(chemin):
        with gzip.open(chemin, "rt", encoding="utf-8") as f:
            return json.load(f)
    out: List[Dict[str, Any]] = []
    for offset in range(0, 10000, 500):
        url = f"https://match.uefa.com/v5/matches?teamId={club_id}&offset={offset}&limit=500&order=ASC&language=FR"
        if depuis:
            url += f"&fromDate={depuis}&toDate={dt.date.today().year + 2}-01-01"
        data = fetch_json(url)
        if not isinstance(data, list):
            return None
        out.extend(data)
        time.sleep(pause)                                # politesse : une pause après chaque requête
        if len(data) < 500:
            break
    if chemin:
        os.makedirs(cache, exist_ok=True)
        with gzip.open(chemin, "wt", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False)
    return out


def fusionner_saison(ancien: Dict[str, Any], club_id: str, nouveaux_bruts: List[Dict[str, Any]], aujourdhui: Optional[dt.date] = None,
                     maintenant: Optional[str] = None) -> Dict[str, Any]:
    """Mise à jour de la saison courante : les éditions présentes dans `nouveaux_bruts` (matchs depuis le début de la saison) REMPLACENT
    celles du fichier ; les autres sont conservées telles quelles (finales comprises : les matchs passés ne changent pas)."""
    nouv = enregistrements(nouveaux_bruts, club_id)
    noms, tours, adv = list(ancien.get("noms") or []), list(ancien.get("tours") or []), dict(ancien.get("adv") or {})
    ed_nouv, noms, tours, adv = construire_editions(nouv, club_id, noms, tours, adv)
    cles = {(e["c"], e["s"]) for e in ed_nouv}
    conserves = [e for e in ancien.get("ed", []) if (e["c"], e["s"]) not in cles]
    return assembler(club_id, conserves + ed_nouv, noms, tours, adv, ancien.get("depuis"), debut_saison_courante(aujourdhui), maintenant)


def collecter(ids: List[str], depuis: Optional[str] = None, dossier: str = DOSSIER_HISTO, cache: Optional[str] = None,
              refaire: bool = False, pause: float = PAUSE_HISTORIQUE) -> int:
    """Premier remplissage (ou `--refaire`) : tout l'historique des clubs sans fichier. `depuis` : mise à jour de la saison courante
    pour les clubs qui ont déjà un fichier (les autres : historique complet). 0 = succès, 1 = au moins un club en échec (reprenable)."""
    echecs = ecrits = 0
    for i, cid in enumerate(ids):
        chemin = chemin_club(cid, dossier)
        ancien = lire(chemin)
        complet = refaire or ancien is None or ancien.get("regle", 0) < REGLE
        if not complet and not depuis:
            continue                                                          # reprenable : déjà fait
        bruts = telecharger_matchs(cid, None if complet else depuis, cache, pause)
        if bruts is None:
            print(f"[WARN] Historique du club {cid} : lecture UEFA impossible (sera repris au prochain passage)")
            echecs += 1
            continue
        doc = construire_historique(cid, bruts) if complet else fusionner_saison(ancien, cid, bruts)
        if ecrire(chemin, doc):
            ecrits += 1
        if doc.get("ecarts"):
            print(f"[WARN] Club {cid} : désaccord calcul / UEFA sur une finale : {doc['ecarts']}")
        print(f"[HISTOIRE] {cid} : {sum(len(e['m']) for e in doc['ed'])} matchs, {len(doc['ed'])} éditions ({i + 1}/{len(ids)})")
    print(f"[HISTOIRE] {ecrits} fichier(s) écrit(s), {echecs} échec(s)")
    return 1 if echecs else 0


# ------------------------------------------------------------------------------
# Tests (fixtures réelles allégées : tools/fixtures/histoire/*.json)
# ------------------------------------------------------------------------------
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools", "fixtures", "histoire")


def _fixture(nom: str) -> List[Dict[str, Any]]:
    with open(os.path.join(FIXTURES, nom), "r", encoding="utf-8") as f:
        return json.load(f)


def _tests() -> None:
    # --- saison depuis la date
    assert debut_saison_date("2019-06-01") == 2018 and debut_saison_date("2023-06-10") == 2022
    assert debut_saison_date("2018-06-26") == 2018 and debut_saison_date("1995-06-24") == 1995
    assert debut_saison_date("2026-11-24") == 2026 and debut_saison_date("2027-01-10") == 2026 and debut_saison_date("1964-08-17") == 1964
    assert libelle_saison(1964) == "1964-65" and libelle_saison(1999) == "1999-00" and libelle_saison(1955, 1958) == "1955-58"
    # exceptions : finale de septembre 1962 (rejouée), août 2020 (finale, 8e et quart de finale), mais pas la qualification d'août 2020
    assert debut_saison_match("1962-09-05", "C2", "FINAL", 1962) == 1961
    assert debut_saison_match("2020-08-23", "C1", "FINAL", 2020) == 2019
    assert debut_saison_match("2020-08-08", "C1", "ROUND_OF_16", 2020) == 2019
    assert debut_saison_match("2020-08-19", "C1", "FIRST_QUALIFYING", 2021) == 2020
    assert debut_saison_match("2021-02-16", "C1", "ROUND_OF_16", 2021) == 2020
    assert debut_saison_match("1960-09-28", "C2", "QUARTER_FINALS", 1961) == 1960           # 1er quart de finale de la Coupe des coupes
    assert debut_saison_match("2019-08-14", "SE", "FINAL", 2019) == 2019                   # la Supercoupe n'est jamais déplacée
    assert nom_epoque("C1", 1991) == "Coupe des clubs champions" and nom_epoque("C1", 1992) == "Ligue des champions"
    assert nom_epoque("C3", 2008) == "Coupe UEFA" and nom_epoque("C3", 2009) == "Ligue Europa"

    # --- résolution de finales sur des cas fictifs
    def leg(date, pour, contre, tab=None, typ="SINGLE", wm=None, wa=None, ident=None):
        d = {"id": ident or date, "date": date, "pour": pour, "contre": contre, "type": typ, "w_match": wm, "w_agg": wa}
        if tab:
            d["tab"] = tab
        return d
    assert resoudre_finale([leg("2000-05-01", 2, 1)], "1")["r"] == "V"
    assert resoudre_finale([leg("2000-05-01", 1, 2)], "1")["r"] == "D"
    r = resoudre_finale([leg("2000-05-01", 1, 1, tab=(4, 5))], "1")
    assert r["r"] == "D" and r["dep"] == "tirs au but"
    assert resoudre_finale([leg("2000-05-01", 1, 1)], "1")["r"] == "?"                        # égalité sans tirs au but : non déterminé
    # deux manches : cumul
    r = resoudre_finale([leg("1973-05-10", 3, 0, typ="FIRST_LEG"), leg("1973-05-23", 0, 2, typ="SECOND_LEG")], "1")
    assert r["r"] == "V" and r["cumul"] == [3, 2]
    # deux manches à égalité : départage seulement par les données
    r = resoudre_finale([leg("1970-05-01", 1, 0, typ="FIRST_LEG"), leg("1970-05-08", 0, 1, typ="SECOND_LEG", wa=("WIN_ON_AWAY_GOAL", "2"))], "1")
    assert r["r"] == "D" and r["dep"] == "buts à l'extérieur" and r["cumul"] == [1, 1]
    r = resoudre_finale([leg("1970-05-01", 1, 0, typ="FIRST_LEG"), leg("1970-05-08", 0, 1, typ="SECOND_LEG")], "1")
    assert r["r"] == "?" and "pourquoi" in r
    r = resoudre_finale([leg("1970-05-01", 1, 0, typ="FIRST_LEG"), leg("1970-05-08", 0, 1, tab=(5, 4), typ="SECOND_LEG")], "1")
    assert r["r"] == "V" and r["dep"] == "tirs au but"
    # match rejoué : seul lui décide
    r = resoudre_finale([leg("1974-05-15", 1, 1, ident="a"), leg("1974-05-17", 4, 0, typ="REPLAY", ident="b")], "1")
    assert r["r"] == "V" and r["rejoue"] is True
    # match non joué : non déterminé
    assert resoudre_finale([{"id": "x", "date": "2000-01-01", "statut": "annule"}], "1")["r"] == "?"
    # désaccord calcul / UEFA consigné
    r = resoudre_finale([leg("2000-05-01", 2, 1, wm=("WIN_REGULAR", "2"))], "1")
    assert r["r"] == "V" and r["ecarts"]

    # --- normalisation : forfait, match annulé, match à venir, trois matchs (Coupe intercontinentale avec match d'appui)
    def brut(ident, jour, statut, dom, ext, total=None, winner=None, comp="UCL", rond="FIRST", typ="FIRST_LEG", penalty=None, regular=None):
        m: Dict[str, Any] = {"id": ident, "status": statut, "type": typ, "seasonYear": "1990", "kickOffTime": {"date": jour},
                             "competition": {"code": comp}, "round": {"metaData": {"type": rond, "name": rond}},
                             "homeTeam": {"id": dom, "internationalName": "Dom", "countryCode": "FRA"},
                             "awayTeam": {"id": ext, "internationalName": "Ext", "countryCode": "ESP"}}
        if total:
            m["score"] = {"total": {"home": total[0], "away": total[1]}, "regular": {"home": (regular or total)[0], "away": (regular or total)[1]}}
            if penalty:
                m["score"]["penalty"] = {"home": penalty[0], "away": penalty[1]}
        if winner:
            m["winner"] = winner
        return m
    assert normaliser_match(brut("1", "2020-01-01", "UPCOMING", "1", "2"), "1") is None
    assert normaliser_match(brut("1", "2020-01-01", "FINISHED", "5", "6", (1, 0)), "1") is None                # le club n'y joue pas
    r = normaliser_match(brut("2", "1990-10-10", "CANCELED", "1", "2"), "1")
    assert r["statut"] == "annule" and not jouable(r)
    r = normaliser_match(brut("3", "2011-08-18", "FINISHED", "1", "2", (3, 0), {"match": {"reason": "WIN_BY_FORFEIT", "team": {"id": "1"}}},
                              regular=(0, 0)), "1")
    assert r["statut"] == "forfait" and "ap" not in r and not jouable(r) and r["pour"] == 3                    # score attribué : affiché, jamais compté
    r = normaliser_match(brut("4", "1990-10-10", "FINISHED", "2", "1", (1, 2), regular=(1, 1)), "1")
    assert (r["pour"], r["contre"], r["dom"], r["ap"]) == (2, 1, False, True) and jouable(r)                   # point de vue du club + prolongation
    r = normaliser_match(brut("5", "1990-10-10", "FINISHED", "2", "1", (1, 1), penalty=(3, 4), rond="FINAL", typ="SINGLE"), "1")
    assert r["tab"] == (4, 3) and r["neutre"] is True                                                           # tirs au but orientés vers le club
    ic = [normaliser_match(brut("6", "1964-09-09", "FINISHED", "2", "1", (1, 0), comp="EUSA", rond="FINAL"), "1"),
          normaliser_match(brut("7", "1964-09-23", "FINISHED", "1", "2", (2, 0), comp="EUSA", rond="FINAL", typ="SECOND_LEG"), "1"),
          normaliser_match(brut("8", "1964-09-26", "FINISHED", "1", "2", (1, 0), comp="EUSA", rond="REPLAY", typ="SINGLE"), "1")]
    r = resoudre_finale(ic, "1")
    assert r["r"] == "V" and r.get("rejoue") is True, r                                                          # 3e match d'appui : seul lui décide
    ed, _, _, _ = construire_editions(ic, "1")
    assert len(ed) == 1 and ed[0]["c"] == "IC" and ed[0]["f"]["r"] == "V" and ed[0]["s"] == "1964-65"

    # --- cas réels (fixtures allégées : matchs bruts UEFA, seuls les champs lus par le code sont gardés)
    def finales(doc: Dict[str, Any]) -> Dict[Tuple[str, str], Dict[str, Any]]:
        return {(e["c"], e["s"]): e["f"] for e in doc["ed"] if "f" in e}

    # Liverpool : titres 1977 / 78 / 81 / 84 (tirs au but) / 2005 (tirs au but) / 2019 en C1 ; C3 1973, 1976 (deux manches), 2001 ; SE 1977 (2 manches)
    liv = construire_historique("7889", _fixture("liverpool.json"), aujourdhui=dt.date(2026, 11, 25))
    fl = finales(liv)
    assert [s for (c, s), f in fl.items() if c == "C1" and f["r"] == "V"] == ["1976-77", "1977-78", "1980-81", "1983-84", "2004-05", "2018-19"], fl.keys()
    assert [s for (c, s), f in fl.items() if c == "C1" and f["r"] == "D"] == ["1984-85", "2006-07", "2017-18", "2021-22"]
    assert fl[("C3", "1972-73")]["r"] == "V" and fl[("C3", "1972-73")]["cumul"] == [3, 2]                 # 3-0 puis 0-2
    assert fl[("C3", "1975-76")]["r"] == "V" and fl[("C3", "1975-76")]["cumul"] == [4, 3]                 # 3-2 puis 1-1
    assert fl[("C3", "2000-01")]["r"] == "V" and fl[("C3", "2000-01")]["m"][0][4:7] == [None, None, 1]    # 5-4 après prolongation (but en or)
    assert fl[("C3", "2015-16")]["r"] == "D"
    assert fl[("C1", "1983-84")]["dep"] == "tirs au but" and fl[("C1", "2004-05")]["dep"] == "tirs au but"
    assert fl[("SE", "1977-78")]["r"] == "V" and fl[("SE", "1977-78")]["cumul"] == [7, 1]               # 1-1 puis 6-0
    assert fl[("SE", "1978-79")]["r"] == "D"                                                          # 3-4 au cumul, finale « 1er tour » du fichier UEFA
    assert fl[("SE", "2019-20")]["r"] == "V" and fl[("SE", "2019-20")]["dep"] == "tirs au but"       # 2-2 a.p. puis 5-4 t.a.b. (l'UEFA ne nomme pas le vainqueur)
    assert fl[("IC", "1981-82")]["r"] == "D" and fl[("IC", "1984-85")]["r"] == "D"                    # Coupe intercontinentale : listée, jamais « titre » européen
    assert liv["pal"]["C1"] == {"V": 6, "D": 4, "?": 0} and liv["pal"]["SE"] == {"V": 4, "D": 2, "?": 0}, liv["pal"]
    assert liv["pal"]["IC"] == {"V": 0, "D": 2, "?": 0} and liv["pal"]["C3"] == {"V": 3, "D": 1, "?": 0}
    assert not liv.get("ecarts"), liv.get("ecarts")
    assert liv["meilleurs"]["C1"]["lib"] == "Vainqueur" and liv["meilleurs"]["C1"]["s"][0] == "1976-77"
    assert liv["comp"]["C1"]["titre"] is True and liv["comp"]["IC"]["titre"] is False
    # saison courante signalée, matchs à venir absents
    cour = [e for e in liv["ed"] if e.get("ec")]
    assert cour and all(e["s"] == "2026-27" for e in cour)
    assert all(m[0] <= "2026-11-25" for e in liv["ed"] for m in e["m"])

    # Bayern : finale 1974 à rejouer (1-1 a.p. puis 4-0), titre sur le match rejoué
    bay = construire_historique("50037", _fixture("bayern.json"), aujourdhui=dt.date(2026, 11, 25))
    f74 = finales(bay)[("C1", "1973-74")]
    assert f74["r"] == "V" and f74.get("rejoue") and len(f74["m"]) == 2 and f74["m"][1][2:4] == [4, 0]
    assert finales(bay)[("C1", "2000-01")]["r"] == "V" and finales(bay)[("C1", "2000-01")]["dep"] == "tirs au but"
    # COVID : les matchs d'août 2020 sont dans l'édition 2019-20, la finale du 23/08/2020 aussi
    assert finales(bay)[("C1", "2019-20")]["r"] == "V" and finales(bay)[("C1", "2019-20")]["m"][0][0] == "2020-08-23"
    e2020 = [e for e in bay["ed"] if e["c"] == "C1" and e["s"] == "2019-20"][0]
    assert any(m[0] == "2020-02-25" for m in e2020["m"]) and any(m[0] == "2020-08-14" for m in e2020["m"])

    # Marseille : C1 1993 (1-0 contre Milan), Supercoupe / Coupe intertoto absentes, finale de 1991 perdue aux tirs au but
    om = construire_historique("52748", _fixture("marseille.json"), aujourdhui=dt.date(2026, 11, 25))
    fo = finales(om)
    assert fo[("C1", "1992-93")]["r"] == "V" and fo[("C1", "1992-93")]["m"][0][2:4] == [1, 0]
    assert fo[("C1", "1990-91")]["r"] == "D" and fo[("C1", "1990-91")]["dep"] == "tirs au but"
    assert fo[("C3", "1998-99")]["r"] == "D" and fo[("C3", "2003-04")]["r"] == "D" and fo[("C3", "2017-18")]["r"] == "D"
    assert om["pal"]["C1"] == {"V": 1, "D": 1, "?": 0}

    # PSG : Coupe des vainqueurs de coupe 1995-96 (1-0 contre Rapid Vienne), finales perdues 1996-97 ; édition en cours
    psg = construire_historique("52747", _fixture("psg.json"), aujourdhui=dt.date(2026, 11, 25))
    fp = finales(psg)
    assert fp[("C2", "1995-96")]["r"] == "V" and fp[("C2", "1995-96")]["m"][0][2:4] == [1, 0]
    assert fp[("C2", "1996-97")]["r"] == "D" and fp[("C1", "2019-20")]["r"] == "D" and fp[("C1", "2024-25")]["r"] == "V"
    assert psg["pal"]["C2"] == {"V": 1, "D": 1, "?": 0} and psg["pal"]["IT"] == {"V": 1, "D": 0, "?": 0}
    assert [e["s"] for e in psg["ed"] if e["c"] == "IT"] == ["2001-02"]                     # Intertoto d'août 2001 : saison de l'année du match
    assert finales(psg)[("SE", "1996-97")]["cumul"] == [2, 9] and finales(psg)[("SE", "1996-97")]["r"] == "D"

    # Real Madrid : cinq premières C1 de suite 1955-56 -> 1959-60, toutes gagnées (match unique) ; 14 titres au total jusqu'en 2024
    rm = construire_historique("50051", _fixture("real_madrid.json"), aujourdhui=dt.date(2026, 11, 25))
    fr_ = finales(rm)
    assert [s for (c, s), f in fr_.items() if c == "C1" and f["r"] == "V"][:5] == ["1955-56", "1956-57", "1957-58", "1958-59", "1959-60"]
    assert rm["pal"]["C1"] == {"V": 15, "D": 3, "?": 0} and rm["pal"]["SE"] == {"V": 6, "D": 3, "?": 0}, rm["pal"]
    assert rm["pal"]["IC"] == {"V": 3, "D": 2, "?": 0} and rm["pal"]["C3"] == {"V": 2, "D": 0, "?": 0} and rm["pal"]["C2"] == {"V": 0, "D": 2, "?": 0}
    assert fr_[("C2", "1970-71")]["cumul"] == [2, 3] and fr_[("C2", "1970-71")]["r"] == "D"      # finale 1971 : 1-1 a.p. puis rejouée 1-2
    assert rm["meilleurs"]["C1"]["lib"] == "Vainqueur" and len(rm["meilleurs"]["C1"]["s"]) == 15

    # Barcelone : Coupe des villes de foires, éditions pluriannuelles (1955-58), finales à deux manches, finale de 1966 gagnée
    bar = construire_historique("50080", _fixture("barcelone.json"), aujourdhui=dt.date(2026, 11, 25))
    fb = finales(bar)
    assert fb[("VF", "1955-58")]["r"] == "V" and fb[("VF", "1955-58")]["cumul"] == [8, 2]
    assert fb[("VF", "1958-60")]["r"] == "V" and fb[("VF", "1958-60")]["cumul"] == [4, 1]
    assert fb[("VF", "1961-62")]["r"] == "D" and fb[("VF", "1961-62")]["cumul"] == [3, 7]        # finale jouée en septembre 1962 : édition 1961-62
    assert fb[("VF", "1965-66")]["r"] == "V" and fb[("VF", "1965-66")]["cumul"] == [4, 3]
    assert [e["s"] for e in bar["ed"] if e["c"] == "VF"][:4] == ["1955-58", "1958-60", "1960-61", "1961-62"]
    assert bar["comp"]["VF"]["titre"] is False

    # Un club sans titre : pas de finale, parcours du meilleur tour atteint, bilan
    pt = construire_historique("88148", _fixture("petit_club.json"), aujourdhui=dt.date(2026, 11, 25))
    assert pt["pal"] == {} and pt["ed"] and all("f" not in e for e in pt["ed"])
    b = pt["bilan"]
    assert all(v["j"] == v["v"] + v["n"] + v["d"] for v in b.values())

    # Bilan = somme des matchs terminés ; tirs au but = nul
    tot = {"j": 0, "v": 0, "n": 0, "d": 0}
    for v in liv["bilan"].values():
        for k in tot:
            tot[k] += v[k]
    jou = [m for e in liv["ed"] for m in e["m"] if m[4] is not None and not (len(m) > 6 and m[6].get("st"))]
    assert tot["j"] == len(jou) and tot["v"] + tot["n"] + tot["d"] == tot["j"]

    # Fusion de la saison courante : les éditions anciennes sont conservées, l'édition courante remplacée
    brut = _fixture("liverpool.json")
    ancien = construire_historique("7889", [m for m in brut if (m.get("kickOffTime") or {}).get("date", "") < "2026-10-01"],
                                   aujourdhui=dt.date(2026, 10, 1))
    maj = fusionner_saison(ancien, "7889", [m for m in brut if (m.get("kickOffTime") or {}).get("date", "") >= "2026-06-20"],
                           aujourdhui=dt.date(2026, 11, 25))
    complet = construire_historique("7889", brut, aujourdhui=dt.date(2026, 11, 25))
    assert [(e["c"], e["s"], len(e["m"])) for e in maj["ed"]] == [(e["c"], e["s"], len(e["m"])) for e in complet["ed"]]
    assert maj["pal"] == complet["pal"] and maj["bilan"] == complet["bilan"] and maj["meilleurs"] == complet["meilleurs"]
    # un match = une ligne [date, tour, adversaire, lieu, pour, contre(, extra)] : le fichier reste compact
    assert all(len(m) in (6, 7) for e in complet["ed"] for m in e["m"])
    print("histoire.py : tests OK")


def main() -> None:
    p = argparse.ArgumentParser(description="Historique européen des clubs")
    p.add_argument("--test", action="store_true")
    a = p.parse_args()
    if a.test:
        _tests()
        return
    p.error("la collecte se lance par `python clubs.py --historique` ; ici seulement --test")


if __name__ == "__main__":
    main()
