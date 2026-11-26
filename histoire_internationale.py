#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Historique des compétitions internationales : RÉSULTATS SEULS de toutes les éditions (décision du propriétaire du 26/11/2026 :
fiches de match complètes réservées aux éditions récentes, voir `run_internationales.py`), palmarès et bilans CALCULÉS.
Étude et règles : docs/etude_internationales.md § 10. Même philosophie que `histoire.py` (clubs) : rien n'est deviné, un champ
absent reste absent, un résultat que les données ne tranchent pas vaut `?` (« non déterminé »).

Sources (mesurées le 26/11/2026, sans clé) :
  - FIFA (`api.fifa.com/api/v3`) : Coupe du monde `cdm` (compétition 17, 23 éditions depuis 1930, phase finale seulement),
    Coupe du monde des clubs `cdmc` (107 « … des Clubs » 2000-2023 + 10005 en 2025), Coupe intercontinentale `ci` (107, 2024-2026).
  - UEFA (`match.uefa.com/v5/matches?competitionId=…&seasonYear=…`) : Euro `euro` (3, depuis 1960, phase finale ET éliminatoires),
    Ligue des nations `ldn` (2014, depuis 2019). `seasonYear` = édition NOMINALE (Euro 2020 joué en 2021 : 2020 ; Ligue des
    nations 2020-21 : 2021).

`ResultType` FIFA (vérifié sur des cas connus) : 1 = temps réglementaire (finale 1998, 2018) ; 2 = tirs au but (finales 1994, 2006,
2022) ; 3 = prolongation (finales 2010, 1966, 1978) ; 8 = but en or / mort subite (1998 France - Paraguay, 2002 Sénégal - Suède,
Corée - Italie, Sénégal - Turquie). Le score FIFA est le score APRÈS prolongation, tirs au but exclus (`HomeTeamPenaltyScore` : 0 / 0
quand il n'y en a pas, d'où le test sur `ResultType`).

