#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Historique des classements FINAUX des championnats (big 5), de l'origine à la dernière saison terminée.

Demande du propriétaire (25/11/2026) : « pour les saisons précédentes, seul l'historique du classement des clubs
m'intéresse » ; Wikipédia a une page par saison ; pages locales si la page FR ne suffit pas. Détail : docs/historique_classements.md.

Sources :
- saisons depuis 2002-03 : classement final ESPN (`site.api.espn.com/apis/v2/sports/soccer/<slug>/standings?season=<année de
  début>`), pénalités de points comprises (mesuré : Serie A 2005-06 = Inter 76 pts) ;
- saisons antérieures : tableau du classement final de la page Wikipédia FR de la saison (« Championnat de France de football
  1933-1934 »…), modèle `{{Foot classement|rang|club|pts|j|g|n|p|bp|bc…}}` ou tableau `wikitable` à en-têtes ; repli sur la
  page LOCALE (IT, ES, DE, EN) quand la page FR n'a pas de tableau lisible.
Début de la série (championnat à poule unique) : Ligue 1 1933-34 (1932-33 = deux poules + finale), première division anglaise
1888-89, Liga 1929, Serie A 1929-30, Bundesliga 1963-64. Saisons sans championnat officiel (guerres) : `SAISONS_ABSENTES`.

Contrôles déterministes (`controler`, rien n'est jamais corrigé ni inventé) : j = g + n + p pour chaque club ; somme des buts
marqués = somme des buts encaissés ; même nombre de matchs pour tous les clubs (sinon noté) ; points = g x V + n selon le barème
de l'époque (`points_victoire`) : un écart est CONSERVÉ tel que publié et listé (pénalité, bonus offensif français 1973-1976,
titre retiré…). Statut : `ok` / `ecarts_points` (structure saine, points publiés différents du barème pour certains clubs) /
`illisible` (aucun tableau, structure incohérente, plusieurs poules) : une saison illisible n'a pas de lignes.

    python historique_classements.py --donnees DIR [--ligues fl1,pl] [--budget-min 40]
    python historique_classements.py --test
    python historique_classements.py --valider [--ligues …]   # recouvrement ESPN / Wikipédia 2002-2010 (réseau)
