#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fiches de club : `clubs/index.json` (108 clubs de la saison) + `clubs/<id UEFA>.json` (une fiche par club).

Sources (aucune valeur n'est devinée : ce qu'une source ne donne pas reste absent) :
  UEFA     match.uefa.com (matchs de la saison, stade, ville), standings.uefa.com (rang), compstats.uefa.com
           (cumuls officiels du club et des joueurs), comp.uefa.com (effectif inscrit, joueurs)
  Wikidata P7361 « UEFA team ID » (SPARQL, un appel pour tous les clubs) + `alias_clubs_wikidata.json` (rapprochements
           validés à la main pour les clubs sans P7361) : fondation, surnom, site officiel, ville du siège, article FR
  Wikipédia FR  introduction de l'article (API MediaWiki, par lots de 20 titres lus dans le lien Wikidata, jamais devinés), CC BY-SA 4.0

Couleurs : `couleurs` de chaque club de `index.json` = {principale, secondaire, maillot, nb_matchs, source} calculées par
`couleurs.couleurs_clubs` depuis les maillots PORTÉS (compositions UEFA des matchs terminés de la saison : `shirtColor` et code du
maillot `pl01` / `pl02` / `pl03` lu dans `kitImageUrl`). Chaque composition n'est lue qu'une fois : `clubs/couleurs.json` garde
{match: {d, e: {club: [maillot, hex]}}} (jamais de valeur déduite : une composition sans couleur reste sans couleur).

Cache : Wikidata et Wikipédia ne sont relus que si la valeur date de plus de 30 jours (ou manque) ; un échec ne remplace
jamais une valeur déjà obtenue. L'effectif inscrit n'est relu que lors d'une mise à jour complète.

