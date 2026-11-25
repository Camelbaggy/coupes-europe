#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Encyclopédie des clubs de CHAMPIONNAT (fiches `championnats/clubs/espn-<id>.json`, appelé par `fiches_ligues.construire`) :
fondation, siège, site, surnom, stade (capacité, ouverture, ville), extrait Wikipédia FR, identifiant UEFA et historique européen,
pour les clubs qui n'ont pas de fiche UEFA (décision du propriétaire du 25/11/2026 : compléter les fiches des clubs de championnat).

Chaîne de PREUVE (jamais de rapprochement par le nom seul) :
1. club ESPN -> article Wikipédia : lien du tableau des résultats de la page de la saison (`journees.json` -> `correspondances`, clubs
   rapprochés puis vérifiés par les scores, voir journees_wiki.py) ; Serie A (calendrier IT sans liens) : le tableau « Squadre
   partecipanti » de la même page IT associe le nom du calendrier (`{{Calcio <nom>|N}}`) à l'article de la saison du club
   (`[[<article du club> 2026-2027|dettagli]]`), même ligne, égalité EXACTE du nom ;
2. article -> élément Wikidata : `pageprops.wikibase_item` de l'article (redirections suivies) ;
3. contrôle : l'élément doit être un club de football (P31/P279* Q476028), sinon rien n'est gardé ;
4. Wikidata -> P571 (année de fondation), P159 (siège), P856 (site), P1449 (surnom FR), P7361 (id UEFA, seulement s'il est unique),
   P115 (stade actuel : sans date de fin, seulement s'il est unique) -> P1083 (capacité, seulement si une seule valeur), P1619
   (ouverture), P131 (ville) ; article FR (lien de site Wikidata) -> extrait (lot MediaWiki, comme clubs.py).
Le stade ESPN (le plus fréquent à domicile) reste la référence : capacité / ouverture / ville Wikidata ne s'y ajoutent que si les noms
concordent (un mot distinctif commun) ; sans stade ESPN, le stade Wikidata est affiché avec `source: "Wikidata"`.
Cache : bloc `wikidata` / `wikipedia` relu après 30 jours (comme clubs.py) ; un échec ne remplace jamais une valeur obtenue.

Historique européen (onglet « Histoire ») d'un club SANS fiche UEFA cette saison mais avec un id UEFA Wikidata : `histoire.py` écrit
`championnats/clubs/historique/<id UEFA>.json` (même format que clubs/historique/ des coupes ; reprenable, budget ; refait après 180 jours).
Un club présent dans clubs/index.json des coupes garde le fichier des coupes.

    python encyclo_ligues.py --test
"""

import json
import os
import re
import sys
import time
import urllib.parse
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import clubs
import journees_wiki
from netutil import normalize

JOURS_HISTORIQUE = 180
CLUB_FOOTBALL = "Q476028"
_MOTS_STADE = {"stade", "stadium", "stadio", "estadio", "stadion", "arena", "de", "du", "des", "la", "le", "les", "del", "di", "the",
               "municipal", "comunale", "park", "parc", "campo", "football", "ground", "d", "l", "y", "e"}


# ------------------------------------------------------------------------------
# 1. Club ESPN -> article Wikipédia
# ------------------------------------------------------------------------------
def articles_serie_a(w: str) -> Dict[str, str]:
    """{nom du calendrier IT: article du club} d'après le tableau « Squadre partecipanti » (même ligne : `{{Calcio <nom>|…}}` et
    `[[<article> AAAA-AAAA|…]]`). Un nom présent deux fois ou une ligne incomplète : écarté."""
    i = w.find("quadre partecipanti")
    if i < 0:
        return {}
    fin = w.find("\n|}", i)
    out: Dict[str, str] = {}
    vus: Dict[str, int] = {}
    for ligne in w[i:fin if fin > 0 else len(w)].split("\n|-"):
        n = re.search(r"\{\{\s*Calcio\s+([^|}]+?)\s*(?:\||\}\})", ligne)
        a = re.search(r"\[\[([^\]|]+?)\s+\d{4}[-–]\d{4}\s*\|", ligne)
        if n and a:
            vus[n.group(1)] = vus.get(n.group(1), 0) + 1
            out[n.group(1)] = a.group(1).strip()
    return {k: v for k, v in out.items() if vus[k] == 1}


def articles(ligue: str, saison: int, journees: Dict[str, Any],
             wikitexte: Callable[..., Any] = journees_wiki.wikitexte) -> Dict[str, Dict[str, str]]:
    """{id ESPN: {lang, titre, preuve}} pour les clubs de la ligue."""
    corr = journees.get("correspondances") or {}
    lang, modele = journees_wiki.PAGES[ligue]
    page = modele.format(a=saison, b=saison + 1)
    if ligue != "sa":
        return {cid: {"lang": lang, "titre": t, "preuve": f"lien du tableau des résultats de « {page} » (Wikipédia {lang}, clubs vérifiés par les scores)"}
                for t, cid in corr.items()}
    lu = wikitexte(lang, page)
    table = articles_serie_a(lu[0]) if lu else {}
    return {cid: {"lang": lang, "titre": table[nom], "preuve": f"tableau des clubs de « {page} » (Wikipédia {lang}) : nom du calendrier = « {nom} »"}
            for nom, cid in corr.items() if nom in table}


# ------------------------------------------------------------------------------
# 2. Article -> élément Wikidata ; 3-4. faits Wikidata
# ------------------------------------------------------------------------------
def parse_pageprops(rep: Any, titres: List[str]) -> Dict[str, str]:
    """Réponse MediaWiki `prop=pageprops&ppprop=wikibase_item` -> {titre demandé: QID} (redirections suivies)."""
    q = (rep or {}).get("query") or {}
    suite = {r.get("from"): r.get("to") for liste in (q.get("normalized") or [], q.get("redirects") or []) for r in liste}
    pages = {p.get("title"): p for p in q.get("pages") or [] if isinstance(p, dict)}
    out = {}
    for t in titres:
        c, n = t, 0
        while c in suite and n < 5:
            c, n = suite[c], n + 1
        qid = ((pages.get(c) or {}).get("pageprops") or {}).get("wikibase_item")
        if qid and re.fullmatch(r"Q\d+", qid):
            out[t] = qid
    return out


def qids_articles(lang: str, titres: List[str], get=clubs.get_poli) -> Optional[Dict[str, str]]:
    out: Dict[str, str] = {}
    for k in range(0, len(titres), 50):
        lot = titres[k:k + 50]
        time.sleep(clubs.PAUSE_WIKIPEDIA)
        rep = get(f"https://{lang}.wikipedia.org/w/api.php?action=query&prop=pageprops&ppprop=wikibase_item&redirects=1&format=json"
                  "&formatversion=2&titles=" + urllib.parse.quote("|".join(lot), safe=""))
        if rep is None:
            return None
        out.update(parse_pageprops(rep, lot))
    return out


def requete_sparql(qids: List[str]) -> str:
    return f"""SELECT ?item ?club ?uefa ?inc ?site ?nick ?hqLabel ?frtitle ?stade ?stadeLabel ?cap ?ouv ?villeLabel ?alt WHERE {{
  VALUES ?item {{ {" ".join("wd:" + q for q in qids)} }}
  BIND(EXISTS {{ ?item wdt:P31/wdt:P279* wd:{CLUB_FOOTBALL} }} AS ?club)
  OPTIONAL {{ ?item wdt:P7361 ?uefa . }}
  OPTIONAL {{ ?item wdt:P571 ?inc . }}
  OPTIONAL {{ ?item wdt:P856 ?site . }}
  OPTIONAL {{ ?item wdt:P1449 ?nick . FILTER(LANG(?nick) IN ("fr", "")) }}
  OPTIONAL {{ ?item wdt:P159 ?hq . }}
  OPTIONAL {{ ?w schema:about ?item ; schema:isPartOf <https://fr.wikipedia.org/> ; schema:name ?frtitle . }}
  OPTIONAL {{ ?item p:P115 ?s . ?s ps:P115 ?stade . FILTER NOT EXISTS {{ ?s pq:P582 ?fin }}
             OPTIONAL {{ ?stade wdt:P1083 ?cap . }} OPTIONAL {{ ?stade wdt:P1619 ?ouv . }} OPTIONAL {{ ?stade wdt:P131 ?ville . }}
             OPTIONAL {{ ?stade rdfs:label|skos:altLabel ?alt . FILTER(LANG(?alt) IN ("fr", "en", "it", "es", "de")) }} }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "fr,en". }}
}}"""


def _qid(uri: str) -> str:
    return (uri or "").rsplit("/", 1)[-1]


def parse_sparql(rep: Any) -> Dict[str, Dict[str, Any]]:
    """{QID: bloc wikidata} ; `club: False` si l'élément n'est pas un club de football. Valeurs multiples : fondation = la plus
    ancienne ; site / surnom / siège = la première par ordre alphabétique (comme clubs.py) ; id UEFA, stade et capacité : gardés
    seulement s'ils sont UNIQUES (sinon absents : jamais de choix arbitraire)."""
    g: Dict[str, Dict[str, set]] = {}
    stades: Dict[str, Dict[str, Dict[str, set]]] = {}
    for b in (((rep or {}).get("results") or {}).get("bindings")) or []:
        q = _qid((b.get("item") or {}).get("value"))
        if not q:
            continue
        d = g.setdefault(q, {})
        for k in ("club", "uefa", "inc", "site", "nick", "hqLabel", "frtitle"):
            if (b.get(k) or {}).get("value"):
                d.setdefault(k, set()).add(b[k]["value"])
        if (b.get("stade") or {}).get("value"):
            s = stades.setdefault(q, {}).setdefault(_qid(b["stade"]["value"]), {})
            for k in ("stadeLabel", "cap", "ouv", "villeLabel", "alt"):
                if (b.get(k) or {}).get("value"):
                    s.setdefault(k, set()).add(b[k]["value"])
    out: Dict[str, Dict[str, Any]] = {}
    for q, d in g.items():
        f: Dict[str, Any] = {"qid": q, "club": "true" in (d.get("club") or set())}
        annees = [int(m.group(0).lstrip("+")) for m in (re.match(r"^\+?\d{1,4}", x) for x in sorted(d.get("inc") or [])) if m]
        if annees:
            f["fondation_annee"] = min(annees)
        for cle, champ in (("site", "site"), ("nick", "surnom"), ("frtitle", "titre_wikipedia")):
            if d.get(cle):
                f[champ] = sorted(d[cle])[0]
        if d.get("hqLabel") and not re.fullmatch(r"Q\d+", sorted(d["hqLabel"])[0]):
            f["ville_siege"] = sorted(d["hqLabel"])[0]
        if len(d.get("uefa") or ()) == 1:
            f["uefa_id"] = next(iter(d["uefa"]))
        st = stades.get(q) or {}
        if len(st) == 1:
            sq, s = next(iter(st.items()))
            nom = sorted(s.get("stadeLabel") or [""])[0]
            if nom and not re.fullmatch(r"Q\d+", nom):
                bloc: Dict[str, Any] = {"nom": nom, "qid": sq}
                caps = {int(float(c)) for c in s.get("cap") or () if re.fullmatch(r"[+]?\d+(\.0+)?", c)}
                if len(caps) == 1:
                    bloc["capacite"] = caps.pop()
                ouv = sorted(s.get("ouv") or [])
                if ouv and re.match(r"^\+?\d{4}", ouv[0]):
                    bloc["ouverture"] = ouv[0].lstrip("+")[:4]
                villes = sorted(v for v in s.get("villeLabel") or () if not re.fullmatch(r"Q\d+", v))
                if len(villes) == 1:
                    bloc["ville"] = villes[0]
                autres = sorted({x for x in s.get("alt") or () if normalize(x) != normalize(nom)})
                if autres:
                    bloc["autres_noms"] = autres[:15]   # noms de la même entité Wikidata (libellés, alias) : servent au rapprochement
                f["stade"] = bloc
        out[q] = f
    return out


def interroger_wikidata(qids: List[str], get=clubs.get_poli) -> Optional[Dict[str, Dict[str, Any]]]:
    url = "https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(requete_sparql(qids))
    rep = get(url, accept="application/sparql-results+json")
    return None if rep is None else parse_sparql(rep)


# ------------------------------------------------------------------------------
# Fusion dans les fiches
# ------------------------------------------------------------------------------
def mots_stade(nom: str) -> set:
    return {m for m in re.split(r"[^a-z0-9]+", normalize(nom)) if m and m not in _MOTS_STADE and len(m) > 1}


def completer_stade(fiche: Dict[str, Any]) -> None:
    """Stade ESPN + capacité / ouverture / ville Wikidata si les noms concordent ; sans stade ESPN : stade Wikidata."""
    wst = (fiche.get("wikidata") or {}).get("stade")
    if not wst:
        return
    st = fiche.get("stade")
    if not st:
        fiche["stade"] = {**{k: wst[k] for k in ("nom", "capacite", "ouverture", "ville") if k in wst}, "source": "Wikidata"}
        return
    noms_wd = [wst["nom"]] + list(wst.get("autres_noms") or [])
    if any(mots_stade(st.get("nom", "")) & mots_stade(n) for n in noms_wd):
        for k in ("capacite", "ouverture", "ville"):
            if k in wst and k not in st:
                st[k] = wst[k]
        st["complement"] = "Wikidata"


def enrichir(fiches: Dict[str, Dict[str, Any]], anciens: Dict[str, Dict[str, Any]], ligue: str, saison: int,
             journees: Dict[str, Any], maintenant: str, get=clubs.get_poli, wikitexte=journees_wiki.wikitexte) -> Dict[str, int]:
    """Ajoute `wikidata` / `wikipedia` aux fiches (clé = id ESPN) ; jamais bloquant (toute erreur : valeurs précédentes)."""
    auj = date.fromisoformat(maintenant[:10])
    for cid, f in fiches.items():
        for k in ("wikidata", "wikipedia"):
            if (anciens.get(cid) or {}).get(k):
                f[k] = anciens[cid][k]
    besoin = [cid for cid, f in fiches.items() if clubs.a_rafraichir(f.get("wikidata"), auj)]
    n = {"wikidata": 0, "wikipedia": 0, "non_relies": 0}
    if besoin:
        arts = articles(ligue, saison, journees, wikitexte)
        par_lang: Dict[str, List[str]] = {}
        for cid in besoin:
            if cid in arts:
                par_lang.setdefault(arts[cid]["lang"], []).append(arts[cid]["titre"])
        qid_de: Dict[Tuple[str, str], str] = {}
        for lang, titres in par_lang.items():
            r = qids_articles(lang, sorted(set(titres)), get)
            if r is None:
                print(f"[WARN] Wikipédia {lang} : éléments Wikidata illisibles, valeurs précédentes conservées")
                continue
            qid_de.update({(lang, t): q for t, q in r.items()})
        blocs = interroger_wikidata(sorted(set(qid_de.values())), get) if qid_de else {}
        if blocs is None:
            print("[WARN] Wikidata injoignable : valeurs précédentes conservées")
            blocs = {}
        for cid in besoin:
            a = arts.get(cid)
            q = a and qid_de.get((a["lang"], a["titre"]))
            b = blocs.get(q) if q else None
            if not b:
                n["non_relies"] += 1
                if not a:
                    print(f"[WIKIDATA] {fiches[cid]['nom']} : aucun article Wikipédia relié au club (voir journees.json)")
                continue
            if not b.pop("club"):
                n["non_relies"] += 1
                print(f"[WARN] {fiches[cid]['nom']} : {q} (article « {a['titre']} ») n'est pas un club de football : écarté")
                continue
            fiches[cid]["wikidata"] = {**b, "preuve": "article", "article": {"lang": a["lang"], "titre": a["titre"], "preuve": a["preuve"]},
                                       "maj": maintenant}
            n["wikidata"] += 1
    voulus = [cid for cid, f in fiches.items() if (f.get("wikidata") or {}).get("titre_wikipedia") and clubs.a_rafraichir(f.get("wikipedia"), auj)]
    echecs = 0
    for k in range(0, len(voulus), 20):
        if echecs >= 3:
            print("[WARN] Wikipédia : échecs de suite, les clubs restants seront traités au prochain passage")
            break
        lot = voulus[k:k + 20]
        titres = [fiches[c]["wikidata"]["titre_wikipedia"] for c in lot]
        time.sleep(clubs.PAUSE_WIKIPEDIA)
        rep = get("https://fr.wikipedia.org/w/api.php?action=query&prop=extracts%7Cinfo%7Cpageprops&ppprop=disambiguation&inprop=url"
                  "&exintro=1&explaintext=1&exlimit=20&redirects=1&format=json&formatversion=2&titles="
                  + urllib.parse.quote("|".join(titres), safe=""))
        res = None if rep is None else clubs.parse_wikipedia_lot(rep, titres)
        if res is None:
            echecs += 1
            continue
        echecs = 0
        for c, t in zip(lot, titres):
            if t in res:
                fiches[c]["wikipedia"] = dict(res[t], maj=maintenant)
                n["wikipedia"] += 1
    for f in fiches.values():
        completer_stade(f)
    return n


def historiques(fiches: List[Dict[str, Any]], base: str, ids_coupes: set, budget_s: float = 480,
                collecter: Optional[Callable[..., int]] = None, aujourdhui: Optional[date] = None) -> int:
    """Historique européen des clubs de championnat SANS fiche UEFA (id UEFA Wikidata) : `<base>/historique/<id>.json`. Pose
    `histoire` = {uefa_id, ou: coupes|donnees, fichier} sur chaque fiche qui a un fichier. Reprenable (budget). Renvoie le nombre de
    fichiers produits pendant ce passage."""
    import histoire
    collecter = collecter or histoire.collecter
    aujourdhui = aujourdhui or datetime.now(timezone.utc).date()
    dossier = os.path.join(base, "historique")
    debut, faits = time.time(), 0
    for f in fiches:
        uid = f.get("uefa_id") or (f.get("wikidata") or {}).get("uefa_id")
        if not uid:
            continue
        if uid in ids_coupes or f.get("uefa_id"):    # fiche UEFA (correspondance prouvée) : historique des coupes
            f["histoire"] = {"uefa_id": uid, "ou": "coupes", "fichier": f"clubs/historique/{uid}.json"}
            continue
        chemin = os.path.join(dossier, f"{uid}.json")
        doc = clubs.lire(chemin)
        vieux = True
        if doc and doc.get("maj"):
            try:
                vieux = (aujourdhui - date.fromisoformat(doc["maj"][:10])).days >= JOURS_HISTORIQUE
            except ValueError:
                vieux = True
        if vieux and time.time() - debut < budget_s:
            if collecter([uid], None, dossier, None, bool(doc)) == 0:
                faits += 1
                doc = clubs.lire(chemin)
        if doc:
            f["histoire"] = {"uefa_id": uid, "ou": "donnees", "fichier": f"championnats/clubs/historique/{uid}.json"}
    return faits


# ------------------------------------------------------------------------------
# Tests (sans réseau)
# ------------------------------------------------------------------------------
def _test() -> None:
    w = """== Squadre partecipanti ==
{| class="wikitable"
!Club
|-
| {{Calcio Atalanta|N}}
| ''[[Atalanta Bergamasca Calcio 2026-2027|dettagli]]''
| [[Bergamo]]
|-
| {{Calcio Inter|N}}
| ''[[Football Club Internazionale Milano 2026-2027|dettagli]]''
|-
| {{Calcio Pisa|N}}
| [[Pisa]]
|}
== Allenatori =="""
    t = articles_serie_a(w)
    assert t == {"Atalanta": "Atalanta Bergamasca Calcio", "Inter": "Football Club Internazionale Milano"}, t
    j = {"correspondances": {"Atalanta": "105", "Inter": "110", "Pisa": "1"}}
    a = articles("sa", 2026, j, wikitexte=lambda lang, p: (w, 1, ""))
    assert set(a) == {"105", "110"} and a["110"]["titre"] == "Football Club Internazionale Milano" and a["105"]["lang"] == "it", a
    a = articles("fl1", 2026, {"correspondances": {"Stade rennais football club": "169"}})
    assert a["169"]["titre"] == "Stade rennais football club" and a["169"]["lang"] == "fr"
    pp = {"query": {"redirects": [{"from": "Inter", "to": "Football Club Internazionale Milano"}],
                    "pages": [{"title": "Football Club Internazionale Milano", "pageprops": {"wikibase_item": "Q631"}}, {"title": "X", "missing": True}]}}
    assert parse_pageprops(pp, ["Inter", "X"]) == {"Inter": "Q631"}

    def v(x):
        return {"value": x}
    rep = {"results": {"bindings": [
        {"item": v("http://www.wikidata.org/entity/Q1"), "club": v("true"), "uefa": v("52747"), "inc": v("+1901-01-01T00:00:00Z"),
         "hqLabel": v("Rennes"), "frtitle": v("Stade rennais football club"), "stade": v("http://www.wikidata.org/entity/Q9"),
         "stadeLabel": v("Roazhon Park"), "cap": v("29778"), "ouv": v("+1912-09-15T00:00:00Z"), "villeLabel": v("Rennes")},
        {"item": v("http://www.wikidata.org/entity/Q1"), "club": v("true"), "inc": v("+1904-01-01T00:00:00Z"), "cap": v("29778"),
         "stade": v("http://www.wikidata.org/entity/Q9"), "stadeLabel": v("Roazhon Park")},
        {"item": v("http://www.wikidata.org/entity/Q2"), "club": v("true"), "uefa": v("1"), "stade": v("http://www.wikidata.org/entity/Q7"),
         "stadeLabel": v("A")},
        {"item": v("http://www.wikidata.org/entity/Q2"), "club": v("true"), "uefa": v("2"), "stade": v("http://www.wikidata.org/entity/Q8"),
         "stadeLabel": v("B")},
        {"item": v("http://www.wikidata.org/entity/Q3"), "club": v("false")}]}}
    b = parse_sparql(rep)
    assert b["Q1"]["fondation_annee"] == 1901 and b["Q1"]["uefa_id"] == "52747" and b["Q1"]["club"], b["Q1"]
    assert b["Q1"]["stade"] == {"nom": "Roazhon Park", "qid": "Q9", "capacite": 29778, "ouverture": "1912", "ville": "Rennes"}, b["Q1"]
    assert "uefa_id" not in b["Q2"] and "stade" not in b["Q2"] and b["Q3"]["club"] is False   # valeurs multiples : absentes
    f = {"stade": {"nom": "Roazhon Park", "source": "ESPN"}, "wikidata": {"stade": b["Q1"]["stade"]}}
    completer_stade(f)
    assert f["stade"]["capacite"] == 29778 and f["stade"]["complement"] == "Wikidata" and f["stade"]["source"] == "ESPN"
    f = {"stade": {"nom": "Stade de la Mosson", "source": "ESPN"}, "wikidata": {"stade": {"nom": "Stade de la Beaujoire", "capacite": 1}}}
    completer_stade(f)
    assert "capacite" not in f["stade"], f      # noms discordants : rien n'est ajouté
    f = {"stade": {"nom": "Groupama Stadium", "source": "ESPN"},
         "wikidata": {"stade": {"nom": "Parc Olympique lyonnais", "autres_noms": ["Groupama Stadium", "OL Stadium"], "capacite": 59186}}}
    completer_stade(f)
    assert f["stade"]["capacite"] == 59186 and f["stade"]["nom"] == "Groupama Stadium"     # alias Wikidata de la même entité
    f = {"wikidata": {"stade": {"nom": "Roazhon Park", "qid": "Q9", "capacite": 3}}}
    completer_stade(f)
    assert f["stade"] == {"nom": "Roazhon Park", "capacite": 3, "source": "Wikidata"}

    # enrichir : bout à bout avec un faux réseau
    def get(url, accept=None):
        if url.startswith("https://fr.wikipedia.org/w/api.php?action=query&prop=pageprops"):
            return {"query": {"pages": [{"title": "Stade rennais football club", "pageprops": {"wikibase_item": "Q1"}},
                                        {"title": "Ville", "pageprops": {"wikibase_item": "Q3"}}]}}
        if "sparql" in url:
            return rep
        if "prop=extracts" in url:
            return {"query": {"pages": [{"title": "Stade rennais football club", "extract": "Le Stade rennais est un club. " * 12,
                                         "fullurl": "https://fr.wikipedia.org/wiki/Stade_rennais"}]}}
        raise AssertionError(url)
    clubs.PAUSE_WIKIPEDIA, pause = 0, clubs.PAUSE_WIKIPEDIA
    fiches = {"169": {"nom": "Rennes", "stade": {"nom": "Roazhon Park", "source": "ESPN"}}, "2": {"nom": "Ville FC"}, "3": {"nom": "Sans article"}}
    anciens = {"3": {"wikidata": {"qid": "Q5", "maj": "2026-11-20T00:00:00Z"}}}
    n = enrichir(fiches, anciens, "fl1", 2026, {"correspondances": {"Stade rennais football club": "169", "Ville": "2"}},
                 "2026-11-25T10:00:00Z", get=get)
    clubs.PAUSE_WIKIPEDIA = pause
    assert fiches["169"]["wikidata"]["qid"] == "Q1" and fiches["169"]["wikidata"]["preuve"] == "article", fiches["169"]
    assert "club" not in fiches["169"]["wikidata"] and fiches["169"]["wikipedia"]["extrait"].startswith("Le Stade rennais")
    assert fiches["169"]["stade"]["capacite"] == 29778 and "wikidata" not in fiches["2"]       # Q3 n'est pas un club
    assert fiches["3"]["wikidata"]["qid"] == "Q5"                                              # cache de moins de 30 jours gardé
    assert n == {"wikidata": 1, "wikipedia": 1, "non_relies": 1}, n

    # historiques
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        appels = []

        def coll(ids, depuis, dossier, cache, refaire):
            appels.append(ids[0])
            os.makedirs(dossier, exist_ok=True)
            with open(os.path.join(dossier, ids[0] + ".json"), "w") as fh:
                json.dump({"maj": "2026-11-25T00:00:00Z", "ed": []}, fh)
            return 0
        fs = [{"wikidata": {"uefa_id": "9"}}, {"uefa_id": "52747"}, {"wikidata": {}}]
        assert historiques(fs, d, {"52747"}, collecter=coll, aujourdhui=date(2026, 11, 25)) == 1 and appels == ["9"]
        assert fs[0]["histoire"] == {"uefa_id": "9", "ou": "donnees", "fichier": "championnats/clubs/historique/9.json"}
        assert fs[1]["histoire"]["ou"] == "coupes" and "histoire" not in fs[2]
        assert historiques(fs, d, {"52747"}, collecter=coll, aujourdhui=date(2026, 12, 1)) == 0 and appels == ["9"]   # fichier récent
    print("[OK] encyclo_ligues : tests passés")


if __name__ == "__main__":
    if "--test" in sys.argv:
        _test()