Format (donnees-football, `internationales/historique/`) :
  <comp>.json   {comp, nom, source, regle, maj, editions: [ED]} ; ED = {edition, libelle, hote?: [code], vainqueur?, finaliste?,
                troisieme?, regle?: "poule_finale", poule_finale?: [[code, j, v, n, d, bp, bc, pts]], ecarts?: [texte],
                pourquoi?, avertissement?, en_cours?: true, equipes: {code: [nom, drapeau]}, tours: [libellé], groupes: [libellé], matchs: [M]}
                `vainqueur` / `finaliste` / `troisieme` = code d'équipe, ou "?" (non déterminé). Absents : édition sans finale
                jouée (en cours), 3e place sans match, hôte absent de la source.
                M = [date, phase, tour, groupe, dom, ext, sd, se, tabd, tabe, statut, id, dp, rj]
                  date   jour UTC AAAA-MM-JJ du coup d'envoi ;
                  phase  "q" éliminatoires / barrages, "g" phase de groupes (ou de ligue), "f" élimination directe ;
                  tour   index dans `tours` ; groupe : index dans `groupes` ou null ;
                  dom, ext   codes d'équipe (null = place à déterminer) ; « dom » est l'équipe nommée en premier par la source
                         (pas un lieu : la plupart des finales sont en terrain neutre) ;
                  sd, se score APRÈS prolongation (tirs au but exclus), null si non joué ; tabd, tabe tirs au but ou null ;
                  statut "T" terminé, "A" annulé, "R" arrêté / abandonné, "F" forfait (score attribué), "P" reporté,
                         "V" à venir, "C" en cours, "X" statut inconnu ; seuls les "T" comptent aux bilans ;
                  id     identifiant source ("fifa:<IdMatch>" / "uefa:<id>") ;
                  dp     "ap" prolongation, "bo" but en or, null sinon ; rj 1 = match rejoué (finale de l'Euro 1968), sinon null.
  equipes/<code>.json  {code, nom, drapeau, club?, pays?, maj, bilans: {comp: {finale: B, elim?: B, titres, finales, meilleur}},
                palmares: [{comp, edition, rang: V|F|3}], tours, adv: {code: [nom, drapeau]}, matchs: {comp: [[date, édition, tour,
                adversaire, pour, contre, tab pour, tab contre, dp, statut]]}} ; B = {ed, j, v, n, d, bp, bc, ntv, ntd} (n = nuls,
                dont ntv gagnés et ntd perdus aux tirs au but) ; `finale` = phase de groupes + élimination directe, `elim` =
                éliminatoires / barrages ; `matchs` : phase finale seulement.
  index.json    {maj, competitions: {comp: {nom, court, famille, editions, vainqueurs: [{edition, code}], en_cours?}},
                equipes: {code: {nom, drapeau, titres: {comp: n}, club?}}}
  etat.json     {regle, maj, comps: {comp: {editions, en_cours: [édition], restantes: [édition]}}}

Règles de calcul (versionnées : REGLE) :
  - Édition = vainqueur de la FINALE : match unique = score, puis tirs au but ; match rejoué = le rejoué décide ; égalité sans tirs
    au but = « ? ». Le vainqueur donné par la source (`Winner` FIFA, `winner.match.team` UEFA) CONTRÔLE le calcul : tout désaccord
    est consigné dans `ecarts` et le vainqueur vaut « ? » ; une source muette ne change rien.
  - Édition sans finale (Coupe du monde 1950 : « Tour final » en poule) : vainqueur = premier de la poule finale calculée avec la
    règle de l'époque (2 points la victoire avant 1994, 3 ensuite ; aucun départage) SEULEMENT s'il est seul à avoir le maximum ;
    finaliste = 2e seulement si son total est unique ; troisième absent (`regle: "poule_finale"`).
  - Troisième = vainqueur du match pour la 3e place s'il existe, sinon absent. Hôte = `HostTeams` FIFA (équipe dans l'édition) ;
    absent pour l'UEFA (les pays des stades actuels ne sont pas ceux de l'époque : Yougoslavie 1976).
  - Matchs annulés / arrêtés / forfaits / à venir : listés, jamais comptés. Pays disparus : code d'ÉPOQUE de la source (URS, FRG, GDR,
    TCH, YUG, SCG, ZAI, INH, CIS), jamais un drapeau de pays successeur (drapeau vide).
  - Éliminatoires de l'Euro : phase UEFA `QUALIFYING` ET, de 1960 à 1976, les huitièmes / quarts de finale à deux manches (classés
    « TOURNAMENT » par l'UEFA, mais ce sont des éliminatoires : la phase finale ne compte que 4 équipes) ; la phase finale = groupes,
    demi-finales, match pour la 3e place, finale.
  - Meilleur parcours : tour le plus avancé de la phase finale selon `NIVEAUX` (ordre indicatif entre formats d'époque) ; vainqueur >
    finaliste > troisième > tour atteint.

Usage :
  python histoire_internationale.py --donnees DIR [--comps cdm,euro,…] [--budget-min N] [--cache DIR] [--relire]
  python histoire_internationale.py --test                       tests purs (fixtures réelles allégées, sans réseau)
Reprenable : une édition écrite, passée et finie n'est plus relue (`--relire` pour forcer) ; une édition en cours est relue à chaque
passage ; panne / liste illisible = rien n'est remplacé ; écriture seulement si le contenu change (hors `maj`).
"""

import argparse
import gzip
import json
import os
import re
import sys
import time
import unicodedata
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import internationales as I
import uefa
from netutil import FLAG_CODES, fetch_json, fr
from run_ligues import _lire, ecrire_si_change

REGLE = 1
DOSSIER = os.path.join("internationales", "historique")
PAUSE_S = 0.3                       # politesse entre deux requêtes (FIFA et UEFA)
PAUSE_ENTRE_ED = 0.0
FLAGS_COMPLEMENT = {"KUW": "kw", "PRK": "kp", "PNG": "pg"}   # pays existants absents de netutil.FLAG_CODES (codes FIFA ; drapeaux flagcdn)

# Source et identifiants par compétition (noms, familles : internationales.COMPETITIONS)
SOURCES: Dict[str, Dict[str, Any]] = {
    "cdm": {"source": "FIFA", "fifa": [17], "motif": ""},
    "euro": {"source": "UEFA", "uefa": 3, "premiere": 1960, "pas": 4, "deux_manches_q": True},
    "ldn": {"source": "UEFA", "uefa": 2014, "premiere": 2019, "pas": 2},
    "cdmc": {"source": "FIFA", "fifa": [107, 10005], "motif": "clubs"},
    "ci": {"source": "FIFA", "fifa": [107], "motif": "intercontinentale"},
}
ORDRE_COMPS = ["cdm", "euro", "ldn", "cdmc", "ci"]

# Niveau d'un tour de phase finale par compétition (comparaison entre éditions de formats différents : INDICATIF ; un libellé absent de
# la table vaut 0 et est signalé par le journal). 10 groupes, 20-45 tours intermédiaires, 50 quarts, 60 demi-finales, 70 finale.
NIVEAUX: Dict[str, Dict[str, int]] = {
    "cdm": {"Phase de groupes": 10, "Deuxième tour": 45, "Seizièmes de finale": 30, "Compétition préliminaire": 40, "1er tour": 40,
            "Huitièmes de finale": 40, "Quarts de finale": 50, "Tour final": 60, "Demi-finales": 60,
            "Match pour la 3e place": 59, "Finale": 70},
    "euro": {"Phase de groupes": 10, "Huitièmes de finale": 40, "Quarts de finale": 50, "Demi-finales": 60,
             "Match pour la 3e place": 59, "Finale": 70},
    "ldn": {"Phase de groupes": 10, "Phase de ligue": 10, "Quarts de finale": 50, "Demi-finales": 60,
            "Match pour la 3e place": 59, "Finale": 70},
    "cdmc": {"Phase de groupes": 10, "1er tour": 30, "Match de barrage pour le quart de finale": 30, "Huitièmes de finale": 40,
             "2e tour": 50, "Quarts de finale": 50, "Match pour la 5e place": 49, "Demi-finales": 60,
             "Match pour la 3e place": 59, "Finale": 70},
    "ci": {"Barrage Afrique-Asie-Pacifique": 10, "Coupe Afrique-Asie-Pacifique": 20, "Derby des Amériques": 20,
           "Challenger Cup": 30, "Finale": 40},
}
NIV_VAINQUEUR, NIV_FINALISTE, NIV_TROISIEME = 100, 90, 85
LIB_NIVEAU = {NIV_VAINQUEUR: "Vainqueur", NIV_FINALISTE: "Finaliste", NIV_TROISIEME: "3e place"}
TOURS_INCONNUS: set = set()         # (comp, libellé) rencontrés sans niveau : à lire dans le journal

# Libellés de tour ramenés à ceux de l'UEFA / de la page (même tour = même libellé)
TOURS_FIFA_FR = dict(I.TOURS_FIFA_FR)
TOURS_FIFA_FR.update({"Matches de groupes": "Phase de groupes", "Group Stage": "Phase de groupes",
                      "Premier tour": "1er tour", "Deuxième tour": "Deuxième tour",
                      "Match pour la cinquième place": "Match pour la 5e place", "5e place": "Match pour la 5e place"})
TOURS_FIFA_FR_CLUBS = {"Deuxième tour": "2e tour"}      # Coupe du monde des clubs 2016 : « Deuxième tour » = notre « 2e tour »
REGLES_TOUR_CI = [(r"intercontinental cup \d{4} final|^finale\b", "Finale"),
                  (r"challenger cup", "Challenger Cup"),
                  (r"derby (des amériques|of the americas)", "Derby des Amériques"),
                  (r"barrage afrique|african-asian-pacific play-?off", "Barrage Afrique-Asie-Pacifique"),
                  (r"coupe afrique-asie|african-asian-pacific cup", "Coupe Afrique-Asie-Pacifique")]
TOURS_UEFA_FR = {"Phase de groupes - phase finale": "Phase de groupes", "Phase de ligues": "Phase de ligue"}
STATUT_UEFA = {"FINISHED": "T", "CANCELED": "A", "CANCELLED": "A", "ABANDONED": "R", "POSTPONED": "P", "UPCOMING": "V"}
# MatchStatus FIFA : 0 terminé, 1 / 12 à venir, 3 en cours, 4 abandonné, 7 reporté, 8 annulé ; 9 vu UNE fois (Coupe du monde des clubs 2020,
# Al Duhail - Auckland City 3-0 : Auckland s'est retiré) = forfait, listé et jamais compté ; toute autre valeur = « X » (inconnu, jamais compté)
STATUT_FIFA = {0: "T", 1: "V", 3: "C", 4: "R", 7: "P", 8: "A", 9: "F", 12: "V"}


# ------------------------------------------------------------------------------
# Outils
# ------------------------------------------------------------------------------
def _sans_accents(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def drapeau(pays: str) -> str:
    """Code flagcdn d'un pays ACTUEL ; vide pour un pays disparu ou inconnu (jamais le drapeau d'un successeur)."""
    p = (pays or "").upper()
    return FLAG_CODES.get(p) or FLAGS_COMPLEMENT.get(p) or ""


def maintenant_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def groupe_libelle(nom: str) -> Optional[str]:
    """« Group  3 » / « Group D3 » -> « Groupe 3 » / « Groupe D3 » (espaces superflus et variantes de la source nettoyés)."""
    n = re.sub(r"\s+", " ", (nom or "").replace("\xa0", " ")).strip()
    if not n:
        return None
    return re.sub(r"^(Groupe|Group)\s*", "Groupe ", n)


def tour_fifa(comp: str, stage: str) -> str:
    s = re.sub(r"\s+", " ", (stage or "").replace("\xa0", " ").replace("™", "")).strip()
    if comp == "ci":
        for motif, lib in REGLES_TOUR_CI:
            if re.search(motif, s.lower()):
                return lib
    s = re.sub(r"\s+de la FIFA(\s+\d{4})?$", "", s)
    s = TOURS_FIFA_FR.get(s, s)
    if comp == "cdmc":
        s = TOURS_FIFA_FR_CLUBS.get(s, s)
    return s


def _entier(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------------------
# Normalisation d'un match brut -> enregistrement commun
# ------------------------------------------------------------------------------
def equipe_fifa(t: Optional[Dict[str, Any]], club: bool) -> Optional[Dict[str, Any]]:
    """{code, nom, pays, drapeau} ; None pour une place à déterminer. Sélection : code = pays FIFA d'ÉPOQUE ; club : « fifa-<IdTeam> »."""
    if not t or not t.get("IdTeam"):
        return None
    pays = (t.get("IdCountry") or "").upper()
    nom = I._fr_liste(t.get("TeamName"))
    code = f"fifa-{t['IdTeam']}" if club or not pays else pays
    return {"code": code, "nom": nom, "pays": pays, "drapeau": drapeau(pays), "fifa_id": str(t["IdTeam"]), "club": club}