"""

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

UA = "coupes-europe/1.0 (dashboard personnel ; https://github.com/Camelbaggy/coupes-europe)"
PAUSE_S = 2.2
LOT_TITRES = 12            # pages par requête MediaWiki
ESPN_DEPUIS = 2002         # première saison lue chez ESPN (2002-03)
ESPN = "https://site.api.espn.com/apis/v2/sports/soccer"

LIGUES: Dict[str, Dict[str, Any]] = {
    "fl1": {"slug": "fra.1", "nom": "Ligue 1", "debut": 1933, "fr": "Championnat de France de football {a}-{b}",
            "local": None, "v3": 1994},
    "pl": {"slug": "eng.1", "nom": "Premier League", "debut": 1888, "fr": "Championnat d'Angleterre de football {a}-{b}",
           "local": ("en", "{a}–{b2} Football League"), "v3": 1981},
    "liga": {"slug": "esp.1", "nom": "Liga", "debut": 1929, "fr": "Championnat d'Espagne de football {a}-{b}",
             "local": ("es", "Primera División de España {a}-{b2}"), "v3": 1995},
    "sa": {"slug": "ita.1", "nom": "Serie A", "debut": 1929, "fr": "Championnat d'Italie de football {a}-{b}",
           "local": ("it", "Serie A {a}-{b}"), "v3": 1994},
    "bl": {"slug": "ger.1", "nom": "Bundesliga", "debut": 1963, "fr": "Championnat d'Allemagne de football {a}-{b}",
           "local": ("de", "Fußball-Bundesliga {a}/{b2}"), "v3": 1995},
}


def titre_local(ligue: str, a: int) -> Tuple[str, str]:
    """(langue, titre) de la page locale d'une saison. EN : « 1899–1900 Football League » (siècle complet au passage),
    « 1992–93 FA Premier League » à partir de la création de la Premier League ; ES : « … 1929 » pour la saison unique."""
    lang, modele = LIGUES[ligue]["local"]
    b2 = str(a + 1)[2:] if str(a + 1)[:2] == str(a)[:2] else str(a + 1)
    if ligue == "pl" and a >= 1992:
        modele = "{a}–{b2} FA Premier League" if a < 2007 else "{a}–{b2} Premier League"
    if ligue == "liga" and a == 1929:
        return lang, "Primera División de España 1929"
    return lang, modele.format(a=a, b=a + 1, b2=b2)


# Saisons sans championnat national officiel (année de début) : rien n'est demandé ni écrit
SAISONS_ABSENTES = {
    "fl1": set(range(1939, 1945)),                          # championnats de guerre, non officiels
    "pl": set(range(1915, 1919)) | set(range(1939, 1946)),  # Première et Seconde Guerres mondiales
    "liga": set(range(1936, 1939)),                         # guerre civile
    "sa": {1943, 1944},                                     # 1943-44 Campionato Alta Italia (non officiel), 1944-45 aucun
    "bl": set(),
}


def libelle(annee: int, ligue: str = "") -> str:
    """« 1933-34 » ; la Liga 1929 se joue sur une seule année civile."""
    if ligue == "liga" and annee == 1929:
        return "1929"
    return f"{annee}-{str(annee + 1)[2:]}"


def saisons(ligue: str, derniere: int) -> List[int]:
    return [a for a in range(LIGUES[ligue]["debut"], derniere + 1) if a not in SAISONS_ABSENTES[ligue]]


def points_victoire(ligue: str, annee: int) -> int:
    return 3 if annee >= LIGUES[ligue]["v3"] else 2


def derniere_saison_terminee(aujourdhui: Optional[dt.date] = None) -> int:
    """Année de début de la dernière saison terminée (la saison courante commence le 1er juillet)."""
    d = aujourdhui or dt.date.today()
    courante = d.year if d.month >= 7 else d.year - 1
    return courante - 1


# ------------------------------------------------------------------------------
# Contrôles (purs)
# ------------------------------------------------------------------------------
def controler(rows: List[Dict[str, Any]], v: int) -> Tuple[str, Dict[str, Any]]:
    """(statut, contrôles). Statut `illisible` si la structure est incohérente (aucune valeur n'est alors gardée)."""
    c: Dict[str, Any] = {"clubs": len(rows), "points_victoire": v}
    if len(rows) < 6:
        return "illisible", {**c, "erreur": "moins de 6 clubs"}
    faux_j = [r["club"] for r in rows if r["j"] != r["g"] + r["n"] + r["p"]]
    if faux_j:
        return "illisible", {**c, "erreur": f"j != g+n+p : {faux_j[:5]}"}
    bp, bc = sum(r["bp"] for r in rows), sum(r["bc"] for r in rows)
    c["buts"] = bp
    if bp != bc:
        return "illisible", {**c, "erreur": f"buts marqués {bp} != buts encaissés {bc}"}
    js = sorted({r["j"] for r in rows})
    if len(js) > 1:
        c["matchs_inegaux"] = js
    rangs = [r["rang"] for r in rows]
    if rangs != sorted(rangs):
        return "illisible", {**c, "erreur": "rangs non croissants"}
    ecarts = [{"club": r["club"], "publie": r["pts"], "bareme": r["g"] * v + r["n"]}
              for r in rows if r["pts"] != r["g"] * v + r["n"]]
    if ecarts:
        c["ecarts_points"] = ecarts
        return "ecarts_points", c
    return "ok", c


# ------------------------------------------------------------------------------
# Analyse du wikitexte
# ------------------------------------------------------------------------------
_REF = re.compile(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>|<!--.*?-->", re.S)
_LIEN = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
_NUM = re.compile(r"^[+−–-]?\d+$")


def _cellules(corps: str) -> List[str]:
    """Cellules séparées par | hors des liens [[…]] et des modèles imbriqués {{…}}."""
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


def _cellules_ligne(l: str) -> List[str]:
    """Découpe une ligne de wikitable sur « || » hors des liens et des modèles."""
    out, cur, prof, i = [], "", 0, 0
    while i < len(l):
        d = l[i:i + 2]
        if d == "||" and prof == 0:
            out.append(cur)
            cur = ""
            i += 2
            continue
        if d in ("[[", "{{", "]]", "}}"):
            prof += 1 if d in ("[[", "{{") else -1
            cur += d
            i += 2
            continue
        cur += l[i]
        i += 1
    out.append(cur)
    return out


def tables_fussballtabelle(w: str) -> List[List[Dict[str, Any]]]:
    """Modèle allemand `{{Fußballtabelle/Zeile|Rang=|S=|U=|N=|ET=|GT=|Siegpunkte=|Abzug=|Verein=}}`. La page ne publie
    pas les points : le modèle les AFFICHE en calculant S x Siegpunkte + U - Abzug ; on refait ce même calcul (ligne
    marquée `pts_calcule`) et `Abzug` (points retirés) est gardé en `penalite`."""
    w = _REF.sub("", w)
    blocs, cur = [], None
    for m in re.finditer(r"\{\{\s*Fußballtabelle/(Kopf|Zeile|Ende)", w):
        kind = m.group(1)
        if kind == "Kopf":
            cur = []
            blocs.append(cur)
            continue
        if kind == "Ende":
            cur = None
            continue
        if cur is None:
            cur = []
            blocs.append(cur)
        i, prof, j = m.start(), 0, m.start()
        while j < len(w):
            if w.startswith("{{", j):
                prof += 1
                j += 2
            elif w.startswith("}}", j):
                prof -= 1
                j += 2
                if prof == 0:
                    break
            else:
                j += 1
        params = {}
        for c in _cellules(w[i + 2:j - 2])[1:]:
            if "=" in c:
                k, v = c.split("=", 1)
                params[k.strip()] = v.strip()
        nums = {k: _nombre(params.get(k, "")) for k in ("Rang", "S", "U", "N", "ET", "GT")}
        sp = _nombre(params.get("Siegpunkte", ""))
        if any(v is None for v in nums.values()) or not sp or not params.get("Verein"):
            continue
        abzug = _nombre(params.get("Abzug", "")) or 0
        nom, cible, mention = _club(params["Verein"])
        r = {"rang": nums["Rang"], "club": nom, "pts": nums["S"] * sp + nums["U"] - abzug,
             "j": nums["S"] + nums["U"] + nums["N"], "g": nums["S"], "n": nums["U"], "p": nums["N"],
             "bp": nums["ET"], "bc": nums["GT"], "pts_calcule": True}
        if abzug:
            r["penalite"] = abzug
        if cible:
            r["club_wiki"] = cible
        mention = re.sub(r"\(\d\)", "", mention).strip()
        if mention:
            r["mention"] = mention
        cur.append(r)
    return [b for b in blocs if b]


# Module Lua « Sports table » (EN) / « Football table » (ES) : paramètres nommés par code d'équipe.
_ST_CLES = {
    "g": ("win", "ganados"), "n": ("draw", "empates"), "p": ("loss", "perdidos"),
    "bp": ("gf",), "bc": ("ga", "gc"), "nom": ("name", "nombre"),
    "ajust": ("adjust_points", "ajustar_puntos", "ajuste_puntos", "startpoints", "puntos_iniciales"),
}
_ST_V = ("winpoints", "puntos_ganado", "puntos_victoria")
_ST_N = ("drawpoints", "puntos_empate")


def tables_sports_table(w: str) -> List[List[Dict[str, Any]]]:
    """`{{#invoke:Sports table|main|style=WDL|team_order=…|win_ARS=…|draw_ARS=…|loss_ARS=…|gf_ARS=…|ga_ARS=…|name_ARS=…}}` (EN)
    et `{{#invoke:Football table|main|equipo1=…|ganados_X=…|empates_X=…|perdidos_X=…|gf_X=…|gc_X=…|nombre_X=…}}` (ES). La page ne
    publie pas les points : le module les AFFICHE en calculant V x victoires + nuls (+ ajustement publié) ; on refait ce calcul
    (`pts_calcule`). Un paramètre de points par équipe inconnu = tableau refusé (on ne devine pas son effet). Une page à plusieurs
    divisions : seuls les tableaux `section` « First Division » / sans section sont gardés."""
    w = re.sub(r"<!--.*?-->", "", w, flags=re.S)
    w = _REF.sub("", w)
    out = []
    for m in re.finditer(r"\{\{\s*#invoke:\s*(?:[Ss]ports|[Ff]ootball) table\s*\|", w):
        i, prof, j = m.start(), 0, m.start()
        while j < len(w):
            if w.startswith("{{", j):
                prof += 1
                j += 2
            elif w.startswith("}}", j):
                prof -= 1
                j += 2
                if prof == 0:
                    break
            else:
                j += 1
        params: Dict[str, str] = {}
        for c in _cellules(w[i + 2:j - 2])[2:]:
            if "=" in c:
                k, v = c.split("=", 1)
                params[k.strip()] = v.strip()
        section = params.get("section", "")
        if section and "first division" not in section.lower() and "primera" not in section.lower():
            continue
        if (params.get("style") or params.get("estilo") or "WDL").upper() != "WDL":
            continue
        if any(k.startswith(("hth_", "result_", "match_")) for k in params) and not any(k.startswith(("win_", "ganados_")) for k in params):
            continue
        ordre = [x.strip() for x in params.get("team_order", "").split(",") if x.strip()]
        if not ordre:
            n = 1
            while params.get(f"team{n}") or params.get(f"equipo{n}"):
                ordre.append((params.get(f"team{n}") or params.get(f"equipo{n}")).strip())
                n += 1
        if not ordre:   # codes numériques « nombre_1 … nombre_20 » sans ordre explicite : le numéro est le rang
            nums = sorted(int(k.split("_")[-1]) for k in params if re.match(r"^(?:name|nombre)_\d+$", k))
            if nums and nums == list(range(1, len(nums) + 1)):
                ordre = [str(x) for x in nums]
        vp = next((_nombre(params[k]) for k in _ST_V if k in params), 3)
        np_ = next((_nombre(params[k]) for k in _ST_N if k in params), 1)
        if not ordre or vp is None or np_ is None:
            continue
        connus = {f"{p}_" for t in _ST_CLES.values() for p in t} | {"status_", "result", "col_", "text_", "note_", "estado_",
                                                                     "color_", "texto_", "nota_", "resultado", "hth_", "dq_"}
        douteux = [k for k in params if re.search(r"(?i)point|punt", k) and k not in _ST_V + _ST_N
                   and not k.startswith(_ST_CLES["ajust"])]
        if douteux:
            continue
        rows, ok = [], True
        for rang, code in enumerate(ordre, 1):
            def val(champ: str) -> Optional[int]:
                for p in _ST_CLES[champ]:
                    if f"{p}_{code}" in params:
                        return _nombre(params[f"{p}_{code}"])
                return None
            g, n_, p_, bp, bc = val("g"), val("n"), val("p"), val("bp"), val("bc")
            nom_brut = next((params[f"{p}_{code}"] for p in _ST_CLES["nom"] if f"{p}_{code}" in params), "")
            if None in (g, n_, p_, bp, bc) or not nom_brut:
                ok = False
                break
            aj = 0
            for p in _ST_CLES["ajust"]:
                if f"{p}_{code}" in params:
                    v = _nombre(params[f"{p}_{code}"])
                    if v is None:
                        ok = False
                    aj += v or 0
            nom, cible, mention = _club(nom_brut)
            r = {"rang": rang, "club": nom, "pts": g * vp + n_ * np_ + aj, "j": g + n_ + p_, "g": g, "n": n_, "p": p_,
                 "bp": bp, "bc": bc, "pts_calcule": True}
            if aj:
                r["penalite"] = -aj
            if cible:
                r["club_wiki"] = cible
            if mention:
                r["mention"] = mention
            rows.append(r)
        if ok and rows:
            out.append(rows)
    return out


def _club(cellule: str) -> Tuple[str, str, str]:
    """(nom affiché, cible du lien, mentions) d'une cellule de club ; mentions = texte hors lien (« déclassé »…)."""
    m = _LIEN.search(cellule)
    if m:
        cible = m.group(1).strip()
        nom = (m.group(2) or m.group(1)).strip()
        reste = cellule[:m.start()] + cellule[m.end():]
    elif re.search(r"\{\{\s*Calcio ", cellule):
        mc = re.search(r"\{\{\s*Calcio ([^|}]+)[^}]*\}\}", cellule)
        cible, nom, reste = "", mc.group(1).strip(), cellule[:mc.start()] + cellule[mc.end():]
    else:
        cible, nom, reste = "", re.sub(r"\{\{[^}]*\}\}", "", cellule), ""
    nom = re.sub(r"'''?|<[^>]+>", "", nom).strip()
    reste = re.sub(r"\{\{[^}]*\}\}|'''?|<[^>]+>|[,;()]", " ", reste)
    return nom, cible, " ".join(reste.split())


def _nombre(s: str) -> Optional[int]:
    s = re.sub(r"'''?|<[^>]+>|\{\{formatnum:([^}]*)\}\}", r"\1", s or "").replace("−", "-").replace("–", "-").strip()
    s = s.split("<")[0].strip()
    return int(s) if _NUM.match(s) else None


def _rang(s: str) -> Optional[int]:
    s = re.sub(r"\{\{[^}]*\}\}|'''?", "", s or "").strip().rstrip(".").strip()
    return int(s) if s.isdigit() else None


def tables_foot_classement(w: str) -> List[List[Dict[str, Any]]]:
    """Blocs `{{Foot classement début}}` … `{{Foot classement fin}}` (ou fin de tableau) : lignes {rang, club, pts, j, g, n,
    p, bp, bc}. Ordre des nombres du modèle : pts, j, g, n, p, bp, bc (vérifié sur 11 pages de 1888 à 1993)."""
    w = _REF.sub("", w)
    blocs, cur = [], None
    for m in re.finditer(r"\{\{\s*[Ff]oot classement(\s+début|\s+fin)?\s*(\||\}\})", w):
        kind = (m.group(1) or "").strip()
        if kind == "début":
            cur = []
            blocs.append(cur)
            continue
        if kind == "fin":
            cur = None
            continue
        if cur is None:
            cur = []
            blocs.append(cur)
        # modèle d'une ligne : jusqu'à la fermeture }} de même niveau
        i, prof = m.start(), 0
        j = i
        while j < len(w):
            if w.startswith("{{", j):
                prof += 1
                j += 2
            elif w.startswith("}}", j):
                prof -= 1
                j += 2
                if prof == 0:
                    break
            else:
                j += 1
        corps = w[i + 2:j - 2]
        cells = _cellules(corps)[1:]
        cells = [c for c in cells if not re.match(r"^\s*[A-Za-zéÉ_]+\s*=", c)]
        if len(cells) < 9:
            continue
        rang = _rang(cells[0])
        nom, cible, mention = _club(cells[1])
        nums = [_nombre(c) for c in cells[2:9]]
        if rang is None or not nom or any(n is None for n in nums):
            continue
        pts, j_, g, n, p, bp, bc = nums
        r = {"rang": rang, "club": nom, "pts": pts, "j": j_, "g": g, "n": n, "p": p, "bp": bp, "bc": bc}
        if cible:
            r["club_wiki"] = cible
        if mention:
            r["mention"] = mention
        cur.append(r)
    return [b for b in blocs if b]


# En-têtes de colonnes des wikitables (FR, EN, IT, ES, DE) -> champ
ENTETES = {
    "j": ["j", "mj", "joués", "matchs", "pld", "p", "pj", "sp", "spiele", "g"],
    "g": ["g", "v", "victoires", "w", "won", "vinte", "pg", "s", "siege"],
    "n": ["n", "nuls", "d", "drawn", "pareggiate", "pe", "u", "unentschieden", "x"],
    "p": ["p", "défaites", "l", "lost", "perse", "pp", "niederlagen"],
    "bp": ["bp", "buts pour", "gf", "f", "goals for", "gol fatti", "gf.", "tore"],
    "bc": ["bc", "buts contre", "ga", "a", "goals against", "gol subiti", "gc"],
    "pts": ["pts", "points", "pt", "puntos", "punkte"],
}


_MODELE_ABBR = re.compile(r"\{\{\s*(?:[Aa]bbr|[Dd]escrizione comando|[Tt]ooltip|[Aa]breviatura|[Hh]:title)\s*\|([^|}]*)\|[^}]*\}\}")
COL_CLUB = {"équipe", "equipe", "club", "clubs", "squadra", "equipo", "verein", "mannschaft", "team", "teams"}


def _texte_entete(h: str) -> str:
    h = _MODELE_ABBR.sub(r"\1", h)
    h = re.sub(r"<[^>]+>|\{\{[^}]*\}\}|\[\[(?:[^\]|]+\|)?([^\]]+)\]\]|'''?", r"\1", h)
    return re.sub(r"^.*\|", "", h).strip().lower().rstrip(".")


def _entete(h: str, lang: str) -> Optional[str]:
    h = _texte_entete(h)
    sp = {  # lettres ambiguës selon la langue
        "fr": {"j": "j", "g": "g", "v": "g", "n": "n", "d": "p", "p": "p"},
        "en": {"p": "j", "w": "g", "d": "n", "l": "p", "f": "bp", "a": "bc"},
        "it": {"g": "j", "v": "g", "n": "n", "p": "p", "pt": "pts", "gf": "bp", "gs": "bc"},
        "es": {"pj": "j", "pg": "g", "pe": "n", "pp": "p", "gf": "bp", "gc": "bc"},
        "de": {"sp": "j", "s": "g", "u": "n", "n": "p"},
    }.get(lang, {})
    if h in sp:
        return sp[h]
    for champ, noms in ENTETES.items():
        if h in noms and len(h) > 2:
            return champ
    return None


def tables_wikitable(w: str, lang: str) -> List[List[Dict[str, Any]]]:
    """Tableaux `{| class="wikitable"` dont les en-têtes donnent au moins j, g, n, p, bp, bc, pts et une colonne de club."""
    w = _REF.sub("", w)
    out = []
    for t in re.finditer(r"\{\|[^\n]*wikitable[^\n]*\n(.*?)\n\|\}", w, re.S):
        lignes = t.group(1).split("\n")
        heads: List[str] = []
        rows_raw: List[List[str]] = []
        cur: Optional[List[str]] = None
        for l in lignes:
            if l.startswith("|+"):
                continue
            if l.startswith("!"):
                heads += [x.strip() for x in re.split(r"!!", l[1:])]
                continue
            if l.startswith("|-"):
                if cur:
                    rows_raw.append(cur)
                cur = []
                continue
            if l.startswith("|") and cur is not None:
                parts = [x.strip() for x in _cellules_ligne(l[1:])]
                if l.startswith("||") and parts and parts[0].startswith("|"):   # suite de ligne : « ||44||30… »
                    parts[0] = parts[0][1:].strip()
                cur += parts
        if cur:
            rows_raw.append(cur)
        champs = [_entete(h, lang) for h in heads]
        idx = {c: i for i, c in enumerate(champs) if c and c not in ()}
        if not all(k in idx for k in ("j", "g", "n", "p", "bp", "bc", "pts")):
            continue
        rows = []
        for cells in rows_raw:
            cells = [re.sub(r"^[a-z]+=\"?[^|\"]*\"?\s*\|\s*", "", c) for c in cells]  # attributs de cellule
            if len(cells) != len(heads):
                continue
            club_i = next((i for i, h in enumerate(heads) if _texte_entete(h) in COL_CLUB), None)
            if club_i is None:
                club_i = next((i for i, c in enumerate(cells) if "[[" in c or "{{Calcio" in c), None)
            rang = next((_rang(c) for c in cells[:club_i or 0] if _rang(c) is not None), None)
            if club_i is None or rang is None:
                continue
            nom, cible, mention = _club(cells[club_i])
            vals = {k: _nombre(cells[i]) for k, i in idx.items()}
            if any(v is None for v in vals.values()):
                continue
            r = {"rang": rang, "club": nom, **vals}
            if cible:
                r["club_wiki"] = cible
            if mention:
                r["mention"] = mention
            rows.append(r)
        if rows:
            out.append(rows)
    return out


def classement_final(w: str, lang: str, v: int) -> Tuple[str, List[Dict[str, Any]], Dict[str, Any]]:
    """(statut, lignes, contrôles) du classement final d'une page de saison. Plusieurs tableaux candidats sains et
    différents (poules) = illisible : on ne choisit jamais au hasard."""
    cands = [b for b in tables_foot_classement(w) + tables_fussballtabelle(w) + tables_sports_table(w) + tables_wikitable(w, lang) if len(b) >= 6]
    sains = []
    for b in cands:
        st, c = controler(b, v)
        if st != "illisible":
            sains.append((st, b, c))
    # un même tableau peut apparaître deux fois (modèle + tableau) : dédoublonnage sur (club, pts)
    uniques = []
    for s in sains:
        sig = [(r["club"], r["pts"], r["j"]) for r in s[1]]
        if not any(sig == [(r["club"], r["pts"], r["j"]) for r in u[1]] for u in uniques):
            uniques.append(s)
    if len(uniques) == 1:
        return uniques[0]
    if not uniques:
        raison = "aucun tableau de classement lisible" if not cands else controler(cands[0], v)[1].get("erreur", "")
        return "illisible", [], {"erreur": raison, "tableaux": len(cands)}
    # plusieurs tableaux : le plus grand s'il est le seul de sa taille et contient tous les autres clubs ? non : poules
    return "illisible", [], {"erreur": f"{len(uniques)} tableaux de classement (poules ?)", "tableaux": len(uniques)}


# ------------------------------------------------------------------------------
# Réseau
# ------------------------------------------------------------------------------
REQUETES = {"wiki": 0, "espn": 0}


def _http_json(url: str, essais: int = 5) -> Optional[Any]:
    for i in range(essais):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return None
            attente = int(e.headers.get("Retry-After") or 0) if e.code == 429 else 0
            attente = max(attente, 10 * (i + 1))
            print(f"[WARN] HTTP {e.code} ; nouvel essai dans {attente} s")
            time.sleep(attente)
        except Exception as e:
            print(f"[WARN] réseau : {e}")
            time.sleep(5 * (i + 1))
    return None


def pages_wiki(lang: str, titres: List[str]) -> Dict[str, Optional[Tuple[str, str]]]:
    """{titre demandé: (wikitexte, titre final) ou None}, redirections suivies, par lots de LOT_TITRES."""
    out: Dict[str, Optional[Tuple[str, str]]] = {}
    for k in range(0, len(titres), LOT_TITRES):
        lot = titres[k:k + LOT_TITRES]
        time.sleep(PAUSE_S)
        REQUETES["wiki"] += 1
        q = urllib.parse.urlencode({"action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main",
                                    "titles": "|".join(lot), "redirects": "1", "format": "json", "formatversion": "2"})
        d = _http_json(f"https://{lang}.wikipedia.org/w/api.php?{q}")
        if d is None:
            continue   # lot illisible : ces saisons restent à faire
        qd = d.get("query") or {}
        vers = {t: t for t in lot}
        for n in qd.get("normalized") or []:
            for t, cible in list(vers.items()):
                if cible == n["from"]:
                    vers[t] = n["to"]
        for rd in qd.get("redirects") or []:
            for t, cible in list(vers.items()):
                if cible == rd["from"]:
                    vers[t] = rd["to"]
        pages = {p["title"]: p for p in qd.get("pages") or []}
        for t in lot:
            p = pages.get(vers[t]) or {}
            rev = (p.get("revisions") or [{}])[0]
            txt = (rev.get("slots") or {}).get("main", {}).get("content")
            out[t] = (txt, vers[t]) if txt else None
    return out


def classement_espn(ligue: str, annee: int) -> Optional[List[Dict[str, Any]]]:
    REQUETES["espn"] += 1
    time.sleep(0.3)
    d = _http_json(f"{ESPN}/{LIGUES[ligue]['slug']}/standings?season={annee}")
    entries = ((((d or {}).get("children") or [{}])[0].get("standings") or {}).get("entries")) or []
    rows = []
    for e in entries:
        s = {x.get("name"): x.get("value") for x in e.get("stats") or []}
        t = e.get("team") or {}
        try:
            rows.append({"rang": int(s["rank"]), "club": t.get("displayName") or t.get("shortDisplayName"),
                         "espn_id": str(t.get("id")), "pts": int(s["points"]), "j": int(s["gamesPlayed"]),
                         "g": int(s["wins"]), "n": int(s["ties"]), "p": int(s["losses"]),
                         "bp": int(s["pointsFor"]), "bc": int(s["pointsAgainst"]),
                         **({"penalite": int(s["deductions"])} if s.get("deductions") not in (None, "", 0) else {})})
        except (KeyError, TypeError, ValueError):
            return None
    rows.sort(key=lambda r: r["rang"])
    return rows or None


# ------------------------------------------------------------------------------
# Rapprochement avec les clubs ESPN (saisons anciennes) : nom identique sans ambiguïté
# ------------------------------------------------------------------------------
def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.split(r"[^a-z0-9]+", s)).strip()


def index_noms_espn(fichier: Dict[str, Any]) -> Dict[str, str]:
    """{nom normalisé: espn_id} d'après les saisons ESPN déjà lues (nom affiché ESPN) ; un nom porté par deux ids est
    écarté. Les noms des saisons Wikipédia ne sont rapprochés que s'ils sont IDENTIQUES (normalisés) à un nom ESPN."""
    vus: Dict[str, set] = {}
    for s in (fichier.get("saisons") or {}).values():
        for r in s.get("rows") or []:
            if r.get("espn_id"):
                vus.setdefault(_norm(r["club"]), set()).add(r["espn_id"])
    return {n: next(iter(ids)) for n, ids in vus.items() if len(ids) == 1}


# ------------------------------------------------------------------------------
# Collecte
# ------------------------------------------------------------------------------
def _lire(chemin: str) -> Any:
    try:
        with open(chemin, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _ecrire(chemin: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    tmp = chemin + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, chemin)


RETENTE_JOURS = 30          # une saison illisible n'est retentée qu'après ce délai (pas de relance sans fin)


def a_faire(ligue: str, fichier: Dict[str, Any], derniere: int, aujourdhui: Optional[dt.date] = None) -> List[int]:
    """Saisons à (re)lire : absentes, illisibles dont le dernier essai date de plus de RETENTE_JOURS jours, et la dernière
    saison terminée (classement final possiblement revu)."""
    auj = aujourdhui or dt.date.today()
    faites = fichier.get("saisons") or {}
    out = []
    for a in saisons(ligue, derniere):
        s = faites.get(libelle(a, ligue))
        if s is None or a == derniere:
            out.append(a)
        elif s.get("statut") == "illisible":
            try:
                essai = dt.date.fromisoformat(s.get("essai", ""))
            except ValueError:
                essai = None
            if essai is None or (auj - essai).days >= RETENTE_JOURS:
                out.append(a)
    return out


def collecter(donnees: str, ligues: List[str], budget_min: float, aujourdhui: Optional[dt.date] = None,
              retenter: bool = False) -> Dict[str, int]:
    debut = time.monotonic()
    derniere = derniere_saison_terminee(aujourdhui)
    jour = (aujourdhui or dt.date.today()).isoformat()
    traites = restants = 0
    for lg in ligues:
        cfg = LIGUES[lg]
        chemin = os.path.join(donnees, "championnats", "historique", f"{lg}.json")
        fichier = _lire(chemin) or {"ligue": lg, "nom": cfg["nom"], "saisons": {}}
        if retenter:   # --retenter : saisons illisibles relues sans attendre RETENTE_JOURS (nouveau lecteur, par exemple)
            for s_ in fichier["saisons"].values():
                if s_.get("statut") == "illisible":
                    s_.pop("essai", None)
        todo = a_faire(lg, fichier, derniere, aujourdhui)
        # 1. ESPN (2002-03 et après), du plus récent au plus ancien
        for a in sorted([a for a in todo if a >= ESPN_DEPUIS], reverse=True):
            if time.monotonic() - debut > budget_min * 60:
                break
            rows = classement_espn(lg, a)
            v = points_victoire(lg, a)
            st, c = controler(rows, v) if rows else ("illisible", {"erreur": "ESPN illisible"})
            ancien = fichier["saisons"].get(libelle(a, lg))
            if not (st == "illisible" and ancien and ancien.get("statut") != "illisible"):
                fichier["saisons"][libelle(a, lg)] = {
                    "source": "ESPN", "url": f"{ESPN}/{cfg['slug']}/standings?season={a}", "statut": st, "controles": c,
                    "rows": rows if st != "illisible" else [], **({"essai": jour} if st == "illisible" else {})}
            traites += a != derniere
        noms = index_noms_espn(fichier)
        espn_illisibles = [a for a in todo if a >= ESPN_DEPUIS
                           and (fichier["saisons"].get(libelle(a, lg)) or {}).get("statut") == "illisible"]
        # 2. Wikipédia (avant 2002-03) : FR, puis page locale pour les saisons restées illisibles
        anciennes = sorted([a for a in todo if a < ESPN_DEPUIS] + espn_illisibles, reverse=True)
        for k in range(0, len(anciennes), LOT_TITRES):
            if time.monotonic() - debut > budget_min * 60:
                break
            lot = anciennes[k:k + LOT_TITRES]
            titres = {a: cfg["fr"].format(a=a, b=a + 1) if not (lg == "liga" and a == 1929)
                      else "Championnat d'Espagne de football 1929" for a in lot}
            pages = pages_wiki("fr", list(titres.values()))
            restes = []
            for a in lot:
                p = pages.get(titres[a])
                res = classement_final(p[0], "fr", points_victoire(lg, a)) if p else ("illisible", [], {"erreur": "page absente"})
                if res[0] == "illisible" and cfg["local"]:
                    restes.append(a)
                ecrire_saison(fichier, lg, a, res, "Wikipédia FR", "fr", p[1] if p else titres[a], noms, jour)
            if restes:
                lang = cfg["local"][0]
                tl = {a: titre_local(lg, a)[1] for a in restes}
                # Angleterre : certaines saisons ont un article propre « … Football League First Division »
                t1 = {a: tl[a].replace("Football League", "Football League First Division") for a in restes
                      if lg == "pl" and tl[a].endswith("Football League")}
                pl = pages_wiki(lang, list(tl.values()) + list(t1.values()))
                for a in restes:
                    res, p = ("illisible", [], {}), None
                    for t in ([t1[a]] if a in t1 else []) + [tl[a]]:
                        p = pl.get(t)
                        if p:
                            res = classement_final(p[0], lang, points_victoire(lg, a))
                            if res[0] != "illisible":
                                break
                    if not p:
                        continue
                    if res[0] != "illisible":
                        ecrire_saison(fichier, lg, a, res, f"Wikipédia {lang.upper()}", lang, p[1], noms, jour)
            traites += sum(1 for a in lot if a != derniere)
        fichier["maj"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        fichier["saisons"] = dict(sorted(fichier["saisons"].items(), key=lambda kv: kv[0]))
        _ecrire(chemin, fichier)
        restants += sum(1 for a in a_faire(lg, fichier, derniere, aujourdhui) if a != derniere)
        st = [s["statut"] for s in fichier["saisons"].values()]
        print(f"[HISTORIQUE] {cfg['nom']} : {len(st)} saison(s) — ok {st.count('ok')}, écarts de points "
              f"{st.count('ecarts_points')}, illisibles {st.count('illisible')}")
    ecrire_index(donnees)
    print(f"[HISTORIQUE] {REQUETES['wiki']} requête(s) Wikipédia, {REQUETES['espn']} ESPN, "
          f"{time.monotonic() - debut:.0f} s ; {traites} saison(s) traitée(s), {restants} à reprendre")
    sortie = os.environ.get("GITHUB_OUTPUT")
    if sortie:
        with open(sortie, "a", encoding="utf-8") as f:
            f.write(f"traites={traites}\nrestants={restants}\n")
    return {"traites": traites, "restants": restants}


def ecrire_saison(fichier: Dict[str, Any], lg: str, a: int, res: Tuple[str, List[Dict[str, Any]], Dict[str, Any]],
                  source: str, lang: str, titre: str, noms: Dict[str, str], jour: str = "") -> None:
    st, rows, c = res
    ancien = (fichier["saisons"] or {}).get(libelle(a, lg))
    if st == "illisible" and ancien and ancien.get("statut") != "illisible":
        return   # un échec ne remplace jamais une saison lue
    for r in rows:
        e = noms.get(_norm(r["club"]))
        if e:
            r["espn_id"] = e
    fichier["saisons"][libelle(a, lg)] = {
        "source": source, "titre": titre,
        "url": f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(titre.replace(' ', '_'))}",
        "statut": st, "controles": c, "rows": rows if st != "illisible" else [],
        **({"essai": jour} if st == "illisible" and jour else {})}


def ecrire_index(donnees: str) -> None:
    idx = {}
    for lg, cfg in LIGUES.items():
        f = _lire(os.path.join(donnees, "championnats", "historique", f"{lg}.json"))
        if not f:
            continue
        ss = f.get("saisons") or {}
        lisibles = [k for k, s in ss.items() if s.get("statut") != "illisible"]
        idx[lg] = {"nom": cfg["nom"], "fichier": f"{lg}.json", "saisons": len(ss), "lisibles": len(lisibles),
                   "premiere": min(lisibles) if lisibles else None, "derniere": max(lisibles) if lisibles else None,
                   "ok": sum(1 for s in ss.values() if s.get("statut") == "ok"),
                   "ecarts_points": sum(1 for s in ss.values() if s.get("statut") == "ecarts_points"),
                   "illisibles": sorted(k for k, s in ss.items() if s.get("statut") == "illisible"),
                   "sources": sorted({s.get("source") for s in ss.values() if s.get("source")}),
                   "maj": f.get("maj")}
    _ecrire(os.path.join(donnees, "championnats", "historique", "index.json"),
            {"maj": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "ligues": idx})


# ------------------------------------------------------------------------------
# Validation (réseau) et tests
# ------------------------------------------------------------------------------
def valider(ligues: List[str], annees: range = range(2002, 2011)) -> None:
    for lg in ligues:
        cfg = LIGUES[lg]
        titres = {a: cfg["fr"].format(a=a, b=a + 1) for a in annees}
        pages = pages_wiki("fr", list(titres.values()))
        ok = tot = 0
        for a in annees:
            e = classement_espn(lg, a)
            p = pages.get(titres[a])
            st, rows, c = classement_final(p[0], "fr", points_victoire(lg, a)) if p else ("illisible", [], {})
            if not e or st == "illisible":
                print(f"[VALIDATION] {lg} {libelle(a)} : {'ESPN illisible' if not e else 'Wikipédia ' + str(c.get('erreur'))}")
                continue
            tot += 1
            cle = lambda r: (r["rang"], r["pts"], r["j"], r["g"], r["n"], r["p"], r["bp"], r["bc"])  # noqa: E731
            diff = [(x, y) for x, y in zip(map(cle, e), map(cle, rows)) if x != y]
            if len(e) == len(rows) and not diff:
                ok += 1
            else:
                print(f"[VALIDATION] {lg} {libelle(a)} : {len(diff)} ligne(s) différente(s), ex. {diff[:2]}")
        print(f"[VALIDATION] {cfg['nom']} : {ok}/{tot} saison(s) identiques ESPN / Wikipédia FR (rangs, points, matchs, buts)")


def _test() -> None:
    fx = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools", "fixtures", "historique_classements")
    attendu = {
        "fl1_1975-76.txt": ("fr", 2, "ecarts_points", 20, ("AS Saint-Étienne", 57)),   # bonus offensif 1973-1976
        "fl1_1992-93.txt": ("fr", 2, "ok", 20, ("Olympique de Marseille", 53)),
        "pl_1960-61.txt": ("fr", 2, "ok", 22, ("Tottenham Hotspur", 66)),
        "liga_1929.txt": ("fr", 2, "illisible", 0, None),             # page FR incohérente : 383 buts marqués, 380 encaissés
        "liga_1960-61.txt": ("fr", 2, "ok", 16, ("Real Madrid", 52)),
        "sa_1929-30.txt": ("fr", 2, "ok", 18, ("AS Ambrosiana", 50)),
        "bl_1963-64.txt": ("fr", 2, "ok", 16, ("1. FC Cologne", 45)),
        "fl1_1932-33.txt": ("fr", 2, "illisible", 0, None),                             # deux poules + finale
        "sa_1934-35_it.txt": ("it", 2, "ok", 16, ("Juventus", 44)),                     # {{Descrizione comando}}, {{Calcio X}}
        "bl_1971-72_de.txt": ("de", 2, "ecarts_points", 18, ("FC Bayern München", 55)),  # Fußballtabelle ; Bielefeld : Abzug 19
        "pl_1980-81_en.txt": ("en", 2, "ok", 22, ("Aston Villa", 60)),                # Sports table ; 2e division écartée
        "liga_1977-78_es.txt": ("es", 2, "ok", 18, ("Real Madrid C. F.", 47)),          # Football table (ES)
    }
    for nom, (lang, v, st_att, n_att, premier) in attendu.items():
        w = open(os.path.join(fx, nom), encoding="utf-8").read()
        st, rows, c = classement_final(w, lang, v)
        assert st == st_att, (nom, st, c)
        assert len(rows) == n_att, (nom, len(rows))
        if premier:
            assert (rows[0]["club"], rows[0]["pts"]) == premier, (nom, rows[0])
    # Marseille 1992-93 : titre retiré, la page publie la ligne avec la mention « déclassé »
    rows = classement_final(open(os.path.join(fx, "fl1_1992-93.txt"), encoding="utf-8").read(), "fr", 2)[1]
    assert "déclassé" in rows[0].get("mention", ""), rows[0]
    # contrôles
    r = lambda c, pts, g, n, p, bp, bc, rang=1: {"rang": rang, "club": c, "pts": pts, "j": g + n + p, "g": g, "n": n,  # noqa: E731
                                                 "p": p, "bp": bp, "bc": bc}
    base = [r(f"c{i}", 6, 3, 0, 0, 3, 3, i) for i in range(1, 7)]
    assert controler(base, 2)[0] == "ok"
    pen = [dict(base[0], pts=4)] + base[1:]
    st, c = controler(pen, 2)
    assert st == "ecarts_points" and c["ecarts_points"][0]["publie"] == 4
    assert controler([dict(base[0], bp=9)] + base[1:], 2)[0] == "illisible"
    assert controler([dict(base[0], j=5)] + base[1:], 2)[0] == "illisible"
    assert points_victoire("fl1", 1993) == 2 and points_victoire("fl1", 1994) == 3 and points_victoire("pl", 1981) == 3
    assert libelle(1929, "liga") == "1929" and libelle(1929, "sa") == "1929-30"
    assert 1940 not in saisons("fl1", 2025) and saisons("bl", 2025)[0] == 1963
    # reprise : saison illisible retentée seulement après RETENTE_JOURS jours ; dernière saison toujours relue
    f = {"saisons": {libelle(a, "bl"): {"statut": "ok"} for a in saisons("bl", 2025)}}
    f["saisons"]["1971-72"] = {"statut": "illisible", "essai": "2026-11-20"}
    assert a_faire("bl", f, 2025, dt.date(2026, 11, 25)) == [2025]
    assert a_faire("bl", f, 2025, dt.date(2026, 12, 25)) == [1971, 2025]
    print("[OK] historique_classements : tests passés")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Historique des classements finaux des championnats")
    ap.add_argument("--donnees", default="../donnees-football")
    ap.add_argument("--ligues", default=",".join(LIGUES))
    ap.add_argument("--budget-min", type=float, default=40)
    ap.add_argument("--retenter", action="store_true", help="relire les saisons illisibles sans attendre 30 jours")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--valider", action="store_true")
    a = ap.parse_args()
    if a.test:
        _test()
    elif a.valider:
        valider(a.ligues.split(","))
    else:
        collecter(a.donnees, a.ligues.split(","), a.budget_min, retenter=a.retenter)
