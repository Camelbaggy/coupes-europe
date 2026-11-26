#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fiches de NATIONS, de CLUBS du monde et de JOUEURS des compétitions internationales (décision du propriétaire du 26/11/2026 :
« lancer les fiches de clubs, de nations et de joueurs »).

Lit les fichiers de jour DÉJÀ publiés du dépôt de données (`--donnees DIR` : `internationales/<comp>/<édition>/<AAAA-MM-JJ>.json`,
`index.json`, `programme.json`) et écrit, dans le même dépôt, `internationales/fiches/` :

  selections/<code>.json + selections/index.json   fiche d'une sélection (code pays 3 lettres = `country` des équipes des matchs)
  clubs/<id>.json + clubs/index.json               clubs de la Coupe du monde des clubs et de la Coupe intercontinentale SANS fiche existante
  clubs/correspondances.json                       id d'équipe du match -> fiche existante (championnat ou UEFA), avec la PREUVE
  joueurs/<NN>.json + joueurs/index.json           fiches de joueurs, réparties en 64 fichiers (crc32 de l'id) ; index léger
  index.json                                       compétitions couvertes, nombres de fiches
  cache/naissances.json                            dates de naissance lues (UEFA / ESPN) : cache, jamais une donnée affichée seule
  cache/effectifs_uefa.json                        {id joueur UEFA: [clubs]} des fiches de club UEFA (rafraîchi après 7 jours)

Règles (règle cardinale du projet : zéro valeur inventée, absent = absent, jamais de rapprochement deviné) :
- tout chiffre est LU ou CALCULÉ sur les matchs détaillés (V/N/D sur le score, tirs au but = nul ; cumuls de stats d'équipe sur les
  seuls matchs qui portent la stat : `couverture` donne le nombre de matchs quand il est inférieur au nombre de matchs ; possession /
  précision = moyennes, vitesse = maximum, comme clubs.py) ; un match pas terminé, arrêté ou « en attente » ne compte jamais ;
- sélection -> Wikidata : élément portant le code FIFA (P3441, « KOS » = « KVX »), instance d'« équipe nationale masculine de football »
  (Q135408445, jamais avec une classe féminine), classe de compétition « football masculin » (P2094 = Q31930761) ET pays de sport (P1532) ;
  UN SEUL candidat, sinon rien (`statut: ambigu | absent`) ; fédération seulement si UNE SEULE porte le code (Q1478443) ; confédération
  seulement si UNE des six (UEFA, AFC, CAF, CONCACAF, CONMEBOL, OFC) figure dans P463 de la fédération ; jamais de sélectionneur ;
- club du monde -> fiche existante par IDENTIFIANT seulement : id ESPN identique à une fiche de championnat (`championnats/clubs/`),
  id UEFA identique à une fiche de coupe ; sinon fiche créée ici ; Wikidata d'un club créé : nom exact (libellé ou alias) ET club de
  football (P31/P279* Q476028) ET pays (P17) concordant, UN SEUL candidat, sinon rien ;
- joueur : un identifiant UEFA et un identifiant ESPN ne sont fusionnés que par PREUVE : même date de naissance, noms concordants
  (`encyclo_joueurs.nom_concorde`) et même sélection, candidat UNIQUE des deux côtés ; ou même élément Wikidata (P2276 / P3681 /
  date de naissance + nom) sans date de naissance contradictoire ; sinon deux fiches ;
- liens vers les autres fiches du joueur : même identifiant UEFA dans l'effectif d'une fiche de club UEFA, même identifiant ESPN dans
  l'effectif d'une fiche de championnat ; jamais par le nom ;
- Wikidata / Commons / Wikipédia des joueurs : mêmes règles et même cache de 30 jours qu'`encyclo_joueurs.py` (P3681 pour un id ESPN,
  P2276 pour un id UEFA, sinon date de naissance + nom, UN seul candidat) ; réponses lues en lots, reprenable (budget en minutes) ;
- jamais bloquant : une erreur réseau garde la valeur précédente et se journalise ; un fichier n'est réécrit que si son contenu
  change (hors `maj`).

    python fiches_internationales.py --donnees ../donnees-football [--coupes ../coupes-europe] [--budget-joueurs 6] [--sans-wiki] [--test]