def normaliser_fifa(comp: str, m: Dict[str, Any]) -> Dict[str, Any]:
    club = I.COMPETITIONS[comp]["famille"] == "clubs"
    h, a = equipe_fifa(m.get("Home"), club), equipe_fifa(m.get("Away"), club)
    tour = tour_fifa(comp, I._fr_liste(m.get("StageName")))
    groupe = groupe_libelle(I._fr_liste(m.get("GroupName")))
    statut = STATUT_FIFA.get(m.get("MatchStatus"), "X")
    sd, se = _entier(m.get("HomeTeamScore")), _entier(m.get("AwayTeamScore"))
    rt = m.get("ResultType")
    ph, pa = _entier(m.get("HomeTeamPenaltyScore")), _entier(m.get("AwayTeamPenaltyScore"))
    tab = (ph, pa) if statut == "T" and ph is not None and pa is not None and (rt == 2 or ph + pa > 0) else None
    gagnant = str(m.get("Winner") or "")
    code_de_id = {x["fifa_id"]: x["code"] for x in (h, a) if x}
    return {"id": f"fifa:{m.get('IdMatch')}", "date": (m.get("Date") or "")[:10], "phase": "g" if groupe else "f", "tour": tour,
            "groupe": groupe, "role": "F" if tour == "Finale" else ("T" if tour == "Match pour la 3e place" else None),
            "dom": h, "ext": a, "sd": sd if statut == "T" else None, "se": se if statut == "T" else None, "tab": tab,
            "statut": statut, "dp": {3: "ap", 8: "bo"}.get(rt) if statut == "T" else None, "rejoue": False,
            "w_code": code_de_id.get(gagnant) if gagnant else None, "w_id": gagnant or None}


def _statut_uefa(m: Dict[str, Any]) -> str:
    st = m.get("status") or ""
    if st == "FINISHED":
        if ((((m.get("winner") or {}).get("match") or {}).get("reason")) or "") == "WIN_BY_FORFEIT":
            return "F"                                   # score attribué par l'UEFA : affiché, jamais compté
        return "T"
    return STATUT_UEFA.get(st, "C" if st else "V")