Usage :
  python clubs.py --tous                  mise à jour complète des fiches (hebdomadaire)
  python clubs.py --clubs 52747,52277     certains clubs seulement
  python clubs.py --couleurs              couleurs des clubs seules (clubs/couleurs.json + champ `couleurs` de l'index)
  python clubs.py --test                  tests purs (sans réseau)
Options : --dossier clubs  --saison 2027  --sans-wiki (ni Wikidata ni Wikipédia)
"""

import argparse
import datetime as dt
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

import couleurs
import uefa
from netutil import FLAG_CODES, fetch_json, fr, to_number

DOSSIER = "clubs"
INDEX = "index.json"
ETAT = "etat.json"
ALIAS = "alias_clubs_wikidata.json"
COULEURS = "couleurs.json"   # maillots portés observés, par match (cache de la couleur principale des clubs)
MAX_LINEUPS_PASSAGE = 60    # passage de soirée : au plus ce nombre de compositions lues pour les couleurs (le rattrapage complet n'a pas de limite)
COMP_NOMS = {"ucl": "Ligue des Champions", "uel": "Ligue Europa", "uecl": "Ligue Conférence"}
COMP_COURT = {"ucl": "LDC", "uel": "LE", "uecl": "LC"}
JOURS_CACHE_WIKI = 30
UA_WIKI = "coupes-europe-dashboard/1.0 (+https://github.com/Camelbaggy/coupes-europe; fiches de club)"
PAUSE_WIKIPEDIA = 2.2

# Statistiques d'équipe : (clé UEFA compstats, libellé, type, groupe). `type` : somme (cumul, moyenne par match = cumul /
# matchs), moyenne (valeur déjà moyenne : possession, précision), max (record : vitesse).
STATS_CLUB = [
    ("goals", "Buts marqués", "somme", "Attaque"),
    ("goals_conceded", "Buts encaissés", "somme", "Défense"),
    ("assists", "Passes décisives", "somme", "Attaque"),
    ("attempts", "Tirs", "somme", "Attaque"),
    ("attempts_on_target", "Tirs cadrés", "somme", "Attaque"),
    ("ball_possession", "Possession (%)", "moyenne", "Construction"),
    ("passes_completed", "Passes réussies", "somme", "Construction"),
    ("passes_accuracy", "Précision des passes (%)", "moyenne", "Construction"),
    ("corners", "Corners", "somme", "Attaque"),
    ("offsides", "Hors-jeu", "somme", "Attaque"),
    ("saves", "Arrêts du gardien", "somme", "Défense"),
    ("clean_sheet", "Matchs sans encaisser", "somme", "Défense"),
    ("tackles", "Tacles", "somme", "Défense"),
    ("fouls_committed", "Fautes commises", "somme", "Discipline"),
    ("yellow_cards", "Cartons jaunes", "somme", "Discipline"),
    ("red_cards", "Cartons rouges", "somme", "Discipline"),
    ("distance_covered", "Distance parcourue (km)", "somme", "Physique"),
    ("top_speed", "Vitesse max. (km/h)", "max", "Physique"),
]
STATS_ENTETE = ["matches_appearance", "played_time"]
STATS_JOUEUR = ["matches_appearance", "minutes_played_official", "goals", "assists", "yellow_cards", "red_cards",
                "saves", "clean_sheet", "goals_conceded"]
POSTES = {"GOALKEEPER": ("Gardiens", 0), "DEFENDER": ("Défenseurs", 1), "MIDFIELDER": ("Milieux", 2), "FORWARD": ("Attaquants", 3)}
STATUTS = {"FINISHED": "Terminé", "LIVE": "En cours", "UPCOMING": "À venir", "POSTPONED": "Reporté",
           "CANCELLED": "Annulé", "ABANDONED": "Arrêté", "SUSPENDED": "Suspendu"}


# ------------------------------------------------------------------------------
# Fonctions pures
# ------------------------------------------------------------------------------
def logos_equipe(team_id: str) -> Dict[str, str]:
    base = "https://img.uefa.com/imgml/TP/teams/logos/%dx%d/" + str(team_id) + ".png"
    return {str(n): base % (n, n) for n in (70, 240, 700)}


def nombre(v: Any) -> Any:
    """Valeur numérique d'une statistique UEFA (chaîne), ou None."""
    return to_number(v)


def extraire_match(m: Dict[str, Any], club_id: str, comp: str, soirees_dispo: Optional[set] = None) -> Optional[Dict[str, Any]]:
    """Un match du club : date, tour, domicile / extérieur, adversaire, score, statut. None si le club n'y joue pas."""
    h, a = m.get("homeTeam") or {}, m.get("awayTeam") or {}
    dom = str(h.get("id")) == str(club_id)
    if not dom and str(a.get("id")) != str(club_id):
        return None
    adv_t = a if dom else h
    adv = uefa.team_info(adv_t)
    st = uefa.stage_info(m)
    kick = m.get("kickOffTime") or {}
    jour = (kick.get("date") or "")[:10]
    out: Dict[str, Any] = {
        "match_id": str(m.get("id")), "date": jour, "heure_utc": kick.get("dateTime") or "", "comp": comp,
        "stage": st["stage"], "tour": st["round"]["name"], "tour_type": st["round"]["type"],
        "journee": st["matchday_short"], "manche": st["leg"],
        "domicile": dom,
        "adversaire": {"id": adv["id"], "nom": adv["name"], "logo": adv_t.get("logoUrl") or "",
                       "pays": adv["country"], "drapeau": adv["flag"]},
        "statut": STATUTS.get(m.get("status"), m.get("status") or ""),
        "statut_uefa": m.get("status") or "",
    }
    stade = m.get("stadium") or {}
    if stade:
        out["stade"] = fr(stade.get("translations"), "name")
    total = ((m.get("score") or {}).get("total")) or {}
    if m.get("status") in ("FINISHED", "LIVE") and total.get("home") is not None and total.get("away") is not None:
        h_s, a_s = int(to_number(total["home"]) or 0), int(to_number(total["away"]) or 0)
        pour, contre = (h_s, a_s) if dom else (a_s, h_s)
        out["pour"], out["contre"] = pour, contre
        pen = ((m.get("score") or {}).get("penalty")) or {}
        if pen.get("home") is not None and pen.get("away") is not None:
            ph, pa = int(to_number(pen["home"]) or 0), int(to_number(pen["away"]) or 0)
            out["tab"] = {"pour": ph if dom else pa, "contre": pa if dom else ph}
        if m.get("status") == "FINISHED":
            out["resultat"] = "V" if pour > contre else "D" if pour < contre else "N"
    if soirees_dispo is not None and jour in soirees_dispo:
        out["soiree"] = jour
    return out


def trier_matchs(matchs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Chronologique (le plus ancien d'abord) ; les doublons d'identifiant de match sont écartés."""
    vus, out = set(), []
    for x in sorted(matchs, key=lambda x: (x.get("heure_utc") or x.get("date") or "", x["match_id"])):
        if x["match_id"] in vus:
            continue
        vus.add(x["match_id"])
        out.append(x)
    return out


def vnd(matchs: List[Dict[str, Any]], comp: Optional[str] = None) -> Dict[str, int]:
    """Victoires / nuls / défaites calculés sur les scores des matchs terminés (tirs au but : un nul)."""
    c = Counter(x["resultat"] for x in matchs if x.get("resultat") and (comp is None or x["comp"] == comp))
    return {"v": c["V"], "n": c["N"], "d": c["D"]}


def forme(matchs: List[Dict[str, Any]], n: int = 5) -> List[str]:
    """Résultats V/N/D des n derniers matchs terminés, du plus ancien au plus récent."""
    return [x["resultat"] for x in matchs if x.get("resultat")][-n:]


def prochain_match(matchs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    a_venir = [x for x in matchs if x.get("statut_uefa") in ("UPCOMING", "LIVE")]
    return a_venir[0] if a_venir else None


def stade_principal(matchs_uefa: List[Dict[str, Any]], club_id: str) -> Optional[Dict[str, Any]]:
    """Stade le plus fréquent des matchs À DOMICILE du club (un club peut avoir deux stades dans la saison) ; capacité,
    ouverture, ville et coordonnées telles que l'UEFA les donne. None sans match à domicile."""
    cpt: Counter = Counter()
    par_id: Dict[str, Dict[str, Any]] = {}
    for m in matchs_uefa:
        if str((m.get("homeTeam") or {}).get("id")) != str(club_id):
            continue
        s = m.get("stadium") or {}
        if not s.get("id"):
            continue
        cpt[str(s["id"])] += 1
        par_id[str(s["id"])] = s
    if not cpt:
        return None
    sid = sorted(cpt, key=lambda k: (-cpt[k], k))[0]
    s = par_id[sid]
    out: Dict[str, Any] = {"id": sid, "nom": fr(s.get("translations"), "name"), "source": "UEFA"}
    ville = fr((s.get("city") or {}).get("translations"), "name")
    if ville:
        out["ville"] = ville
    if to_number(s.get("capacity")):
        out["capacite"] = int(to_number(s["capacity"]))
    if s.get("openingDate"):
        out["ouverture"] = str(s["openingDate"])[:10]
    geo = s.get("geolocation") or {}
    if geo.get("latitude") is not None and geo.get("longitude") is not None:
        out["lat"], out["lon"] = geo["latitude"], geo["longitude"]
    if len(cpt) > 1:
        out["autres_stades"] = [fr(par_id[k].get("translations"), "name") for k in sorted(cpt) if k != sid]
    return out


def extraire_rang(item: Dict[str, Any], comp: str) -> Dict[str, Any]:
    """Ligne du classement UEFA actuel (phase de ligue) d'un club."""
    def n(k):
        v = to_number(item.get(k))
        return int(v) if v is not None else None
    out = {"comp": comp, "rang": n("rank"), "points": n("points"), "joues": n("played"), "v": n("won"), "n": n("drawn"),
           "d": n("lost"), "bp": n("goalsFor"), "bc": n("goalsAgainst"), "diff": n("goalDifference"),
           "rang_precedent": n("previousRank"), "tendance": item.get("rankTrend") or ""}
    return {k: v for k, v in out.items() if v is not None and v != ""}


def parse_stats_equipe(reponse: Any) -> Dict[str, Dict[str, Any]]:
    """Réponse compstats team-statistics -> {teamId: {stat: nombre}} (clé absente = absente)."""
    out: Dict[str, Dict[str, Any]] = {}
    for t in reponse if isinstance(reponse, list) else []:
        if not isinstance(t, dict) or t.get("teamId") is None:
            continue
        out[str(t["teamId"])] = {s.get("name"): nombre(s.get("value")) for s in t.get("statistics") or []
                                 if nombre(s.get("value")) is not None}
    return out


def par_match(cumuls: Dict[str, Any]) -> Dict[str, Any]:
    """Moyennes par match calculées : cumul / matchs pour les sommes, valeur telle quelle pour une moyenne ou un record."""
    n = cumuls.get("matches_appearance")
    out: Dict[str, Any] = {}
    for cle, _, type_, _g in STATS_CLUB:
        v = cumuls.get(cle)
        if v is None:
            continue
        if type_ == "somme":
            if n:
                out[cle] = round(v / n, 2)
        else:
            out[cle] = v
    return out


def moyenne_competition(par_club: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Moyenne, sur les clubs de la compétition, de la valeur par match de chaque statistique (CALCULÉE ici, pas une
    donnée UEFA). `n` = nombre de clubs pris en compte (matchs > 0)."""
    valeurs: Dict[str, List[float]] = {}
    clubs = 0
    for cumuls in par_club.values():
        if not cumuls.get("matches_appearance"):
            continue
        clubs += 1
        for k, v in par_match(cumuls).items():
            valeurs.setdefault(k, []).append(v)
    out: Dict[str, Any] = {k: round(sum(v) / len(v), 2) for k, v in valeurs.items()}
    return {"valeurs": out, "clubs": clubs} if clubs else {}


def bloc_stats(cumuls: Dict[str, Any], matchs: List[Dict[str, Any]], comp: str, moy: Dict[str, Any]) -> Dict[str, Any]:
    """Statistiques d'un club dans une compétition : cumuls officiels UEFA, V/N/D calculés, moyennes par match calculées,
    moyenne de la compétition (calculée)."""
    out: Dict[str, Any] = {"matchs": int(cumuls.get("matches_appearance") or 0)}
    cum = {k: v for k, v in cumuls.items() if v is not None}
    if cum:
        out["cumul"] = cum
        out["par_match"] = par_match(cumuls)
    out["vnd"] = vnd(matchs, comp)
    if moy:
        out["moyenne_competition"] = moy
    return out


def extraire_joueur(p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Un joueur inscrit (comp.uefa.com/v2/players). None sans identifiant."""
    if not p.get("id"):
        return None
    pays = (p.get("countryCode") or "").upper()
    tr = p.get("translations")
    out: Dict[str, Any] = {
        "id": str(p["id"]), "nom": p.get("internationalName") or fr(tr, "name"),
        "nom_court": p.get("clubShirtName") or fr(tr, "shortName"),
        "poste": p.get("fieldPosition") or "", "poste_fr": fr(tr, "fieldPosition"),
    }
    if p.get("clubJerseyNumber") not in (None, ""):
        out["numero"] = str(p["clubJerseyNumber"])
    if to_number(p.get("age")) is not None:
        out["age"] = int(to_number(p["age"]))
    if p.get("birthDate"):
        out["naissance"] = str(p["birthDate"])[:10]
    if pays:
        out["pays"] = pays
        out["nationalite"] = fr(tr, "countryName", pays)
        if FLAG_CODES.get(pays):
            out["drapeau"] = FLAG_CODES[pays]
    if p.get("imageUrl"):
        out["photo"] = p["imageUrl"]
    if to_number(p.get("height")):
        out["taille"] = int(to_number(p["height"]))
    return {k: v for k, v in out.items() if v not in ("", None)}


def effectif_depuis_inscrits(inscrits: List[Dict[str, Any]], club_id: str) -> List[Dict[str, Any]]:
    """Joueurs du club (clubId) ayant un numéro de club : l'UEFA inscrit aussi des jeunes sans numéro (voir `stats`)."""
    out, vus = [], set()
    for p in inscrits:
        if str(p.get("clubId")) != str(club_id):
            continue
        j = extraire_joueur(p)
        if j and j["id"] not in vus:
            vus.add(j["id"])
            out.append(j)
    return out


def parse_stats_joueurs(reponse: Any) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for x in reponse if isinstance(reponse, list) else []:
        if isinstance(x, dict) and x.get("playerId") is not None:
            out[str(x["playerId"])] = {s.get("name"): nombre(s.get("value")) for s in x.get("statistics") or []
                                       if nombre(s.get("value")) is not None}
    return out


def appliquer_stats_joueurs(effectif: List[Dict[str, Any]], par_comp: Dict[str, Dict[str, Dict[str, Any]]]) -> None:
    """Ajoute à chaque joueur `stats = {comp: {stat: valeur}}` pour les seules compétitions où il a des minutes
    (un joueur sans minutes n'a pas de `stats`) ; `joue` = au moins une minute."""
    for j in effectif:
        stats = {}
        for comp, table in par_comp.items():
            s = table.get(j["id"]) or {}
            if (s.get("minutes_played_official") or 0) > 0 or (s.get("matches_appearance") or 0) > 0:
                stats[comp] = {k: v for k, v in s.items() if k in STATS_JOUEUR}
        if stats:
            j["stats"] = stats
            j["joue"] = True
        else:
            j.pop("stats", None)
            j.pop("joue", None)


def trier_effectif(effectif: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Par poste (gardiens, défenseurs, milieux, attaquants), puis numéro, puis nom."""
    def cle(j):
        num = to_number(j.get("numero"))
        return (POSTES.get(j.get("poste"), ("", 9))[1], num if num is not None else 999, j.get("nom") or "")
    return sorted(effectif, key=cle)


# ------------------------------------------------------------------------------
# Wikidata / Wikipédia
# ------------------------------------------------------------------------------
def requete_sparql(ids_uefa: List[str], qids_alias: List[str]) -> str:
    vals_uefa = " ".join('"%s"' % i for i in ids_uefa)
    vals_qid = " ".join("wd:%s" % q for q in qids_alias)
    return f"""SELECT ?item ?uefa ?inc ?site ?nick ?hqLabel ?frtitle WHERE {{
  {{ VALUES ?uefa {{ {vals_uefa} }} ?item wdt:P7361 ?uefa . }}
  {"UNION { VALUES ?item { %s } }" % vals_qid if qids_alias else ""}
  OPTIONAL {{ ?item wdt:P571 ?inc . }}
  OPTIONAL {{ ?item wdt:P856 ?site . }}
  OPTIONAL {{ ?item wdt:P1449 ?nick . FILTER(LANG(?nick) IN ("fr", "")) }}
  OPTIONAL {{ ?item wdt:P159 ?hq . }}
  OPTIONAL {{ ?w schema:about ?item ; schema:isPartOf <https://fr.wikipedia.org/> ; schema:name ?frtitle . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "fr,en". }}
}}"""


def lire_alias(chemin: str = ALIAS) -> Dict[str, Dict[str, Any]]:
    """{id UEFA: {qid, valide_le, note}} (rapprochements validés à la main par le propriétaire)."""
    try:
        with open(chemin, "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    return {str(k): v for k, v in d.items() if isinstance(v, dict) and re.match(r"^Q\d+$", str(v.get("qid", "")))}


def _qid(uri: str) -> str:
    return (uri or "").rsplit("/", 1)[-1]


def parse_wikidata(reponse: Any, alias: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Résultat SPARQL -> {id UEFA: fiche}. Rapprochement par P7361 (preuve « P7361 »), sinon par alias validé (preuve
    « alias »). Plusieurs valeurs différentes d'une même propriété : fondation = la plus ancienne, les autres champs = les
    premières par ordre alphabétique de la valeur (tri stable) ; aucune valeur n'est fabriquée."""
    lignes = (((reponse or {}).get("results") or {}).get("bindings")) or []
    par_qid: Dict[str, Dict[str, set]] = {}
    uefa_de_qid: Dict[str, set] = {}
    for b in lignes:
        qid = _qid((b.get("item") or {}).get("value"))
        if not qid:
            continue
        g = par_qid.setdefault(qid, {})
        for cle in ("inc", "site", "nick", "hqLabel", "frtitle"):
            if b.get(cle, {}).get("value"):
                g.setdefault(cle, set()).add(b[cle]["value"])
        if b.get("uefa", {}).get("value"):
            uefa_de_qid.setdefault(qid, set()).add(b["uefa"]["value"])
    out: Dict[str, Dict[str, Any]] = {}

    def fiche(qid: str, preuve: str) -> Dict[str, Any]:
        g = par_qid.get(qid, {})
        f: Dict[str, Any] = {"qid": qid, "preuve": preuve}
        if g.get("inc"):
            # l'année seulement : la précision d'une date Wikidata (jour / année) n'est pas lue, un 1er janvier peut être un défaut
            annees = [int(m.group(0)) for m in (re.match(r"^\+?\d{1,4}", d) for d in sorted(g["inc"])) if m]
            if annees:
                f["fondation_annee"] = min(annees)
        if g.get("site"):
            f["site"] = sorted(g["site"])[0]
        if g.get("nick"):
            f["surnom"] = sorted(g["nick"])[0]
        if g.get("hqLabel") and not re.match(r"^Q\d+$", sorted(g["hqLabel"])[0]):
            f["ville_siege"] = sorted(g["hqLabel"])[0]
        if g.get("frtitle"):
            f["titre_wikipedia"] = sorted(g["frtitle"])[0]
        return f

    for qid, ids in uefa_de_qid.items():
        for i in ids:
            out[i] = fiche(qid, "P7361")
    for i, a in alias.items():
        if i not in out and a["qid"] in par_qid:
            out[i] = fiche(a["qid"], "alias")
            out[i]["valide_le"] = a.get("valide_le", "")
    return out


def resume_intro(texte: str, mini: int = 250, maxi: int = 900) -> str:
    """Début de l'introduction d'un article (texte brut) : paragraphes entiers jusqu'à `mini` caractères ; un paragraphe
    qui ferait dépasser `maxi` n'est pas ajouté (le premier est toujours gardé, coupé à la dernière phrase entière)."""
    paras = [p.strip() for p in (texte or "").split("\n") if p.strip()]
    out = ""
    for p in paras:
        if out and (len(out) >= mini or len(out) + len(p) + 1 > maxi):
            break
        out = (out + "\n" + p) if out else p
    if len(out) > maxi:
        coupe = out[:maxi]
        i = max(coupe.rfind(". "), coupe.rfind(".\n"))
        out = coupe[:i + 1] if i >= 100 else coupe.rsplit(" ", 1)[0] + "…"
    return out


def parse_wikipedia_lot(reponse: Any, titres: List[str]) -> Dict[str, Dict[str, Any]]:
    """Réponse MediaWiki (`prop=extracts|info|pageprops`, redirections suivies) -> {titre demandé: {extrait, titre, url,
    licence}}. Pas d'entrée pour une page absente, sans extrait ou d'homonymie."""
    q = (reponse or {}).get("query") or {}
    suite = {}
    for liste in (q.get("normalized") or [], q.get("redirects") or []):
        for r in liste:
            suite[r.get("from")] = r.get("to")
    pages = {p.get("title"): p for p in q.get("pages") or [] if isinstance(p, dict)}
    out: Dict[str, Dict[str, Any]] = {}
    for t in titres:
        cible, vus = t, 0
        while cible in suite and vus < 5:
            cible, vus = suite[cible], vus + 1
        p = pages.get(cible)
        if not p or p.get("missing") or "disambiguation" in (p.get("pageprops") or {}):
            continue
        extrait = resume_intro(p.get("extract") or "")
        if not extrait:
            continue
        d = {"extrait": extrait, "titre": p.get("title") or cible, "url": p.get("fullurl") or "",
             "licence": "CC BY-SA 4.0", "licence_url": "https://creativecommons.org/licenses/by-sa/4.0/deed.fr"}
        out[t] = {k: v for k, v in d.items() if v}
    return out


def a_rafraichir(bloc: Optional[Dict[str, Any]], aujourdhui: dt.date, jours: int = JOURS_CACHE_WIKI) -> bool:
    """Vrai si le bloc manque ou date de plus de `jours` jours (cache mensuel)."""
    if not bloc or not bloc.get("maj"):
        return True
    try:
        return (aujourdhui - dt.date.fromisoformat(bloc["maj"][:10])).days >= jours
    except ValueError:
        return True


# ------------------------------------------------------------------------------
# Réseau poli (Wikidata, Wikipédia)
# ------------------------------------------------------------------------------
def get_poli(url: str, accept: str = "application/json", essais: int = 3, pause_429: float = 20.0) -> Optional[Any]:
    """GET JSON avec User-Agent explicite ; HTTP 429 / 503 : attend `Retry-After` (borné à 90 s) puis reprend. None si échec.
    L'attente est celle que le serveur demande : redemander avant la fin la rallonge."""
    for i in range(essais):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA_WIKI, "Accept": accept})
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read()
                if body[:2] == b"\x1f\x8b":
                    body = gzip.decompress(body)
                return json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (404, 400):
                print(f"[WARN] HTTP {e.code} sur {url[:120]}")
                return None
            try:
                attente = float(e.headers.get("Retry-After", "") or pause_429)
            except (TypeError, ValueError):
                attente = pause_429
            attente = min(90.0, max(5.0, attente)) + 2
            print(f"[WARN] HTTP {e.code} sur {url[:100]} : nouvelle tentative dans {attente:.0f} s")
            if i < essais - 1:
                time.sleep(attente)
        except Exception as e:  # réseau, JSON illisible
            print(f"[WARN] Erreur sur {url[:100]} : {e}")
            time.sleep(3 * (i + 1))
    return None


def interroger_wikidata(ids_uefa: List[str], alias: Dict[str, Dict[str, Any]], essais: int = 3) -> Optional[Dict[str, Dict[str, Any]]]:
    q = requete_sparql(ids_uefa, [a["qid"] for a in alias.values()])
    url = "https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(q)
    rep = get_poli(url, accept="application/sparql-results+json", essais=essais)
    return None if rep is None else parse_wikidata(rep, alias)


def interroger_wikipedia(titres: List[str], essais: int = 3) -> Optional[Dict[str, Dict[str, Any]]]:
    """Introduction de 20 articles au plus en une requête. None si la requête a échoué."""
    url = ("https://fr.wikipedia.org/w/api.php?action=query&prop=extracts%7Cinfo%7Cpageprops&ppprop=disambiguation&inprop=url"
           "&exintro=1&explaintext=1&exlimit=20&redirects=1&format=json&formatversion=2&titles="
           + urllib.parse.quote("|".join(titres), safe=""))
    rep = get_poli(url, essais=essais)
    return None if rep is None else parse_wikipedia_lot(rep, titres)


# ------------------------------------------------------------------------------
# Lecture / écriture
# ------------------------------------------------------------------------------
def lire(chemin: str, defaut: Any = None) -> Any:
    try:
        with open(chemin, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return defaut


def ecrire(chemin: str, data: Any) -> bool:
    """JSON compact ; n'écrit que si le contenu (hors `maj`) change. Vrai si le fichier a été (ré)écrit."""
    texte = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
    ancien = lire(chemin)
    if ancien is not None and _sans_maj(ancien) == _sans_maj(data):
        return False
    os.makedirs(os.path.dirname(chemin) or ".", exist_ok=True)
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(texte + "\n")
    return True


def _sans_maj(x: Any, garder: bool = False) -> Any:
    """Contenu sans les horodatages `maj` (un passage qui ne change rien ne réécrit pas le fichier) — sauf ceux des blocs
    `wikidata` / `wikipedia`, qui servent de cache mensuel et doivent donc être réécrits à chaque rafraîchissement."""
    if isinstance(x, dict):
        return {k: _sans_maj(v, k in ("wikidata", "wikipedia")) for k, v in x.items() if garder or k != "maj"}
    if isinstance(x, list):
        return [_sans_maj(v, garder) for v in x]
    return x


def observer_maillots(m: Dict[str, Any], lineups: Dict[str, Any]) -> Dict[str, Any]:
    """Maillots portés dans un match terminé : {d: date, e: {club: [code maillot | None, hex | None]}}. Rien n'est déduit :
    une composition sans `shirtColor` / `kitImageUrl` donne None."""
    kits = uefa.kit_info(lineups)
    obs: Dict[str, Any] = {}
    for cote, cle in (("home", "homeTeam"), ("away", "awayTeam")):
        tid = str((m.get(cle) or {}).get("id") or "")
        if not tid:
            continue
        k = kits.get(cote) or {}
        obs[tid] = [couleurs.code_maillot(k.get("kit_image")), k.get("shirt_color")]
    return {"d": ((m.get("kickOffTime") or {}).get("date") or "")[:10], "e": obs}


def collecter_couleurs(ctx: "Contexte", dossier: str, max_nouveaux: Optional[int] = None) -> Dict[str, Dict[str, Any]]:
    """Complète `clubs/couleurs.json` avec les compositions des matchs terminés pas encore lus (au plus `max_nouveaux`,
    les plus récents d'abord ; None = tous) et renvoie les observations. Une composition illisible n'est pas notée (relue
    au passage suivant) ; une composition lue sans couleur l'est (inutile de la relire)."""
    chemin = os.path.join(dossier, COULEURS)
    obs = lire(chemin, {}) or {}
    vus = 0
    a_lire = [m for comp in uefa.COMPETITION_IDS for m in ctx.matchs_uefa.get(comp, [])
              if m.get("status") == "FINISHED" and str(m.get("id")) not in obs]
    a_lire.sort(key=lambda m: (m.get("kickOffTime") or {}).get("dateTime") or "", reverse=True)
    for m in a_lire:
        if max_nouveaux is not None and vus >= max_nouveaux:
            break
        vus += 1
        lineups = uefa.fetch_lineups(str(m.get("id")))
        if not lineups:
            continue
        obs[str(m.get("id"))] = observer_maillots(m, lineups)
    if a_lire:
        print(f"[CLUBS] couleurs : {vus} composition(s) lue(s), {len(a_lire) - vus} restante(s) pour un prochain passage")
        ecrire(chemin, dict(sorted(obs.items())))
    return obs


def soirees_disponibles(dossier_soirees: str = "soirees") -> set:
    try:
        return {f[:-5] for f in os.listdir(dossier_soirees) if re.match(r"^\d{4}-\d{2}-\d{2}\.json$", f)}
    except OSError:
        return set()


# ------------------------------------------------------------------------------
# Collecte UEFA
# ------------------------------------------------------------------------------
def standings_brut(comp: str, saison: int) -> List[Dict[str, Any]]:
    data = fetch_json(f"https://standings.uefa.com/v1/standings?competitionId={uefa.COMPETITION_IDS[comp]}"
                      f"&seasonYear={saison}&language=FR") or []
    groupes = [g for g in data if isinstance(g, dict) and (g.get("group") or {}).get("phase") == "TOURNAMENT"] or data
    if not groupes:
        return []
    return max(groupes, key=lambda g: len(g.get("items", []))).get("items", [])


def stats_equipes(comp: str, saison: int, ids: List[str]) -> Dict[str, Dict[str, Any]]:
    cles = ",".join([k for k, *_ in STATS_CLUB] + STATS_ENTETE)
    out: Dict[str, Dict[str, Any]] = {}
    for i in range(0, len(ids), 40):
        lot = ",".join(ids[i:i + 40])
        rep = fetch_json(f"https://compstats.uefa.com/v1/team-statistics?competitionId={uefa.COMPETITION_IDS[comp]}"
                         f"&seasonYear={saison}&teamId={lot}&stats={cles}")
        out.update(parse_stats_equipe(rep))
    return out


def joueurs_inscrits(comp: str, saison: int) -> Optional[List[Dict[str, Any]]]:
    """Tous les joueurs inscrits dans la compétition (le filtre par club est ignoré par l'API : on filtre ensuite)."""
    out: List[Dict[str, Any]] = []
    for offset in range(0, 20000, 500):
        data = fetch_json(f"https://comp.uefa.com/v2/players?competitionId={uefa.COMPETITION_IDS[comp]}"
                          f"&seasonYear={saison}&offset={offset}&limit=500&language=FR")
        if not isinstance(data, list):
            return None if offset == 0 else out
        out.extend(data)
        if len(data) < 500:
            break
    return out


def stats_joueurs(comp: str, saison: int, ids: List[str]) -> Dict[str, Dict[str, Any]]:
    cles = ",".join(STATS_JOUEUR)
    out: Dict[str, Dict[str, Any]] = {}
    for i in range(0, len(ids), 50):
        rep = fetch_json(f"https://compstats.uefa.com/v1/player-statistics?playerId={','.join(ids[i:i + 50])}"
                         f"&competitionId={uefa.COMPETITION_IDS[comp]}&seasonYear={saison}&stats={cles}")
        out.update(parse_stats_joueurs(rep))
    return out


# ------------------------------------------------------------------------------
# Construction des fiches
# ------------------------------------------------------------------------------
def construire_index(standings: Dict[str, List[Dict[str, Any]]], anciens: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Index des clubs : ceux du classement de chaque compétition (phase de ligue). `anciens` = fiches déjà écrites
    (pour y reprendre le QID)."""
    clubs: Dict[str, Dict[str, Any]] = {}
    for comp, items in standings.items():
        for it in items:
            t = uefa.team_info(it.get("team") or {})
            if not t["id"]:
                continue
            c = clubs.setdefault(t["id"], {
                "id": t["id"], "nom": t["name"], "nom_officiel": t["official_name"], "nom_court": t["short"],
                "pays": t["country_name"], "code_pays": t["country"], "drapeau": t["flag"], "francais": t["is_french"],
                "logos": logos_equipe(t["id"]), "competitions": []})
            if comp not in c["competitions"]:
                c["competitions"].append(comp)
    for i, c in clubs.items():
        qid = ((anciens.get(i) or {}).get("wikidata") or {}).get("qid")
        if qid:
            c["qid"] = qid
        c["fichier"] = f"clubs/{i}.json"
    return sorted(clubs.values(), key=lambda c: (c["pays"], c["nom"]))


class Contexte:
    """Données UEFA communes à une exécution (lues une fois)."""

    def __init__(self, saison: int, dossier: str = DOSSIER, dossier_soirees: str = "soirees"):
        self.saison, self.dossier, self.dossier_soirees = saison, dossier, dossier_soirees
        self.standings: Dict[str, List[Dict[str, Any]]] = {}
        self.matchs_uefa: Dict[str, List[Dict[str, Any]]] = {}
        self.stats_equipe: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self.moyennes: Dict[str, Dict[str, Any]] = {}
        self.inscrits: Dict[str, List[Dict[str, Any]]] = {}
        self.soirees = soirees_disponibles(dossier_soirees)

    def charger(self, avec_inscrits: bool) -> bool:
        """Lit listes de saison, classements et cumuls d'équipe ; False si une liste de saison est illisible."""
        uefa._SAISONS.clear()
        for comp in uefa.COMPETITION_IDS:
            ms = uefa.fetch_season_matches(comp, self.saison)
            if ms is None:
                print(f"[ERREUR] Liste de saison {comp} {self.saison} illisible : pas de mise à jour des clubs")
                return False
            self.matchs_uefa[comp] = ms
            self.standings[comp] = standings_brut(comp, self.saison)
            ids = [str((it.get("team") or {}).get("id")) for it in self.standings[comp]]
            self.stats_equipe[comp] = stats_equipes(comp, self.saison, ids) if ids else {}
            self.moyennes[comp] = moyenne_competition({i: self.stats_equipe[comp].get(i, {}) for i in ids})
            if avec_inscrits:
                ins = joueurs_inscrits(comp, self.saison)
                if ins is None:
                    print(f"[WARN] Effectif inscrit {comp} illisible : effectifs conservés tels quels")
                else:
                    self.inscrits[comp] = ins
        return True

    def comps_du_club(self, club_id: str) -> List[str]:
        """Compétitions où le club a au moins un match cette saison."""
        return [c for c in uefa.COMPETITION_IDS
                if any(extraire_match(m, club_id, c) for m in self.matchs_uefa.get(c, []))]


def construire_fiche(ctx: Contexte, entree: Dict[str, Any], ancienne: Optional[Dict[str, Any]], maintenant: str,
                     avec_effectif: bool) -> Dict[str, Any]:
    """Fiche d'un club. Les blocs `wikidata` / `wikipedia` / l'effectif de `ancienne` sont conservés (puis éventuellement
    rafraîchis par l'appelant) : un échec d'une source n'efface jamais une valeur déjà obtenue."""
    cid = entree["id"]
    ancienne = ancienne or {}
    matchs: List[Dict[str, Any]] = []
    tous_uefa: List[Dict[str, Any]] = []
    for comp, ms in ctx.matchs_uefa.items():
        for m in ms:
            x = extraire_match(m, cid, comp, ctx.soirees)
            if x:
                matchs.append(x)
                tous_uefa.append(m)
    matchs = trier_matchs(matchs)
    comps_jouees = [c for c in uefa.COMPETITION_IDS if any(x["comp"] == c for x in matchs)]
    fiche: Dict[str, Any] = {
        "id": cid, "nom": entree["nom"], "nom_officiel": entree.get("nom_officiel", ""), "nom_court": entree.get("nom_court", ""),
        "pays": entree["pays"], "code_pays": entree["code_pays"], "drapeau": entree.get("drapeau", ""),
        "francais": entree["francais"], "logos": entree["logos"], "competitions": entree["competitions"],
        "saison_uefa": ctx.saison,
    }
    stade = stade_principal(tous_uefa, cid)
    if stade:
        fiche["stade"] = stade
    elif ancienne.get("stade"):
        fiche["stade"] = ancienne["stade"]
    for bloc in ("wikidata", "wikipedia"):
        if ancienne.get(bloc):
            fiche[bloc] = ancienne[bloc]
    fiche["saison"] = {"matchs": matchs, "forme": forme(matchs)}
    pm = prochain_match(matchs)
    if pm:
        fiche["saison"]["prochain"] = pm["match_id"]
    rangs = []
    for comp, items in ctx.standings.items():
        for it in items:
            if str((it.get("team") or {}).get("id")) == cid:
                rangs.append(extraire_rang(it, comp))
    if rangs:
        fiche["rang"] = rangs
    stats = {}
    for comp in comps_jouees:
        cumuls = ctx.stats_equipe.get(comp, {}).get(cid)
        if cumuls:
            moy = ctx.moyennes.get(comp) or {}
            stats[comp] = bloc_stats(cumuls, matchs, comp, dict(moy, maj=maintenant[:10]) if moy else {})
    if stats:
        fiche["stats"] = stats
    # effectif : relu seulement en mise à jour complète (ou s'il manque) ; stats des joueurs toujours rafraîchies
    effectif = [dict(j) for j in (ancienne.get("effectif") or [])]
    if avec_effectif or not effectif:
        inscrits = [p for comp in ctx.inscrits for p in ctx.inscrits[comp] if str(p.get("clubId")) == cid]
        if inscrits:
            effectif = effectif_depuis_inscrits(inscrits, cid)
    fiche["effectif"] = effectif
    fiche["maj"] = maintenant
    return fiche


def completer_stats_joueurs(ctx: Contexte, fiches: Dict[str, Dict[str, Any]]) -> None:
    """Stats cumulées officielles des joueurs de ces fiches, une requête par lot de 50 et par compétition."""
    par_comp_ids: Dict[str, List[str]] = {}
    for f in fiches.values():
        for comp in {x["comp"] for x in f["saison"]["matchs"] if x.get("resultat") or x.get("statut_uefa") == "LIVE"}:
            par_comp_ids.setdefault(comp, []).extend(j["id"] for j in f["effectif"])
    tables = {comp: stats_joueurs(comp, ctx.saison, sorted(set(ids))) for comp, ids in par_comp_ids.items()}
    for f in fiches.values():
        comps_club = {x["comp"] for x in f["saison"]["matchs"]}
        appliquer_stats_joueurs(f["effectif"], {c: t for c, t in tables.items() if c in comps_club})
        f["effectif"] = trier_effectif(f["effectif"])


def rafraichir_wiki(fiches: Dict[str, Dict[str, Any]], maintenant: str, alias: Dict[str, Dict[str, Any]],
                    forcer: bool = False, sauver=None, echecs_max: int = 3, essais: int = 3) -> None:
    """Wikidata (un appel SPARQL pour tous les clubs à rafraîchir) puis Wikipédia (≥ 2 s entre requêtes). `sauver(club_id)`
    est appelé après chaque club mis à jour (une panne en cours de route ne perd rien). Après `echecs_max` échecs de suite
    de Wikipédia (limite de débit), les clubs restants sont laissés au prochain passage."""
    auj = dt.date.fromisoformat(maintenant[:10])
    besoin_wd = [i for i, f in fiches.items() if forcer or a_rafraichir(f.get("wikidata"), auj)]
    if besoin_wd:
        res = interroger_wikidata(sorted(besoin_wd), {i: a for i, a in alias.items() if i in besoin_wd}, essais)
        if res is None:
            print("[WARN] Wikidata injoignable : valeurs précédentes conservées")
        else:
            for i in besoin_wd:
                if i in res:
                    fiches[i]["wikidata"] = dict(res[i], maj=maintenant)
                    print(f"[WIKIDATA] {fiches[i]['nom']} -> {res[i]['qid']} ({res[i]['preuve']})")
                else:
                    print(f"[WIKIDATA] {fiches[i]['nom']} : aucun élément rapproché (P7361 ni alias validé)")
            if sauver:
                for i in besoin_wd:
                    sauver(i)
    voulus = [i for i, f in fiches.items() if (f.get("wikidata") or {}).get("titre_wikipedia")
              and (forcer or a_rafraichir(f.get("wikipedia"), auj))]
    echecs = 0
    for k in range(0, len(voulus), 20):
        if echecs >= echecs_max:
            print("[WARN] Wikipédia : échecs de suite (limite de débit ?), les clubs restants seront traités au prochain passage")
            break
        lot = voulus[k:k + 20]
        titres = [fiches[i]["wikidata"]["titre_wikipedia"] for i in lot]
        time.sleep(PAUSE_WIKIPEDIA)
        res = interroger_wikipedia(titres, essais)
        if res is None:
            echecs += 1
            continue
        echecs = 0
        for i, t in zip(lot, titres):
            if t in res:
                fiches[i]["wikipedia"] = dict(res[t], maj=maintenant)
                if sauver:
                    sauver(i)
            else:
                print(f"[WARN] Wikipédia : pas de résumé pour {fiches[i]['nom']} ({t}), valeur précédente conservée")


# ------------------------------------------------------------------------------
# Points d'entrée
# ------------------------------------------------------------------------------
def maintenant_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def mettre_a_jour(ids: Optional[List[str]] = None, saison: Optional[int] = None, dossier: str = DOSSIER,
                  dossier_soirees: str = "soirees", complet: bool = False, avec_wiki: bool = True, patient: bool = True) -> int:
    """Met à jour les fiches des clubs `ids` (None = tous) ; `complet` : effectif inscrit et réécriture de l'index ; `patient` faux
    (passage de soirée) : une seule tentative Wikidata / Wikipédia, jamais d'attente de `Retry-After`.
    Renvoie 0 si tout va bien, 1 si la mise à jour a échoué (rien n'est écrit dans ce cas)."""
    saison = saison or uefa.season_year_for(dt.date.today())
    maintenant = maintenant_iso()
    ctx = Contexte(saison, dossier, dossier_soirees)
    if not ctx.charger(avec_inscrits=complet):
        return 1
    anciens = {}
    for fn in os.listdir(dossier) if os.path.isdir(dossier) else []:
        if re.match(r"^\d+\.json$", fn):
            anciens[fn[:-5]] = lire(os.path.join(dossier, fn)) or {}
    index = construire_index(ctx.standings, anciens)
    if not index:
        print("[ERREUR] Aucun classement UEFA lisible : pas de mise à jour des clubs")
        return 1
    par_id = {c["id"]: c for c in index}
    voulus = [i for i in (ids or par_id)]
    inconnus = [i for i in voulus if i not in par_id]
    if inconnus:
        print(f"[INFO] Clubs hors des classements de la saison (sans fiche) : {', '.join(inconnus)}")
    voulus = [i for i in voulus if i in par_id]
    fiches = {i: construire_fiche(ctx, par_id[i], anciens.get(i), maintenant, complet) for i in voulus}
    completer_stats_joueurs(ctx, fiches)
    try:
        coul = couleurs.couleurs_clubs(collecter_couleurs(ctx, dossier, None if (complet or patient) else MAX_LINEUPS_PASSAGE))
    except Exception as e:  # jamais bloquant : les couleurs déjà écrites sont conservées
        print(f"[WARN] Couleurs des clubs : erreur {type(e).__name__} : {e}")
        coul = {}
    ecrits = 0

    def sauver(i: str) -> None:
        nonlocal ecrits
        if ecrire(os.path.join(dossier, f"{i}.json"), fiches[i]):
            ecrits += 1

    for i in fiches:
        sauver(i)
    try:
        if avec_wiki:
            rafraichir_wiki(fiches, maintenant, lire_alias(), sauver=sauver, echecs_max=3 if patient else 1, essais=3 if patient else 1)
    finally:
        # l'index est écrit même si Wikipédia / Wikidata ont échoué ou ont été interrompus
        chemin_index = os.path.join(dossier, INDEX)
        if complet or not os.path.exists(chemin_index):
            for c in index:
                qid = ((fiches.get(c["id"]) or anciens.get(c["id"]) or {}).get("wikidata") or {}).get("qid")
                if qid:
                    c["qid"] = qid
                if c["id"] in coul:
                    c["couleurs"] = coul[c["id"]]
            ecrire(chemin_index, {"saison": ctx.saison, "maj": maintenant, "clubs": index})
        elif coul:
            # passage de soirée : l'index existant n'est pas reconstruit, seules les couleurs sont complétées
            courant = lire(chemin_index) or {}
            changes = False
            for c in courant.get("clubs") or []:
                if c.get("id") in coul and c.get("couleurs") != coul[c["id"]]:
                    c["couleurs"] = coul[c["id"]]
                    changes = True
            if changes:
                courant["maj"] = maintenant
                ecrire(chemin_index, courant)
    print(f"[CLUBS] {len(fiches)} club(s) traités, {ecrits} fichier(s) modifié(s) (saison {ctx.saison})")
    return 0


def mettre_a_jour_couleurs(saison: Optional[int] = None, dossier: str = DOSSIER, dossier_soirees: str = "soirees") -> int:
    """Couleurs seules (`--couleurs`) : lit les compositions pas encore vues, réécrit `clubs/couleurs.json` et le champ
    `couleurs` de `clubs/index.json` ; ne touche ni aux fiches ni à Wikidata / Wikipédia. 0 = succès, 1 = échec (rien écrit)."""
    saison = saison or uefa.season_year_for(dt.date.today())
    chemin_index = os.path.join(dossier, INDEX)
    courant = lire(chemin_index)
    if not courant or not courant.get("clubs"):
        print("[ERREUR] clubs/index.json absent : lancer d'abord --tous")
        return 1
    ctx = Contexte(saison, dossier, dossier_soirees)
    uefa._SAISONS.clear()
    for comp in uefa.COMPETITION_IDS:
        ms = uefa.fetch_season_matches(comp, saison)
        if ms is None:
            print(f"[ERREUR] Liste de saison {comp} {saison} illisible : couleurs non mises à jour")
            return 1
        ctx.matchs_uefa[comp] = ms
    coul = couleurs.couleurs_clubs(collecter_couleurs(ctx, dossier, None))
    n = 0
    for c in courant["clubs"]:
        if c.get("id") in coul and c.get("couleurs") != coul[c["id"]]:
            c["couleurs"] = coul[c["id"]]
            n += 1
    if n:
        courant["maj"] = maintenant_iso()
        ecrire(chemin_index, courant)
    sans = [c["id"] for c in courant["clubs"] if "couleurs" not in c]
    print(f"[CLUBS] couleurs : {n} club(s) mis à jour, {len(courant['clubs']) - len(sans)}/{len(courant['clubs'])} avec couleurs"
          + (f" ; sans maillot lisible : {', '.join(sans)}" if sans else ""))
    return 0


def clubs_du_jour(data: Dict[str, Any]) -> List[str]:
    """Identifiants des équipes des matchs d'une soirée (data.json / soirees/<date>.json)."""
    ids: List[str] = []
    for comp in (data.get("competitions") or {}).values():
        for m in comp.get("matches") or []:
            for cote in ("home_team", "away_team"):
                i = str((m.get(cote) or {}).get("id") or "")
                if i and i not in ids:
                    ids.append(i)
    return ids


def apres_soiree(data: Dict[str, Any], jour: str, dossier: str = DOSSIER) -> bool:
    """Fin d'un passage de soirée : met à jour les fiches des clubs qui ont joué, plus celles restées « à refaire » d'un
    passage précédent. Ne lève jamais d'exception (la notification ne dépend pas des fiches) ; en cas d'échec, les clubs
    restent dans `clubs/etat.json` et sont repris au passage suivant. Vrai si tout s'est bien passé."""
    try:
        if not os.path.exists(os.path.join(dossier, INDEX)):
            print("[CLUBS] clubs/index.json absent : fiches de club non mises à jour (premier remplissage : clubs.yml)")
            return True
        etat = lire(os.path.join(dossier, ETAT), {}) or {}
        ids = list(dict.fromkeys(clubs_du_jour(data) + list(etat.get("a_refaire") or [])))
        if not ids:
            return True
        saison = uefa.season_year_for(dt.date.fromisoformat(jour))
        ecrire(os.path.join(dossier, ETAT), {"a_refaire": ids})
        code = mettre_a_jour(ids, saison, dossier, complet=False, avec_wiki=True, patient=False)
        if code == 0:
            ecrire(os.path.join(dossier, ETAT), {"a_refaire": []})
            return True
        print(f"[WARN] Fiches de club non mises à jour pour la soirée {jour} : reprise au prochain passage")
        return False
    except Exception as e:  # jamais bloquant
        print(f"[WARN] Fiches de club : erreur {type(e).__name__} : {e} (reprise au prochain passage)")
        return False


# ------------------------------------------------------------------------------
# Tests purs
# ------------------------------------------------------------------------------
def _match_fictif(mid, jour, dom_id, ext_id, h, a, statut="FINISHED", pen=None, stade_id="9", rnd="GROUP"):
    def eq(i, n):
        return {"id": i, "internationalName": n, "countryCode": "FRA", "logoUrl": f"https://img.uefa.com/{i}.png",
                "translations": {"displayName": {"FR": n}, "countryName": {"FR": "France"}}}
    sc = {"total": {"home": h, "away": a}} if statut != "UPCOMING" else None
    if sc and pen:
        sc["penalty"] = {"home": pen[0], "away": pen[1]}
    return {"id": mid, "status": statut, "kickOffTime": {"date": jour, "dateTime": jour + "T20:00:00Z"},
            "homeTeam": eq(dom_id, "Dom"), "awayTeam": eq(ext_id, "Ext"), "score": sc,
            "round": {"mode": rnd, "phase": "TOURNAMENT", "metaData": {"name": "League Phase", "type": "GROUP_STANDINGS"},
                      "translations": {"name": {"FR": "Phase de ligue"}}},
            "matchday": {"translations": {"name": {"FR": "J 4"}}, "type": "MATCHDAY"},
            "stadium": {"id": stade_id, "capacity": 40000, "openingDate": "1905-01-01",
                        "translations": {"name": {"FR": "Stade " + stade_id}},
                        "city": {"translations": {"name": {"FR": "Ville"}}}, "geolocation": {"latitude": 1.5, "longitude": 2.5}}}


def _tests() -> None:
    ok = 0

    def check(cond, msg):
        nonlocal ok
        assert cond, msg
        ok += 1

    # --- extraction de match
    m1 = _match_fictif("1", "2026-11-04", "10", "20", 3, 1)
    x = extraire_match(m1, "10", "ucl", {"2026-11-04"})
    check(x["domicile"] and x["pour"] == 3 and x["contre"] == 1 and x["resultat"] == "V", "domicile gagné")
    check(x["soiree"] == "2026-11-04" and x["adversaire"]["id"] == "20" and x["tour"] == "Phase de ligue", "soirée + adversaire")
    y = extraire_match(m1, "20", "ucl", set())
    check(not y["domicile"] and y["pour"] == 1 and y["contre"] == 3 and y["resultat"] == "D" and "soiree" not in y, "extérieur perdu")
    check(extraire_match(m1, "99", "ucl") is None, "club absent du match")
    m2 = _match_fictif("2", "2026-12-09", "10", "20", 0, 0, "UPCOMING")
    z = extraire_match(m2, "10", "ucl")
    check("pour" not in z and "resultat" not in z and z["statut"] == "À venir", "match à venir : aucun score inventé")
    m3 = _match_fictif("3", "2026-12-10", "10", "20", 1, 1, pen=(4, 5))
    w = extraire_match(m3, "10", "uel")
    check(w["resultat"] == "N" and w["tab"] == {"pour": 4, "contre": 5}, "nul avec tirs au but")
    # --- V/N/D, forme, tri
    ms = trier_matchs([extraire_match(m, c, "ucl") for m, c in ((m3, "10"), (m1, "10"), (m2, "10"), (m1, "10"))])
    check([x["match_id"] for x in ms] == ["1", "2", "3"] or [x["match_id"] for x in ms] == ["1", "3", "2"], "tri + doublon écarté")
    check(len(ms) == 3, "doublon écarté")
    check(vnd(ms) == {"v": 1, "n": 1, "d": 0}, "V/N/D calculés")
    check(forme(ms) == ["V", "N"], "forme")
    check(prochain_match(ms)["match_id"] == "2", "prochain match")
    # --- stade
    st = stade_principal([m1, m2, _match_fictif("5", "2026-10-01", "10", "20", 1, 0, stade_id="8")], "10")
    check(st["nom"] in ("Stade 9", "Stade 8") and st["capacite"] == 40000 and st["ville"] == "Ville" and st["source"] == "UEFA", "stade")
    check(len(st["autres_stades"]) == 1, "deux stades")
    check(stade_principal([m1], "20") is None, "pas de match à domicile = pas de stade")
    # --- rang
    r = extraire_rang({"rank": 3, "points": 9, "played": 4, "won": 3, "drawn": 0, "lost": 1, "goalsFor": 7, "goalsAgainst": 4,
                       "goalDifference": 3, "previousRank": 5, "rankTrend": "UP"}, "ucl")
    check(r["rang"] == 3 and r["rang_precedent"] == 5 and r["tendance"] == "UP", "rang")
    check("rang" not in extraire_rang({}, "ucl"), "rang absent = absent")
    # --- stats d'équipe
    rep = [{"teamId": "10", "statistics": [{"name": "goals", "value": "12"}, {"name": "ball_possession", "value": "54.8"},
                                           {"name": "matches_appearance", "value": "4"}, {"name": "top_speed", "value": "35.6"}]},
           {"teamId": "20", "statistics": [{"name": "goals", "value": "6"}, {"name": "matches_appearance", "value": "3"},
                                           {"name": "ball_possession", "value": "45"}]}]
    pe = parse_stats_equipe(rep)
    check(pe["10"]["goals"] == 12 and pe["10"]["ball_possession"] == 54.8, "parse stats équipe")
    pm = par_match(pe["10"])
    check(pm["goals"] == 3 and pm["ball_possession"] == 54.8 and pm["top_speed"] == 35.6, "par match : somme / moyenne / max")
    check("attempts" not in pm, "statistique absente = absente")
    mc = moyenne_competition(pe)
    check(mc["clubs"] == 2 and mc["valeurs"]["goals"] == 2.5 and mc["valeurs"]["ball_possession"] == 49.9, "moyenne de compétition")
    check(moyenne_competition({"1": {}}) == {}, "aucun club avec matchs = aucune moyenne")
    bs = bloc_stats(pe["10"], ms, "ucl", mc)
    check(bs["matchs"] == 4 and bs["cumul"]["goals"] == 12 and bs["vnd"]["v"] == 1 and "moyenne_competition" in bs, "bloc stats")
    check(par_match({"goals": 5}) == {}, "pas de matchs = pas de moyenne par match")
    # --- effectif
    inscrits = [{"id": "1", "clubId": "10", "internationalName": "A Gardien", "fieldPosition": "GOALKEEPER", "clubJerseyNumber": "1",
                 "age": "30", "birthDate": "1996-01-02", "countryCode": "FRA", "imageUrl": "https://x/1.jpg",
                 "translations": {"fieldPosition": {"FR": "Gardien"}, "countryName": {"FR": "France"}}},
                {"id": "2", "clubId": "10", "internationalName": "B Attaquant", "fieldPosition": "FORWARD", "clubJerseyNumber": "9"},
                {"id": "3", "clubId": "10", "internationalName": "C Défenseur", "fieldPosition": "DEFENDER"},
                {"id": "4", "clubId": "99", "internationalName": "Autre club"}]
    eff = effectif_depuis_inscrits(inscrits, "10")
    check([j["id"] for j in eff] == ["1", "2", "3"], "filtre sur le club")
    check(eff[0]["age"] == 30 and eff[0]["drapeau"] == "fr" and eff[0]["poste_fr"] == "Gardien", "joueur")
    check("age" not in eff[1] and "nationalite" not in eff[1] and "numero" in eff[1], "valeur absente = absente")
    ps = parse_stats_joueurs([{"playerId": "1", "statistics": [{"name": "minutes_played_official", "value": "383"},
                                                              {"name": "goals", "value": "0"}, {"name": "xx", "value": "1"}]},
                              {"playerId": "3", "statistics": [{"name": "yellow_cards", "value": "1"}]}])
    appliquer_stats_joueurs(eff, {"ucl": ps})
    check(eff[0]["joue"] and eff[0]["stats"]["ucl"]["minutes_played_official"] == 383 and "xx" not in eff[0]["stats"]["ucl"], "stats joueur")
    check("stats" not in eff[2] and "joue" not in eff[2], "sans minutes : pas de stats")
    check([j["id"] for j in trier_effectif([eff[1], eff[2], eff[0]])] == ["1", "3", "2"], "tri par poste")
    # --- Wikidata, alias
    sp = {"results": {"bindings": [
        {"item": {"value": "http://www.wikidata.org/entity/Q100"}, "uefa": {"value": "10"}, "inc": {"value": "1905-03-01T00:00:00Z"},
         "site": {"value": "https://club.example"}, "hqLabel": {"value": "Lens"}, "frtitle": {"value": "RC Lens"}},
        {"item": {"value": "http://www.wikidata.org/entity/Q100"}, "uefa": {"value": "10"}, "inc": {"value": "1906-01-01T00:00:00Z"}},
        {"item": {"value": "http://www.wikidata.org/entity/Q200"}, "hqLabel": {"value": "Q123"}}]}}
    wd = parse_wikidata(sp, {"20": {"qid": "Q200", "valide_le": "2026-11-25"}, "30": {"qid": "Q999"}})
    check(wd["10"]["qid"] == "Q100" and wd["10"]["preuve"] == "P7361" and "fondation" not in wd["10"] and wd["10"]["fondation_annee"] == 1905, "Wikidata P7361")
    check(wd["10"]["ville_siege"] == "Lens" and wd["10"]["titre_wikipedia"] == "RC Lens" and "surnom" not in wd["10"], "champs Wikidata, surnom absent")
    check(wd["20"]["preuve"] == "alias" and wd["20"]["valide_le"] == "2026-11-25" and "ville_siege" not in wd["20"], "alias validé, libellé brut Q écarté")
    check("30" not in wd, "alias sans élément lu : rien")
    check("QID absent sans preuve" and "99" not in wd, "club sans P7361 ni alias : absent")
    a = lire_alias(ALIAS)
    check(set(a) == {"79946", "53360", "2603107", "74233", "52883"}, "alias lus")
    check("Q" in requete_sparql(["10"], ["Q1"]) and '"10"' in requete_sparql(["10"], []), "requête SPARQL")
    # --- Wikipédia, cache
    par = ("Le RC Lens est un club de football. " * 8).strip()
    rep_wp = {"query": {"normalized": [{"from": "Rc lens", "to": "RC Lens"}], "redirects": [{"from": "RC Lens", "to": "Racing Club de Lens"}],
                        "pages": [{"title": "Racing Club de Lens", "extract": par + "\nDeuxième paragraphe.\nTroisième.", "fullurl": "https://fr.wikipedia.org/wiki/Racing_Club_de_Lens"},
                                  {"title": "Homonyme", "extract": "x", "pageprops": {"disambiguation": ""}},
                                  {"title": "Absent", "missing": True},
                                  {"title": "Vide", "extract": ""}]}}
    lot = parse_wikipedia_lot(rep_wp, ["Rc lens", "Homonyme", "Absent", "Vide", "Inconnu"])
    check(list(lot) == ["Rc lens"] and lot["Rc lens"]["url"].endswith("Racing_Club_de_Lens") and lot["Rc lens"]["titre"] == "Racing Club de Lens", "résumé Wikipédia : normalisation + redirection")
    check(lot["Rc lens"]["extrait"] == par, "premier paragraphe assez long : seul gardé")
    check(resume_intro("Court.\nDeuxième.\n" + par + "\nFin.") == "Court.\nDeuxième.\n" + par, "paragraphes ajoutés jusqu'à 250 caractères")
    check(parse_wikipedia_lot(None, ["a"]) == {} and parse_wikipedia_lot({}, []) == {}, "pas de réponse = rien")
    check(resume_intro("") == "" and len(resume_intro("A. " * 600)) <= 900, "résumé borné")
    check(resume_intro("Une phrase. " * 100).endswith("."), "coupe à une phrase entière")
    j = dt.date(2026, 11, 25)
    check(a_rafraichir(None, j) and a_rafraichir({}, j) and a_rafraichir({"maj": "2026-10-01T00:00:00Z"}, j), "cache à rafraîchir")
    check(not a_rafraichir({"maj": "2026-11-10T00:00:00Z"}, j), "cache frais")
    # --- écriture : pas de réécriture si seul `maj` change
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "x.json")
        check(ecrire(p, {"a": 1, "maj": "1"}), "première écriture")
        check(not ecrire(p, {"a": 1, "maj": "2"}), "seul maj change : pas de réécriture")
        check(ecrire(p, {"a": 2, "maj": "2"}), "contenu changé : réécriture")
        check(ecrire(p, {"a": 2, "maj": "3", "wikidata": {"maj": "1"}}), "bloc wikidata nouveau")
        check(ecrire(p, {"a": 2, "maj": "4", "wikidata": {"maj": "2"}}), "le maj du cache Wikidata est réécrit")
        check(not ecrire(p, {"a": 2, "maj": "5", "wikidata": {"maj": "2"}}), "seul le maj de la fiche change")
    # --- clubs du jour
    check(clubs_du_jour({"competitions": {"ucl": {"matches": [{"home_team": {"id": "1"}, "away_team": {"id": "2"}},
                                                                {"home_team": {"id": "2"}, "away_team": {"id": "3"}}]}}}) == ["1", "2", "3"], "clubs du jour")
    # --- index
    idx = construire_index({"ucl": [{"team": {"id": "10", "internationalName": "Dom", "countryCode": "FRA",
                                              "translations": {"displayName": {"FR": "Dom"}, "countryName": {"FR": "France"}}}}],
                            "uel": [{"team": {"id": "10", "internationalName": "Dom", "countryCode": "FRA", "translations": {}}}]},
                           {"10": {"wikidata": {"qid": "Q100"}}})
    check(len(idx) == 1 and idx[0]["competitions"] == ["ucl", "uel"] and idx[0]["qid"] == "Q100" and idx[0]["francais"], "index : un club dans deux compétitions")
    # --- couleurs : observation d'un match (jamais de valeur déduite) puis agrégation
    lu = {"homeTeam": {"shirtColor": "#FFFFFF", "kitImageUrl": "https://img.uefa.com/imgml/teamkits/1/2027/10/Kits/pl02.png"},
          "awayTeam": {"kitImageUrl": "https://img.uefa.com/imgml/teamkits/1/2027/20/Kits/pl01.png"}}
    o = observer_maillots(m1, lu)
    check(o["e"] == {"10": ["pl02", "#ffffff"], "20": ["pl01", None]} and o["d"] == "2026-11-04", f"observation : {o}")
    check(observer_maillots(m1, {"homeTeam": {"shirtColor": "pas un hex"}})["e"]["10"] == [None, None], "hex invalide ignoré")
    agr = couleurs.couleurs_clubs({"1": o, "2": {"d": "2026-11-11", "e": {"10": ["pl01", "#c8102e"], "20": ["pl01", "#0000ff"]}}})
    check(agr["10"]["principale"] == "#c8102e" and agr["10"]["secondaire"] == "#ffffff" and agr["10"]["nb_matchs"] == 1, "couleurs du club 10")
    check(agr["20"]["principale"] == "#0000ff" and agr["20"]["secondaire"] is None, "club 20 sans pl02 : pas de secondaire inventée")
    print(f"[OK] clubs.py : {ok} contrôles")


def main() -> None:
    p = argparse.ArgumentParser(description="Fiches de club")
    p.add_argument("--tous", action="store_true", help="mise à jour complète (effectifs, Wikidata, Wikipédia si cache périmé)")
    p.add_argument("--couleurs", action="store_true", help="couleurs des clubs seules (compositions UEFA), sans toucher aux fiches")
    p.add_argument("--clubs", help="identifiants UEFA séparés par des virgules")
    p.add_argument("--saison", type=int)
    p.add_argument("--dossier", default=DOSSIER)
    p.add_argument("--sans-wiki", action="store_true")
    p.add_argument("--test", action="store_true")
    a = p.parse_args()
    if a.test:
        _tests()
        return
    if a.couleurs:
        sys.exit(mettre_a_jour_couleurs(a.saison, a.dossier))
    if not a.tous and not a.clubs:
        p.error("--tous, --clubs ou --couleurs requis")
    ids = [x.strip() for x in a.clubs.split(",") if x.strip()] if a.clubs else None
    sys.exit(mettre_a_jour(ids, a.saison, a.dossier, complet=a.tous, avec_wiki=not a.sans_wiki))


if __name__ == "__main__":
    main()
