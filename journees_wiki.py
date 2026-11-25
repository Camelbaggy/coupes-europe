#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Numéro de journée des matchs de championnat, lu sur Wikipédia (ESPN ne le donne pas ; décision du 25/11/2026 :
Wikipédia d'abord, football-data.org seulement en secours).

Sources (mesurées le 25/11/2026) :
- Wikipédia FR, Ligue 1 / Premier League / Liga / Bundesliga : tableau croisé `{{Foot résultat}}` (ligne = domicile,
  colonne = extérieur). Une case NON jouée vaut `Jnn` (journée), une case jouée vaut le score. Un match reporté garde
  sa journée d'origine.
- Wikipédia IT, Serie A (la page FR n'a pas ce tableau) : § Calendario, une table par « Nª giornata », lignes
  `date || Domicile-Extérieur || score`, matchs joués compris.

Méthode :
- la journée d'un match est lue tant que la case vaut `Jnn` et CONSERVÉE ensuite (cache `journees/<ligue>-<saison>.json`) ;
  pour les matchs déjà joués, on remonte l'historique de la page (révisions anciennes, une tous les 14 jours depuis le
  1er juillet) jusqu'à la révision où la case valait encore `Jnn` ;
- clubs Wikipédia -> clubs ESPN : noms (mots distinctifs communs) + alias manuels `alias_equipes_wiki.json`, bijection
  exigée ; PREUVE : chaque score déjà inscrit sur Wikipédia doit égaler le score ESPN du même match ; un désaccord
  invalide le championnat entier (aucune journée écrite, journal) ;
- contrôle de cohérence : un club au plus une fois par journée, au plus N/2 matchs par journée ; sinon la journée de ces
  matchs reste absente. Jamais de journée devinée.
Wikipédia est modifiable par tous : la révision lue est enregistrée (`rev`).
"""

import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

UA = "coupes-europe/1.0 (dashboard personnel ; https://github.com/Camelbaggy/coupes-europe)"
PAUSE_S = 2.2
ALIAS_FICHIER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alias_equipes_wiki.json")

PAGES = {
    "fl1": ("fr", "Championnat de France de football {a}-{b}"),
    "pl": ("fr", "Championnat d'Angleterre de football {a}-{b}"),
    "liga": ("fr", "Championnat d'Espagne de football {a}-{b}"),
    "bl": ("fr", "Championnat d'Allemagne de football {a}-{b}"),
    "fl2": ("fr", "Championnat de France de football de deuxième division {a}-{b}"),
    # Secondaires (26/11/2026) : pages FR de la saison ; sans tableau {{Foot résultat}} lisible, les matchs restent sans journée
    "por": ("fr", "Championnat du Portugal de football {a}-{b}"),
    "ned": ("fr", "Championnat des Pays-Bas de football {a}-{b}"),
    "bel": ("fr", "Championnat de Belgique de football {a}-{b}"),
    # Turquie : fiches de match du modèle « …/maçlar » de Wikipédia TR (champ `tur` = journée), la page FR n'en donne aucune
    "tur": ("tr", "Şablon:{a}-{b2} Süper Lig maçları/maçlar"),
    "aut": ("fr", "Championnat d'Autriche de football {a}-{b}"),
    "gre": ("fr", "Championnat de Grèce de football {a}-{b}"),
    # Norvège : page NO, une section « N. serierunde » par journée (la page FR n'a qu'un tableau de scores, sans journée)
    "nor": ("no", "Eliteserien i fotball for menn {a}"),
    "sa": ("it", "Serie A {a}-{b}"),
}
# Pages LOCALES de secours (demande du propriétaire du 25/11/2026 : « prendre les pages locales si les données FR ne sont pas
# complètes ») : lues seulement pour les matchs restés sans journée après la page principale ; recoupées avec elle.
SECOURS = {
    "liga": ("es", "Primera División de España {a}-{b2}"),
}


# ------------------------------------------------------------------------------
# Accès Wikipédia (API MediaWiki, Retry-After respecté)
# ------------------------------------------------------------------------------
def _api(lang: str, params: Dict[str, str], essais: int = 4) -> Optional[Dict[str, Any]]:
    url = f"https://{lang}.wikipedia.org/w/api.php?" + urllib.parse.urlencode({**params, "format": "json", "formatversion": "2"})
    for i in range(essais):
        time.sleep(PAUSE_S)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=40) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            attente = int(e.headers.get("Retry-After") or 0) if e.code == 429 else 0
            print(f"[WARN] Wikipédia HTTP {e.code} ({lang}) ; nouvel essai dans {max(attente, 5 * (i + 1))} s")
            time.sleep(max(attente, 5 * (i + 1)))
        except Exception as e:
            print(f"[WARN] Wikipédia injoignable ({lang}) : {e}")
            time.sleep(5 * (i + 1))
    return None


def wikitexte(lang: str, titre: str, avant: Optional[str] = None) -> Optional[Tuple[str, int, str]]:
    """(wikitexte, id de révision, horodatage) de la page, actuelle ou la dernière révision antérieure à `avant` (ISO)."""
    p = {"action": "query", "prop": "revisions", "titles": titre, "rvprop": "content|ids|timestamp",
         "rvslots": "main", "rvlimit": "1", "redirects": "1"}
    if avant:
        p.update(rvstart=avant, rvdir="older")
    d = _api(lang, p)
    pages = ((d or {}).get("query") or {}).get("pages") or []
    if not pages or "revisions" not in pages[0]:
        return None
    rv = pages[0]["revisions"][0]
    return (rv.get("slots") or {}).get("main", {}).get("content", ""), int(rv["revid"]), rv["timestamp"]


# ------------------------------------------------------------------------------
# Analyse des pages
# ------------------------------------------------------------------------------
_LIEN = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


def _cible(cellule: str) -> str:
    m = _LIEN.search(cellule)
    return (m.group(1) if m else re.sub(r"[{}'\[\]]", "", cellule)).strip()


def _cellules(corps: str) -> List[str]:
    """Cellules d'un modèle, séparées par | hors des liens [[a|b]] et des modèles imbriqués {{…}}."""
    out, cur, prof, i = [], "", 0, 0
    while i < len(corps):
        d = corps[i:i + 2]
        if d in ("[[", "{{", "]]", "}}"):
            prof += 1 if d in ("[[", "{{") else -1
            cur += d
            i += 2
            continue
        if corps[i] == "|" and prof == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += corps[i]
        i += 1
    out.append(cur.strip())
    return out