def normaliser_uefa(comp: str, m: Dict[str, Any]) -> Dict[str, Any]:
    r = m.get("round") or {}
    meta = r.get("metaData") or {}
    tt, mode, md = meta.get("type") or "", r.get("mode") or "", r.get("modeDetail") or ""
    deux_q = SOURCES[comp].get("deux_manches_q") and md == "KNOCK_OUT_TWO_LEGS"
    if (r.get("phase") or "") == "QUALIFYING" or deux_q:
        phase = "q"
    else:
        phase = "g" if mode == "GROUP" else "f"
    tour = fr(r.get("translations"), "name") or meta.get("name", "")
    tour = TOURS_UEFA_FR.get(tour, tour)
    g = m.get("group") or {}
    groupe = groupe_libelle((g.get("metaData") or {}).get("groupName") or fr(g.get("translations"), "name"))
    h, a = (m.get("homeTeam") or {}), (m.get("awayTeam") or {})

    def eq(t: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not t or t.get("isPlaceHolder") or not t.get("countryCode"):
            return None
        info = uefa.team_info(t)
        pays = info["country"].upper()
        return {"code": pays, "nom": info["name"], "pays": pays, "drapeau": drapeau(pays), "club": False}

    statut = _statut_uefa(m)
    sc = m.get("score") or {}
    tot, reg, pen = sc.get("total") or {}, sc.get("regular") or {}, sc.get("penalty") or {}
    sd, se = _entier(tot.get("home")), _entier(tot.get("away"))
    jouee = statut in ("T", "F") and sd is not None and se is not None
    tab = (_entier(pen.get("home")), _entier(pen.get("away"))) if statut == "T" and pen.get("home") is not None and pen.get("away") is not None else None
    dp = "ap" if jouee and reg.get("home") is not None and reg.get("away") is not None and \
        (_entier(reg["home"]), _entier(reg["away"])) != (sd, se) else None
    w = ((m.get("winner") or {}).get("match") or {}).get("team") or {}
    kick = m.get("kickOffTime") or {}
    jour = (kick.get("dateTime") or kick.get("date") or "")[:10]
    return {"id": f"uefa:{m.get('id')}", "date": jour, "phase": phase, "tour": tour, "groupe": groupe,
            "role": "F" if tt == "FINAL" else ("T" if tt == "THIRD_PLAY_OFF" else None),
            "dom": eq(h), "ext": eq(a), "sd": sd if jouee else None, "se": se if jouee else None, "tab": tab, "statut": statut,
            "dp": dp, "rejoue": (m.get("type") == "REPLAY" or tt == "REPLAY"), "w_code": (w.get("countryCode") or "").upper() or None,
            "w_id": None}


# ------------------------------------------------------------------------------
# Édition : finale, troisième, poule finale
# ------------------------------------------------------------------------------
def vainqueur_match(m: Dict[str, Any]) -> Tuple[Optional[str], str]:
    """(code du vainqueur, raison) d'un match terminé : score, puis tirs au but ; (None, raison) si les données ne tranchent pas."""
    if m["statut"] != "T" or m["sd"] is None or m["se"] is None:
        return None, "match non joué ou sans score"
    if m["sd"] != m["se"]:
        return (m["dom"]["code"] if m["sd"] > m["se"] else m["ext"]["code"]), "score"
    t = m.get("tab")
    if t and t[0] != t[1]:
        return (m["dom"]["code"] if t[0] > t[1] else m["ext"]["code"]), "tirs au but"
    return None, "égalité sans tirs au but dans les données"


def _decider(matchs: List[Dict[str, Any]], role: str, ecarts: List[str]) -> Tuple[Optional[str], Optional[str], str]:
    """(vainqueur, perdant, pourquoi) du match de rôle `role` ; match rejoué : seul lui décide. vainqueur « ? » = non déterminé."""
    cand = sorted([m for m in matchs if m["role"] == role], key=lambda x: (x["date"], x["id"]))
    if not cand:
        return None, None, ""
    rej = [m for m in cand if m["rejoue"]]
    if len(cand) > 1 and not rej:
        return "?", None, f"{len(cand)} matchs pour le même rôle sans match rejoué (cas non prévu)"
    dec = (rej or cand)[-1]
    if not dec["dom"] or not dec["ext"]:
        return None, None, "adversaires à déterminer"
    if dec["statut"] in ("V", "C", "P"):
        return None, None, "pas encore joué"
    v, pourquoi = vainqueur_match(dec)
    src = dec.get("w_code")
    if v is None:
        if src:
            ecarts.append(f"{dec['date']} : calcul indéterminé / source {src}")
        return "?", None, pourquoi
    if src and src != v:
        ecarts.append(f"{dec['date']} : calcul {v} / source {src}")
        return "?", None, "désaccord avec la source"
    perdant = dec["ext"]["code"] if v == dec["dom"]["code"] else dec["dom"]["code"]
    return v, perdant, pourquoi


def poule_finale(matchs: List[Dict[str, Any]], edition: int) -> Optional[List[List[Any]]]:
    """Classement de la poule finale (édition sans finale) : tour du dernier match, tous terminés, chaque paire une fois ; None sinon.
    Points de l'ÉPOQUE (2 la victoire avant 1994), aucun départage. Lignes [code, j, v, n, d, bp, bc, pts], par points décroissants."""
    f = [m for m in matchs if m["phase"] == "f" and m["statut"] != "V"]
    if not f:
        return None
    dernier = max(f, key=lambda x: (x["date"], x["id"]))["tour"]
    ms = [m for m in f if m["tour"] == dernier]
    if any(m["statut"] != "T" or not m["dom"] or not m["ext"] or m["sd"] is None for m in ms):
        return None
    equipes = sorted({m[c]["code"] for m in ms for c in ("dom", "ext")})
    paires = {frozenset((m["dom"]["code"], m["ext"]["code"])) for m in ms}
    n = len(equipes)
    if n < 3 or len(ms) != n * (n - 1) // 2 or len(paires) != len(ms):
        return None
    pv = 2 if edition < 1994 else 3
    t = {c: [c, 0, 0, 0, 0, 0, 0, 0] for c in equipes}
    for m in ms:
        for cote, adv, pour, contre in (("dom", "ext", m["sd"], m["se"]), ("ext", "dom", m["se"], m["sd"])):
            r = t[m[cote]["code"]]
            r[1] += 1
            r[5] += pour
            r[6] += contre
            if pour > contre:
                r[2] += 1
                r[7] += pv
            elif pour == contre:
                r[3] += 1
                r[7] += 1
            else:
                r[4] += 1
    return sorted(t.values(), key=lambda r: (-r[7], r[0]))


def resoudre_edition(comp: str, edition: int, matchs: List[Dict[str, Any]], en_cours: bool) -> Dict[str, Any]:
    """vainqueur / finaliste / troisieme / regle / ecarts / pourquoi d'une édition (voir l'en-tête du module)."""
    ecarts: List[str] = []
    out: Dict[str, Any] = {}
    v, p, pourquoi = _decider(matchs, "F", ecarts)
    if v is None and not any(m["role"] == "F" for m in matchs) and not en_cours:
        pf = poule_finale(matchs, edition)
        if pf:
            out["regle"] = "poule_finale"
            out["poule_finale"] = pf
            tete = [r for r in pf if r[7] == pf[0][7]]
            out["vainqueur"] = pf[0][0] if len(tete) == 1 else "?"
            if len(tete) == 1:
                reste = [r for r in pf if r[7] < pf[0][7]]
                sec = [r for r in reste if r[7] == reste[0][7]] if reste else []
                out["finaliste"] = sec[0][0] if len(sec) == 1 else "?"
        else:
            out["vainqueur"], out["pourquoi"] = "?", "aucune finale dans les données"
    elif v is not None:
        out["vainqueur"] = v
        if p:
            out["finaliste"] = p
        elif v == "?":
            out["pourquoi"] = pourquoi
    t, _, _ = _decider(matchs, "T", ecarts)
    if t is not None:
        out["troisieme"] = t
    if ecarts:
        out["ecarts"] = ecarts
    return out


def construire_edition(comp: str, edition: int, libelle: str, matchs_norm: List[Dict[str, Any]], hotes: List[str]) -> Dict[str, Any]:
    """Édition COMPACTE (format du module) à partir des matchs normalisés."""
    matchs_norm = sorted(matchs_norm, key=lambda x: (x["date"], x["phase"], x["id"]))
    equipes: Dict[str, List[str]] = {}
    tours: List[str] = []
    groupes: List[str] = []
    lignes: List[List[Any]] = []
    for m in matchs_norm:
        for c in ("dom", "ext"):
            if m[c]:
                equipes[m[c]["code"]] = [m[c]["nom"], m[c]["drapeau"]]
        if m["tour"] not in tours:
            tours.append(m["tour"])
        if m["groupe"] and m["groupe"] not in groupes:
            groupes.append(m["groupe"])
        lignes.append([m["date"], m["phase"], tours.index(m["tour"]), groupes.index(m["groupe"]) if m["groupe"] else None,
                       m["dom"]["code"] if m["dom"] else None, m["ext"]["code"] if m["ext"] else None, m["sd"], m["se"],
                       m["tab"][0] if m["tab"] else None, m["tab"][1] if m["tab"] else None, m["statut"], m["id"], m["dp"],
                       1 if m["rejoue"] else None])
    en_cours = any(m["statut"] in ("V", "C", "P") for m in matchs_norm)   # « X » / « F » : jamais « en cours »
    ed: Dict[str, Any] = {"edition": edition, "libelle": libelle}
    h = [c for c in hotes if c in equipes]
    if h:
        ed["hote"] = h
    ed.update(resoudre_edition(comp, edition, matchs_norm, en_cours))
    if en_cours:
        ed["en_cours"] = True
    if "?" in (ed.get("vainqueur"), ed.get("troisieme")) and not ed.get("ecarts"):
        nuls = [m for m in matchs_norm if m["phase"] == "f" and m["statut"] == "T" and m["sd"] is not None and m["sd"] == m["se"]
                and not m["tab"] and not m["rejoue"]]
        if len(nuls) > 1:
            ed["avertissement"] = (f"{len(nuls)} matchs à élimination directe nuls sans tirs au but : scores de la source probablement "
                                   "incomplets (un tour à élimination directe ne finit pas sur un nul)")
    ed.update({"equipes": dict(sorted(equipes.items())), "tours": tours, "groupes": groupes, "matchs": lignes})
    return ed


# ------------------------------------------------------------------------------
# Collecte
# ------------------------------------------------------------------------------
def _cache_chemin(cache: Optional[str], nom: str) -> Optional[str]:
    return os.path.join(cache, nom + ".json.gz") if cache else None


def _cache_lire(chemin: Optional[str]) -> Optional[Any]:
    if chemin and os.path.exists(chemin):
        try:
            with gzip.open(chemin, "rt", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
    return None


def _cache_ecrire(chemin: Optional[str], obj: Any) -> None:
    if chemin:
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        with gzip.open(chemin, "wt", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)


def editions_fifa(comp: str) -> Optional[List[Dict[str, Any]]]:
    """Éditions FIFA de la compétition : [{edition, id_competition, id_saison, nom, hotes: [IdTeam]}], récentes d'abord ; None si illisible."""
    cfg = SOURCES[comp]
    out: List[Dict[str, Any]] = []
    for idc in cfg["fifa"]:
        time.sleep(PAUSE_S)
        d = fetch_json(f"{I.FIFA}/seasons?idCompetition={idc}&language=fr&count=100")
        if not isinstance(d, dict) or not isinstance(d.get("Results"), list):
            return None
        for s in d["Results"]:
            nom = I._fr_liste(s.get("Name"))
            ans = re.findall(r"\b(1[89]\d\d|20\d\d)\b", nom)
            if not ans or (cfg["motif"] and cfg["motif"] not in _sans_accents(nom)):
                continue
            out.append({"edition": int(ans[-1]), "idc": idc, "ids": str(s.get("IdSeason")), "nom": nom,
                        "hotes": [str(x.get("IdTeam")) for x in (s.get("HostTeams") or []) if x.get("IdTeam")]})
    return sorted(out, key=lambda e: -e["edition"])


def collecter_fifa(comp: str, e: Dict[str, Any], cache: Optional[str]) -> Optional[Dict[str, Any]]:
    chemin = _cache_chemin(cache, f"fifa_{comp}_{e['edition']}")
    brut = _cache_lire(chemin)
    if brut is None:
        ms = I.fifa_matchs(e["idc"], e["ids"])
        if ms is None:
            return None
        brut = {"matchs": ms, "hotes": e["hotes"]}
        _cache_ecrire(chemin, brut)
    brut.setdefault("hotes", e["hotes"])
    club = I.COMPETITIONS[comp]["famille"] == "clubs"
    norm = [normaliser_fifa(comp, m) for m in brut["matchs"]]
    codes = {}
    for m in brut["matchs"]:
        for t in (m.get("Home"), m.get("Away")):
            x = equipe_fifa(t, club)
            if x:
                codes[x["fifa_id"]] = x["code"]
    return {"matchs": norm, "hotes": [codes[h] for h in brut["hotes"] if h in codes]}


def uefa_liste(cid: int, edition: int) -> Optional[List[Dict[str, Any]]]:
    """Tous les matchs UEFA d'une édition (pages de 500) ; None si une page est illisible ; [] si l'édition n'existe pas."""
    out: List[Dict[str, Any]] = []
    for off in range(0, 5000, 500):
        time.sleep(PAUSE_S)
        d = fetch_json(f"https://match.uefa.com/v5/matches?competitionId={cid}&seasonYear={edition}&offset={off}&limit=500&order=ASC&language=FR")
        if not isinstance(d, list):
            return None
        out.extend(d)
        if len(d) < 500:
            break
    return out


def collecter_uefa(comp: str, edition: int, cache: Optional[str]) -> Optional[Dict[str, Any]]:
    chemin = _cache_chemin(cache, f"uefa_{comp}_{edition}")
    brut = _cache_lire(chemin)
    if brut is None:
        ms = uefa_liste(SOURCES[comp]["uefa"], edition)
        if ms is None:
            return None
        brut = {"matchs": ms}
        if ms:
            _cache_ecrire(chemin, brut)
    return {"matchs": [normaliser_uefa(comp, m) for m in brut["matchs"]], "hotes": []}


def annees_uefa(comp: str, aujourdhui: Optional[date] = None) -> List[int]:
    """Éditions UEFA possibles (formule documentée : Euro tous les 4 ans depuis 1960, Ligue des nations tous les 2 ans depuis 2019),
    jusqu'à 6 ans après aujourd'hui (éliminatoires publiés d'avance) ; récentes d'abord."""
    c = SOURCES[comp]
    an = (aujourdhui or date.today()).year
    return sorted(range(c["premiere"], an + 7, c["pas"]), reverse=True)


def lire_comp(donnees: str, comp: str) -> Dict[str, Any]:
    d = _lire(os.path.join(donnees, DOSSIER, f"{comp}.json")) or {}
    return d if d.get("regle") == REGLE else {}


def collecter_comp(comp: str, donnees: str, cache: Optional[str], budget_s: float, debut: float, relire: bool,
                   journal: List[str]) -> Dict[str, Any]:
    """Collecte reprenable d'une compétition -> `<comp>.json`. Retourne {traites, restantes, en_cours, editions}."""
    cfg = SOURCES[comp]
    doc = lire_comp(donnees, comp)
    existantes = {e["edition"]: e for e in doc.get("editions", [])}
    restantes: List[int] = []
    traites = 0
    if cfg["source"] == "FIFA":
        eds = editions_fifa(comp)
        if eds is None:
            journal.append(f"[WARN] {comp} : liste des éditions FIFA illisible ; rien ce passage")
            return {"traites": 0, "restantes": [-1], "en_cours": [], "editions": len(existantes)}
        a_voir = [(e["edition"], e) for e in eds]
    else:
        a_voir = [(an, an) for an in annees_uefa(comp)]
    for edition, ref in a_voir:
        ancienne = existantes.get(edition)
        if ancienne and not ancienne.get("en_cours") and not relire:
            continue
        if time.time() - debut > budget_s:
            restantes.append(edition)
            continue
        res = collecter_fifa(comp, ref, cache) if cfg["source"] == "FIFA" else collecter_uefa(comp, edition, cache)
        if res is None:
            journal.append(f"[WARN] {comp} {edition} : liste illisible, édition non remplacée")
            restantes.append(edition)
            continue
        if not res["matchs"]:
            continue                                     # édition pas encore publiée (Euro 2028…)
        ed = construire_edition(comp, edition, I.libelle_edition(comp, edition), res["matchs"], res["hotes"])
        if ancienne and len(ancienne["matchs"]) > len(ed["matchs"]):
            journal.append(f"[WARN] {comp} {edition} : liste réduite ({len(ed['matchs'])} < {len(ancienne['matchs'])} matchs), conservée")
            continue
        if ancienne != ed:
            traites += 1
            existantes[edition] = ed
            journal.append(f"[HISTO] {comp} {edition} : {len(ed['matchs'])} match(s), vainqueur {ed.get('vainqueur', '-')}"
                           f"{' (en cours)' if ed.get('en_cours') else ''}")
        ecrire_comp(donnees, comp, existantes)
    ecrire_comp(donnees, comp, existantes)
    return {"traites": traites, "restantes": restantes, "editions": len(existantes),
            "en_cours": sorted(e["edition"] for e in existantes.values() if e.get("en_cours"))}


def ecrire_comp(donnees: str, comp: str, existantes: Dict[int, Dict[str, Any]]) -> bool:
    if not existantes:
        return False
    doc = {"comp": comp, "nom": I.COMPETITIONS[comp]["nom"], "source": SOURCES[comp]["source"], "regle": REGLE, "maj": maintenant_iso(),
           "editions": [existantes[k] for k in sorted(existantes, reverse=True)]}
    return ecrire_si_change(os.path.join(donnees, DOSSIER, f"{comp}.json"), doc)


# ------------------------------------------------------------------------------
# Bilans par équipe (calculés)
# ------------------------------------------------------------------------------
def _bilan_vide() -> Dict[str, int]:
    return {"ed": 0, "j": 0, "v": 0, "n": 0, "d": 0, "bp": 0, "bc": 0, "ntv": 0, "ntd": 0}


def niveau_tour(comp: str, libelle: str) -> int:
    n = NIVEAUX.get(comp, {}).get(libelle)
    if n is None:
        TOURS_INCONNUS.add((comp, libelle))
        return 0
    return n


def bilans_comp(comp: str, editions: List[Dict[str, Any]], equipes: Dict[str, Dict[str, Any]]) -> None:
    """Met à jour `equipes` (code -> fiche en construction) avec les bilans, palmarès, matchs de phase finale de la compétition."""
    for ed in editions:
        eq = ed["equipes"]
        part: Dict[str, Dict[str, set]] = {}                 # code -> {"finale": {éd}, "elim": {éd}} (éditions avec match terminé)
        atteint: Dict[str, Tuple[int, str]] = {}
        finalistes = set()
        for ln in ed["matchs"]:
            date_, phase, t, g, d, e, sd, se, td, te, statut, mid, dp, rj = ln
            if not d or not e:
                continue
            for code, nom in ((d, None), (e, None)):
                f = equipes.setdefault(code, {"code": code, "nom": eq[code][0], "drapeau": eq[code][1], "bilans": {}, "palmares": [],
                                              "adv": {}, "tours": [], "matchs": {}, "_ed": {}, "_an": 0})
                if ed["edition"] >= f.get("_an", 0):                   # nom et drapeau de l'édition la plus récente (toutes compétitions)
                    f["nom"], f["drapeau"], f["_an"] = eq[code][0], eq[code][1], ed["edition"]
            lib = ed["tours"][t]
            if statut == "T" and sd is not None and se is not None:
                bloc = "elim" if phase == "q" else "finale"
                for code, pour, contre, tp, tc in ((d, sd, se, td, te), (e, se, sd, te, td)):
                    b = equipes[code]["bilans"].setdefault(comp, {}).setdefault(bloc, _bilan_vide())
                    b["j"] += 1
                    b["bp"] += pour
                    b["bc"] += contre
                    if pour > contre:
                        b["v"] += 1
                    elif pour < contre:
                        b["d"] += 1
                    else:
                        b["n"] += 1
                        if tp is not None and tc is not None and tp != tc:
                            b["ntv" if tp > tc else "ntd"] += 1
                    part.setdefault(code, {}).setdefault(bloc, set()).add(ed["edition"])
                if phase in ("g", "f"):
                    for code in (d, e):
                        niv = niveau_tour(comp, lib)
                        if code not in atteint or niv > atteint[code][0]:
                            atteint[code] = (niv, lib)
            if ln[1] == "f" and mid and statut == "T":
                pass
            if phase in ("g", "f") and statut != "V":
                for code, adv, pour, contre, tp, tc in ((d, e, sd, se, td, te), (e, d, se, sd, te, td)):
                    f = equipes[code]
                    f["adv"][adv] = list(eq[adv])
                    if lib not in f["tours"]:
                        f["tours"].append(lib)
                    f["matchs"].setdefault(comp, []).append([date_, ed["edition"], f["tours"].index(lib), adv, pour, contre, tp, tc, dp,
                                                             None if statut == "T" else statut])
            if ln[1] == "f" and statut == "T":
                pass
        # finalistes : équipes d'un match « finale » terminé (rôle lu par le libellé) ou nommées par l'édition
        for code in (ed.get("vainqueur"), ed.get("finaliste")):
            if code and code != "?":
                finalistes.add(code)
        for ln in ed["matchs"]:
            if ed["tours"][ln[2]] == "Finale" and ln[10] == "T" and ln[4] and ln[5]:
                finalistes.update((ln[4], ln[5]))
        for code, blocs in part.items():
            for bloc, eds in blocs.items():
                equipes[code]["bilans"][comp][bloc]["ed"] += len(eds)
        for code in finalistes:
            if code in equipes:
                equipes[code]["_ed"].setdefault(comp, {"finales": set(), "titres": set(), "niv": {}})["finales"].add(ed["edition"])
        # palmarès et meilleur parcours de l'édition
        ordre = ((ed.get("vainqueur"), "V", NIV_VAINQUEUR), (ed.get("finaliste"), "F", NIV_FINALISTE), (ed.get("troisieme"), "3", NIV_TROISIEME))
        rang = {}
        for code, r, niv in ordre:
            if code and code != "?" and code in equipes:
                rang[code] = (r, niv)
                equipes[code]["palmares"].append({"comp": comp, "edition": ed["edition"], "rang": r})
                if r == "V":
                    equipes[code]["_ed"].setdefault(comp, {"finales": set(), "titres": set(), "niv": {}})["titres"].add(ed["edition"])
        for code, (niv, lib) in atteint.items():
            info = equipes[code]["_ed"].setdefault(comp, {"finales": set(), "titres": set(), "niv": {}})
            if code in rang:
                niv, lib = rang[code][1], LIB_NIVEAU[rang[code][1]]
            info["niv"][ed["edition"]] = (niv, lib)


def finaliser_equipes(equipes: Dict[str, Dict[str, Any]], maj: str) -> None:
    for code, f in equipes.items():
        f.pop("_an", None)
        for comp, info in f.pop("_ed").items():
            b = f["bilans"].setdefault(comp, {})
            b["titres"] = len(info["titres"])
            b["finales"] = len(info["finales"])
            if info["niv"]:
                ed, (niv, lib) = max(info["niv"].items(), key=lambda kv: (kv[1][0], kv[0]))
                b["meilleur"] = {"edition": ed, "lib": lib, "niveau": niv}
        f["palmares"].sort(key=lambda p: (p["edition"], p["comp"]))
        for comp, ms in f["matchs"].items():
            ms.sort(key=lambda x: (x[0], x[1]))
        f["maj"] = maj
        f["club"] = True if code.startswith("fifa-") else None
        if not f["club"]:
            f.pop("club")


def construire_derives(donnees: str, journal: Optional[List[str]] = None) -> Dict[str, Any]:
    """Relit les `<comp>.json` et écrit `equipes/<code>.json` + `index.json` (aucun réseau). Retourne un bilan chiffré."""
    docs = {c: _lire(os.path.join(donnees, DOSSIER, f"{c}.json")) for c in ORDRE_COMPS}
    docs = {c: d for c, d in docs.items() if d and d.get("regle") == REGLE}
    equipes: Dict[str, Dict[str, Any]] = {}
    maj = maintenant_iso()
    for comp in ORDRE_COMPS:
        if comp in docs:
            bilans_comp(comp, docs[comp]["editions"], equipes)
    finaliser_equipes(equipes, maj)
    dossier_eq = os.path.join(donnees, DOSSIER, "equipes")
    ecrits = 0
    for code, f in equipes.items():
        f = {k: v for k, v in f.items() if k in ("code", "nom", "drapeau", "club", "maj", "bilans", "palmares", "tours", "adv", "matchs")}
        ecrits += 1 if ecrire_si_change(os.path.join(dossier_eq, f"{code}.json"), f) else 0
    if os.path.isdir(dossier_eq):
        for nom in os.listdir(dossier_eq):
            if nom.endswith(".json") and nom[:-5] not in equipes:
                os.remove(os.path.join(dossier_eq, nom))
    idx = {"maj": maj, "competitions": {}, "equipes": {}}
    for comp, d in docs.items():
        c = I.COMPETITIONS[comp]
        idx["competitions"][comp] = {"nom": c["nom"], "court": c["court"], "famille": c["famille"], "editions": len(d["editions"]),
                                     "vainqueurs": [{"edition": e["edition"], "code": e["vainqueur"]} for e in d["editions"] if e.get("vainqueur")]}
        enc = [e["edition"] for e in d["editions"] if e.get("en_cours")]
        if enc:
            idx["competitions"][comp]["en_cours"] = enc
    for code, f in sorted(equipes.items()):
        t = {comp: b["titres"] for comp, b in f["bilans"].items() if b.get("titres")}
        x = {"nom": f["nom"], "drapeau": f["drapeau"], "titres": t}
        if f.get("club"):
            x["club"] = True
        idx["equipes"][code] = x
    ecrire_si_change(os.path.join(donnees, DOSSIER, "index.json"), idx)
    return {"equipes": len(equipes), "equipes_ecrites": ecrits}


# ------------------------------------------------------------------------------
# Programme principal
# ------------------------------------------------------------------------------
def taille_fichiers(donnees: str) -> List[Tuple[str, int, int]]:
    """[(chemin relatif, octets bruts, octets gzip)] des fichiers de l'historique (équipes agrégées sur une ligne)."""
    out = []
    racine = os.path.join(donnees, DOSSIER)
    eq_brut = eq_gz = n = 0
    for dossier, _, fichiers in os.walk(racine):
        for nom in sorted(fichiers):
            ch = os.path.join(dossier, nom)
            with open(ch, "rb") as f:
                data = f.read()
            rel = os.path.relpath(ch, racine)
            if rel.startswith("equipes"):
                eq_brut += len(data)
                eq_gz += len(gzip.compress(data))
                n += 1
            else:
                out.append((rel, len(data), len(gzip.compress(data))))
    out.append((f"equipes/ ({n} fichiers)", eq_brut, eq_gz))
    return sorted(out)


def run(donnees: str, comps: List[str], budget_min: float, cache: Optional[str], relire: bool) -> Dict[str, Any]:
    debut = time.time()
    journal: List[str] = []
    resultats: Dict[str, Any] = {}
    for comp in comps:
        resultats[comp] = collecter_comp(comp, donnees, cache, budget_min * 60, debut, relire, journal)
    for ligne in journal:
        print(ligne)
    derives = construire_derives(donnees)
    restants = sum(len(r["restantes"]) for r in resultats.values())
    traites = sum(r["traites"] for r in resultats.values())
    etat_precedent = _lire(os.path.join(donnees, DOSSIER, "etat.json")) or {}
    comps_etat = dict(etat_precedent.get("comps") or {})
    for comp, r in resultats.items():
        comps_etat[comp] = {"editions": r["editions"], "en_cours": r["en_cours"], "restantes": sorted(set(r["restantes"]) - {-1})}
    ecrire_si_change(os.path.join(donnees, DOSSIER, "etat.json"), {"regle": REGLE, "maj": maintenant_iso(), "comps": comps_etat})
    if TOURS_INCONNUS:
        print(f"[WARN] tours sans niveau (meilleur parcours incomplet) : {sorted(TOURS_INCONNUS)}")
    print(f"[HISTO] {traites} édition(s) écrite(s), {restants} restante(s), {derives['equipes']} équipes "
          f"({derives['equipes_ecrites']} fiches modifiées), {time.time() - debut:.0f} s")
    sortie = os.environ.get("GITHUB_OUTPUT")
    if sortie:
        with open(sortie, "a", encoding="utf-8") as f:
            f.write(f"traites={traites}\nrestants={restants}\n")
    return {"traites": traites, "restants": restants, "resultats": resultats, "derives": derives}


# ------------------------------------------------------------------------------
# Tests (sans réseau)
# ------------------------------------------------------------------------------
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools", "fixtures", "histoire_internationale")


def _fixture(nom: str) -> Any:
    with open(os.path.join(FIXTURES, nom), encoding="utf-8") as f:
        return json.load(f)


def _edition_fixture(comp: str, nom: str, edition: int, hotes_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    brut = _fixture(nom)
    if SOURCES[comp]["source"] == "FIFA":
        norm = [normaliser_fifa(comp, m) for m in brut["matchs"]]
        club = I.COMPETITIONS[comp]["famille"] == "clubs"
        codes = {}
        for m in brut["matchs"]:
            for t in (m.get("Home"), m.get("Away")):
                x = equipe_fifa(t, club)
                if x:
                    codes[x["fifa_id"]] = x["code"]
        hotes = [codes[h] for h in (brut.get("hotes") or []) if h in codes]
    else:
        norm, hotes = [normaliser_uefa(comp, m) for m in brut["matchs"]], []
    return construire_edition(comp, edition, I.libelle_edition(comp, edition), norm, hotes)


def _tests() -> None:
    ok = 0

    def verif(cond: bool, msg: str) -> None:
        nonlocal ok
        assert cond, msg
        ok += 1

    # --- outils
    verif(drapeau("FRA") == "fr" and drapeau("URS") == "" and drapeau("FRG") == "" and drapeau("KUW") == "kw", "drapeaux")
    verif(groupe_libelle("Group  3 ") == "Groupe 3" and groupe_libelle("Group D3") == "Groupe D3" and groupe_libelle("Groupe\xa01") == "Groupe 1",
          "libellé de groupe")
    verif(tour_fifa("cdm", "Matches de groupes") == "Phase de groupes" and tour_fifa("cdm", "Bronze final") == "Match pour la 3e place"
          and tour_fifa("cdmc", "Deuxième tour") == "2e tour" and tour_fifa("cdmc", "5e place") == "Match pour la 5e place", "tours FIFA")
    verif(tour_fifa("ci", "FIFA Intercontinental Cup 2025 Final") == "Finale"
          and tour_fifa("ci", "Finale de la Coupe intercontinentale de la FIFA 2026™") == "Finale"
          and tour_fifa("ci", "FIFA Derby of the Americas 2025") == "Derby des Amériques"
          and tour_fifa("ci", "Barrage Afrique-Asie-Pacifique de la FIFA 2026™") == "Barrage Afrique-Asie-Pacifique"
          and tour_fifa("ci", "FIFA African-Asian-Pacific Cup 2025™") == "Coupe Afrique-Asie-Pacifique"
          and tour_fifa("ci", "Challenger Cup de la FIFA") == "Challenger Cup", "tours de la Coupe intercontinentale")

    # --- Coupe du monde 2022 : finale aux tirs au but, hôte
    e22 = _edition_fixture("cdm", "cdm_2022.json", 2022)
    verif(e22["vainqueur"] == "ARG" and e22["finaliste"] == "FRA" and e22["troisieme"] == "CRO" and e22["hote"] == ["QAT"], "CdM 2022")
    fin22 = [m for m in e22["matchs"] if e22["tours"][m[2]] == "Finale"][0]
    verif(fin22[6:10] == [3, 3, 4, 2] and fin22[10] == "T" and fin22[12] is None, "finale 2022 : 3-3, tirs au but 4-2, pas de prolongation notée")
    # --- finale 2010 : prolongation (ResultType 3) ; 1998 : but en or (ResultType 8)
    e10 = _edition_fixture("cdm", "cdm_2010.json", 2010)
    verif(e10["vainqueur"] == "ESP" and e10["finaliste"] == "NED" and e10["matchs"][-1][12] == "ap", "CdM 2010 : prolongation")
    e98 = _edition_fixture("cdm", "cdm_1998.json", 1998)
    verif(e98["vainqueur"] == "FRA" and e98["finaliste"] == "BRA" and any(m[12] == "bo" for m in e98["matchs"]), "CdM 1998 : but en or")
    # --- 1930 : pas de 3e place, pays disparus sans drapeau
    e30 = _edition_fixture("cdm", "cdm_1930.json", 1930)
    verif(e30["vainqueur"] == "URU" and e30["finaliste"] == "ARG" and "troisieme" not in e30 and e30["hote"] == ["URU"], "CdM 1930")
    verif(e30["equipes"]["YUG"] == ["Yougoslavie", ""], "Yougoslavie sans drapeau")
    # --- 1950 : poule finale, Uruguay (5 points) devant le Brésil (4)
    e50 = _edition_fixture("cdm", "cdm_1950.json", 1950)
    verif(e50["regle"] == "poule_finale" and e50["vainqueur"] == "URU" and e50["finaliste"] == "BRA" and "troisieme" not in e50, "CdM 1950")
    verif(e50["poule_finale"][0] == ["URU", 3, 2, 1, 0, 7, 5, 5] and e50["poule_finale"][1][7] == 4, "poule finale 1950 : points 2/1/0")
    # poule à égalité de tête : vainqueur « ? » (jamais deviné) ; ici Uruguay - Suède devient 2-2 : Uruguay 4 points, Brésil 4 points
    brut = _fixture("cdm_1950.json")
    norm = [normaliser_fifa("cdm", m) for m in brut["matchs"]]
    for m in norm:
        if m["tour"] == "Tour final" and {m["dom"]["code"], m["ext"]["code"]} == {"URU", "SWE"}:
            m["sd"], m["se"] = 2, 2
    r = resoudre_edition("cdm", 1950, norm, False)
    verif(r["regle"] == "poule_finale" and r["vainqueur"] == "?" and "finaliste" not in r, "poule à égalité : « ? »")
    # poule incomplète (un match manque) : pas de règle, « ? »
    r = resoudre_edition("cdm", 1950, [m for m in norm if m["id"] != norm[-1]["id"]], False)
    verif(r["vainqueur"] == "?" and "regle" not in r, "poule incomplète : jamais devinée")
    # --- Euro 1968 : finale 1-1 puis rejoué 2-0
    e68 = _edition_fixture("euro", "euro_1968.json", 1968)
    verif(e68["vainqueur"] == "ITA" and e68["finaliste"] == "YUG" and e68["troisieme"] == "ENG", "Euro 1968 : rejoué décisif")
    verif(sum(1 for m in e68["matchs"] if m[13] == 1) == 1, "un seul match rejoué")
    verif("hote" not in e68, "hôte absent pour l'UEFA")
    # --- Euro 1976 : tirs au but, Tchécoslovaquie (code d'époque, sans drapeau)
    e76 = _edition_fixture("euro", "euro_1976.json", 1976)
    verif(e76["vainqueur"] == "TCH" and e76["finaliste"] == "FRG" and e76["troisieme"] == "NED" and e76["equipes"]["TCH"][1] == "", "Euro 1976")
    verif("ecarts" not in e76, "pas d'écart sur l'Euro 1976 (la source dit « nul » sans équipe)")
    # --- phases de l'Euro 1960 : quarts à deux manches = éliminatoires ; phase finale = 4 équipes
    e60 = _edition_fixture("euro", "euro_1960.json", 1960)
    verif({m[1] for m in e60["matchs"] if e60["tours"][m[2]] in ("Quarts de finale", "Huitièmes de finale")} == {"q"}, "Euro 1960 : manches = éliminatoires")
    verif(any(e60["tours"][m[2]] == "Huitièmes de finale" for m in e60["matchs"]), "Euro 1960 : huitièmes présents")
    verif({m[1] for m in e60["matchs"] if e60["tours"][m[2]] in ("Demi-finales", "Finale")} == {"f"}, "Euro 1960 : phase finale")
    verif(e60["vainqueur"] == "URS" and e60["finaliste"] == "YUG", "Euro 1960 : prolongation (1-1, 2-1)")
    verif(any(m[10] == "A" for m in e60["matchs"]), "Euro 1960 : quart annulé listé")
    # --- Ligue des nations : final four 2025 (tirs au but) et 2021
    l25 = _edition_fixture("ldn", "ldn_2025.json", 2025)
    verif(l25["vainqueur"] == "POR" and l25["finaliste"] == "ESP" and l25["troisieme"] == "FRA" and l25["libelle"] == "2024-25", "LdN 2025")
    l21 = _edition_fixture("ldn", "ldn_2021.json", 2021)
    verif(l21["vainqueur"] == "FRA" and l21["finaliste"] == "ESP", "LdN 2021")
    # --- clubs : Coupe du monde des clubs 2000 (tirs au but), Coupe intercontinentale 2025
    c00 = _edition_fixture("cdmc", "cdmc_2000.json", 2000)
    verif(c00["vainqueur"] == "fifa-44213" and c00["finaliste"] == "fifa-44129" and c00["troisieme"] == "fifa-1884381", "CdMC 2000")
    verif(c00["equipes"]["fifa-44213"] == ["Corinthians", "br"] and len(c00["hote"]) == 2, "clubs : drapeau du pays, deux hôtes")
    c25 = _edition_fixture("ci", "ci_2025.json", 2025)
    verif(c25["vainqueur"] == "fifa-1956449" and c25["finaliste"] == "fifa-1914822", "Coupe intercontinentale 2025 : PSG aux tirs au but")
    c26 = _edition_fixture("ci", "ci_2026.json", 2026)
    verif(c26.get("en_cours") and "vainqueur" not in c26, "Coupe intercontinentale 2026 : en cours, pas de vainqueur")
    # --- désaccord avec la source : vainqueur « ? » + ecarts
    brut = _fixture("cdm_2022.json")
    norm = [normaliser_fifa("cdm", m) for m in brut["matchs"]]
    for m in norm:
        if m["role"] == "F":
            m["w_code"] = "FRA"
    r = resoudre_edition("cdm", 2022, norm, False)
    verif(r["vainqueur"] == "?" and r["ecarts"] and "finaliste" not in r, "désaccord : « ? » et ecarts")
    for m in norm:
        if m["role"] == "F":
            m["tab"], m["w_code"] = None, None
    r = resoudre_edition("cdm", 2022, norm, False)
    verif(r["vainqueur"] == "?" and "pourquoi" in r, "égalité sans tirs au but : « ? »")
    # --- bilans sur un petit corpus : France (titres CdM 1998 et 2018, Euro 1984 et 2000, LdN 2021)
    equipes: Dict[str, Dict[str, Any]] = {}
    corpus = {"cdm": [("cdm_2022.json", 2022), ("cdm_2018.json", 2018), ("cdm_2006.json", 2006), ("cdm_1998.json", 1998)],
              "euro": [("euro_2016.json", 2016), ("euro_2000.json", 2000), ("euro_1984.json", 1984)],
              "ldn": [("ldn_2025.json", 2025), ("ldn_2021.json", 2021)]}
    for comp, lst in corpus.items():
        bilans_comp(comp, [_edition_fixture(comp, n, a) for n, a in lst], equipes)
    finaliser_equipes(equipes, "2026-11-26T00:00:00Z")
    fra = equipes["FRA"]["bilans"]
    verif(fra["cdm"]["titres"] == 2 and fra["cdm"]["finales"] == 4 and fra["euro"]["titres"] == 2 and fra["ldn"]["titres"] == 1, "titres de la France")
    verif(fra["euro"]["finales"] == 3 and fra["ldn"]["finales"] == 1 and fra["cdm"]["meilleur"]["lib"] == "Vainqueur", "finales de la France")
    verif(fra["cdm"]["finale"]["ed"] == 4 and fra["euro"]["finale"]["ed"] == 3 and fra["cdm"]["finale"]["j"] == 5
          and (fra["cdm"]["finale"]["v"], fra["cdm"]["finale"]["n"], fra["cdm"]["finale"]["d"]) == (3, 2, 0)
          and (fra["cdm"]["finale"]["bp"], fra["cdm"]["finale"]["bc"]) == (12, 6),
          "bilan France : 4 finales + France - Paraguay 1998 (but en or = victoire), nuls de 2006 et 2022")
    verif([(x["comp"], x["edition"], x["rang"]) for x in equipes["FRA"]["palmares"][:2]] == [("euro", 1984, "V"), ("cdm", 1998, "V")],
          "palmarès trié par édition")
    verif(equipes["ARG"]["bilans"]["cdm"]["finale"]["ntv"] == 1, "tirs au but gagnés (Argentine, finale 2022) comptés à part, en nul")
    verif(equipes["FRA"]["bilans"]["cdm"]["finale"]["ntd"] == 2, "tirs au but perdus : finales 2006 et 2022")
    print(f"[OK] histoire_internationale : {ok} contrôles")


def main() -> None:
    ap = argparse.ArgumentParser(description="Historique des compétitions internationales (résultats seuls)")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--donnees", help="dossier du dépôt de données (donnees-football) : écrit internationales/historique/")
    ap.add_argument("--comps", default="", help="cdm,euro,ldn,cdmc,ci (vide = toutes)")
    ap.add_argument("--budget-min", type=float, default=45.0)
    ap.add_argument("--cache", help="dossier de cache du JSON brut (HORS du dépôt)")
    ap.add_argument("--relire", action="store_true", help="relit aussi les éditions déjà écrites et finies")
    ap.add_argument("--derives", action="store_true", help="reconstruit seulement equipes/ et index.json (sans réseau)")
    ap.add_argument("--taille", action="store_true", help="affiche la taille brute et gzip des fichiers")
    a = ap.parse_args()
    if a.test:
        _tests()
        return
    if not a.donnees:
        ap.print_help()
        sys.exit(2)
    comps = [c for c in (a.comps.split(",") if a.comps else ORDRE_COMPS) if c in SOURCES]
    if a.derives:
        print(construire_derives(a.donnees))
    else:
        run(a.donnees, comps, a.budget_min, a.cache, a.relire)
    if a.taille or not a.derives:
        for rel, b, g in taille_fichiers(a.donnees):
            print(f"  {rel:40s} {b / 1024:9.1f} Ko  gzip {g / 1024:8.1f} Ko")


if __name__ == "__main__":
    main()