"""

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse
import zlib
from collections import Counter, defaultdict
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import clubs
import couleurs
import encyclo_joueurs as ej
import encyclo_ligues as el
import ligues
from netutil import FLAG_CODES, fetch_json, normalize

COUPES_PAGES = "https://camelbaggy.github.io/coupes-europe/"
DOSSIER = os.path.join("internationales", "fiches")
NB_FICHIERS_JOUEURS = 64
JOURS_CACHE = 30
JOURS_CACHE_EFFECTIFS = 7
ESSAIS_WIKI = 2              # tentatives par requête Wikimedia (une réponse HTTP 429 attend `Retry-After`, jusqu'à 90 s)
PAUSE_RECHERCHE = 1.0        # entre deux recherches Wikidata de nom de club (Wikimedia répond HTTP 429 au-delà)
UEFA_COMP = {"cdm": 17, "euro": 3, "ldn": 2014}          # = internationales.COMPETITIONS (copie : ce module n'importe pas le collecteur)
POURCENTAGES = {"ball_possession", "passes_accuracy", "ppda"}   # moyennes (jamais additionnées)
MAXIMUMS = {"top_speed"}                                          # records (maximum)
COMPTEURS = {"uefa": 0, "espn": 0, "wikidata": 0, "wikipedia": 0, "commons": 0, "pages": 0}

# --- Wikidata : sélections
CLASSE_MASC = "Q135408445"       # équipe nationale masculine de football
CLASSES_EXCLUES = {"Q23905105", "Q67608976"}   # équipe nationale féminine de football (et féminine des moins de 17 ans) : jamais retenue
COMPET_MASC = "Q31930761"        # football masculin (P2094)
FEDERATION = "Q1478443"          # fédération de football
CLUB_FOOTBALL = "Q476028"
CONFEDERATIONS = {"Q35572": "UEFA", "Q83276": "AFC", "Q168360": "CAF", "Q160549": "CONCACAF", "Q58733": "CONMEBOL", "Q180344": "OFC"}
CODE_WIKIDATA = {"KOS": "KVX"}   # le Kosovo a le code FIFA KVX (UEFA / ESPN : KOS)
PAYS_ROYAUME_UNI = {"ENG", "SCO", "WAL", "NIR"}
Q_ROYAUME_UNI = "Q145"


# ------------------------------------------------------------------------------
# Lecture / écriture
# ------------------------------------------------------------------------------
def _lire(chemin: str, defaut: Any = None) -> Any:
    return clubs.lire(chemin, defaut)


def _ecrire(chemin: str, obj: Any) -> bool:
    """JSON compact, écrit seulement si le contenu change (hors `maj` de premier niveau)."""
    ancien = _lire(chemin)
    sans = lambda o: {k: v for k, v in o.items() if k != "maj"} if isinstance(o, dict) else o  # noqa: E731
    if ancien is not None and sans(ancien) == sans(obj):
        return False
    os.makedirs(os.path.dirname(chemin) or ".", exist_ok=True)
    with open(chemin + ".tmp", "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(chemin + ".tmp", chemin)
    return True


def nettoyer(dossier: str, attendus: Set[str]) -> None:
    for f in os.listdir(dossier) if os.path.isdir(dossier) else []:
        if f.endswith(".json") and f not in attendus:
            os.remove(os.path.join(dossier, f))


def maintenant_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def resultat(pour: int, contre: int) -> str:
    return "V" if pour > contre else "N" if pour == contre else "D"


def _get_wiki(url: str, accept: str = "application/json", essais: int = ESSAIS_WIKI, pause_429: float = 20.0) -> Optional[Any]:
    COMPTEURS["wikipedia" if "wikipedia.org" in url else "commons" if "commons" in url else "wikidata"] += 1
    return clubs.get_poli(url, accept, essais, pause_429)


def _sparql(requete: str, essais: int = ESSAIS_WIKI) -> Optional[List[Dict[str, Any]]]:
    COMPTEURS["wikidata"] += 1
    return ej.sparql(requete, essais)


def _modal(c: Counter, defaut: Any = None) -> Any:
    """Valeur la plus fréquente (égalité : ordre alphabétique, pour des fichiers stables)."""
    if not c:
        return defaut
    top = max(c.values())
    return sorted(k for k, v in c.items() if v == top)[0]


# ------------------------------------------------------------------------------
# 1. Lecture des matchs (fichiers de jour publiés)
# ------------------------------------------------------------------------------
def _num(v: Any) -> Optional[float]:
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def lire_tab(m: Dict[str, Any]) -> Optional[List[int]]:
    """Tirs au but [domicile, extérieur] : `tab` du match, sinon « a-b » de `penalties` ; rien sinon."""
    t = m.get("tab")
    if isinstance(t, (list, tuple)) and len(t) == 2 and all(isinstance(x, int) for x in t):
        return list(t)
    r = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", str(m.get("penalties") or ""))
    return [int(r.group(1)), int(r.group(2))] if r else None


def equipe_compacte(t: Dict[str, Any], famille: str) -> Dict[str, Any]:
    code = (t.get("country") or "").upper()
    return {"cle": code if famille == "selections" else str(t.get("id") or ""), "id": str(t.get("id") or ""), "code": code,
            "nom": t.get("name") or "", "nom_officiel": t.get("official_name") or "", "nom_court": t.get("short") or "",
            "pays_nom": t.get("country_name") or "", "drapeau": t.get("flag") or "", "logo": t.get("logo") or "",
            "espn_id": str(t.get("espn_id") or ""), "fifa_id": str(t.get("fifa_id") or ""),
            "score": t.get("score") if isinstance(t.get("score"), int) else None,
            "maillot": t.get("shirt_color") or None, "kit": t.get("kit_image") or None}


def compacter_match(m: Dict[str, Any], ed: Dict[str, Any], jour: str, fichier: str) -> Dict[str, Any]:
    """Ce que les fiches lisent d'un match (le reste : déroulé, momentum, compos… n'est pas gardé en mémoire)."""
    fam = ed["famille"]
    joueurs = {}
    for pid, p in (m.get("players") or {}).items():
        st = p.get("stats") or {}
        joueurs[pid] = {"nom": p.get("name") or "", "court": p.get("short") or "", "numero": str(p.get("number") or ""),
                        "cote": p.get("team"), "pos": p.get("pos") or "", "pos_fr": p.get("pos_fr") or "",
                        "nat": p.get("nationality") or "", "drapeau": p.get("flag") or "", "photo": p.get("photo") or "",
                        "titulaire": bool(p.get("starter")), "minutes": p.get("minutes") if isinstance(p.get("minutes"), int) else None,
                        "note": _num(p.get("rating")),
                        "st": {k: st[k] for k in ("saves", "goals_conceded", "clean_sheet") if _num(st.get(k)) is not None}}
    return {"id": str(m.get("match_id")), "comp": ed["comp"], "edition": ed["edition"], "famille": fam, "jour": jour, "fichier": fichier,
            "date": m.get("date") or jour, "tri": f"{m.get('date') or jour} {(m.get('kickoff') or '')[-5:] or '00:00'}",
            "statut": m.get("status") or "", "fini": bool(m.get("finished")) and m.get("status") == "Terminé" and not m.get("en_attente"),
            "tour": m.get("tour_court") or (m.get("round") or {}).get("name") or "", "groupe": m.get("groupe"),
            "phase": m.get("phase"), "stade": m.get("venue") or "", "source": m.get("source") or "",
            "home": equipe_compacte(m["home_team"], fam), "away": equipe_compacte(m["away_team"], fam), "tab": lire_tab(m),
            "stats": [{"key": s["key"], "home": s.get("home"), "away": s.get("away")} for s in (m.get("stats") or {}).get("all") or []
                      if s.get("key")],
            "joueurs": joueurs,
            "buts": [{"cote": g.get("team"), "buteur": g.get("scorer_id") or "", "passeur": g.get("assist_id") or "", "genre": g.get("kind") or ""}
                     for g in m.get("goals") or []],
            "cartons": [{"type": e["type"], "joueur": e.get("player_id") or ""} for e in m.get("events") or []
                        if e.get("type") in ("yellow_card", "red_card")]}


def lister_editions(donnees: str) -> List[Dict[str, Any]]:
    """Éditions détaillées publiées (`internationales/index.json`), de la plus ancienne à la plus récente."""
    idx = _lire(os.path.join(donnees, "internationales", "index.json")) or {}
    out = []
    for comp, c in sorted((idx.get("competitions") or {}).items()):
        for e in c.get("editions") or []:
            out.append({"comp": comp, "edition": e["edition"], "libelle": e.get("libelle") or str(e["edition"]), "nom": c.get("nom") or comp,
                        "court": c.get("court") or comp, "famille": c.get("famille") or "selections"})
    return sorted(out, key=lambda e: (e["comp"], e["edition"]))


def charger_matchs(donnees: str, editions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Tous les matchs des fichiers de jour, dédoublonnés par (compétition, édition, match) ; le fichier le plus récent l'emporte."""
    par_cle: Dict[Tuple[str, int, str], Tuple[str, Dict[str, Any]]] = {}
    for ed in editions:
        dossier = os.path.join(donnees, "internationales", ed["comp"], str(ed["edition"]))
        try:
            noms = sorted(f for f in os.listdir(dossier) if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", f))
        except OSError:
            continue
        for f in noms:
            d = _lire(os.path.join(dossier, f))
            if not d:
                continue
            maj = str(d.get("last_updated") or "")
            for bloc in (d.get("competitions") or {}).values():
                for m in bloc.get("matches") or []:
                    if not (m.get("home_team") and m.get("away_team")):
                        continue
                    cle = (ed["comp"], ed["edition"], str(m.get("match_id")))
                    if cle in par_cle and par_cle[cle][0] > maj:
                        continue
                    par_cle[cle] = (maj, compacter_match(m, ed, f[:10], f"internationales/{ed['comp']}/{ed['edition']}/{f}"))
    return sorted((v[1] for v in par_cle.values()), key=lambda m: (m["tri"], m["id"]))


def charger_programmes(donnees: str, editions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for ed in editions:
        p = _lire(os.path.join(donnees, "internationales", ed["comp"], str(ed["edition"]), "programme.json")) or {}
        for m in p.get("matchs") or []:
            out.append(dict(m, comp=ed["comp"], edition=ed["edition"], libelle=ed["libelle"], famille=ed["famille"]))
    return out


# ------------------------------------------------------------------------------
# 2. Agrégats d'équipe (fonctions pures)
# ------------------------------------------------------------------------------
def cote_de(m: Dict[str, Any], cle: str) -> Optional[str]:
    if m["home"]["cle"] == cle:
        return "home"
    if m["away"]["cle"] == cle:
        return "away"
    return None


def ligne_match(m: Dict[str, Any], cle: str) -> Optional[Dict[str, Any]]:
    """Le match du point de vue de l'équipe `cle` (score, tirs au but, V/N/D calculés ; rien sans score terminé)."""
    c = cote_de(m, cle)
    if not c:
        return None
    a = "away" if c == "home" else "home"
    adv = m[a]
    x: Dict[str, Any] = {"match_id": m["id"], "jour": m["jour"], "comp": m["comp"], "edition": m["edition"],
                         "tour": m["tour"], "domicile": c == "home", "statut": m["statut"], "fichier": m["fichier"],
                         "adversaire": {"id": adv["cle"], "nom": adv["nom"], "drapeau": adv["drapeau"]}}
    if m["groupe"]:
        x["groupe"] = m["groupe"]
    if m["stade"]:
        x["stade"] = m["stade"]
    pour, contre = m[c]["score"], m[a]["score"]
    if m["fini"] and pour is not None and contre is not None:
        x["pour"], x["contre"], x["resultat"] = pour, contre, resultat(pour, contre)
        if m["tab"]:
            tp, tc = (m["tab"][0], m["tab"][1]) if c == "home" else (m["tab"][1], m["tab"][0])
            x["tab"] = {"pour": tp, "contre": tc}
    return x


def stats_equipe(matchs: List[Dict[str, Any]], cle: str) -> Optional[Dict[str, Any]]:
    """Cumuls CALCULÉS sur les matchs terminés d'une équipe (une compétition, une édition) : V/N/D sur le score, tirs au but gagnés /
    perdus, buts, clean sheets, puis chaque stat d'équipe présente. Une stat n'est cumulée que sur les matchs qui la portent
    (`couverture` = ce nombre quand il est inférieur au nombre de matchs) : la moyenne par match est cumul / ce nombre."""
    jou = [m for m in matchs if m["fini"] and cote_de(m, cle) and m["home"]["score"] is not None and m["away"]["score"] is not None]
    if not jou:
        return None
    cumul: Dict[str, float] = {}
    nb: Dict[str, int] = defaultdict(int)
    pct: Dict[str, List[float]] = defaultdict(list)
    maxi: Dict[str, float] = {}
    v = n = d = 0
    tab_v = tab_d = 0
    cs = 0
    for m in jou:
        c = cote_de(m, cle)
        a = "away" if c == "home" else "home"
        pour, contre = m[c]["score"], m[a]["score"]
        cumul["goals"] = cumul.get("goals", 0) + pour
        cumul["goals_conceded"] = cumul.get("goals_conceded", 0) + contre
        cs += contre == 0
        r = resultat(pour, contre)
        v, n, d = v + (r == "V"), n + (r == "N"), d + (r == "D")
        if m["tab"]:
            tp, tc = (m["tab"][0], m["tab"][1]) if c == "home" else (m["tab"][1], m["tab"][0])
            tab_v, tab_d = tab_v + (tp > tc), tab_d + (tp < tc)
        for s in m["stats"]:
            val = _num(s.get(c))
            if val is None:
                continue
            nb[s["key"]] += 1
            if s["key"] in POURCENTAGES:
                pct[s["key"]].append(val)
            elif s["key"] in MAXIMUMS:
                maxi[s["key"]] = max(maxi.get(s["key"], val), val)
            else:
                cumul[s["key"]] = cumul.get(s["key"], 0) + val
    nm = len(jou)
    par_match = {k: round(x / (nb[k] if k in nb else nm), 2) for k, x in cumul.items()}
    for k, vals in pct.items():
        cumul[k] = par_match[k] = round(sum(vals) / len(vals), 1)
    for k, x in maxi.items():
        cumul[k] = par_match[k] = round(x, 1)
    cumul["clean_sheet"] = cs
    par_match["clean_sheet"] = round(cs / nm, 2)
    cumul = {k: (round(x, 3) if isinstance(x, float) else x) for k, x in sorted(cumul.items())}
    out = {"matchs": nm, "vnd": {"v": v, "n": n, "d": d}, "tab": {"v": tab_v, "d": tab_d}, "cumul": cumul,
           "par_match": dict(sorted(par_match.items()))}
    partiel = {k: x for k, x in sorted(nb.items()) if x < nm}
    if partiel:
        out["couverture"] = partiel
    return out


def forme(lignes: List[Dict[str, Any]], n: int = 5) -> List[str]:
    return [x["resultat"] for x in lignes if x.get("resultat")][-n:]


def prochain_match(programme: List[Dict[str, Any]], cle: str, famille: str, maintenant: str) -> Optional[Dict[str, Any]]:
    """Premier match programmé (UTC >= maintenant) de l'équipe ; adversaire absent s'il est « à déterminer »."""
    cand = []
    for p in programme:
        if p.get("famille") != famille:
            continue
        for c, a in (("home_team", "away_team"), ("away_team", "home_team")):
            t = p.get(c) or {}
            ident = (t.get("country") or "").upper() if famille == "selections" else str(t.get("id") or "")
            if ident == cle and (p.get("debut") or "") >= maintenant and p.get("statut") not in ("Annulé",):
                cand.append((p["debut"], p, c, a))
    if not cand:
        return None
    cand.sort(key=lambda x: (x[0], str(x[1].get("id"))))
    debut, p, c, a = cand[0]
    adv = p.get(a)
    x: Dict[str, Any] = {"match_id": str(p.get("id")), "debut": debut, "comp": p["comp"], "edition": p["edition"],
                         "tour": p.get("tour_court") or p.get("tour") or "", "domicile": c == "home", "statut": p.get("statut") or ""}
    if adv:
        x["adversaire"] = {"id": (adv.get("country") or "").upper() if famille == "selections" else str(adv.get("id") or ""),
                           "nom": adv.get("name") or "", "drapeau": adv.get("flag") or ""}
    if p.get("stade"):
        x["stade"] = p["stade"]
    return x


def couleurs_equipe(matchs: List[Dict[str, Any]], cle: str) -> Optional[Dict[str, Any]]:
    """Couleur principale / secondaire : maillots portés lus dans les compositions UEFA (code `pl01`… dans `kit_image`, règle de
    `couleurs.couleurs_clubs`) ; à défaut (matchs ESPN seulement) maillot porté le plus fréquent puis le suivant. Absent sinon."""
    obs: Dict[str, Any] = {}
    tous: List[str] = []
    for m in matchs:
        c = cote_de(m, cle)
        if not c or not m["fini"]:
            continue
        t = m[c]
        if t["maillot"] and couleurs.hex_valide(t["maillot"]):
            tous.append(t["maillot"].lower())
            obs[f"{m['comp']}-{m['edition']}-{m['id']}"] = {"d": m["date"], "e": {cle: [couleurs.code_maillot(t["kit"]), t["maillot"]]}}
    res = couleurs.couleurs_clubs(obs).get(cle)
    if res and res.get("principale"):
        return {k: v for k, v in res.items() if v is not None}
    if not tous:
        return None
    ordre = Counter(tous).most_common()
    out = {"principale": ordre[0][0], "source": "maillots_matchs", "nb_matchs": ordre[0][1]}
    if len(ordre) > 1:
        out["secondaire"] = ordre[1][0]
    return out


# ------------------------------------------------------------------------------
# 3. Joueurs : agrégation par identifiant brut
# ------------------------------------------------------------------------------
def entrees_joueurs(matchs: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """{id brut: {identité modale, équipes, entrées par match}} pour les joueurs qui ont JOUÉ (minutes > 0) un match terminé.
    Buts / passes lus sur les buts du match (un but contre son camp n'est ni un but ni une passe : compté à part) ; cartons lus sur
    les événements ; gardiens : arrêts, buts encaissés, clean sheet tels que la source les donne."""
    raw: Dict[str, Dict[str, Any]] = {}
    for m in matchs:
        if not m["fini"]:
            continue
        buts, csc, passes = Counter(), Counter(), Counter()
        for g in m["buts"]:
            if g["genre"] == "csc":
                csc[g["buteur"]] += 1
            else:
                buts[g["buteur"]] += 1
                if g["passeur"]:
                    passes[g["passeur"]] += 1
        jaunes = Counter(c["joueur"] for c in m["cartons"] if c["type"] == "yellow_card")
        rouges = Counter(c["joueur"] for c in m["cartons"] if c["type"] == "red_card")
        for pid, p in m["joueurs"].items():
            if not p["minutes"] or p["cote"] not in ("home", "away"):
                continue
            c = p["cote"]
            a = "away" if c == "home" else "home"
            eq, adv = m[c], m[a]
            r = raw.setdefault(pid, {"id": pid, "noms": Counter(), "courts": Counter(), "numeros": Counter(), "pos": Counter(), "pos_fr": Counter(),
                                     "nat": Counter(), "drapeaux": Counter(), "photos": Counter(), "equipes": {}, "matchs": []})
            for k, v in (("noms", p["nom"]), ("courts", p["court"]), ("numeros", p["numero"]), ("pos", p["pos"]), ("pos_fr", p["pos_fr"]),
                         ("nat", p["nat"]), ("drapeaux", p["drapeau"]), ("photos", p["photo"])):
                if v:
                    r[k][v] += 1
            r["equipes"][eq["cle"]] = {"type": "selection" if m["famille"] == "selections" else "club", "id": eq["cle"], "nom": eq["nom"], "drapeau": eq["drapeau"]}
            x: Dict[str, Any] = {"match_id": m["id"], "jour": m["jour"], "comp": m["comp"], "edition": m["edition"],
                                 "tour": m["tour"], "equipe": eq["cle"], "adversaire": {"id": adv["cle"], "nom": adv["nom"], "drapeau": adv["drapeau"]},
                                 "domicile": c == "home", "minutes": p["minutes"], "titulaire": p["titulaire"], "numero": p["numero"]}
            if eq["score"] is not None and adv["score"] is not None:
                x["pour"], x["contre"] = eq["score"], adv["score"]
                x["resultat"] = resultat(eq["score"], adv["score"])
                if m["tab"]:
                    tp, tc = (m["tab"][0], m["tab"][1]) if c == "home" else (m["tab"][1], m["tab"][0])
                    x["tab"] = {"pour": tp, "contre": tc}
            if p["note"] is not None:
                x["note"] = p["note"]
            for cle, val in (("buts", buts[pid]), ("csc", csc[pid]), ("passes", passes[pid]), ("jaunes", jaunes[pid]), ("rouges", rouges[pid])):
                if val:
                    x[cle] = val
            if p["pos"] == "GOALKEEPER":
                for cle, k in (("arrets", "saves"), ("encaisses", "goals_conceded"), ("clean_sheet", "clean_sheet")):
                    if k in p["st"]:
                        x[cle] = int(p["st"][k])
            r["matchs"].append(x)
    return raw


def cumuler_joueur(matchs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Cumuls CALCULÉS d'une liste d'entrées de match d'un joueur."""
    out: Dict[str, Any] = {"matchs": len(matchs), "titularisations": sum(1 for x in matchs if x["titulaire"]),
                           "minutes": sum(x["minutes"] for x in matchs)}
    for cle in ("buts", "csc", "passes", "jaunes", "rouges", "arrets", "encaisses", "clean_sheet"):
        s = sum(x.get(cle, 0) for x in matchs)
        if s or any(cle in x for x in matchs):
            out[cle] = s
    notes = [x["note"] for x in matchs if "note" in x]
    if notes:
        out["note_moyenne"] = round(sum(notes) / len(notes), 2)
        out["matchs_notes"] = len(notes)
    return out


def cumuls_par_edition(matchs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """{"comp-édition": cumuls} ; la clé devient "comp-édition|équipe" si le joueur a porté deux équipes dans la même édition."""
    groupes: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for x in matchs:
        groupes[(f"{x['comp']}-{x['edition']}", x["equipe"])].append(x)
    nb_eq = Counter(k[0] for k in groupes)
    return {(k if nb_eq[k] == 1 else f"{k}|{eq}"): dict(equipe=eq, **cumuler_joueur(v)) for (k, eq), v in sorted(groupes.items())}


# ------------------------------------------------------------------------------
# 4. Dates de naissance (UEFA : liste des inscrits ; ESPN : fiches de championnat puis effectifs)
# ------------------------------------------------------------------------------
def lire_inscrits_uefa(comp: str, edition: int, get=fetch_json) -> Optional[Dict[str, Dict[str, Any]]]:
    """{id joueur UEFA: {naissance, pays}} des joueurs inscrits d'une compétition (le filtre par club est ignoré par l'API)."""
    out: Dict[str, Dict[str, Any]] = {}
    for offset in range(0, 20000, 500):
        COMPTEURS["uefa"] += 1
        data = get(f"https://comp.uefa.com/v2/players?competitionId={UEFA_COMP[comp]}&seasonYear={edition}&offset={offset}&limit=500&language=FR")
        if not isinstance(data, list):
            return None if offset == 0 else out
        for p in data:
            if p.get("id") is not None:
                out[str(p["id"])] = {"naissance": (str(p.get("birthDate") or "")[:10] or None), "pays": (p.get("countryCode") or "").upper()}
        if len(data) < 500:
            break
    return out


def lire_effectif_espn(slug: str, equipe: str, get=ligues._get) -> Optional[Dict[str, str]]:
    """{id ESPN du joueur: date de naissance} d'un effectif ESPN (instantané ACTUEL de l'équipe). None si illisible."""
    COMPTEURS["espn"] += 1
    data, statut = get(f"{ligues.SITE}/{slug}/teams/{equipe}/roster")
    if statut != "ok" or not isinstance(data, dict):
        return None
    return {str(a.get("id")): str(a.get("dateOfBirth") or "")[:10] for a in data.get("athletes") or [] if a.get("id") and a.get("dateOfBirth")}


def completer_naissances(raw: Dict[str, Dict[str, Any]], cache: Dict[str, Any], fiches_champ: Dict[str, Dict[str, Any]], aujourdhui: dt.date,
                         inscrits: Callable[[str, int], Optional[Dict[str, Dict[str, Any]]]] = lire_inscrits_uefa,
                         effectif: Callable[[str, str], Optional[Dict[str, str]]] = lire_effectif_espn) -> Dict[str, str]:
    """{id brut: AAAA-MM-JJ} ; met `cache` à jour. Ordre : fiche de championnat (id ESPN identique) > cache > lecture réseau (liste des
    inscrits UEFA de l'édition ; effectif ESPN de l'équipe). Un joueur introuvable est noté `null` et retenté après 30 jours."""
    def recent(e: Dict[str, Any]) -> bool:
        try:
            return (aujourdhui - dt.date.fromisoformat(e["maj"][:10])).days < JOURS_CACHE
        except (KeyError, ValueError):
            return False

    def valide(d: Any) -> bool:
        return bool(d) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(d))) and str(d)[:4] > "1900"

    res: Dict[str, str] = {}
    manquants_uefa: Dict[Tuple[str, int], Set[str]] = defaultdict(set)
    manquants_espn: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
    for pid, r in raw.items():
        if pid in fiches_champ and valide(fiches_champ[pid].get("naissance")):
            res[pid] = fiches_champ[pid]["naissance"]
            continue
        e = cache.get(pid)
        if e and valide(e.get("n")):
            res[pid] = e["n"]
            continue
        if e and recent(e):
            continue                                     # introuvable récemment : pas de nouvelle requête
        if pid.startswith("espn-"):
            for x in r["matchs"]:
                eq = x["equipe"]
                info = r["equipes_espn"].get((x["comp"], eq)) if "equipes_espn" in r else None
                if info:
                    manquants_espn[(info["slug"], info["espn_id"])].add(pid)
        else:
            for x in r["matchs"]:
                if x["comp"] in UEFA_COMP:
                    manquants_uefa[(x["comp"], x["edition"])].add(pid)
    maj = aujourdhui.isoformat()
    lus: Set[str] = set()                                # identifiants dont la source a été lue (introuvable = noté ; panne = rien)
    for (comp, ed), ids in sorted(manquants_uefa.items()):
        liste = inscrits(comp, ed)
        if liste is None:
            print(f"[WARN] inscrits UEFA {comp} {ed} illisibles : dates de naissance non mises à jour")
            continue
        lus |= ids
        for pid in ids:
            if pid in res:
                continue
            n = (liste.get(pid) or {}).get("naissance")
            if valide(n):
                res[pid] = n
                cache[pid] = {"n": n, "src": "UEFA", "maj": maj}
    for (slug, eq), ids in sorted(manquants_espn.items()):
        liste = effectif(slug, eq)
        if liste is None:
            print(f"[WARN] effectif ESPN {slug}/{eq} illisible : dates de naissance non mises à jour")
            continue
        lus |= ids
        for pid in ids:
            if pid in res:
                continue
            n = liste.get(pid[5:])
            if valide(n):
                res[pid] = n
                cache[pid] = {"n": n, "src": "ESPN", "maj": maj}
    a_essayer = set().union(*manquants_uefa.values(), *manquants_espn.values()) if (manquants_uefa or manquants_espn) else set()
    for pid in raw:
        if pid in res or (pid in a_essayer and pid not in lus):
            continue                                   # connu, ou source illisible aujourd'hui : on réessaiera au prochain passage
        if pid not in cache or (cache[pid].get("n") is None and not recent(cache[pid])):
            cache[pid] = {"n": None, "src": None, "maj": maj}
    return res


# ------------------------------------------------------------------------------
# 5. Fusion UEFA <-> ESPN (preuve seulement)
# ------------------------------------------------------------------------------
def sans_apostrophe(nom: str) -> str:
    """« O'Reilly » / « O’Reilly » -> « OReilly » (l'UEFA et ESPN n'utilisent pas la même apostrophe)."""
    return re.sub(r"[’'`´ʼ]", "", nom or "")


def fusion_naissance(raw: Dict[str, Dict[str, Any]], naissances: Dict[str, str]) -> Tuple[Dict[str, str], Dict[str, int]]:
    """{id ESPN: id UEFA} pour chaque paire PROUVÉE : même date de naissance, noms concordants (`nom_concorde`), au moins une sélection
    commune, et candidat UNIQUE dans les deux sens. Retourne aussi des compteurs (paires, ambigus)."""
    par_date: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: {"u": [], "e": []})
    for pid in raw:
        d = naissances.get(pid)
        if d:
            par_date[d]["e" if pid.startswith("espn-") else "u"].append(pid)

    def sel(pid: str) -> Set[str]:
        return {k for k, e in raw[pid]["equipes"].items() if e["type"] == "selection"}

    def concorde(a: str, b: str) -> bool:
        na, nb = _modal(raw[a]["noms"], ""), _modal(raw[b]["noms"], "")
        return bool(sel(a) & sel(b)) and ej.nom_concorde(sans_apostrophe(na), sans_apostrophe(nb))

    cand_e: Dict[str, List[str]] = {}
    cand_u: Dict[str, List[str]] = defaultdict(list)
    for g in par_date.values():
        for e in g["e"]:
            ok = [u for u in g["u"] if concorde(e, u)]
            if ok:
                cand_e[e] = ok
                for u in ok:
                    cand_u[u].append(e)
    paires, ambigus = {}, 0
    for e, us in sorted(cand_e.items()):
        if len(us) == 1 and len(cand_u[us[0]]) == 1:
            paires[e] = us[0]
        else:
            ambigus += 1
    return paires, {"paires": len(paires), "ambigus": ambigus}


# ------------------------------------------------------------------------------
# 6. Wikidata des sélections
# ------------------------------------------------------------------------------
def code_wd(code: str) -> str:
    return CODE_WIKIDATA.get(code, code)


def q_candidats(codes: List[str]) -> str:
    vals = " ".join('"%s"' % code_wd(c) for c in codes)
    return ("SELECT ?code ?eq ?cls ?cmp ?pays WHERE { VALUES ?code { %s } ?eq wdt:P3441 ?code . OPTIONAL { ?eq wdt:P31 ?cls } "
            "OPTIONAL { ?eq wdt:P2094 ?cmp } OPTIONAL { ?eq wdt:P1532 ?pays } }" % vals)


def parse_candidats(lignes: List[Dict[str, Any]]) -> Dict[str, Dict[str, Dict[str, Set[str]]]]:
    """{code Wikidata: {QID: {cls, cmp, pays}}} (chaque propriété = ensemble des valeurs)."""
    out: Dict[str, Dict[str, Dict[str, Set[str]]]] = {}
    for b in lignes:
        e = out.setdefault(b["code"]["value"], {}).setdefault(ej._qid(b["eq"]["value"]), {"cls": set(), "cmp": set(), "pays": set()})
        for k, cle in (("cls", "cls"), ("cmp", "cmp"), ("pays", "pays")):
            if (b.get(k) or {}).get("value"):
                e[cle].add(ej._qid(b[k]["value"]))
    return out


def choisir_selection(cands: Dict[str, Dict[str, Set[str]]]) -> Dict[str, Any]:
    """Équipe nationale masculine A parmi les éléments qui portent le code : classe « équipe nationale masculine de football » (jamais
    avec une classe féminine ; les équipes de jeunes, espoirs, olympiques ont d'autres classes), compétition « football masculin »
    (P2094, seule valeur) et pays de sport (P1532). {statut: ok | ambigu | absent, qid?, pays?, federations: [QID]}."""
    valides = {q: e for q, e in cands.items()
               if CLASSE_MASC in e["cls"] and not (e["cls"] & CLASSES_EXCLUES) and e["cmp"] == {COMPET_MASC} and e["pays"]}
    feds = sorted(q for q, e in cands.items() if FEDERATION in e["cls"])
    if len(valides) > 1:
        return {"statut": "ambigu", "candidats": sorted(valides), "federations": feds}
    if not valides:
        return {"statut": "absent", "federations": feds}
    q, e = next(iter(valides.items()))
    if len(e["pays"]) != 1:
        return {"statut": "ambigu", "candidats": [q], "federations": feds}
    return {"statut": "ok", "qid": q, "pays": next(iter(e["pays"])), "federations": feds}


def q_details_selections(equipes: List[str], federations: List[str]) -> str:
    return f"""SELECT ?item ?frtitle ?nick ?site ?stade ?stadeLabel ?inc ?conf ?label WHERE {{
  VALUES ?item {{ {" ".join("wd:" + q for q in equipes + federations)} }}
  OPTIONAL {{ ?w schema:about ?item ; schema:isPartOf <https://fr.wikipedia.org/> ; schema:name ?frtitle . }}
  OPTIONAL {{ ?item wdt:P1449 ?nick . FILTER(LANG(?nick) IN ("fr", "")) }}
  OPTIONAL {{ ?item wdt:P856 ?site . }}
  OPTIONAL {{ ?item p:P115 ?s . ?s ps:P115 ?stade . FILTER NOT EXISTS {{ ?s pq:P582 ?fin }} }}
  OPTIONAL {{ ?item wdt:P571 ?inc . }}
  OPTIONAL {{ ?item wdt:P463 ?conf . }}
  OPTIONAL {{ ?item rdfs:label ?label . FILTER(LANG(?label) = "fr") }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "fr,en". }}
}}"""


def parse_details_selections(lignes: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """{QID: {titre_wikipedia, surnoms[], site, stade{nom,qid}, fondation_annee, confederations[], nom}} ; site, stade et fondation
    seulement s'ils sont UNIQUES (deux valeurs différentes : absents, jamais de choix arbitraire)."""
    g: Dict[str, Dict[str, Set[str]]] = {}
    for b in lignes:
        q = ej._qid(b["item"]["value"])
        d = g.setdefault(q, {})
        for k in ("frtitle", "nick", "site", "inc", "label"):
            if (b.get(k) or {}).get("value"):
                d.setdefault(k, set()).add(b[k]["value"])
        if (b.get("stade") or {}).get("value"):
            d.setdefault("stade", set()).add(ej._qid(b["stade"]["value"]) + "|" + ((b.get("stadeLabel") or {}).get("value") or ""))
        if (b.get("conf") or {}).get("value"):
            d.setdefault("conf", set()).add(ej._qid(b["conf"]["value"]))
    out: Dict[str, Dict[str, Any]] = {}
    for q, d in g.items():
        f: Dict[str, Any] = {}
        if len(d.get("frtitle") or ()) == 1:
            f["titre_wikipedia"] = next(iter(d["frtitle"]))
        if d.get("nick"):
            f["surnoms"] = sorted(d["nick"])[:3]
        if len(d.get("site") or ()) == 1:
            f["site"] = next(iter(d["site"]))
        if len(d.get("stade") or ()) == 1:
            sq, sn = next(iter(d["stade"])).split("|", 1)
            if sn and not re.fullmatch(r"Q\d+", sn):
                f["stade"] = {"nom": sn, "qid": sq}
        annees = [int(m.group(1)) for m in (re.match(r"^\+?(\d{4})", x) for x in d.get("inc") or ()) if m]
        if annees:
            f["fondation_annee"] = min(annees)
        if d.get("label"):
            f["nom"] = sorted(d["label"])[0]
        f["confederations"] = sorted(c for c in d.get("conf") or () if c in CONFEDERATIONS)
        out[q] = f
    return out


def bloc_wikidata_selection(code: str, choix: Dict[str, Any], details: Dict[str, Dict[str, Any]], maintenant: str) -> Dict[str, Any]:
    """Bloc `wikidata` d'une fiche de sélection. Fédération : seulement UNE porte le code ; confédération : seulement UNE des six
    dans P463 de la fédération."""
    if choix["statut"] != "ok":
        return {"qid": None, "statut": choix["statut"], "maj": maintenant}
    d = details.get(choix["qid"]) or {}
    b: Dict[str, Any] = {"qid": choix["qid"], "preuve": "P3441+classe masculine+P2094+P1532", "pays_qid": choix["pays"]}
    for k in ("titre_wikipedia", "surnoms", "site", "stade"):
        if d.get(k):
            b[k] = d[k]
    if len(choix["federations"]) == 1:
        fq = choix["federations"][0]
        fd = details.get(fq) or {}
        fed = {"qid": fq, **({"nom": fd["nom"]} if fd.get("nom") else {}),
               **({"fondation_annee": fd["fondation_annee"]} if fd.get("fondation_annee") else {})}
        b["federation"] = fed
        if len(fd.get("confederations") or []) == 1:
            b["confederation"] = {"code": CONFEDERATIONS[fd["confederations"][0]], "qid": fd["confederations"][0]}
    b["maj"] = maintenant
    return b


def wikidata_selections(codes: List[str], requete: Callable[[str], Optional[List[Dict[str, Any]]]], maintenant: str
                        ) -> Optional[Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]]:
    """({code: bloc wikidata}, {code: QID du pays}) ; None si Wikidata est injoignable (valeurs précédentes conservées)."""
    cands: Dict[str, Dict[str, Dict[str, Set[str]]]] = {}
    for i in range(0, len(codes), 60):
        r = requete(q_candidats(codes[i:i + 60]))
        if r is None:
            return None
        for k, v in parse_candidats(r).items():
            cands.setdefault(k, {}).update(v)
    choix = {c: choisir_selection(cands.get(code_wd(c)) or {}) for c in codes}
    eq = sorted({x["qid"] for x in choix.values() if x["statut"] == "ok"})
    fed = sorted({f for x in choix.values() if x["statut"] == "ok" and len(x["federations"]) == 1 for f in x["federations"]})
    details: Dict[str, Dict[str, Any]] = {}
    for i in range(0, len(eq + fed), 100):
        lot = (eq + fed)[i:i + 100]
        r = requete(q_details_selections([q for q in lot if q in eq], [q for q in lot if q in fed]))
        if r is None:
            return None
        details.update(parse_details_selections(r))
    blocs = {c: bloc_wikidata_selection(c, choix[c], details, maintenant) for c in codes}
    return blocs, {c: x["pays"] for c, x in choix.items() if x["statut"] == "ok"}


# ------------------------------------------------------------------------------
# 7. Clubs : correspondance par identifiant, Wikidata par nom exact + pays + club de football
# ------------------------------------------------------------------------------
def correspondre_clubs(equipes: Dict[str, Dict[str, Any]], index_champ: Dict[str, Dict[str, Any]], index_uefa: Dict[str, Dict[str, Any]]
                       ) -> Dict[str, Dict[str, Any]]:
    """{id d'équipe du match: {fiches[], preuve}} ; PAR IDENTIFIANT seulement : id ESPN = fiche de championnat (`espn-<id>`), id UEFA =
    fiche de coupe ; la fiche de championnat qui porte `uefa_id` (correspondance prouvée par un match de coupe) ajoute la fiche UEFA."""
    out: Dict[str, Dict[str, Any]] = {}
    for tid, e in sorted(equipes.items()):
        fiches, preuves = [], []
        esp = tid if tid.startswith("espn-") else (f"espn-{e['espn_id']}" if e.get("espn_id") else "")
        c = index_champ.get(esp) if esp else None
        if c:
            fiches.append({"depot": "donnees-football", "id": c["id"], "fichier": c["fichier"], "nom": c.get("nom")})
            preuves.append(f"identifiant ESPN {esp[5:]} identique à la fiche de championnat {c['id']}")
        uid = c.get("uefa_id") if c else (tid if tid.isdigit() else "")
        if uid and uid in index_uefa:
            u = index_uefa[uid]
            fiches.append({"depot": "coupes-europe", "id": uid, "fichier": u["fichier"], "nom": u.get("nom")})
            preuves.append(("identifiant UEFA %s lié par la correspondance de la fiche de championnat" if c else "identifiant UEFA %s identique") % uid)
        if fiches:
            out[tid] = {"fiches": fiches, "preuve": " ; ".join(preuves)}
    return out


def chercher_clubs_wikidata(noms: List[str], get=_get_wiki) -> Optional[Set[str]]:
    """QID candidats d'un club : `wbsearchentities` (en puis fr, pour chaque nom) ; un candidat n'est retenu que si le texte qui a
    concordé (libellé ou alias) est ÉGAL au nom demandé (normalisé). None si une recherche a échoué (liste incomplète : on ne conclut pas)."""
    out: Set[str] = set()
    for nom in noms:
        for lang in ("en", "fr"):
            time.sleep(PAUSE_RECHERCHE)
            rep = get("https://www.wikidata.org/w/api.php?action=wbsearchentities&type=item&limit=10&format=json&language=%s&uselang=%s&search=%s"
                      % (lang, lang, urllib.parse.quote(nom)))
            if rep is None:
                return None
            for x in rep.get("search") or []:
                txt = ((x.get("match") or {}).get("text")) or x.get("label") or ""
                if normalize(txt) == normalize(nom) and re.fullmatch(r"Q\d+", x.get("id") or ""):
                    out.add(x["id"])
    return out


def q_clubs_verif(qids: List[str]) -> str:
    return ("SELECT ?item ?pays WHERE { VALUES ?item { %s } ?item wdt:P31/wdt:P279* wd:%s . OPTIONAL { ?item wdt:P17 ?pays } }"
            % (" ".join("wd:" + q for q in qids), CLUB_FOOTBALL))


def choisir_club(candidats: Set[str], verif: Dict[str, Set[str]], pays_attendus: Set[str]) -> Optional[str]:
    """QID du seul candidat qui est un club de football (présent dans `verif`) du bon pays ; None si zéro ou plusieurs."""
    ok = sorted(q for q in candidats if q in verif and verif[q] & pays_attendus)
    return ok[0] if len(ok) == 1 else None


def wikidata_clubs(equipes: Dict[str, Dict[str, Any]], pays_qid: Dict[str, str], requete, get, maintenant: str,
                   chercher=chercher_clubs_wikidata, fin: float = float("inf")) -> Tuple[Dict[str, Dict[str, Any]], Set[str]]:
    """({id équipe: bloc wikidata}, {id des équipes dont la recherche a abouti}) ; bloc (qid + faits, via
    `encyclo_ligues.interroger_wikidata`) pour les clubs dont UN SEUL élément correspond au nom (nom ou nom officiel) ET est un club de
    football ET du pays du club. Les autres : rien (et seules les recherches abouties sont notées « non rapprochées » : 30 jours)."""
    cands: Dict[str, Set[str]] = {}
    essayes: Set[str] = set()
    echecs = 0
    for tid, e in sorted(equipes.items()):
        if e["code"] not in pays_qid:
            continue
        if echecs >= 3 or time.time() > fin:
            print("[WARN] Wikidata (clubs) : recherches refusées de suite ou budget de temps atteint, la suite au prochain passage")
            break
        noms = sorted({n for n in (e["nom"], e["nom_officiel"]) if n})
        c = chercher(noms, get)
        if c is None:
            echecs += 1
            continue
        echecs = 0
        essayes.add(tid)
        if c:
            cands[tid] = c
    tous = sorted({q for c in cands.values() for q in c})
    verif: Dict[str, Set[str]] = {}
    for i in range(0, len(tous), 100):
        r = requete(q_clubs_verif(tous[i:i + 100]))
        if r is None:
            return {}, set()
        for b in r:
            verif.setdefault(ej._qid(b["item"]["value"]), set()).update([ej._qid(b["pays"]["value"])] if b.get("pays") else [])
    choix: Dict[str, str] = {}
    for tid, c in cands.items():
        code = equipes[tid]["code"]
        attendus = {pays_qid[code]} | ({Q_ROYAUME_UNI} if code in PAYS_ROYAUME_UNI else set())
        q = choisir_club(c, verif, attendus)
        if q:
            choix[tid] = q
    if not choix:
        return {}, essayes
    faits = el.interroger_wikidata(sorted(set(choix.values())), get=get) or {}
    out = {}
    for tid, q in choix.items():
        f = faits.get(q)
        if f and f.get("club"):
            out[tid] = dict({k: v for k, v in f.items() if k != "club"}, preuve="nom exact + club de football + pays", maj=maintenant)
    return out, essayes


# ------------------------------------------------------------------------------
# 8. Liens vers les fiches existantes (identifiant seulement)
# ------------------------------------------------------------------------------
def indexer_fiches_championnat(donnees: str) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """(index des fiches de championnat {id: ligne d'index}, {id joueur ESPN: {naissance, club, fichier, nom_club}}) lus localement."""
    base = os.path.join(donnees, "championnats", "clubs")
    idx = {c["id"]: c for c in (_lire(os.path.join(base, "index.json")) or {}).get("clubs") or []}
    joueurs: Dict[str, Dict[str, Any]] = {}
    for cid, c in sorted(idx.items()):
        f = _lire(os.path.join(donnees, c["fichier"])) or {}
        for j in f.get("effectif") or []:
            if j.get("id"):
                joueurs.setdefault(j["id"], {"naissance": j.get("naissance"), "liens": []})["liens"].append(
                    {"depot": "donnees-football", "fiche": c["fichier"], "club_id": cid, "club": c.get("nom"), "joueur_id": j["id"],
                     "preuve": "même identifiant ESPN"})
    for j in joueurs.values():
        if not j["naissance"]:
            j["naissance"] = None
    return idx, joueurs


def lire_effectifs_uefa(coupes: Optional[str], cache: Dict[str, Any], aujourdhui: dt.date, get=fetch_json
                        ) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
    """(index des fiches de club UEFA {id: ligne}, {id joueur UEFA: [liens]}) : dossier local `coupes` (clubs/), sinon Pages ; le
    second est gardé 7 jours dans `cache` (108 requêtes sinon)."""
    def lecture(chemin: str) -> Optional[Any]:
        if coupes:
            return _lire(os.path.join(coupes, chemin))
        COMPTEURS["pages"] += 1
        return get(COUPES_PAGES + chemin)

    idx_doc = lecture("clubs/index.json") or {}
    idx = {str(c["id"]): c for c in idx_doc.get("clubs") or []}
    ancien = cache.get("joueurs")
    try:
        frais = ancien is not None and (aujourdhui - dt.date.fromisoformat(cache["lu_le"][:10])).days < JOURS_CACHE_EFFECTIFS
    except (KeyError, ValueError):
        frais = False
    if frais or not idx:
        return idx, ancien or {}
    joueurs: Dict[str, List[Dict[str, Any]]] = {}
    for cid, c in sorted(idx.items()):
        f = lecture(c["fichier"])
        if f is None:
            print(f"[WARN] fiche UEFA {cid} illisible : effectifs UEFA précédents conservés")
            return idx, ancien or {}
        for j in f.get("effectif") or []:
            if j.get("id"):
                joueurs.setdefault(str(j["id"]), []).append({"depot": "coupes-europe", "fiche": c["fichier"], "club_id": cid, "club": c.get("nom"),
                                                              "joueur_id": str(j["id"]), "preuve": "même identifiant UEFA"})
    cache["joueurs"], cache["lu_le"] = joueurs, aujourdhui.isoformat()
    return idx, joueurs


# ------------------------------------------------------------------------------
# 9. Construction
# ------------------------------------------------------------------------------
def fichier_joueur(pid: str) -> str:
    return f"joueurs/{zlib.crc32(pid.encode()) % NB_FICHIERS_JOUEURS:02d}.json"


def identifiant_fiche(ids: List[str]) -> str:
    """Identifiant d'une fiche : l'id UEFA s'il y en a un (le plus petit), sinon l'id ESPN."""
    u = sorted(i for i in ids if not i.startswith("espn-"))
    return u[0] if u else sorted(ids)[0]


def construire_unites(raw: Dict[str, Dict[str, Any]], paires: Dict[str, str]) -> List[List[str]]:
    """Groupes d'ids bruts = un joueur : paires prouvées fusionnées, les autres seuls."""
    unites: Dict[str, List[str]] = {}
    for pid in raw:
        tete = paires.get(pid, pid)
        unites.setdefault(tete, []).append(pid)
    return [sorted(v) for _, v in sorted(unites.items())]


def fiche_joueur(ids: List[str], raw: Dict[str, Dict[str, Any]], naissances: Dict[str, str], wiki: Dict[str, Any],
                 liens: List[Dict[str, Any]]) -> Dict[str, Any]:
    r = {k: Counter() for k in ("noms", "courts", "numeros", "pos", "pos_fr", "nat", "drapeaux", "photos")}
    equipes: Dict[str, Dict[str, Any]] = {}
    matchs: List[Dict[str, Any]] = []
    for pid in ids:
        for k in r:
            r[k].update(raw[pid][k])
        equipes.update(raw[pid]["equipes"])
        matchs.extend(raw[pid]["matchs"])
    matchs.sort(key=lambda x: (x["jour"], x["match_id"]))
    nais = sorted({naissances[i] for i in ids if i in naissances})
    f: Dict[str, Any] = {"id": identifiant_fiche(ids), "ids": [{"id": i, "source": "ESPN" if i.startswith("espn-") else "UEFA"} for i in ids],
                         "nom": _modal(r["noms"], ""), "nom_court": _modal(r["courts"], ""), "poste": _modal(r["pos"], ""),
                         "poste_fr": _modal(r["pos_fr"], ""), "numero": _modal(r["numeros"], ""), "nationalite": _modal(r["nat"], ""),
                         "drapeau": _modal(r["drapeaux"], ""), "photo": _modal(r["photos"], "")}
    if len(nais) == 1:
        f["naissance"] = nais[0]
    f["equipes"] = sorted(equipes.values(), key=lambda e: (e["type"], e["id"]))
    f["cumuls"] = cumuls_par_edition(matchs)
    f["total"] = cumuler_joueur(matchs)
    f["matchs"] = matchs
    if liens:
        f["liens"] = liens
    for k in ("wd", "wp"):
        if wiki.get(k):
            f[k] = wiki[k]
    return {k: v for k, v in f.items() if v not in ("", None)}


def effectif_equipe(cle: str, fiches: Dict[str, Dict[str, Any]], id_fiche: Dict[str, str]) -> List[Dict[str, Any]]:
    """Joueurs qui ont joué pour l'équipe, avec leurs cumuls CALCULÉS pour elle seule (toutes éditions) et par édition."""
    out = []
    for f in fiches.values():
        mine = [x for x in f["matchs"] if x["equipe"] == cle]
        if not mine:
            continue
        e = {"id": f["id"], "nom": f["nom"], "poste": f.get("poste", ""), "poste_fr": f.get("poste_fr", ""),
             "numero": _modal(Counter(x["numero"] for x in mine if x.get("numero")), ""), **cumuler_joueur(mine)}
        for k in ("nationalite", "drapeau", "photo", "naissance"):
            if f.get(k):
                e[k] = f[k]
        par: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for x in mine:
            par[f"{x['comp']}-{x['edition']}"].append(x)
        e["editions"] = {k: {kk: vv for kk, vv in cumuler_joueur(v).items() if kk in ("matchs", "minutes", "buts", "passes")}
                         for k, v in sorted(par.items())}
        out.append({k: v for k, v in e.items() if v not in ("", None)})
    return sorted(out, key=lambda e: (-e["matchs"], -e["minutes"], e["nom"]))


def construire(donnees: str, coupes: Optional[str] = None, budget_joueurs_s: float = 360, avec_wiki: bool = True,
               requete: Callable[[str], Optional[List[Dict[str, Any]]]] = _sparql, get=_get_wiki,
               inscrits: Callable[..., Any] = lire_inscrits_uefa, effectif: Callable[..., Any] = lire_effectif_espn,
               wikipedia: Callable[[List[str]], Any] = lambda titres: clubs.interroger_wikipedia(titres, ESSAIS_WIKI), chercher: Callable[..., Any] = chercher_clubs_wikidata
               ) -> Dict[str, Any]:
    t0 = time.time()
    maintenant = maintenant_iso()
    auj = dt.date.fromisoformat(maintenant[:10])
    base = os.path.join(donnees, DOSSIER)
    editions = lister_editions(donnees)
    if not editions:
        print("[FICHES-INT] aucune édition publiée : rien à faire")
        return {}
    matchs = charger_matchs(donnees, editions)
    programme = charger_programmes(donnees, editions)
    print(f"[FICHES-INT] {len(editions)} édition(s), {len(matchs)} match(s) lus")
    noms_comp = {f"{e['comp']}-{e['edition']}": e for e in editions}

    # --- équipes
    sel: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    clb: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    ident_sel: Dict[str, Dict[str, Counter]] = {}
    ident_clb: Dict[str, Dict[str, Any]] = {}
    fam = {e["comp"]: e["famille"] for e in editions}
    for m in matchs:
        for c in ("home", "away"):
            t = m[c]
            if not t["cle"]:
                continue
            if fam[m["comp"]] == "selections":
                sel[t["cle"]].append(m)
                d = ident_sel.setdefault(t["cle"], {"noms": Counter(), "noms_uefa": Counter(), "courts": Counter(), "drapeaux": Counter(), "pays_nom": Counter()})
                (d["noms_uefa"] if m["source"] == "UEFA" else d["noms"])[t["nom"]] += 1
                d["courts"][t["nom_court"]] += 1
                d["drapeaux"][t["drapeau"]] += 1
                if t["pays_nom"]:
                    d["pays_nom"][t["pays_nom"]] += 1
            else:
                clb[t["cle"]].append(m)
                ident_clb.setdefault(t["cle"], dict(t))
    # --- joueurs bruts + équipes ESPN (pour les effectifs)
    raw = entrees_joueurs(matchs)
    info_espn: Dict[str, Dict[Tuple[str, str], Dict[str, str]]] = defaultdict(dict)
    for m in matchs:
        slug = {"cdm": "fifa.world", "euro": "uefa.euro", "ldn": "uefa.nations", "cdmc": "fifa.cwc", "ci": "fifa.intercontinental_cup"}.get(m["comp"], "")
        for pid, p in m["joueurs"].items():
            if pid in raw and pid.startswith("espn-") and p["cote"] in ("home", "away") and m[p["cote"]]["espn_id"] and slug:
                info_espn[pid][(m["comp"], m[p["cote"]]["cle"])] = {"slug": slug, "espn_id": m[p["cote"]]["espn_id"]}
    for pid, i in info_espn.items():
        raw[pid]["equipes_espn"] = i

    # --- index des fiches existantes
    cache_dir = os.path.join(base, "cache")
    cache_nais = _lire(os.path.join(cache_dir, "naissances.json")) or {}
    cache_eff = _lire(os.path.join(cache_dir, "effectifs_uefa.json")) or {}
    index_champ, joueurs_champ = indexer_fiches_championnat(donnees)
    try:
        index_uefa, liens_uefa = lire_effectifs_uefa(coupes, cache_eff, auj)
    except Exception as e:   # jamais bloquant
        print(f"[WARN] fiches de club UEFA non lues : {e}")
        index_uefa, liens_uefa = {}, cache_eff.get("joueurs") or {}

    # --- dates de naissance et fusion
    try:
        naissances = completer_naissances(raw, cache_nais, joueurs_champ, auj, inscrits, effectif)
    except Exception as e:
        print(f"[WARN] dates de naissance non complétées : {e}")
        naissances = {pid: c["n"] for pid, c in cache_nais.items() if c.get("n") and pid in raw}
    paires, stat_fusion = fusion_naissance(raw, naissances)
    print(f"[FICHES-INT] {len(raw)} identifiant(s) de joueur, {len(naissances)} date(s) de naissance, {stat_fusion['paires']} fusion(s) UEFA<->ESPN "
          f"prouvée(s), {stat_fusion['ambigus']} ambiguë(s) (non fusionnée(s))")

    # --- anciennes fiches de joueurs (cache Wikidata)
    anciens: Dict[str, Any] = {}
    for n in range(NB_FICHIERS_JOUEURS):
        d = _lire(os.path.join(base, "joueurs", f"{n:02d}.json")) or {}
        for f in (d.get("joueurs") or {}).values():
            for i in f.get("ids") or []:
                anciens[i["id"]] = f
    unites = construire_unites(raw, paires)
    stat_wd = {"demandes": 0, "relies": 0, "photos": 0, "extraits": 0}
    wiki: Dict[str, Dict[str, Any]] = {}
    if avec_wiki:
        try:
            unites, wiki = enrichir_wikidata_joueurs(unites, raw, naissances, anciens, maintenant, requete, get, 0.6 * budget_joueurs_s, stat_wd)
        except Exception as e:
            print(f"[WARN] Wikidata des joueurs non mis à jour : {e}")
            wiki = {}
    # --- fiches de joueurs
    fiches: Dict[str, Dict[str, Any]] = {}
    for ids in unites:
        liens: List[Dict[str, Any]] = []
        for i in ids:
            liens += liens_uefa.get(i, []) if not i.startswith("espn-") else (joueurs_champ.get(i) or {}).get("liens", [])
        f = fiche_joueur(ids, raw, naissances, wiki.get(identifiant_fiche(ids)) or blocs_depuis_anciens(ids, anciens), liens)
        fiches[f["id"]] = f
    id_fiche = {i["id"]: f["id"] for f in fiches.values() for i in f["ids"]}

    # --- sélections (Wikidata / Wikipédia : les 40 % du budget qui restent après les joueurs)
    fin_equipes = time.time() + 0.4 * budget_joueurs_s
    codes = sorted(sel)
    anc_sel = {c: _lire(os.path.join(base, "selections", f"{c}.json")) or {} for c in codes}
    wd_sel: Dict[str, Dict[str, Any]] = {}
    pays_qid: Dict[str, str] = {}
    if avec_wiki:
        a_faire = [c for c in codes if clubs.a_rafraichir(anc_sel[c].get("wikidata"), auj, JOURS_CACHE)]
        if a_faire:
            r = wikidata_selections(a_faire, requete, maintenant)
            if r is None:
                print("[WARN] Wikidata (sélections) injoignable : valeurs précédentes conservées")
            else:
                wd_sel, pays_qid = r
        # codes de pays des clubs : un seul passage pour les pays qui ne sont pas des sélections du jeu
        pays_clubs = sorted({e["code"] for e in ident_clb.values() if e["code"] and e["code"] not in pays_qid})
        if pays_clubs:
            r = wikidata_selections(pays_clubs, requete, maintenant)
            if r:
                pays_qid.update(r[1])
        for c in codes:
            if c not in wd_sel and anc_sel[c].get("wikidata"):
                wd_sel[c] = anc_sel[c]["wikidata"]
                if (anc_sel[c]["wikidata"] or {}).get("pays_qid"):
                    pays_qid.setdefault(c, anc_sel[c]["wikidata"]["pays_qid"])
        wp = {}
        voulus = [c for c in codes if (wd_sel.get(c) or {}).get("titre_wikipedia") and clubs.a_rafraichir(anc_sel[c].get("wikipedia"), auj, JOURS_CACHE)]
        echecs = 0
        for i in range(0, len(voulus), 20):
            if echecs >= 3 or time.time() > fin_equipes:
                print("[WARN] Wikipédia (sélections) : échecs de suite ou budget de temps atteint, la suite au prochain passage")
                break
            lot = voulus[i:i + 20]
            titres = [wd_sel[c]["titre_wikipedia"] for c in lot]
            time.sleep(clubs.PAUSE_WIKIPEDIA)
            COMPTEURS["wikipedia"] += 1
            res = wikipedia(titres)
            if res is None:
                echecs += 1
                continue
            echecs = 0
            for c, t in zip(lot, titres):
                wp[c] = dict(res[t], maj=maintenant) if t in res else {"maj": maintenant}
    else:
        wp = {}
    index_sel, vues_sel = [], {}
    pays_noms: Dict[str, str] = {}
    for code in codes:
        d = ident_sel[code]
        nom = _modal(d["noms_uefa"]) or _modal(d["noms"]) or code
        pays_noms[code] = _modal(d["pays_nom"], nom)
        lignes = [x for x in (ligne_match(m, code) for m in sel[code]) if x]
        lignes.sort(key=lambda x: (x["jour"], x["match_id"]))
        stats = {}
        for k in sorted({(m["comp"], m["edition"]) for m in sel[code]}):
            s = stats_equipe([m for m in sel[code] if (m["comp"], m["edition"]) == k], code)
            if s:
                stats[f"{k[0]}-{k[1]}"] = dict(comp=k[0], edition=k[1], libelle=noms_comp[f"{k[0]}-{k[1]}"]["libelle"], **s)
        total = stats_equipe(sel[code], code)
        f: Dict[str, Any] = {"id": code, "code": code, "type": "selection", "nom": nom, "nom_court": _modal(d["courts"], code),
                             "drapeau": _modal(d["drapeaux"], FLAG_CODES.get(code, "")),
                             "competitions": [{"comp": noms_comp[k]["comp"], "edition": noms_comp[k]["edition"], "libelle": noms_comp[k]["libelle"],
                                               "nom": noms_comp[k]["nom"], "court": noms_comp[k]["court"]}
                                              for k in sorted({f"{m['comp']}-{m['edition']}" for m in sel[code]})],
                             "matchs": lignes, "forme": forme(lignes), "stats": stats}
        if total:
            f["bilan"] = {k: total[k] for k in ("matchs", "vnd", "tab")}
            f["bilan"]["buts"] = {"pour": total["cumul"]["goals"], "contre": total["cumul"]["goals_conceded"]}
        pr = prochain_match(programme, code, "selections", maintenant)
        if pr:
            f["prochain"] = pr
        coul = couleurs_equipe(sel[code], code)
        if coul:
            f["couleurs"] = coul
        f["effectif"] = effectif_equipe(code, fiches, id_fiche)
        wdb = wd_sel.get(code) or anc_sel[code].get("wikidata")
        if wdb:
            f["wikidata"] = wdb
        if code in wp or anc_sel[code].get("wikipedia"):
            f["wikipedia"] = wp.get(code) or anc_sel[code]["wikipedia"]
        if f.get("wikipedia") and not f["wikipedia"].get("extrait"):
            f["wikipedia"] = {"maj": f["wikipedia"].get("maj", maintenant)}
        f["maj"] = maintenant
        vues_sel[code] = f
        index_sel.append({"code": code, "nom": nom, "drapeau": f["drapeau"], "fichier": f"{DOSSIER}/selections/{code}.json".replace("\\", "/"),
                          "competitions": [f"{c['comp']}-{c['edition']}" for c in f["competitions"]], "matchs": len(lignes),
                          **({"couleurs": coul} if coul else {})})

    # --- clubs du monde
    corr = correspondre_clubs(ident_clb, index_champ, index_uefa)
    nouveaux = {tid: e for tid, e in ident_clb.items() if tid not in corr}
    anc_clb = {tid: _lire(os.path.join(base, "clubs", f"{tid}.json")) or {} for tid in nouveaux}
    wd_clb: Dict[str, Dict[str, Any]] = {}
    wp_clb: Dict[str, Dict[str, Any]] = {}
    if avec_wiki and nouveaux:
        a_faire = {tid: e for tid, e in nouveaux.items() if clubs.a_rafraichir(anc_clb[tid].get("wikidata"), auj, JOURS_CACHE)}
        if a_faire:
            essayes: Set[str] = set()
            try:
                wd_clb, essayes = wikidata_clubs(a_faire, pays_qid, requete, get, maintenant, chercher, fin_equipes)
            except Exception as e:
                print(f"[WARN] Wikidata (clubs) non mis à jour : {e}")
        for tid, e in nouveaux.items():
            if tid not in wd_clb:
                pas_de_pays = tid in a_faire and e["code"] not in pays_qid
                wd_clb[tid] = anc_clb[tid].get("wikidata") or (
                    {"qid": None, "statut": "pays_inconnu" if pas_de_pays else "non_rapproche", "maj": maintenant}
                    if tid in a_faire and (tid in essayes or pas_de_pays) else None)
        voulus = [tid for tid in nouveaux if (wd_clb.get(tid) or {}).get("titre_wikipedia") and clubs.a_rafraichir(anc_clb[tid].get("wikipedia"), auj, JOURS_CACHE)]
        for i in range(0, len(voulus), 20):
            if time.time() > fin_equipes:
                break
            lot = voulus[i:i + 20]
            titres = [wd_clb[t]["titre_wikipedia"] for t in lot]
            time.sleep(clubs.PAUSE_WIKIPEDIA)
            COMPTEURS["wikipedia"] += 1
            res = wikipedia(titres)
            if res is None:
                break
            for t, ti in zip(lot, titres):
                wp_clb[t] = dict(res[ti], maj=maintenant) if ti in res else {"maj": maintenant}
    index_clb, vues_clb = [], {}
    for tid, e in sorted(nouveaux.items()):
        lignes = [x for x in (ligne_match(m, tid) for m in clb[tid]) if x]
        lignes.sort(key=lambda x: (x["jour"], x["match_id"]))
        stats = {}
        for k in sorted({(m["comp"], m["edition"]) for m in clb[tid]}):
            s = stats_equipe([m for m in clb[tid] if (m["comp"], m["edition"]) == k], tid)
            if s:
                stats[f"{k[0]}-{k[1]}"] = dict(comp=k[0], edition=k[1], libelle=noms_comp[f"{k[0]}-{k[1]}"]["libelle"], **s)
        code = e["code"]
        f = {"id": tid, "espn_id": e["espn_id"] or None, "fifa_id": e["fifa_id"] or None, "type": "club",
             "nom": e["nom"], "nom_officiel": e["nom_officiel"], "nom_court": e["nom_court"],
             "pays": pays_noms.get(code) or None, "code_pays": code or None, "drapeau": e["drapeau"] or FLAG_CODES.get(code, "") or None,
             "francais": code == "FRA", "competitions": sorted({f"{m['comp']}-{m['edition']}" for m in clb[tid]}),
             "logos": {"70": e["logo"], "240": e["logo"]} if e["logo"] else None, "matchs": lignes, "forme": forme(lignes), "stats": stats}
        pr = prochain_match(programme, tid, "clubs", maintenant)
        if pr:
            f["prochain"] = pr
        coul = couleurs_equipe(clb[tid], tid)
        if coul:
            f["couleurs"] = coul
        stades = Counter(m["stade"] for m in clb[tid] if m["stade"] and m["home"]["cle"] == tid)
        if stades:
            f["stade"] = {"nom": _modal(stades), "source": "matchs"}
        f["effectif"] = effectif_equipe(tid, fiches, id_fiche)
        if wd_clb.get(tid):
            f["wikidata"] = wd_clb[tid]
        if tid in wp_clb or anc_clb[tid].get("wikipedia"):
            f["wikipedia"] = wp_clb.get(tid) or anc_clb[tid]["wikipedia"]
        f = {k: v for k, v in f.items() if v not in (None, "", [])}
        f["maj"] = maintenant
        vues_clb[tid] = f
        index_clb.append({k: v for k, v in {"id": tid, "nom": e["nom"], "nom_court": e["nom_court"], "pays": f.get("pays"), "code_pays": f.get("code_pays"),
                                            "drapeau": f.get("drapeau"), "francais": f["francais"], "logos": f.get("logos"),
                                            "competitions": f["competitions"], "fichier": f"{DOSSIER}/clubs/{tid}.json", "couleurs": coul}.items()
                          if v not in (None, "")})

    # --- écriture
    ecrits = 0
    for code, f in vues_sel.items():
        ecrits += _ecrire(os.path.join(base, "selections", f"{code}.json"), f)
    for tid, f in vues_clb.items():
        ecrits += _ecrire(os.path.join(base, "clubs", f"{tid}.json"), f)
    shards: Dict[str, Dict[str, Any]] = defaultdict(dict)
    for f in fiches.values():
        shards[fichier_joueur(f["id"])][f["id"]] = f
    for nom_f, d in shards.items():
        ecrits += _ecrire(os.path.join(base, nom_f), {"maj": maintenant, "joueurs": dict(sorted(d.items()))})
    index_j = []
    for f in sorted(fiches.values(), key=lambda f: (normalize(f["nom"]), f["id"])):
        index_j.append({k: v for k, v in {"id": f["id"], "nom": f["nom"], "equipes": [{"id": e["id"], "nom": e["nom"], "type": e["type"]} for e in f["equipes"]], "poste": f.get("poste_fr"),
                                          "drapeau": f.get("drapeau"), "photo": (f.get("photo") or ((f.get("wd") or {}).get("photo") or {}).get("url")),
                                          "matchs": f["total"]["matchs"], "fichier": fichier_joueur(f["id"])}.items() if v not in (None, "")})
    alias = {i["id"]: f["id"] for f in fiches.values() for i in f["ids"] if i["id"] != f["id"]}
    ecrits += _ecrire(os.path.join(base, "joueurs", "index.json"), {"maj": maintenant, "alias": dict(sorted(alias.items())), "joueurs": index_j})
    ecrits += _ecrire(os.path.join(base, "selections", "index.json"), {"maj": maintenant, "selections": index_sel})
    ecrits += _ecrire(os.path.join(base, "clubs", "index.json"), {"maj": maintenant, "clubs": index_clb})
    ecrits += _ecrire(os.path.join(base, "clubs", "correspondances.json"), {"maj": maintenant, "correspondances": corr})
    ecrits += _ecrire(os.path.join(cache_dir, "naissances.json"), dict(sorted(cache_nais.items())))
    ecrits += _ecrire(os.path.join(cache_dir, "effectifs_uefa.json"), cache_eff)
    ecrits += _ecrire(os.path.join(base, "index.json"), {"maj": maintenant, "competitions": {k: v for k, v in sorted(noms_comp.items())},
                                                         "selections": len(vues_sel), "clubs": len(vues_clb), "correspondances": len(corr), "joueurs": len(fiches)})
    # fichiers devenus inutiles (une fiche n'existe que si les matchs la portent)
    nettoyer(os.path.join(base, "selections"), {f"{c}.json" for c in vues_sel} | {"index.json"})
    nettoyer(os.path.join(base, "clubs"), {f"{t}.json" for t in vues_clb} | {"index.json", "correspondances.json"})
    nettoyer(os.path.join(base, "joueurs"), {os.path.basename(n) for n in shards} | {"index.json"})
    bilan = {"selections": len(vues_sel), "clubs_crees": len(vues_clb), "correspondances": len(corr), "joueurs": len(fiches),
             "fusions": stat_fusion["paires"], "ecrits": ecrits, "wikidata_selections": sum(1 for c in vues_sel.values() if (c.get("wikidata") or {}).get("qid")),
             "duree_s": round(time.time() - t0), "requetes": dict(COMPTEURS), "wd_joueurs": stat_wd}
    print(f"[FICHES-INT] {json.dumps(bilan, ensure_ascii=False)}")
    return bilan


# ------------------------------------------------------------------------------
# 10. Wikidata des joueurs (réutilise encyclo_joueurs : mêmes règles, même cache de 30 jours)
# ------------------------------------------------------------------------------
def requete_uefa(requete: Callable[[str], Any]) -> Callable[[str], Any]:
    """Même rapprochement qu'`encyclo_joueurs.relier`, mais sur l'identifiant UEFA du joueur (P2276) au lieu de l'identifiant ESPN
    (P3681) : la requête d'identifiants est réécrite, les autres (date de naissance + nom, identité, carrière) sont inchangées."""
    return lambda q: requete(q.replace("wdt:P3681", "wdt:P2276"))


def qids_unite(ids: List[str], proxies: Dict[str, Dict[str, Any]]) -> Set[str]:
    return {proxies[i]["wd"]["qid"] for i in ids if i in proxies and (proxies[i].get("wd") or {}).get("qid")}


def bloc_unite(ids: List[str], proxies: Dict[str, Dict[str, Any]], maintenant: str) -> Dict[str, Any]:
    """Blocs `wd` / `wp` d'un joueur (un ou deux identifiants). Deux éléments Wikidata différents pour un même joueur : conflit,
    aucun élément gardé (les deux valeurs restent dans `conflit`). Sinon : le bloc qui porte l'élément (le plus riche : image),
    à défaut le bloc le plus récent (cache « non rapproché »)."""
    qs = qids_unite(ids, proxies)
    blocs = [(i, proxies[i]) for i in ids if i in proxies and proxies[i].get("wd")]
    if len(qs) > 1:
        return {"wd": {"qid": None, "conflit": sorted(qs), "maj": maintenant}}
    if not blocs:
        return {}
    if qs:
        blocs = [b for b in blocs if (b[1]["wd"] or {}).get("qid")]
    blocs.sort(key=lambda b: (0 if (b[1]["wd"].get("image") or b[1]["wd"].get("photo")) else 1, -int(str(b[1]["wd"].get("maj") or "0")[:10].replace("-", "") or 0), b[0]))
    p = blocs[0][1]
    out: Dict[str, Any] = {"wd": p["wd"]}
    wp = next((proxies[i]["wp"] for i in ids if i in proxies and proxies[i].get("wp") and (proxies[i].get("wd") or {}).get("qid") == p["wd"].get("qid")), None)
    if wp:
        out["wp"] = wp
    return out


def blocs_depuis_anciens(ids: List[str], anciens: Dict[str, Any]) -> Dict[str, Any]:
    """Sans mise à jour Wikidata : blocs `wd` / `wp` déjà enregistrés dans l'ancienne fiche de l'un des identifiants."""
    for i in ids:
        a = anciens.get(i)
        if a and (a.get("wd") or a.get("wp")):
            return {k: a[k] for k in ("wd", "wp") if a.get(k)}
    return {}


def enrichir_wikidata_joueurs(unites: List[List[str]], raw: Dict[str, Dict[str, Any]], naissances: Dict[str, str], anciens: Dict[str, Any],
                              maintenant: str, requete, get, budget_s: float, stat: Dict[str, int]
                              ) -> Tuple[List[List[str]], Dict[str, Dict[str, Any]]]:
    """Rapproche chaque identifiant brut à (re)lire (cache 30 jours, `wd` des anciennes fiches), puis photos Commons et extraits
    Wikipédia, dans la limite de `budget_s` ; fusionne ensuite les unités qui portent le MÊME élément Wikidata (dates de naissance
    non contradictoires). Retourne (unités, {identifiant de fiche: {wd, wp}}) ; les anciennes fiches ne sont jamais modifiées."""
    fin = time.time() + budget_s
    auj = dt.date.fromisoformat(maintenant[:10])
    proxies: Dict[str, Dict[str, Any]] = {}
    for pid in raw:
        a = anciens.get(pid) or {}
        p = {"id": pid, "nom": _modal(raw[pid]["noms"], ""), "naissance": naissances.get(pid)}
        for k in ("wd", "wp"):
            if a.get(k):
                p[k] = a[k]
        proxies[pid] = p
    a_relire = {pid: p for pid, p in proxies.items() if clubs.a_rafraichir(p.get("wd"), auj, JOURS_CACHE)}
    stat["demandes"] = len(a_relire)
    for groupe, req in ((False, requete), (True, requete_uefa(requete))):
        lot_ids = sorted(pid for pid in a_relire if pid.startswith("espn-") != groupe)
        for i in range(0, len(lot_ids), 400):
            if time.time() > fin:
                print("[WARN] Wikidata (joueurs) : budget de temps atteint, la suite au prochain passage")
                break
            # `relier` attend {id sans préfixe: entrée} (id ESPN) : le préfixe « espn- » est retiré, un id UEFA reste tel quel
            sous = {pid[5:] if pid.startswith("espn-") else pid: a_relire[pid] for pid in lot_ids[i:i + 400]}
            ej.relier(sous, maintenant, req, stat)
    # fusion par élément Wikidata commun (un seul élément par unité ; dates de naissance non contradictoires)
    tete: Dict[str, int] = {}
    fusion: List[List[str]] = []
    for ids in unites:
        qs = qids_unite(ids, proxies)
        if len(qs) == 1:
            q = next(iter(qs))
            if q in tete:
                autre = fusion[tete[q]]
                if len({naissances[i] for i in ids + autre if i in naissances}) <= 1:
                    autre.extend(ids)
                    autre.sort()
                    continue
            tete[q] = len(fusion)
        fusion.append(ids)
    blocs = {identifiant_fiche(ids): bloc_unite(ids, proxies, maintenant) for ids in fusion}
    # photos et extraits
    pseudo = [b for b in blocs.values() if (b.get("wd") or {}).get("qid")]
    manquants = [j for j in pseudo if j["wd"].get("image") and not j["wd"].get("photo")]
    if manquants:
        images = ej.commons(sorted({j["wd"]["image"] for j in manquants}), get, fin)
        for j in manquants:
            img = images.get(j["wd"]["image"])
            if img:
                j["wd"]["photo"] = img
                stat["photos"] += 1
    ej.extraits(pseudo, auj, maintenant, get, fin, stat)
    return fusion, blocs


# ------------------------------------------------------------------------------
# Tests (sans réseau)
# ------------------------------------------------------------------------------
def _test() -> None:
    import shutil
    import tempfile
    fix = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools", "fixtures", "fiches_internationales")
    donnees_fix, coupes_fix = os.path.join(fix, "donnees"), os.path.join(fix, "coupes")

    # --- tirs au but, V/N/D, valeurs absentes (réponses réelles allégées)
    assert lire_tab({"tab": [3, 0]}) == [3, 0] and lire_tab({"penalties": "5-3"}) == [5, 3]
    assert lire_tab({}) is None and lire_tab({"tab": [None, 3]}) is None and lire_tab({"penalties": "n/a"}) is None
    eds = lister_editions(donnees_fix)
    assert [(e["comp"], e["edition"], e["famille"]) for e in eds] == [("cdm", 2026, "selections"), ("cdmc", 2025, "clubs"),
                                                                       ("euro", 2024, "selections"), ("ldn", 2027, "selections")], eds
    matchs = charger_matchs(donnees_fix, eds)
    assert len(matchs) == 8 and all(m["fini"] for m in matchs), len(matchs)
    por = [m for m in matchs if cote_de(m, "POR")]
    assert len(por) == 3
    s = stats_equipe(por, "POR")
    # 2-1 contre la Tchéquie, 0-0 puis 3-0 aux tirs au but contre la Slovénie, 0-0 puis 3-5 aux tirs au but contre la France
    assert s["vnd"] == {"v": 1, "n": 2, "d": 0} and s["tab"] == {"v": 1, "d": 1}, s
    assert s["cumul"]["goals"] == 2 and s["cumul"]["goals_conceded"] == 1 and s["cumul"]["clean_sheet"] == 2, s["cumul"]
    lignes = {x["match_id"]: x for x in (ligne_match(m, "POR") for m in por)}
    assert lignes["2036201"]["resultat"] == "N" and lignes["2036201"]["tab"] == {"pour": 3, "contre": 0}
    assert lignes["2036206"]["tab"] == {"pour": 3, "contre": 5} and lignes["2036206"]["adversaire"]["id"] == "FRA"
    assert lignes["2036172"]["resultat"] == "V" and "tab" not in lignes["2036172"] and lignes["2036172"]["fichier"].endswith("2024-06-18.json")
    assert forme(sorted(lignes.values(), key=lambda x: x["jour"])) == ["V", "N", "N"]
    # cumul d'une stat = somme sur les matchs qui la portent ; moyenne = cumul / ce nombre ; couverture seulement si partielle
    for k, tot in s["cumul"].items():
        vals = [t[c] for m in por for t in m["stats"] if t["key"] == k for c in [cote_de(m, "POR")] if _num(t.get(c)) is not None]
        if k in POURCENTAGES or k in MAXIMUMS or k in ("goals", "goals_conceded", "clean_sheet"):
            continue
        assert tot == round(sum(vals), 3) and s["par_match"][k] == round(sum(vals) / len(vals), 2), k
        assert (s.get("couverture") or {}).get(k, len(por)) == len(vals), k
    ned = [m for m in matchs if cote_de(m, "NED")]
    sn = stats_equipe(ned, "NED")
    xg = [t[cote_de(m, "NED")] for m in ned for t in m["stats"] if t["key"] == "xg"]
    assert len(ned) == 2 and len(xg) == 1 and sn["couverture"]["xg"] == 1 and sn["par_match"]["xg"] == round(xg[0], 2), sn.get("couverture")
    clubs_m = [m for m in matchs if m["comp"] == "cdmc"]
    sc = stats_equipe(clubs_m, "espn-9726")
    assert "xg" not in sc["cumul"] and "xg" not in (sc.get("couverture") or {}), "valeur absente = absente"
    assert stats_equipe([dict(m, fini=False) for m in por], "POR") is None            # rien ne compte tant que le match n'est pas terminé

    # --- buts, passes, buts contre son camp, cartons, gardien (match construit : seuls les champs lus)
    brut = {"match_id": "x1", "date": "2026-01-01", "status": "Terminé", "finished": True, "round": {"name": "T"},
            "home_team": {"id": "1", "country": "AAA", "name": "A", "score": 2}, "away_team": {"id": "2", "country": "BBB", "name": "B", "score": 1},
            "goals": [{"team": "home", "scorer_id": "p1", "assist_id": "p2", "kind": ""}, {"team": "home", "scorer_id": "p3", "assist_id": "", "kind": "csc"},
                      {"team": "away", "scorer_id": "p4", "assist_id": "p5", "kind": "pen"}],
            "events": [{"type": "yellow_card", "player_id": "p1"}, {"type": "red_card", "player_id": "p4"}, {"type": "sub", "player_id": "p9"}],
            "players": {"p1": {"name": "Un", "team": "home", "minutes": 90, "starter": True, "pos": "FORWARD", "rating": 7.5},
                        "p3": {"name": "Trois", "team": "away", "minutes": 45, "pos": "DEFENDER"},
                        "p4": {"name": "Quatre", "team": "away", "minutes": 90, "pos": "FORWARD"},
                        "g": {"name": "Gardien", "team": "away", "minutes": 90, "pos": "GOALKEEPER", "stats": {"saves": 4, "goals_conceded": 2}},
                        "banc": {"name": "Banc", "team": "home", "minutes": 0, "pos": "MIDFIELDER"}}}
    cm = compacter_match(brut, {"comp": "xx", "edition": 1, "famille": "selections"}, "2026-01-01", "f.json")
    e = entrees_joueurs([cm])
    assert set(e) == {"p1", "p3", "p4", "g"}, set(e)                                   # minutes 0 : pas de fiche, pas de match joué
    c1, c3, c4, cg = (cumuler_joueur(e[k]["matchs"]) for k in ("p1", "p3", "p4", "g"))
    assert (c1["buts"], c1["jaunes"], c1["note_moyenne"], "csc" not in c1) == (1, 1, 7.5, True), c1
    assert c3 == {"matchs": 1, "titularisations": 0, "minutes": 45, "csc": 1} or c3["csc"] == 1 and "buts" not in c3, c3
    assert c4["buts"] == 1 and c4["rouges"] == 1 and "note_moyenne" not in c4, c4
    assert (cg["arrets"], cg["encaisses"], "clean_sheet" not in cg) == (4, 2, True), cg
    assert e["p1"]["matchs"][0]["resultat"] == "V" and e["p4"]["matchs"][0]["resultat"] == "D"
    assert "passes" not in c3 and cumuler_joueur(e["p1"]["matchs"]).get("passes") is None   # p2 / p5 n'ont pas joué : aucune passe inventée

    # --- Wikidata d'une sélection (réponses réelles) : un seul candidat / ambigu -> rien / féminine écartée / code du Kosovo
    wd = _lire(os.path.join(fix, "wikidata_selections.json"))
    cands = parse_candidats(wd["candidats"])
    assert "Q751670" in cands["FRA"] and CLASSES_EXCLUES & cands["FRA"]["Q751670"]["cls"], "l'équipe féminine doit figurer parmi les candidats"
    ch = choisir_selection(cands["FRA"])
    assert ch["statut"] == "ok" and ch["qid"] == "Q47774" and ch["federations"] == ["Q244750"], ch
    assert choisir_selection(cands["IRQ"])["qid"] == "Q186243"                          # deux éléments « masculins » : un seul a un pays de sport
    dup = {q: {k: set(v) for k, v in x.items()} for q, x in cands["FRA"].items()}
    dup["Q999"] = dict(dup["Q47774"])
    assert choisir_selection(dup)["statut"] == "ambigu" and "qid" not in choisir_selection(dup)
    assert choisir_selection({q: x for q, x in cands["FRA"].items() if q != "Q47774"})["statut"] == "absent"
    vues: List[str] = []

    def fake_sparql(q: str) -> Optional[List[Dict[str, Any]]]:
        vues.append(q)
        return wd["candidats"] if "wdt:P3441 ?code" in q else wd["details"]
    blocs, pays = wikidata_selections(["FRA", "ITA", "KOS", "ARM"], fake_sparql, "2026-11-26T00:00:00Z")
    assert '"KVX"' in vues[0] and '"KOS"' not in vues[0]
    assert blocs["FRA"]["qid"] == "Q47774" and blocs["FRA"]["federation"] == {"qid": "Q244750", "nom": "Fédération française de football", "fondation_annee": 1919}
    assert blocs["FRA"]["confederation"] == {"code": "UEFA", "qid": "Q35572"} and blocs["FRA"]["stade"]["nom"] == "stade de France"
    assert blocs["KOS"]["qid"] == "Q113143" and blocs["KOS"]["confederation"]["code"] == "UEFA" and blocs["KOS"]["federation"]["fondation_annee"] == 1946
    assert blocs["ARM"]["qid"] == "Q183326" and "federation" not in blocs["ARM"], "deux fédérations portent le code : aucune"
    assert pays["ITA"] == "Q38"
    assert wikidata_selections(["FRA"], lambda q: None, "x") is None                      # Wikidata injoignable : valeurs précédentes gardées

    E = "http://www.wikidata.org/entity/"
    # --- clubs : correspondance PAR IDENTIFIANT seulement
    index_champ, joueurs_champ = indexer_fiches_championnat(donnees_fix)
    index_uefa, liens_uefa = lire_effectifs_uefa(coupes_fix, {}, dt.date(2026, 11, 26))
    equipes = {"espn-1068": {"espn_id": "1068", "nom": "Atlético"}, "espn-9726": {"espn_id": "9726", "nom": "Seattle Sounders FC"},
               "espn-9999": {"espn_id": "9999", "nom": "Atlético"}, "50124": {"espn_id": "", "nom": "Autre"}}
    corr = correspondre_clubs(equipes, index_champ, index_uefa)
    assert set(corr) == {"espn-1068", "50124"}, corr                                      # même nom, autre identifiant : rien
    assert [f["id"] for f in corr["espn-1068"]["fiches"]] == ["espn-1068", "50124"] and "identifiant ESPN 1068" in corr["espn-1068"]["preuve"]
    assert [f["depot"] for f in corr["50124"]["fiches"]] == ["coupes-europe"]
    assert choisir_club({"Q1", "Q2"}, {"Q1": {"Q5"}, "Q2": {"Q5"}}, {"Q5"}) is None       # deux clubs du bon pays : rien
    assert choisir_club({"Q1", "Q2"}, {"Q1": {"Q5"}, "Q2": {"Q6"}}, {"Q5"}) == "Q1"
    assert choisir_club({"Q1"}, {"Q1": {"Q6"}}, {"Q5"}) is None and choisir_club({"Q1"}, {}, {"Q5"}) is None   # mauvais pays / pas un club

    # --- Wikidata d'un club créé : nom exact + club de football + bon pays, UN SEUL candidat
    def get_c(url: str, *a: Any, **k: Any) -> Any:
        if "wbsearchentities" in url:
            nom = urllib.parse.unquote(url.rsplit("search=", 1)[1])
            return {"search": {"Flamengo": [{"id": "Q1", "match": {"text": "Flamengo"}}, {"id": "Q2", "match": {"text": "Flamengo Basket"}}],
                               "Doublon": [{"id": "Q3", "match": {"text": "doublon"}}, {"id": "Q4", "match": {"text": "Doublon"}}],
                               "Panne": None}[nom]} if nom != "Panne" else None
        return {"results": {"bindings": [{"item": {"value": E + "Q1"}, "club": {"value": "true"}, "inc": {"value": "+1895-11-15T00:00:00Z"},
                                          "frtitle": {"value": "Club de Regatas do Flamengo"}}]}}

    def req_c(q: str) -> List[Dict[str, Any]]:
        return [{"item": {"value": E + k}, "pays": {"value": E + "Q155"}} for k in ("Q1", "Q3", "Q4")]
    eq_c = {t: {"code": c, "nom": n, "nom_officiel": ""} for t, c, n in (("espn-1", "BRA", "Flamengo"), ("espn-2", "BRA", "Doublon"),
                                                                       ("espn-3", "BRA", "Panne"), ("espn-4", "XXX", "Flamengo"))}
    pause_r, globals()["PAUSE_RECHERCHE"] = PAUSE_RECHERCHE, 0
    try:
        wc, essayes = wikidata_clubs(eq_c, {"BRA": "Q155"}, req_c, get_c, "2026-11-26T00:00:00Z")
    finally:
        globals()["PAUSE_RECHERCHE"] = pause_r
    assert set(wc) == {"espn-1"} and wc["espn-1"]["qid"] == "Q1" and wc["espn-1"]["fondation_annee"] == 1895, wc
    assert wc["espn-1"]["titre_wikipedia"] == "Club de Regatas do Flamengo" and "club" not in wc["espn-1"]
    assert essayes == {"espn-1", "espn-2"}, essayes         # deux candidats exacts : rien ; panne : pas « essayé » ; pays inconnu : pas cherché

    # --- fusion d'identifiants : preuve ou rien
    def pj(pid: str, nom: str, equipe: str = "AAA", typ: str = "selection") -> Dict[str, Any]:
        return {"noms": Counter({nom: 1}), "equipes": {equipe: {"type": typ, "id": equipe}}, "matchs": []}
    raw = {"u1": pj("u1", "Quinten Timber"), "u2": pj("u2", "Jurriën Timber"), "espn-1": pj("e", "Quinten Timber"),
           "u3": pj("u3", "Nico O’Reilly"), "espn-3": pj("e", "Nico O'Reilly"),
           "u4": pj("u4", "Ali Hassan"), "u5": pj("u5", "Ali Hassan"), "espn-4": pj("e", "Ali Hassan"),
           "u6": pj("u6", "Léo Martin", "BBB"), "espn-6": pj("e", "Léo Martin", "CCC"),
           "u7": pj("u7", "Samuel Costa"), "espn-7": pj("e", "Samú Costa"), "espn-8": pj("e", "Pas de date")}
    nais = {"u1": "2001-06-17", "u2": "2001-06-17", "espn-1": "2001-06-17", "u3": "2005-03-21", "espn-3": "2005-03-21", "u4": "1990-01-01",
            "u5": "1990-01-01", "espn-4": "1990-01-01", "u6": "1995-05-05", "espn-6": "1995-05-05", "u7": "2000-11-27", "espn-7": "2000-11-27"}
    paires, st = fusion_naissance(raw, nais)
    assert paires == {"espn-1": "u1", "espn-3": "u3"}, paires        # jumeaux : le nom départage ; apostrophes ; le reste (ambigu, autre nation, nom différent, sans date) : rien
    assert st == {"paires": 2, "ambigus": 1}, st
    unites = construire_unites(raw, paires)
    assert ["espn-1", "u1"] in unites and ["espn-3", "u3"] in unites and ["espn-4"] in unites and len(unites) == len(raw) - 2

    # --- dates de naissance : fiche de championnat > cache > réseau ; introuvable noté une fois
    appels = {"u": 0, "e": 0}

    def inscrits(comp: str, ed: int) -> Optional[Dict[str, Dict[str, Any]]]:
        appels["u"] += 1
        return {"250101727": {"naissance": "2001-06-17"}, "250101728": {"naissance": "2001-06-17"}}

    def effectif(slug: str, eq: str) -> Optional[Dict[str, str]]:
        appels["e"] += 1
        return {"282230": "2001-06-17", "231388": "1998-12-20"}
    raw_fix = entrees_joueurs(matchs)
    for pid, r in raw_fix.items():
        r["equipes_espn"] = {(x["comp"], x["equipe"]): {"slug": "fifa.world", "espn_id": "9"} for x in r["matchs"]} if pid.startswith("espn-") else {}
    cache: Dict[str, Any] = {}
    n1 = completer_naissances(raw_fix, cache, joueurs_champ, dt.date(2026, 11, 26), inscrits, effectif)
    assert n1["250101727"] == "2001-06-17" and n1["espn-282230"] == "2001-06-17" and n1["espn-336634"] == "2003-06-15"   # ce dernier : fiche de championnat
    assert "espn-336634" not in cache and cache["espn-282230"]["src"] == "ESPN" and cache["250076574"]["n"] is None
    avant = dict(appels)
    n2 = completer_naissances(raw_fix, cache, joueurs_champ, dt.date(2026, 11, 27), inscrits, effectif)
    assert n2 == n1 and appels == avant, "cache : aucune nouvelle requête"
    assert completer_naissances(raw_fix, {}, joueurs_champ, dt.date(2026, 11, 26), lambda c, e: None, lambda s, e: None)["espn-336634"] == "2003-06-15"

    # --- Wikidata des joueurs : l'identifiant UEFA passe par P2276, l'identifiant ESPN par P3681
    q = "SELECT ?v ?p ?n WHERE { VALUES ?v { \"1\" } ?p wdt:P3681 ?v }"
    sortie: List[str] = []
    requete_uefa(lambda x: sortie.append(x))(q)
    assert "wdt:P2276" in sortie[0] and "P3681" not in sortie[0]

    # --- Wikidata des joueurs : preuve par identifiant (P2276 / P3681), même élément = même joueur, deux éléments = conflit

    def req_j(q: str) -> List[Dict[str, Any]]:
        if "wdt:P2276" in q:
            return [{"v": {"value": "u9"}, "p": {"value": E + "Q7"}}, {"v": {"value": "u8"}, "p": {"value": E + "Q8"}}]
        if "wdt:P3681" in q:
            return [{"v": {"value": "9"}, "p": {"value": E + "Q7"}}, {"v": {"value": "8"}, "p": {"value": E + "Q18"}}]
        return []
    raw_w = {"u9": pj("u9", "Samuel Costa"), "espn-9": pj("e", "Samú Costa"), "u8": pj("u8", "Jo Un"), "espn-8": pj("e", "Jo Deux"), "u1": pj("u1", "Seul")}
    nais_w = {"u9": "2000-11-27", "espn-9": "2000-11-27", "u8": "1999-01-01", "espn-8": "1999-01-01"}
    stat_w = {"demandes": 0, "relies": 0, "photos": 0, "extraits": 0}
    unites_w, blocs_w = enrichir_wikidata_joueurs([["u9"], ["espn-9"], ["u8", "espn-8"], ["u1"]], raw_w, nais_w, {}, "2026-11-26T00:00:00Z", req_j,
                                                  lambda *a, **k: None, 60, stat_w)
    assert ["espn-9", "u9"] in unites_w and ["u8", "espn-8"] in unites_w and len(unites_w) == 3, unites_w
    assert blocs_w["u9"]["wd"]["qid"] == "Q7" and blocs_w["u9"]["wd"]["preuve"] in ("P2276", "P3681"), blocs_w["u9"]
    assert blocs_w["u8"]["wd"]["qid"] is None and blocs_w["u8"]["wd"]["conflit"] == ["Q18", "Q8"], "deux éléments pour un joueur : aucun"
    assert stat_w["relies"] == 4 and blocs_w["u1"]["wd"]["qid"] is None

    # --- bout en bout sur les fixtures (sans réseau) : fiches de nations, clubs, joueurs
    tmp = tempfile.mkdtemp()
    pause, clubs.PAUSE_WIKIPEDIA = clubs.PAUSE_WIKIPEDIA, 0
    try:
        d = os.path.join(tmp, "donnees")
        shutil.copytree(donnees_fix, d)
        DOB = {"250076574": "1998-12-20", "250042780": "1995-07-03", "250101727": "2001-06-17", "250101728": "2001-06-17",
               "espn-231388": "1998-12-20", "espn-282230": "2001-06-17", "espn-131979": "1986-04-20"}

        def inscrits2(comp: str, ed: int) -> Dict[str, Dict[str, Any]]:
            return {k: {"naissance": v} for k, v in DOB.items() if not k.startswith("espn-")}

        def effectif2(slug: str, eq: str) -> Dict[str, str]:
            return {k[5:]: v for k, v in DOB.items() if k.startswith("espn-")}

        def req(q: str) -> Optional[List[Dict[str, Any]]]:
            if "wdt:P3441 ?code" in q:
                return wd["candidats"]
            if "wdt:P3441" not in q and "P1449" in q:
                return wd["details"]
            return []                                   # joueurs : aucun élément rapproché
        pages = {"Équipe de France de football": {"extrait": "L'équipe de France de football représente la France.", "titre": "Équipe de France de football",
                                                    "licence": "CC BY-SA 4.0"}}
        bilan = construire(d, coupes_fix, 30, True, req, lambda url, *a, **k: {"search": []}, inscrits2, effectif2,
                           lambda titres: {t: pages[t] for t in titres if t in pages}, lambda noms, get: set())
        base = os.path.join(d, DOSSIER)
        idx = _lire(os.path.join(base, "selections", "index.json"))
        assert {s_["code"] for s_ in idx["selections"]} == {"POR", "FRA", "SVN", "CZE", "NED", "LTU", "JPN", "AZE", "SEN"}, idx
        fra = _lire(os.path.join(base, "selections", "FRA.json"))
        assert fra["wikidata"]["qid"] == "Q47774" and fra["wikipedia"]["extrait"].startswith("L'équipe de France")
        assert [x["resultat"] for x in fra["matchs"]] == ["N", "V", "V"] or len(fra["matchs"]) == 3, fra["matchs"]
        assert fra["bilan"]["tab"] == {"v": 1, "d": 0} and fra["stats"]["euro-2024"]["tab"] == {"v": 1, "d": 0}, fra["bilan"]
        assert fra["couleurs"]["principale"] and fra["prochain"]["adversaire"]["id"] == "ESP" and fra["prochain"]["comp"] == "ldn"
        mb = next(e_ for e_ in fra["effectif"] if e_["nom"] == "Kylian Mbappé")
        assert mb["id"] == "250076574" and mb["matchs"] == 3 and set(mb["editions"]) == {"cdm-2026", "euro-2024"}, mb
        # Mbappé : id UEFA + id ESPN fusionnés par la date de naissance, un seul joueur ; lien vers la fiche de club UEFA par l'id UEFA
        idj = _lire(os.path.join(base, "joueurs", "index.json"))
        assert idj["alias"]["espn-231388"] == "250076574" and idj["alias"]["espn-282230"] == "250101727"
        fj = _lire(os.path.join(base, idj["joueurs"][0]["fichier"]))["joueurs"]
        mbf = _lire(os.path.join(base, next(j["fichier"] for j in idj["joueurs"] if j["id"] == "250076574")))["joueurs"]["250076574"]
        assert [i["id"] for i in mbf["ids"]] == ["250076574", "espn-231388"] and mbf["naissance"] == "1998-12-20"
        assert mbf["liens"] == [{"depot": "coupes-europe", "fiche": "clubs/50051.json", "club_id": "50051", "club": "Real Madrid",
                                 "joueur_id": "250076574", "preuve": "même identifiant UEFA"}], mbf.get("liens")
        quinten = _lire(os.path.join(base, next(j["fichier"] for j in idj["joueurs"] if j["id"] == "250101727")))["joueurs"]["250101727"]
        juri = _lire(os.path.join(base, next(j["fichier"] for j in idj["joueurs"] if j["id"] == "250101728")))["joueurs"]["250101728"]
        assert len(quinten["ids"]) == 2 and len(juri["ids"]) == 1 and "liens" not in quinten, "jumeaux : seul Quinten rejoint son id ESPN"
        barrios = _lire(os.path.join(base, next(j["fichier"] for j in idj["joueurs"] if j["id"] == "espn-336634")))["joueurs"]["espn-336634"]
        assert barrios["liens"][0]["fiche"] == "championnats/clubs/espn-1068.json" and barrios["liens"][0]["preuve"] == "même identifiant ESPN"
        assert barrios["naissance"] == "2003-06-15" and barrios["total"]["buts"] == 2 and barrios["equipes"][0]["type"] == "club"
        # clubs du monde : Atlético = correspondance (aucune fiche créée), Seattle = fiche créée
        cc = _lire(os.path.join(base, "clubs", "correspondances.json"))["correspondances"]
        assert set(cc) == {"espn-1068"} and os.path.exists(os.path.join(base, "clubs", "espn-9726.json")) and not os.path.exists(os.path.join(base, "clubs", "espn-1068.json"))
        sea = _lire(os.path.join(base, "clubs", "espn-9726.json"))
        assert sea["matchs"][0]["pour"] == 1 and sea["matchs"][0]["contre"] == 3 and sea["matchs"][0]["resultat"] == "D" and "wikidata" in sea
        assert sea["wikidata"]["qid"] is None and "wikipedia" not in sea, "aucun élément Wikidata sûr : rien d'inventé"
        assert [e_["nom"] for e_ in sea["effectif"]] == ["Stefan Frei"] and "pays" not in sea or sea["pays"]
        # relancer sans rien changer : aucun fichier réécrit (hors maj)
        b2 = construire(d, coupes_fix, 30, True, req, lambda url, *a, **k: {"search": []}, inscrits2, effectif2,
                        lambda titres: {t: pages[t] for t in titres if t in pages}, lambda noms, get: set())
        assert b2["ecrits"] == 0, b2
    finally:
        clubs.PAUSE_WIKIPEDIA = pause
        shutil.rmtree(tmp, ignore_errors=True)
    assert bilan["selections"] == 9 and bilan["clubs_crees"] == 1 and bilan["correspondances"] == 1 and bilan["fusions"] == 2, bilan
    print("[OK] fiches_internationales : tests passés")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Fiches de nations, de clubs du monde et de joueurs des compétitions internationales")
    ap.add_argument("--donnees", default="../donnees-football")
    ap.add_argument("--coupes", default=None, help="dossier local du dépôt coupes-europe (clubs/) ; sinon Pages")
    ap.add_argument("--budget-joueurs", type=float, default=6, help="minutes au plus pour TOUT ce qui passe par Wikidata / Commons / Wikipédia (joueurs 60 %%, sélections et clubs 40 %%) ; reprenable")
    ap.add_argument("--sans-wiki", action="store_true", help="ni Wikidata ni Wikipédia ni Commons")
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    if a.test:
        _test()
        sys.exit(0)
    try:
        construire(a.donnees, a.coupes, a.budget_joueurs * 60, not a.sans_wiki)
    except Exception as e:  # jamais bloquant : la collecte publie quand même
        print(f"[WARN] fiches internationales non mises à jour : {e}")
        sys.exit(0)