def matrice_fr(w: str) -> List[Tuple[str, str, str]]:
    """Cases (domicile, extérieur, contenu) du tableau `{{Foot résultat début}}…{{Foot résultat fin}}` (clubs = cible du
    lien wiki ; modèles sur une ou plusieurs lignes). Contenu brut : `J07`, `2-1`, `XXX`…"""
    w = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>|<!--.*?-->", "", w, flags=re.S)
    mi = re.search(r"\{\{\s*[Ff]oot résultat début", w)
    if not mi:
        return []
    i = mi.start()
    mj = re.search(r"\{\{\s*[Ff]oot résultat fin", w[i:])
    j = i + mj.start() if mj else -1
    bloc = re.sub(r"<!--.*?-->", "", w[i:j if j > 0 else len(w)], flags=re.S).replace("\n", " ")
    morceaux = [m for m in re.split(r"\{\{\s*[Ff]oot résultat", bloc) if m.strip()]
    if not morceaux or not morceaux[0].lstrip().startswith("début"):
        return []

    def contenu(m: str) -> List[str]:
        m = m.strip()
        if m.endswith("}}"):
            m = m[:-2]
        # 1re cellule = « début » (en-tête) ou vide ; paramètres nommés (align=…, mise à jour=…) écartés
        return [c for c in _cellules(m)[1:] if c and "=" not in c.split("[[")[0]]

    colonnes = [_cible(c) for c in contenu(morceaux[0]) if "[[" in c]
    cases = []
    for m in morceaux[1:]:
        cells = contenu(m)
        if not cells or "[[" not in cells[0]:
            continue
        # Le club de la ligne est celui de la colonne de sa case « XXX » (diagonale) : le lien de la ligne peut viser
        # une redirection (« SV 07 Elversberg » / « SV Elversberg »)
        vals = [c.strip() for c in cells[1:]]
        dom = colonnes[vals.index("XXX")] if "XXX" in vals and vals.index("XXX") < len(colonnes) else _cible(cells[0])
        for ext, val in zip(colonnes, cells[1:]):
            if ext != dom:
                cases.append((dom, ext, val.strip()))
    return cases


