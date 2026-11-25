#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Encyclopédie des JOUEURS de championnat (effectif des fiches `championnats/clubs/espn-<id>.json`, appelé par `fiches_ligues.construire`) :
photo (Wikimedia Commons, auteur et licence), taille, lieu de naissance, carrière en clubs et en sélection (dates, matchs / buts quand
Wikidata les donne), extrait Wikipédia FR. Décision du propriétaire du 25/11/2026 (« Go pour les deux »).

Rapprochement joueur ESPN <-> élément Wikidata, jamais par le nom seul :
1. `P3681` (identifiant ESPN FC du joueur) = id ESPN : accepté, sauf si les deux dates de naissance existent et diffèrent ;
2. sinon : footballeur (P106 = Q937857) né le MÊME JOUR (P569 à précision jour : une date connue à l'année seulement, stockée au
   1er janvier, ne compte pas) ET dont un libellé / alias (fr, en, mul) concorde avec le nom ESPN (tous les mots du nom le plus court
   présents dans l'autre) ; UN SEUL candidat, sinon rien (ambigu).
Valeurs multiples : taille / lieu de naissance gardés seulement s'ils sont uniques. Photo : seulement avec une licence lisible sur Commons.
Cache : bloc `wd` de chaque joueur relu après 30 jours ; un joueur non rapproché (`qid: null`) est retenté après 30 jours ; un échec réseau
ne remplace jamais une valeur obtenue.

    python encyclo_joueurs.py --test
"""

import gzip
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from typing import Any, Callable, Dict, List, Optional

import clubs

FOOTBALLEUR = "Q937857"
SELECTION = "Q6979593"          # équipe nationale de football (et sous-classes : espoirs, jeunes…)
JOURS_CACHE = 30


# ------------------------------------------------------------------------------
# Réseau (SPARQL en POST : les listes VALUES dépassent la longueur d'une URL)
# ------------------------------------------------------------------------------
def sparql(requete: str, essais: int = 3) -> Optional[List[Dict[str, Any]]]:
    corps = urllib.parse.urlencode({"query": requete, "format": "json"}).encode()
    for i in range(essais):
        try:
            req = urllib.request.Request("https://query.wikidata.org/sparql", data=corps,
                                         headers={"User-Agent": clubs.UA_WIKI, "Accept": "application/sparql-results+json",
                                                  "Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req, timeout=120) as r:
                b = r.read()
                if b[:2] == b"\x1f\x8b":
                    b = gzip.decompress(b)
                return json.loads(b.decode("utf-8"))["results"]["bindings"]
        except urllib.error.HTTPError as e:
            if e.code == 400:
                print(f"[WARN] SPARQL HTTP 400 (requête refusée)")
                return None
            try:
                attente = float(e.headers.get("Retry-After", "") or 20)
            except (TypeError, ValueError):
                attente = 20.0
            print(f"[WARN] SPARQL HTTP {e.code} : nouvelle tentative dans {min(90, attente):.0f} s")
            if i < essais - 1:
                time.sleep(min(90.0, max(5.0, attente)))
        except Exception as e:
            print(f"[WARN] SPARQL : {e}")
            time.sleep(5 * (i + 1))
    return None


# ------------------------------------------------------------------------------
# Règles pures
# ------------------------------------------------------------------------------
def mots(nom: str) -> List[str]:
    t = unicodedata.normalize("NFKD", (nom or "").translate(str.maketrans({"ø": "o", "Ø": "O", "æ": "ae", "Æ": "AE", "ł": "l", "Ł": "L",
                                                                            "ß": "ss", "đ": "d", "Đ": "D", "ı": "i"})))
    return [m for m in re.split(r"[^a-z0-9]+", t.encode("ascii", "ignore").decode().lower()) if m]


def nom_concorde(a: str, b: str) -> bool:
    """Vrai si tous les mots du nom le plus court figurent dans l'autre (« Vitinha » / « Vitinha » ; « Kylian Mbappé » /
    « Kylian Mbappé Lottin »)."""
    ma, mb = set(mots(a)), set(mots(b))
    if not ma or not mb:
        return False
    petit, grand = (ma, mb) if len(ma) <= len(mb) else (mb, ma)
    return petit <= grand


def _qid(uri: str) -> str:
    return (uri or "").rsplit("/", 1)[-1]


def choisir(joueurs: Dict[str, Dict[str, Any]], par_espn: Dict[str, Dict[str, Any]],
            candidats: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    """{id ESPN: {qid, preuve}}. `joueurs` = {id ESPN: {nom, naissance}} ; `par_espn` = {id ESPN: {qid, naissances}} (P3681) ;
    `candidats` = {qid: {naissance, noms}} (footballeurs nés aux dates demandées, précision jour)."""
    out: Dict[str, Dict[str, str]] = {}
    par_date: Dict[str, List[str]] = {}
    for q, c in candidats.items():
        par_date.setdefault(c["naissance"], []).append(q)
    for pid, j in joueurs.items():
        e = par_espn.get(pid)
        if e:
            if j.get("naissance") and e["naissances"] and j["naissance"] not in e["naissances"]:
                continue                                                      # identifiant contredit par la date : rien
            out[pid] = {"qid": e["qid"], "preuve": "P3681"}
            continue
        if not j.get("naissance"):
            continue
        ok = [q for q in par_date.get(j["naissance"], []) if any(nom_concorde(j["nom"], n) for n in candidats[q]["noms"])]
        if len(ok) == 1:
            out[pid] = {"qid": ok[0], "preuve": "naissance+nom"}
    return out


def parse_identite(lignes: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    g: Dict[str, Dict[str, set]] = {}
    for b in lignes:
        q = _qid(b["p"]["value"])
        d = g.setdefault(q, {})
        for k in ("img", "h", "lieuLabel", "frtitle"):
            if (b.get(k) or {}).get("value"):
                d.setdefault(k, set()).add(b[k]["value"])
    out = {}
    for q, d in g.items():
        f: Dict[str, Any] = {}
        tailles = {round(float(h) * 100) for h in d.get("h") or () if re.fullmatch(r"[+]?\d+(\.\d+)?", h)}
        tailles = {t for t in tailles if 140 <= t <= 215}
        if len(tailles) == 1:
            f["taille"] = tailles.pop()
        lieux = {x for x in d.get("lieuLabel") or () if not re.fullmatch(r"Q\d+", x)}
        if len(lieux) == 1:
            f["lieu_naissance"] = lieux.pop()
        if len(d.get("img") or ()) >= 1:
            f["image"] = urllib.parse.unquote(sorted(d["img"])[0].rsplit("/", 1)[-1])
        if d.get("frtitle"):
            f["titre_wikipedia"] = sorted(d["frtitle"])[0]
        out[q] = f
    return out


def _an(v: str) -> Optional[int]:
    m = re.match(r"^\+?(\d{4})", v or "")
    return int(m.group(1)) if m else None


def parse_carriere(lignes: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """{qid: [{club, debut, fin, matchs, buts, selection}]} : une entrée par déclaration P54 (prêts compris), triée par début."""
    par: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for b in lignes:
        q, st = _qid(b["p"]["value"]), b["st"]["value"]
        e = par.setdefault(q, {}).setdefault(st, {"club": None, "selection": False})
        nom = (b.get("teamLabel") or {}).get("value")
        if nom and not re.fullmatch(r"Q\d+", nom):
            e["club"] = nom
        e["selection"] = e["selection"] or (b.get("nat") or {}).get("value") == "true"
        for k, champ in (("deb", "debut"), ("fin", "fin")):
            a = _an((b.get(k) or {}).get("value", ""))
            if a:
                e[champ] = a
        for k, champ in (("mj", "matchs"), ("bu", "buts")):
            v = (b.get(k) or {}).get("value")
            if v and re.fullmatch(r"[+]?\d+(\.0+)?", v):
                e[champ] = int(float(v))
    out = {}
    for q, sts in par.items():
        liste = [e for e in sts.values() if e["club"]]
        liste.sort(key=lambda e: (e.get("debut") or 9999, e.get("fin") or 9999, e["club"]))
        out[q] = [{k: v for k, v in e.items() if v not in (None, False)} for e in liste]
    return out


def texte_html(h: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", h or "")).strip()


def parse_commons(rep: Any) -> Dict[str, Dict[str, Any]]:
    """{nom de fichier: {url, page, auteur, licence, licence_url, annee}} ; sans licence lisible : absent."""
    out = {}
    q = (rep or {}).get("query") or {}
    norm = {n.get("to"): n.get("from") for n in q.get("normalized") or []}
    for p in q.get("pages") or []:
        ii = (p.get("imageinfo") or [{}])[0]
        md = ii.get("extmetadata") or {}
        lic = texte_html((md.get("LicenseShortName") or {}).get("value"))
        if not lic or not ii.get("thumburl"):
            continue
        titre = norm.get(p.get("title"), p.get("title")) or ""
        nom = titre.split(":", 1)[-1]
        d = {"url": ii["thumburl"], "page": ii.get("descriptionurl", ""), "licence": lic,
             "licence_url": texte_html((md.get("LicenseUrl") or {}).get("value")),
             "auteur": texte_html((md.get("Artist") or {}).get("value"))[:120]}
        a = _an(texte_html((md.get("DateTimeOriginal") or {}).get("value")))
        if a:
            d["annee"] = a
        out[nom.replace("_", " ")] = {k: v for k, v in d.items() if v}
    return out


# ------------------------------------------------------------------------------
# Requêtes
# ------------------------------------------------------------------------------
def q_espn(ids: List[str]) -> str:
    return ('SELECT ?v ?p ?n WHERE { VALUES ?v { %s } ?p wdt:P3681 ?v . OPTIONAL { ?p p:P569/psv:P569 [ wikibase:timeValue ?n ; '
            'wikibase:timePrecision 11 ] } }' % " ".join('"%s"' % i for i in ids))


def q_dates(dates: List[str]) -> str:
    vals = " ".join('"%sT00:00:00Z"^^xsd:dateTime' % d for d in dates)
    return ('SELECT ?p ?n ?l WHERE { VALUES ?n { %s } ?p p:P569/psv:P569 [ wikibase:timeValue ?n ; wikibase:timePrecision 11 ] ; '
            'wdt:P106 wd:%s ; rdfs:label|skos:altLabel ?l . FILTER(LANG(?l) IN ("fr", "en", "mul")) }' % (vals, FOOTBALLEUR))


def q_identite(qids: List[str]) -> str:
    return ('SELECT ?p ?img ?h ?lieuLabel ?frtitle WHERE { VALUES ?p { %s } OPTIONAL { ?p wdt:P18 ?img } '
            'OPTIONAL { ?p p:P2048/psn:P2048/wikibase:quantityAmount ?h } OPTIONAL { ?p wdt:P19 ?lieu } '
            'OPTIONAL { ?w schema:about ?p ; schema:isPartOf <https://fr.wikipedia.org/> ; schema:name ?frtitle } '
            'SERVICE wikibase:label { bd:serviceParam wikibase:language "fr,en". } }' % " ".join("wd:" + q for q in qids))


def q_carriere(qids: List[str]) -> str:
    return ('SELECT ?p ?st ?teamLabel ?deb ?fin ?mj ?bu ?nat WHERE { VALUES ?p { %s } ?p p:P54 ?st . ?st ps:P54 ?team . '
            'OPTIONAL { ?st pq:P580 ?deb } OPTIONAL { ?st pq:P582 ?fin } OPTIONAL { ?st pq:P1350 ?mj } OPTIONAL { ?st pq:P1351 ?bu } '
            'BIND(EXISTS { ?team wdt:P31/wdt:P279* wd:%s } AS ?nat) '
            'SERVICE wikibase:label { bd:serviceParam wikibase:language "fr,en". } }' % (" ".join("wd:" + q for q in qids), SELECTION))


def commons(fichiers: List[str], get=clubs.get_poli, fin: float = float("inf")) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for k in range(0, len(fichiers), 50):
        if time.time() > fin:
            print("[WARN] Commons : budget de temps atteint, la suite au prochain passage")
            break
        lot = fichiers[k:k + 50]
        time.sleep(clubs.PAUSE_WIKIPEDIA)
        rep = get("https://commons.wikimedia.org/w/api.php?action=query&prop=imageinfo&iiprop=url%7Cextmetadata&iiurlwidth=240"
                  "&iiextmetadatafilter=Artist%7CLicenseShortName%7CLicenseUrl%7CDateTimeOriginal&format=json&formatversion=2&titles="
                  + urllib.parse.quote("|".join("File:" + f for f in lot), safe=""))
        if rep is not None:
            out.update(parse_commons(rep))
    return out


# ------------------------------------------------------------------------------
# Enrichissement des effectifs
# ------------------------------------------------------------------------------
def enrichir(fiches: Dict[str, Dict[str, Any]], anciens: Dict[str, Dict[str, Any]], maintenant: str,
             requete: Callable[[str], Optional[List[Dict[str, Any]]]] = sparql, get=clubs.get_poli, budget_s: float = 240) -> Dict[str, int]:
    """Ajoute `wd` (et `wp`) aux joueurs des effectifs ; jamais bloquant pour la fiche (erreur = valeurs précédentes). Photos (Commons)
    et extraits (Wikipédia) dans la limite de `budget_s` secondes : le reste est repris au passage suivant (fichier `image` gardé dans
    `wd`, extrait absent = à relire)."""
    fin = time.time() + budget_s
    auj = date.fromisoformat(maintenant[:10])
    prec = {j["id"]: j for f in anciens.values() for j in (f or {}).get("effectif") or []}
    joueurs: Dict[str, Dict[str, Any]] = {}
    for f in fiches.values():
        for j in f.get("effectif") or []:
            if not j["id"].startswith("espn-"):
                continue
            a = prec.get(j["id"]) or {}
            for k in ("wd", "wp"):
                if a.get(k):
                    j[k] = a[k]
            if clubs.a_rafraichir(j.get("wd"), auj, JOURS_CACHE):
                joueurs[j["id"][5:]] = j
    n = {"demandes": len(joueurs), "relies": 0, "photos": 0, "extraits": 0}
    if joueurs:
        relier(joueurs, maintenant, requete, n)
    tous = [j for f in fiches.values() for j in f.get("effectif") or [] if (j.get("wd") or {}).get("qid")]
    # Photos : fichier Commons connu sans métadonnées lisibles (licence, auteur)
    manquants = [j for j in tous if j["wd"].get("image") and not j["wd"].get("photo")]
    if manquants:
        images = commons(sorted({j["wd"]["image"] for j in manquants}), get, fin)
        for j in manquants:
            img = images.get(j["wd"]["image"])
            if img:
                j["wd"]["photo"] = img
                n["photos"] += 1
    extraits(tous, auj, maintenant, get, fin, n)
    return n


def relier(joueurs: Dict[str, Dict[str, Any]], maintenant: str, requete, n: Dict[str, int]) -> None:
    """Rapprochement Wikidata + identité + carrière des joueurs à (re)lire (`joueurs` = {id ESPN: entrée d'effectif})."""
    ids = sorted(joueurs)
    par_espn: Dict[str, Dict[str, Any]] = {}
    for k in range(0, len(ids), 300):
        r = requete(q_espn(ids[k:k + 300]))
        if r is None:
            print("[WARN] Joueurs : Wikidata injoignable, valeurs précédentes conservées")
            return
        for b in r:
            e = par_espn.setdefault(b["v"]["value"], {"qid": _qid(b["p"]["value"]), "naissances": set(), "qids": set()})
            e["qids"].add(_qid(b["p"]["value"]))
            if b.get("n"):
                e["naissances"].add(b["n"]["value"][:10])
    par_espn = {k: v for k, v in par_espn.items() if len(v["qids"]) == 1}      # un id ESPN porté par deux éléments : ignoré
    dates = sorted({j["naissance"] for pid, j in joueurs.items() if j.get("naissance") and pid not in par_espn})
    candidats: Dict[str, Dict[str, Any]] = {}
    for k in range(0, len(dates), 60):
        r = requete(q_dates(dates[k:k + 60]))
        if r is None:
            print("[WARN] Joueurs : recherche par date de naissance interrompue, valeurs précédentes conservées")
            return
        for b in r:
            c = candidats.setdefault(_qid(b["p"]["value"]), {"naissance": b["n"]["value"][:10], "noms": set()})
            c["noms"].add(b["l"]["value"])
    lies = choisir({pid: {"nom": j.get("nom"), "naissance": j.get("naissance")} for pid, j in joueurs.items()}, par_espn, candidats)
    qids = sorted({x["qid"] for x in lies.values()})
    ident: Dict[str, Dict[str, Any]] = {}
    carr: Dict[str, List[Dict[str, Any]]] = {}
    for k in range(0, len(qids), 150):
        r1, r2 = requete(q_identite(qids[k:k + 150])), requete(q_carriere(qids[k:k + 150]))
        if r1 is None or r2 is None:
            print("[WARN] Joueurs : détails Wikidata incomplets, valeurs précédentes conservées")
            return
        ident.update(parse_identite(r1))
        carr.update(parse_carriere(r2))
    for pid, j in joueurs.items():
        x = lies.get(pid)
        if not x:
            j["wd"] = {"qid": None, "maj": maintenant}
            j.pop("wp", None)
            continue
        i = dict(ident.get(x["qid"]) or {})
        if i.get("image"):
            i["image"] = i["image"].replace("_", " ")
        ancien = j.get("wd") or {}
        if ancien.get("photo") and ancien.get("image") == i.get("image"):
            i["photo"] = ancien["photo"]                  # même fichier : crédit déjà lu
        j["wd"] = {"qid": x["qid"], "preuve": x["preuve"], **i, **({"carriere": carr[x["qid"]]} if carr.get(x["qid"]) else {}), "maj": maintenant}
        if ancien.get("qid") != x["qid"]:
            j.pop("wp", None)
        n["relies"] += 1


def extraits(tous: List[Dict[str, Any]], auj: date, maintenant: str, get, fin: float, n: Dict[str, int]) -> None:
    """Extraits Wikipédia FR (lots de 20, comme les clubs), dans le budget de temps."""
    voulus = [j for j in tous if j["wd"].get("titre_wikipedia") and clubs.a_rafraichir(j.get("wp"), auj, JOURS_CACHE)]
    echecs = 0
    for k in range(0, len(voulus), 20):
        if time.time() > fin:
            print("[WARN] Wikipédia (joueurs) : budget de temps atteint, la suite au prochain passage")
            break
        if echecs >= 3:
            print("[WARN] Wikipédia (joueurs) : échecs de suite, la suite au prochain passage")
            break
        lot = voulus[k:k + 20]
        titres = [j["wd"]["titre_wikipedia"] for j in lot]
        time.sleep(clubs.PAUSE_WIKIPEDIA)
        rep = get("https://fr.wikipedia.org/w/api.php?action=query&prop=extracts%7Cinfo%7Cpageprops&ppprop=disambiguation&inprop=url"
                  "&exintro=1&explaintext=1&exlimit=20&redirects=1&format=json&formatversion=2&titles="
                  + urllib.parse.quote("|".join(titres), safe=""))
        if rep is None:
            echecs += 1
            continue
        echecs = 0
        res = clubs.parse_wikipedia_lot(rep, titres)
        for j, t in zip(lot, titres):
            if t in res:
                j["wp"] = dict(res[t], maj=maintenant)
                n["extraits"] += 1
            else:
                j["wp"] = {"maj": maintenant}       # pas d'extrait : relu dans 30 jours seulement


# ------------------------------------------------------------------------------
# Tests (sans réseau)
# ------------------------------------------------------------------------------
def _test() -> None:
    assert nom_concorde("Kylian Mbappé", "Kylian Mbappé Lottin") and nom_concorde("Vitinha", "Vitinha")
    assert not nom_concorde("Bernardo Silva", "André Silva") and not nom_concorde("Silva", "")
    assert nom_concorde("Martin Ødegaard", "Martin Odegaard") and nom_concorde("Thomas Müller", "Thomas Mueller") is False
    j = {"1": {"nom": "Kylian Mbappé", "naissance": "1998-12-20"}, "2": {"nom": "Bernardo Silva", "naissance": "1994-08-10"},
         "3": {"nom": "Jean Dupont", "naissance": "2000-01-01"}, "4": {"nom": "Ali Ben", "naissance": "1999-05-05"},
         "5": {"nom": "Sans Date"}}
    par_espn = {"1": {"qid": "Q1", "naissances": {"1998-12-20"}}, "5": {"qid": "Q5", "naissances": set()}}
    cand = {"Q2": {"naissance": "1994-08-10", "noms": {"Bernardo Silva", "Bernardo Mota Veiga de Carvalho e Silva"}},
            "Q9": {"naissance": "1994-08-10", "noms": {"André Silva"}},
            "Q3": {"naissance": "2000-01-01", "noms": {"Jean Dupont"}}, "Q4": {"naissance": "2000-01-01", "noms": {"Jean Dupont"}},
            "Q6": {"naissance": "1999-05-05", "noms": {"Ali Benarfa"}}}
    r = choisir(j, par_espn, cand)
    assert r == {"1": {"qid": "Q1", "preuve": "P3681"}, "2": {"qid": "Q2", "preuve": "naissance+nom"},
                 "5": {"qid": "Q5", "preuve": "P3681"}}, r            # 3 : deux candidats ; 4 : nom non concordant
    assert choisir({"1": {"nom": "X", "naissance": "1998-12-21"}}, par_espn, {}) == {}    # P3681 contredit par la date

    def v(x):
        return {"value": x}
    E = "http://www.wikidata.org/entity/"
    idt = parse_identite([{"p": v(E + "Q1"), "img": v("http://commons.wikimedia.org/wiki/Special:FilePath/Kylian%20Mbapp%C3%A9.jpg"),
                           "h": v("1.78"), "lieuLabel": v("Paris"), "frtitle": v("Kylian Mbappé")},
                          {"p": v(E + "Q1"), "h": v("1.78"), "lieuLabel": v("Bondy")}])
    assert idt["Q1"] == {"taille": 178, "image": "Kylian Mbappé.jpg", "titre_wikipedia": "Kylian Mbappé"}, idt   # deux lieux : aucun
    c = parse_carriere([{"p": v(E + "Q1"), "st": v("s1"), "teamLabel": v("AS Monaco"), "deb": v("+2015-01-01T00:00:00Z"),
                         "fin": v("+2018-01-01T00:00:00Z"), "mj": v("41"), "bu": v("16"), "nat": v("false")},
                        {"p": v(E + "Q1"), "st": v("s0"), "teamLabel": v("équipe de France de football"), "deb": v("+2017-01-01T00:00:00Z"),
                         "nat": v("true")},
                        {"p": v(E + "Q1"), "st": v("s2"), "teamLabel": v("Q123"), "nat": v("false")}])
    assert c["Q1"] == [{"club": "AS Monaco", "debut": 2015, "fin": 2018, "matchs": 41, "buts": 16},
                       {"club": "équipe de France de football", "debut": 2017, "selection": True}], c
    cm = parse_commons({"query": {"normalized": [{"from": "File:Kylian_Mbappé.jpg", "to": "File:Kylian Mbappé.jpg"}],
                                  "pages": [{"title": "File:Kylian Mbappé.jpg", "imageinfo": [{"thumburl": "https://u/240px.jpg",
                                             "descriptionurl": "https://commons/p", "extmetadata": {
                                                 "LicenseShortName": {"value": "CC BY-SA 4.0"}, "Artist": {"value": "<a href='x'>Auteur</a>"},
                                                 "DateTimeOriginal": {"value": "2019-06-01"}}}]},
                                            {"title": "File:Sans.jpg", "imageinfo": [{"thumburl": "u", "extmetadata": {}}]}]}})
    assert cm == {"Kylian Mbappé.jpg": {"url": "https://u/240px.jpg", "page": "https://commons/p", "licence": "CC BY-SA 4.0",
                                        "auteur": "Auteur", "annee": 2019}}, cm

    # bout à bout avec un faux réseau
    def req(q):
        if "P3681" in q:
            return [{"v": v("100"), "p": v(E + "Q1"), "n": v("1998-12-20T00:00:00Z")}]
        if "timePrecision 11 ] ; wdt:P106" in q:
            return [{"p": v(E + "Q2"), "n": v("1994-08-10T00:00:00Z"), "l": v("Bernardo Silva")}]
        if "P2048" in q:
            return [{"p": v(E + "Q1"), "img": v("http://commons.wikimedia.org/wiki/Special:FilePath/K.jpg"), "frtitle": v("Kylian Mbappé")}]
        if "P54" in q:
            return [{"p": v(E + "Q2"), "st": v("s"), "teamLabel": v("Benfica"), "nat": v("false")}]
        raise AssertionError(q)

    def get(url, accept=None):
        if "commons" in url:
            return {"query": {"pages": [{"title": "File:K.jpg", "imageinfo": [{"thumburl": "https://t", "extmetadata": {"LicenseShortName": {"value": "CC BY 2.0"}}}]}]}}
        return {"query": {"pages": [{"title": "Kylian Mbappé", "extract": "Kylian Mbappé est un footballeur. " * 10, "fullurl": "https://fr"}]}}
    pause, clubs.PAUSE_WIKIPEDIA = clubs.PAUSE_WIKIPEDIA, 0
    fiches = {"c": {"effectif": [{"id": "espn-100", "nom": "Kylian Mbappé", "naissance": "1998-12-20"},
                                 {"id": "espn-200", "nom": "Bernardo Silva", "naissance": "1994-08-10"},
                                 {"id": "espn-300", "nom": "Inconnu", "naissance": "2001-02-03"},
                                 {"id": "espn-400", "nom": "Récent"}]}}
    anciens = {"c": {"effectif": [{"id": "espn-400", "wd": {"qid": "Q7", "maj": "2026-11-20T00:00:00Z"}}]}}
    n = enrichir(fiches, anciens, "2026-11-25T00:00:00Z", requete=req, get=get)
    clubs.PAUSE_WIKIPEDIA = pause
    e = {j["id"]: j for j in fiches["c"]["effectif"]}
    assert e["espn-100"]["wd"]["photo"]["url"] == "https://t" and e["espn-100"]["wp"]["extrait"].startswith("Kylian"), e["espn-100"]
    assert e["espn-200"]["wd"]["carriere"] == [{"club": "Benfica"}] and e["espn-200"]["wd"]["preuve"] == "naissance+nom"
    assert e["espn-300"]["wd"]["qid"] is None and e["espn-400"]["wd"]["qid"] == "Q7"
    assert n == {"demandes": 3, "relies": 2, "photos": 1, "extraits": 1}, n
    print("[OK] encyclo_joueurs : tests passés")


if __name__ == "__main__":
    if "--test" in sys.argv:
        _test()