_REF = re.compile(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>|<!--.*?-->", re.S)
_SCORE = re.compile(r"^(\d+)\s*[-–]\s*(\d+)$")
_JOURNEE = re.compile(r"^J\s*0*(\d+)$")


def calendrier_it(w: str) -> List[Tuple[int, str, str, str]]:
    """(giornata, domicile, extérieur, score ou '') du § Calendario de Wikipédia IT."""
    w = _REF.sub("", w)
    i = w.find("=== Calendario ===")
    if i < 0:
        i = w.find("== Calendario ==")
    if i < 0:
        return []
    out, g = [], None
    for l in w[i + 5:].split("\n"):
        if re.match(r"^={2,3}\s*[^=]", l):
            break   # section suivante (les sous-sections ==== andata / ritorno restent)
        m = re.search(r"'''(\d+)ª giornata'''", l)
        if m:
            g = int(m.group(1))
            continue
        if g is None or "||" not in l:
            continue
        # « | attributs | 17 gen. || Atalanta-Roma || 2-1 » ou « | Cagliari-Como|| »
        segs = [re.sub(r"\[\[(?:[^\]|]+\|)?([^\]]+)\]\]", r"\1", s).split("|")[-1].strip() for s in l.split("||")]
        for k, sg in enumerate(segs):
            if sg.count("-") == 1 and not _SCORE.match(sg.replace(" ", "")) and re.match(r"^[A-Za-zÀ-ÿ]", sg):
                dom, ext = [x.strip() for x in sg.split("-")]
                score = segs[k + 1] if k + 1 < len(segs) else ""
                out.append((g, dom, ext, score if _SCORE.match(score.replace(" ", "")) else ""))
                break
    return out


# ------------------------------------------------------------------------------
# Rapprochement Wikipédia <-> ESPN
# ------------------------------------------------------------------------------
_GENERIQUES = {"fc", "cf", "ac", "as", "sc", "afc", "club", "football", "futbol", "calcio", "de", "du", "la", "le", "les",
               "the", "and", "of", "sporting", "association", "athletic", "sportive", "olympique", "stade", "real", "united",
               "city", "town", "borussia", "vfl", "vfb", "tsg", "sv", "ssc", "us", "fk", "rcd", "ud", "cd", "sd", "rc",
               "deportivo", "hotspur", "albion", "wanderers", "1", "04", "05", "1899", "1846", "1907", "1909", "1910",
               "et", "d", "l", "y", "s"}


def _mots(*noms: str) -> set:
    out = set()
    for n in noms:
        n = unicodedata.normalize("NFKD", n or "").encode("ascii", "ignore").decode().lower()
        out |= {m for m in re.split(r"[^a-z0-9]+", n) if m and m not in _GENERIQUES}
    return out


def charger_alias() -> Dict[str, Dict[str, str]]:
    try:
        with open(ALIAS_FICHIER, encoding="utf-8") as f:
            return {k: v for k, v in json.load(f).items() if not k.startswith("_")}
    except FileNotFoundError:
        return {}


def apparier(noms_wiki: List[str], equipes_espn: Dict[str, List[str]], ligue: str) -> Tuple[Dict[str, str], List[str]]:
    """{nom wiki: id ESPN}, anomalies. Alias manuels d'abord ; sinon UN seul club ESPN a la plus forte proportion de mots
    distinctifs communs (indice de Jaccard) et aucun autre club Wikipédia ne lui est aussi proche. Un club non apparié = anomalie (journée absente pour ses matchs)."""
    alias = charger_alias().get(ligue, {})
    res, anomalies = {}, []
    restants = dict(equipes_espn)
    for nw in noms_wiki:
        if nw in alias and alias[nw] in restants:
            res[nw] = alias[nw]
    pris = set(res.values())
    def jaccard(a: set, b: set) -> float:
        return len(a & b) / len(a | b) if a and b else 0.0
    scores = {nw: {eid: jaccard(_mots(nw), _mots(*noms)) for eid, noms in restants.items() if eid not in pris}
              for nw in noms_wiki if nw not in res}
    for nw, sc in scores.items():
        if not sc:
            anomalies.append(f"{nw} : aucun club ESPN disponible")
            continue
        meilleur = max(sc.values())
        cands = [e for e, v in sc.items() if v == meilleur]
        if meilleur == 0 or len(cands) > 1:
            anomalies.append(f"{nw} : rapprochement ESPN impossible ({'aucun mot commun' if meilleur == 0 else 'ambigu'})")
            continue
        e = cands[0]
        rivaux = [n for n, s2 in scores.items() if n != nw and s2.get(e, 0) >= meilleur]
        if rivaux:
            anomalies.append(f"{nw} : club ESPN {e} disputé avec {rivaux}")
            continue
        res[nw] = e
    return res, anomalies


# ------------------------------------------------------------------------------
# Cache et calcul des journées d'une saison
# ------------------------------------------------------------------------------
def _score_ok(val: str) -> Optional[Tuple[int, int]]:
    m = _SCORE.match((val or "").replace(" ", ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


_FK = re.compile(r"\{\{\s*fk\s*\|\s*([^}|]+?)\s*(?:\|[^}]*)?\}\}", re.I)
_SCORE_NO = re.compile(r"(\d+)\s*[–-]\s*(\d+)")


def calendrier_no(w: str) -> List[Tuple[int, str, str, str]]:
    """(journée, domicile, extérieur, score ou '') de Wikipédia NO (§ Terminliste : titre de section « N. serierunde », puis une ligne
    par match : score en gras, {{fk|Domicile}} – {{fk|Extérieur}})."""
    w = _REF.sub("", w)
    out, n = [], None
    for l in w.split("\n"):
        m = re.match(r"^={2,4}\s*(?:\[\[[^\]|]*\|)?\s*(\d+)\.\s*serierunde", l, re.I)
        if m:
            n = int(m.group(1))
            continue
        if re.match(r"^={2,3}[^=]", l) and n is not None and "serierunde" not in l.lower():
            n = None                       # section suivante (classement, statistiques…)
            continue
        if n is None or not l.startswith("*"):
            continue
        clubs = _FK.findall(l)
        if len(clubs) != 2:
            continue
        sc = _SCORE_NO.search(l.split("{{")[0])
        out.append((n, clubs[0], clubs[1], f"{sc.group(1)}-{sc.group(2)}" if sc else ""))
    return out


_BOITE = re.compile(r"\{\{\s*(?:Kapanabilir futbol maçı kutusu|Football box collapsible|Football box)\s*\n(.*?)\n\}\}", re.S | re.I)
_LIEN = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


def _champ(corps: str, noms: Tuple[str, ...]) -> str:
    for n in noms:
        m = re.search(r"^\|\s*" + n + r"\s*=\s*(.*)$", corps, re.M)
        if m:
            return m.group(1).strip()
    return ""


def _club_boite(x: str) -> str:
    """Cible du lien d'un club (« [[Galatasaray (futbol takımı)|Galatasaray]] » -> « Galatasaray (futbol takımı) »), sinon le texte."""
    m = _LIEN.search(x)
    if m:
        return m.group(1).strip()
    return re.sub(r"\{\{[^}]*\}\}", "", x).strip()


def calendrier_boites(w: str) -> List[Tuple[int, str, str, str]]:
    """(journée, domicile, extérieur, score ou '') des fiches de match (« Kapanabilir futbol maçı kutusu » TR, « Football box
    collapsible » EN) : champs `tur` / `round` (journée), `takım1` / `team1`, `takım2` / `team2`, `sonuç` / `score`. Une fiche sans
    journée numérique ou sans les deux clubs est ignorée."""
    out = []
    for corps in _BOITE.findall(_REF.sub("", w)):
        j = re.search(r"\d+", _champ(corps, ("tur", "round")))
        h, a = _champ(corps, ("takım1", "team1")), _champ(corps, ("takım2", "team2"))
        if not j or not h or not a:
            continue
        brut = _LIEN.sub(lambda m: m.group(2) or m.group(1), _champ(corps, ("sonuç", "score")))
        sc = _score_ok(re.sub(r"\s*\(.*$", "", re.sub(r"\{\{[^}]*\}\}", "", brut)).strip())
        out.append((int(j.group(0)), _club_boite(h), _club_boite(a), f"{sc[0]}-{sc[1]}" if sc else ""))
    return out


def calendrier_es(w: str) -> List[Tuple[int, str, str, str]]:
    """(jornada, domicile, extérieur, score ou '') de Wikipédia ES (§ Resultados : une table « Jornada N » par journée ; une
    ligne = local, resultado, visitante, …)."""
    w = _REF.sub("", w)
    out: List[Tuple[int, str, str, str]] = []
    j: Optional[int] = None
    cellules: List[str] = []

    def vider() -> None:
        if j is not None and len(cellules) >= 3 and "[[" in cellules[0] and "[[" in cellules[2]:
            sc = re.sub(r"\[https?://\S+\s+([^\]]+)\]", r"\1", cellules[1]).replace("'", "").replace("–", "-").strip()
            sc = re.sub(r"^.*\|", "", sc).strip()
            out.append((j, _cible(cellules[0].split("|", 1)[-1] if cellules[0].count("|") and "[[" not in cellules[0].split("|", 1)[0] else cellules[0]),
                        _cible(cellules[2].split("|", 1)[-1] if cellules[2].count("|") and "[[" not in cellules[2].split("|", 1)[0] else cellules[2]),
                        sc if _SCORE.match(sc.replace(" ", "")) else ""))

    for l in w.split("\n"):
        m = re.search(r"\|\s*Jornada (\d+)\s*$", l)
        if l.startswith("!") and m:
            vider()
            j, cellules = int(m.group(1)), []
            continue
        if l.startswith("|-") or l.startswith("|}"):
            vider()
            cellules = []
            if l.startswith("|}"):
                j = None
            continue
        if j is not None and l.startswith("|") and not l.startswith("|+"):
            cellules.append(l[1:].strip())
    return out


def lire_revision(ligue: str, saison: int, avant: Optional[str] = None, secours: bool = False
                  ) -> Optional[Tuple[List[Tuple[str, str, Optional[int], Optional[Tuple[int, int]]]], int, str]]:
    """[(domicile wiki, extérieur wiki, journée ou None, score ou None)], révision, horodatage."""
    lang, modele = (SECOURS if secours else PAGES)[ligue]
    titre = modele.format(a=saison, b=saison + 1, b2=str(saison + 1)[2:])
    r = wikitexte(lang, titre, avant)
    if not r:
        return None
    w, rev, ts = r
    items = []
    lecteur = {"it": calendrier_it, "es": calendrier_es, "no": calendrier_no, "tr": calendrier_boites}.get(lang)
    if lecteur:
        for g, dom, ext, sc in lecteur(w):
            items.append((dom, ext, g, _score_ok(sc)))
    else:
        for dom, ext, val in matrice_fr(w):
            m = _JOURNEE.match(val)
            items.append((dom, ext, int(m.group(1)) if m else None, _score_ok(val)))
    return items, rev, ts


def fusionner(lot: List[Tuple[str, str, int]], paires: Dict[Tuple[str, str], int], occupe: Dict[int, set],
              etiquette: str) -> List[str]:
    """Ajoute à `paires` les journées d'une révision (`lot` = [(id ESPN domicile, id ESPN extérieur, journée)]), sans
    jamais remplacer une journée déjà connue (révisions lues de la plus récente à la plus ancienne).
    Contrôle : un club au plus une fois par journée. Une case qui contredit une révision plus récente est ignorée ; deux
    cases de la MÊME révision qui se contredisent (erreur de la page) sont toutes deux écartées. Retourne les anomalies."""
    anomalies = []
    nouveaux = [(h, a, j) for h, a, j in lot if (h, a) not in paires]
    retenus = []
    for h, a, j in nouveaux:
        deja = occupe.get(j, set()) & {h, a}
        if deja:
            anomalies.append(f"{etiquette} : J{j} {h}-{a} ignoré (club déjà présent en J{j})")
        else:
            retenus.append((h, a, j))
    compte: Dict[Tuple[int, str], int] = {}
    for h, a, j in retenus:
        for c in (h, a):
            compte[(j, c)] = compte.get((j, c), 0) + 1
    for h, a, j in retenus:
        if compte[(j, h)] > 1 or compte[(j, a)] > 1:
            anomalies.append(f"{etiquette} : J{j} {h}-{a} écarté (club deux fois en J{j} sur la page)")
            continue
        paires[(h, a)] = j
        occupe.setdefault(j, set()).update((h, a))
    return anomalies


def completer_par_scores(items: List[Tuple[str, str, Optional[int], Any]], corr: Dict[str, str],
                         matchs_espn: List[Dict[str, Any]], equipes_espn: Dict[str, List[str]]) -> List[str]:
    """Clubs Wikipédia non rapprochés par le nom : rapprochés par leurs SCORES. Candidat ESPN retenu seulement si TOUS
    les matchs joués inscrits sur Wikipédia contre des clubs déjà rapprochés (au moins 3) existent chez ESPN avec le
    même score, et s'il est le seul candidat. Répété tant que cela progresse. Retourne les clubs restés sans club ESPN."""
    par_paire = {(m["home"], m["away"]): m for m in matchs_espn}
    while True:
        libres_w = sorted({x[0] for x in items} | {x[1] for x in items} - set(corr))
        libres_e = [e for e in equipes_espn if e not in corr.values()]
        progres = False
        for w in libres_w:
            ok = []
            for e in libres_e:
                preuves, contra = 0, 0
                for dom, ext, _, sc in items:
                    if sc is None or w not in (dom, ext):
                        continue
                    autre = ext if dom == w else dom
                    if autre not in corr:
                        continue
                    cle = (e, corr[autre]) if dom == w else (corr[autre], e)
                    m = par_paire.get(cle)
                    if m and m.get("score") is not None and tuple(m["score"]) == sc:
                        preuves += 1
                    else:
                        contra += 1
                if preuves >= 3 and contra == 0:
                    ok.append(e)
            if len(ok) == 1:
                corr[w] = ok[0]
                libres_e.remove(ok[0])
                progres = True
        if not progres:
            return [w for w in libres_w if w not in corr]


def calculer(ligue: str, saison: int, matchs_espn: List[Dict[str, Any]], equipes_espn: Dict[str, List[str]],
             cache: Optional[Dict[str, Any]] = None, aujourdhui: Optional[date] = None) -> Dict[str, Any]:
    """Journée de chaque match ESPN de la saison. `matchs_espn` : [{espn_id, home, away (ids ESPN), score (h, a) ou None}].
    `cache` : résultat d'un passage précédent (journées déjà connues, jamais relues ni remplacées). Retourne
    {ligue, saison, source, rev, correspondances, paires {"h|a": n}, journees {espn_id: n}, anomalies, maj} ;
    `erreur: True` (et le cache inchangé) si la page est illisible ou contredit un score ESPN."""
    aujourdhui = aujourdhui or datetime.now(timezone.utc).date()
    cache = cache or {}
    anomalies: List[str] = []
    lu = lire_revision(ligue, saison)
    if not lu:
        return {**cache, "anomalies": ["page Wikipédia illisible"], "erreur": True}
    items, rev, ts = lu
    noms_wiki = sorted({x[0] for x in items} | {x[1] for x in items})
    corr, _ = apparier(noms_wiki, equipes_espn, ligue)
    for w in completer_par_scores(items, corr, matchs_espn, equipes_espn):
        anomalies.append(f"{w} : aucun club ESPN (nom ni scores) : ajouter un alias dans alias_equipes_wiki.json")
    # Preuve : chaque score inscrit sur Wikipédia = score ESPN du même match
    par_paire = {(m["home"], m["away"]): m for m in matchs_espn}
    desaccords, compares = [], 0
    for dom, ext, _, sc in items:
        if sc is None or dom not in corr or ext not in corr:
            continue
        m = par_paire.get((corr[dom], corr[ext]))
        if m and m.get("score") is not None:
            compares += 1
            if tuple(m["score"]) != sc:
                desaccords.append(f"écart de score {dom}-{ext} : Wikipédia {sc[0]}-{sc[1]}, ESPN {m['score'][0]}-{m['score'][1]}")
    if desaccords:
        print(f"[WARN] journées {ligue} : {len(desaccords)}/{compares} score(s) Wikipédia ≠ ESPN : {desaccords[:3]}")
    # Quelques écarts isolés (saisie Wikipédia, ou ESPN : à recouper, jamais tranché ici) ne remettent pas en cause la
    # correspondance des clubs, prouvée par les autres scores ; au-delà de 2 % (au moins 3), elle est jugée fausse
    if len(desaccords) > max(2, 0.02 * compares):
        return {**cache, "anomalies": anomalies + desaccords, "erreur": True}
    anomalies += desaccords

    paires: Dict[Tuple[str, str], int] = {}
    occupe: Dict[int, set] = {}
    # 1. journées déjà connues (passages précédents) : prioritaires, jamais relues
    anciens = [(k.split("|")[0], k.split("|")[1], j) for k, j in (cache.get("paires") or {}).items()]
    anomalies += fusionner(anciens, paires, occupe, "cache")

    def lot(liste: List[Tuple[str, str, Optional[int], Any]]) -> List[Tuple[str, str, int]]:
        # Révision ancienne : un club a pu y porter un autre lien (« SV 07 Elversberg » / « SV Elversberg »). Ses noms
        # inconnus sont rapprochés (noms) des seuls clubs ESPN dont le nom actuel est ABSENT de cette révision.
        noms = {x[0] for x in liste} | {x[1] for x in liste}
        local = {n: corr[n] for n in noms if n in corr}
        inconnus = sorted(n for n in noms if n not in corr)
        if inconnus:
            absents = {e: equipes_espn.get(e, []) + [w for w, e2 in corr.items() if e2 == e]
                       for e in set(corr.values()) - set(local.values())}
            extra, _ = apparier(inconnus, absents, ligue)
            local.update(extra)
        return [(local[d], local[e], j) for d, e, j, _ in liste if j is not None and d in local and e in local]

    anomalies += fusionner(lot(items), paires, occupe, f"révision {rev}")
    manquants = lambda: [m for m in matchs_espn if (m["home"], m["away"]) not in paires]  # noqa: E731
    revs = [rev]
    # 2. matchs déjà joués : révisions plus anciennes, de la plus récente à la plus ancienne (tous les 14 jours, puis
    #    celle d'avant le 1er juillet), jusqu'à ce que chaque match ait sa journée
    t = aujourdhui - timedelta(days=14)
    debut = date(saison, 7, 1)
    dates = []
    while t >= debut:
        dates.append(f"{t.isoformat()}T23:59:59Z")
        t -= timedelta(days=14)
    dates.append(f"{debut.isoformat()}T00:00:00Z")
    for avant in dates:
        if not manquants():
            break
        r = lire_revision(ligue, saison, avant=avant)
        if r and r[1] not in revs:
            anomalies += fusionner(lot(r[0]), paires, occupe, f"révision {r[1]}")
            revs.append(r[1])
    # 3. page locale de secours pour les matchs encore sans journée, si ses journées concordent avec la page principale
    if manquants() and ligue in SECOURS:
        r = lire_revision(ligue, saison, secours=True)
        if r:
            items_s, rev_s, _ = r
            corr_s, _ = apparier(sorted({x[0] for x in items_s} | {x[1] for x in items_s}), equipes_espn, ligue)
            completer_par_scores(items_s, corr_s, matchs_espn, equipes_espn)
            lot_s = [(corr_s[d], corr_s[e], j) for d, e, j, _ in items_s if j is not None and d in corr_s and e in corr_s]
            communs = [(h, a, j) for h, a, j in lot_s if (h, a) in paires]
            diff = [x for x in communs if paires[(x[0], x[1])] != x[2]]
            if communs and len(diff) <= max(2, 0.02 * len(communs)):
                avant_n = len(paires)
                anomalies += fusionner(lot_s, paires, occupe, f"secours {SECOURS[ligue][0]} {rev_s}")
                revs.append(rev_s)
                print(f"[JOURNÉES] {ligue} : page locale ({SECOURS[ligue][0]}) : {len(paires) - avant_n} journée(s) ajoutée(s), "
                      f"{len(communs) - len(diff)}/{len(communs)} concordante(s) avec la page principale")
            else:
                anomalies.append(f"page locale ({SECOURS[ligue][0]}) écartée : {len(diff)}/{len(communs)} journée(s) discordante(s)")
    journees = {m["espn_id"]: paires[(m["home"], m["away"])] for m in matchs_espn if (m["home"], m["away"]) in paires}
    sans = [m["espn_id"] for m in matchs_espn if m["espn_id"] not in journees]
    if sans:
        anomalies.append(f"{len(sans)} match(s) sans journée")
    # Une même erreur de page se répète d'une révision à l'autre : une ligne par anomalie
    vues, uniques = set(), []
    for x in anomalies:
        cle = re.sub(r"^révision \d+ : ", "", x)
        if cle not in vues:
            vues.add(cle)
            uniques.append(cle)
    anomalies = uniques
    return {"ligue": ligue, "saison": saison,
            "source": f"Wikipédia ({PAGES[ligue][0]}) « {PAGES[ligue][1].format(a=saison, b=saison + 1, b2=str(saison + 1)[2:])} »",
            "rev": rev, "revisions_lues": revs, "correspondances": dict(sorted(corr.items())),
            "paires": {f"{h}|{a}": j for (h, a), j in sorted(paires.items())},
            "journees": journees, "anomalies": anomalies,
            "maj": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


# ------------------------------------------------------------------------------
# Tests (sans réseau) : extraits réels de pages enregistrés le 25/11/2026
# ------------------------------------------------------------------------------
def _test() -> None:
    w = ("{{Foot résultat début|[[Angers Sporting Club de l'Ouest|SCO]]|[[Olympique de Marseille|OM]]|[[Stade rennais "
         "Football Club|SRFC]]}}\n"
         "{{Foot résultat|[[Angers Sporting Club de l'Ouest|Angers SCO]]|XXX|J23|0-2}}\n"
         "{{Foot résultat|[[Olympique de Marseille]]|J20|XXX|2-3}}\n"
         "{{Foot résultat|[[Stade rennais Football Club|Stade rennais FC]]|J06|4-1|XXX}}\n{{Foot résultat fin}}")
    cases = matrice_fr(w)
    assert ("Angers Sporting Club de l'Ouest", "Olympique de Marseille", "J23") in cases, cases
    assert ("Stade rennais Football Club", "Angers Sporting Club de l'Ouest", "J06") in cases
    assert ("Olympique de Marseille", "Stade rennais Football Club", "2-3") in cases
    assert len(cases) == 6
    it = ("=== Calendario ===\n{| \n| bgcolor=#d3d3d3 |'''1ª giornata'''\n|-\n| bgcolor=#e0f0ff | 23 ago. || Atalanta-Sassuolo || 2-1\n"
          "|- bgcolor=#f5f5f5\n| Inter-Monza || 4-1\n|}\n| bgcolor=#d3d3d3 |'''2ª giornata'''\n| 30 ago. || Lazio-Genoa || \n|}\n== Statistiche ==")
    cal = calendrier_it(it)
    assert cal == [(1, "Atalanta", "Sassuolo", "2-1"), (1, "Inter", "Monza", "4-1"), (2, "Lazio", "Genoa", "")], cal
    corr, an = apparier(["Olympique de Marseille", "Olympique lyonnais", "Paris Saint-Germain Football Club", "Paris Football Club"],
                        {"176": ["Marseille", "Olympique de Marseille"], "167": ["Lyon", "Olympique Lyonnais"],
                         "160": ["Paris Saint-Germain", "PSG"], "6851": ["Paris FC", "Paris FC"]}, "test")
    assert corr == {"Olympique de Marseille": "176", "Olympique lyonnais": "167",
                    "Paris Saint-Germain Football Club": "160", "Paris Football Club": "6851"}, (corr, an)
    paires, occupe = {}, {}
    an = fusionner([("a", "b", 1), ("c", "d", 1), ("a", "c", 2), ("b", "d", 2), ("a", "d", 2)], paires, occupe, "rév. 2")
    assert ("a", "b") in paires and ("b", "d") not in paires and ("a", "c") not in paires and ("a", "d") not in paires, (an, paires)
    an = fusionner([("a", "c", 3), ("c", "b", 1), ("d", "c", 5)], paires, occupe, "rév. 1")   # plus ancienne
    assert paires[("a", "c")] == 3 and ("c", "b") not in paires and paires[("d", "c")] == 5, (an, paires)
    items = [("X", "M", None, (2, 0)), ("Y", "X", None, (1, 1)), ("X", "N", None, (0, 3)), ("M", "N", 4, None)]
    corr = {"M": "10", "N": "11", "Y": "12"}
    ms = [{"home": "20", "away": "10", "score": (2, 0)}, {"home": "12", "away": "20", "score": (1, 1)},
          {"home": "20", "away": "11", "score": (0, 3)}, {"home": "21", "away": "10", "score": (2, 0)}]
    reste = completer_par_scores(items, corr, ms, {"10": [], "11": [], "12": [], "20": [], "21": []})
    assert corr["X"] == "20" and not reste, (corr, reste)
    es = ('{|class="wikitable"\n! colspan="10" | Jornada 1\n|-\n! Local\n|-\n|bgcolor="D0E7FF"|' "'''[[Deportivo Alavés]]'''\n"
          "|[https://www.laliga.com/x 3 – 0]\n|[[Getafe Club de Fútbol|Getafe C. F.]]\n|[[Estadio|E]]\n|-\n"
          '|[[Real Racing Club de Santander|Racing]]\n|bgcolor="D0E7FF"|' "'''[https://x 2 – 2]'''\n"
          "|[[Villarreal Club de Fútbol|Villarreal]]\n|}\n"
          '{|\n! colspan="10" | Jornada 2\n|-\n|[[Sevilla Fútbol Club|Sevilla]]\n|\n|[[Elche Club de Fútbol|Elche]]\n|}')
    assert calendrier_es(es) == [(1, "Deportivo Alavés", "Getafe Club de Fútbol", "3 - 0"),
                                 (1, "Real Racing Club de Santander", "Villarreal Club de Fútbol", "2 - 2"),
                                 (2, "Sevilla Fútbol Club", "Elche Club de Fútbol", "")], calendrier_es(es)
    # Norvège (extrait réel de « Eliteserien i fotball for menn 2026 », Wikipédia NO)
    no = ("== Terminliste ==\n===[[1. serierunde i Eliteserien 2026|1. serierunde]]===\n'''Lørdag 14. mars'''\n"
          "*'''2–1''' '''{{fk|HamKam}}''' – {{fk|Viking}}\n*'''1–3''' {{fk|Aalesund}} – '''{{fk|Lillestrøm}}'''\n{{col-4}}\n"
          "===[[2. serierunde i Eliteserien 2026|2. serierunde]]===\n*{{fk|Start}} – {{fk|Aalesund}}\n== Tabell ==\n*{{fk|A}} – {{fk|B}}")
    assert calendrier_no(no) == [(1, "HamKam", "Viking", "2-1"), (1, "Aalesund", "Lillestrøm", "1-3"), (2, "Start", "Aalesund", "")], calendrier_no(no)
    # Turquie (extrait réel du modèle « 2026-27 Süper Lig maçları/maçlar », Wikipédia TR)
    tr = ("{{#switch:{{{1}}}\n|GAL-ÇFK = \n{{Kapanabilir futbol maçı kutusu\n|tarih = {{Başlangıç tarihi|2026|8|14}}\n|tur               = 1\n"
          "|takım1            = [[Galatasaray (futbol takımı)|Galatasaray]]\n|sonuç             = 2 - 2\n|takım2            = [[Çorum FK|Çorum]]\n"
          "|goller1 = \n* [[Victor Osimhen]] {{gol|53||90}}\n}}\n|X-Y = \n{{Kapanabilir futbol maçı kutusu\n|tur = 12\n|takım1 = [[Kasımpaşa SK|Kasımpaşa]]\n"
          "|sonuç = [[#x|v]]\n|takım2 = [[Trabzonspor (futbol takımı)|Trabzonspor]]\n}}\n}}")
    assert calendrier_boites(tr) == [(1, "Galatasaray (futbol takımı)", "Çorum FK", "2-2"),
                                     (12, "Kasımpaşa SK", "Trabzonspor (futbol takımı)", "")], calendrier_boites(tr)
    print("[OK] journees_wiki : tests passés")


if __name__ == "__main__":
    if "--test" in sys.argv:
        _test()
