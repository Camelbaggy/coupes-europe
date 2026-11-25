#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Source complémentaire ESPN :
- fil de commentaires texte (Opta, en anglais) des matchs de clubs français : matière première du récit des agents Gemini ;
- buts attendus (xG, modèle Opta) de TOUS les matchs terminés : l'UEFA n'en publie pas. Rapprochement STRICT d'un match UEFA
  avec un événement ESPN (date + score + les deux équipes reconnues, un seul candidat) ; au moindre doute, pas d'xG.
  Jamais bloquant : une panne ESPN = pas d'xG, le passage continue.
"""

import datetime as dt
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from netutil import fetch_json, fetch_json_ex, normalize

ESPN_SITE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
ESPN_CORE = "https://sports.core.api.espn.com/v2/sports/soccer/leagues"
XG_SOURCE = "ESPN (Opta)"
PAUSE_XG_S = 0.3            # pause entre deux requêtes de statistiques (politesse)
MAX_ERREURS_DE_SUITE = 6    # au-delà, plus aucune requête xG pendant ce passage (ESPN injoignable)
TOLERANCE_COHERENCE = 0.05  # écart toléré entre xG d'une équipe et xGC de l'adversaire (arrondis)
# (clé stockée dans stats.all, nom ESPN, libellé)
XG_STATS = [
    ("xg", "expectedGoals", "Buts attendus (xG)"),
    ("xgot", "expectedGoalsOnTarget", "xG des tirs cadrés (xGOT)"),
    ("xg_sans_penalty", "expectedGoalsNonPenalty", "xG hors penalty"),
    ("xa", "expectedAssists", "Passes décisives attendues (xA)"),
]
XG_CLES = [k for k, _, _ in XG_STATS]
ESPN_SLUGS = {"ucl": "uefa.champions", "uel": "uefa.europa", "uecl": "uefa.europa.conf"}

_SCOREBOARDS: Dict[str, List[Dict[str, Any]]] = {}
REQUETES = {"scoreboard": 0, "stats": 0}   # requêtes réseau réellement émises (mesure, journal)


def _clock_label(display: str) -> str:
    nums = [int(n) for n in re.findall(r"\d+", display or "")]
    if not nums:
        return ""
    return f"{nums[0]}'+{nums[1]}" if len(nums) > 1 else f"{nums[0]}'"


def _sort_key(display: str) -> float:
    nums = [int(n) for n in re.findall(r"\d+", display or "")]
    return (nums[0] + (nums[1] / 100 if len(nums) > 1 else 0)) if nums else 0.0


def _scoreboard_ex(comp_key: str, ymd: str) -> Tuple[List[Dict[str, Any]], str]:
    """(événements, statut) ; un échec réseau n'est jamais mis en cache (statut « erreur »)."""
    key = f"{comp_key}_{ymd}"
    if key not in _SCOREBOARDS:
        REQUETES["scoreboard"] += 1
        data, statut = fetch_json_ex(f"{ESPN_SITE}/{ESPN_SLUGS[comp_key]}/scoreboard?dates={ymd}",
                                     raw_name=f"espn_scoreboard_{key}.json")
        if statut == "erreur":
            return [], "erreur"
        _SCOREBOARDS[key] = (data or {}).get("events", []) or []
    return _SCOREBOARDS[key], "ok"


def _scoreboard(comp_key: str, ymd: str) -> List[Dict[str, Any]]:
    return _scoreboard_ex(comp_key, ymd)[0]


_TRANSLIT = str.maketrans({"ø": "o", "Ø": "O", "æ": "ae", "Æ": "AE", "ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "ß": "ss", "œ": "oe"})
# Dénominations différentes UEFA / ESPN d'un même club (mot -> mots équivalents ajoutés) ; liste courte, vérifiée à la main
_ALIAS_MOTS = {"zvezda": {"red", "star", "belgrade"}, "copenhagen": {"kobenhavn"}, "kobenhavn": {"copenhagen"}}


def _norm(n: str) -> str:
    return normalize((n or "").translate(_TRANSLIT))


def _words(*names: str) -> set:
    out = set()
    for n in names:
        out |= {w for w in _norm(n).replace("/", " ").replace("-", " ").split() if len(w) > 2}
    for w in list(out):
        out |= _ALIAS_MOTS.get(w, set())
    return out - {"fc", "afc", "club", "sporting", "real", "the"}


def find_espn_event(comp_key: str, date_str: str, home_names: List[str], away_names: List[str],
                    home_score: int, away_score: int) -> Optional[str]:
    """Retrouve l'identifiant ESPN d'un match UEFA : même date, même score, au moins une équipe reconnue."""
    hw, aw = _words(*home_names), _words(*away_names)
    for ev in _scoreboard(comp_key, date_str.replace("-", "")):
        comp = (ev.get("competitions") or [{}])[0]
        cs = {c.get("homeAway"): c for c in comp.get("competitors", []) or []}
        if "home" not in cs or "away" not in cs:
            continue
        try:
            if int(cs["home"].get("score")) != home_score or int(cs["away"].get("score")) != away_score:
                continue
        except (TypeError, ValueError):
            continue
        eh = _words(cs["home"].get("team", {}).get("displayName", ""), cs["home"].get("team", {}).get("shortDisplayName", ""))
        ea = _words(cs["away"].get("team", {}).get("displayName", ""), cs["away"].get("team", {}).get("shortDisplayName", ""))
        if (hw & eh) or (aw & ea):
            return str(ev.get("id"))
    return None


def fetch_commentary(comp_key: str, event_id: str) -> List[str]:
    """Fil de commentaires chronologique, au format « [minute] texte »."""
    summary = fetch_json(f"{ESPN_SITE}/{ESPN_SLUGS[comp_key]}/summary?event={event_id}",
                         raw_name=f"espn_summary_{event_id}.json") or {}
    items = []
    for idx, c in enumerate(summary.get("commentary", []) or []):
        text = (c.get("text") or "").strip()
        if not text:
            continue
        disp = (c.get("time") or {}).get("displayValue", "") or ""
        seq = c.get("sequence")
        items.append((_sort_key(disp), seq if isinstance(seq, (int, float)) else idx, _clock_label(disp), text))
    items.sort(key=lambda x: (x[0], x[1]))
    return [f"[{lbl}] {txt}" if lbl else txt for _, _, lbl, txt in items]


# ------------------------------------------------------------------------------
# Buts attendus (xG)
# ------------------------------------------------------------------------------
_STATS_EQUIPES: Dict[str, Tuple[Optional[Dict[str, float]], str]] = {}
_ERREURS_DE_SUITE = 0


def reinitialiser() -> None:
    """Vide les caches et le disjoncteur (tests, nouveau passage)."""
    global _ERREURS_DE_SUITE
    _SCOREBOARDS.clear()
    _STATS_EQUIPES.clear()
    _ERREURS_DE_SUITE = 0
    REQUETES.update(scoreboard=0, stats=0)


def _noms_concordent(noms_uefa: List[str], noms_espn: List[str]) -> bool:
    """Au moins un mot distinctif commun, ou noms normalisés identiques (« Sporting CP » n'a aucun mot distinctif)."""
    if _words(*noms_uefa) & _words(*noms_espn):
        return True
    return bool({_norm(n) for n in noms_uefa if n} & {_norm(n) for n in noms_espn if n})


def _noms_espn(c: Dict[str, Any]) -> List[str]:
    t = c.get("team") or {}
    return [n for n in (t.get("displayName"), t.get("shortDisplayName"), t.get("name"), t.get("location")) if n]


def _jour_utc(iso: str) -> Optional[dt.date]:
    try:
        return dt.date.fromisoformat((iso or "")[:10])
    except ValueError:
        return None


def trouver_evenement_strict(comp_key: str, date_str: str, home_names: List[str], away_names: List[str],
                             home_score: int, away_score: int) -> Tuple[Optional[Dict[str, str]], str]:
    """Rapprochement STRICT d'un match UEFA terminé avec un événement ESPN : même jour (UTC, à un jour près), événement
    terminé, score identique, les DEUX équipes reconnues, UN SEUL candidat (deux candidats = ambigu = aucun).
    Gère un domicile / extérieur inversé (terrain neutre) en reportant les identifiants dans l'ordre UEFA.
    Retourne ({event_id, home_id, away_id}, "ok") ou (None, "non_trouve" | "erreur")."""
    try:
        jour = dt.date.fromisoformat(date_str)
    except ValueError:
        return None, "non_trouve"
    evenements, statut = _scoreboard_ex(comp_key, date_str.replace("-", ""))
    if statut == "erreur":
        return None, "erreur"
    candidats = []
    for ev in evenements:
        comp = (ev.get("competitions") or [{}])[0]
        cs = {c.get("homeAway"): c for c in comp.get("competitors", []) or []}
        if "home" not in cs or "away" not in cs:
            continue
        if ((ev.get("status") or {}).get("type") or {}).get("completed") is not True:
            continue
        jev = _jour_utc(ev.get("date", ""))
        if jev is not None and abs((jev - jour).days) > 1:
            continue
        try:
            sh, sa = int(cs["home"].get("score")), int(cs["away"].get("score"))
        except (TypeError, ValueError):
            continue
        for a, b, sa_, sb_ in ((cs["home"], cs["away"], sh, sa), (cs["away"], cs["home"], sa, sh)):
            if (sa_, sb_) == (home_score, away_score) and _noms_concordent(home_names, _noms_espn(a)) \
                    and _noms_concordent(away_names, _noms_espn(b)):
                candidats.append({"event_id": str(ev.get("id") or ""), "home_id": str(a.get("id") or ""),
                                  "away_id": str(b.get("id") or "")})
                break
    if len(candidats) == 1 and all(candidats[0].values()):
        return candidats[0], "ok"
    return None, "non_trouve"


def _stats_equipe(comp_key: str, event_id: str, team_id: str) -> Tuple[Optional[Dict[str, float]], str]:
    """Statistiques d'équipe d'un match ESPN (nom -> valeur) ; statut « ok » | « absent » | « erreur »."""
    global _ERREURS_DE_SUITE
    cle = f"{comp_key}/{event_id}/{team_id}"
    if cle in _STATS_EQUIPES:
        return _STATS_EQUIPES[cle]
    if _ERREURS_DE_SUITE >= MAX_ERREURS_DE_SUITE:
        return None, "erreur"
    time.sleep(PAUSE_XG_S)
    REQUETES["stats"] += 1
    data, statut = fetch_json_ex(f"{ESPN_CORE}/{ESPN_SLUGS[comp_key]}/events/{event_id}/competitions/{event_id}"
                                 f"/competitors/{team_id}/statistics", raw_name=f"espn_stats_{event_id}_{team_id}.json")
    if statut == "erreur":
        _ERREURS_DE_SUITE += 1
        return None, "erreur"
    _ERREURS_DE_SUITE = 0
    valeurs: Dict[str, float] = {}
    for cat in ((data or {}).get("splits") or {}).get("categories", []) or []:
        for st in cat.get("stats", []) or []:
            v = st.get("value")
            if st.get("name") and isinstance(v, (int, float)) and not isinstance(v, bool) and st["name"] not in valeurs:
                valeurs[st["name"]] = float(v)
    res = (valeurs, "ok") if valeurs else (None, "absent")
    _STATS_EQUIPES[cle] = res
    return res


def lire_xg(comp_key: str, ev: Dict[str, str]) -> Tuple[Optional[Dict[str, Any]], str]:
    """xG des deux équipes d'un événement ESPN rapproché. Retourne ({stats, note}, "ok") ou (None, "absent" | "erreur").
    Il faut l'xG des DEUX équipes (sinon rien) ; xGOT / xA / xG hors penalty seulement s'ils existent pour les deux."""
    h, sh = _stats_equipe(comp_key, ev["event_id"], ev["home_id"])
    a, sa = _stats_equipe(comp_key, ev["event_id"], ev["away_id"])
    if sh == "erreur" or sa == "erreur":
        return None, "erreur"
    if not h or not a or "expectedGoals" not in h or "expectedGoals" not in a:
        return None, "absent"
    stats = []
    for cle, nom, libelle in XG_STATS:
        if nom in h and nom in a:
            if cle == "xg_sans_penalty" and abs(h[nom] - h["expectedGoals"]) < 1e-9 and abs(a[nom] - a["expectedGoals"]) < 1e-9:
                continue   # aucun penalty tiré : même valeur que l'xG, inutile à l'écran
            stats.append({"key": cle, "label": libelle, "home": round(h[nom], 3), "away": round(a[nom], 3)})
    ecarts = []
    if "expectedGoalsConceded" in a:
        ecarts.append(abs(h["expectedGoals"] - a["expectedGoalsConceded"]))
    if "expectedGoalsConceded" in h:
        ecarts.append(abs(a["expectedGoals"] - h["expectedGoalsConceded"]))
    note = ""
    if ecarts and max(ecarts) > TOLERANCE_COHERENCE:
        note = ("xG de chaque équipe conservé tel que publié ; il diffère de l'xG encaissé par l'adversaire "
                f"(écart maximal {max(ecarts):.2f}).")
    return {"stats": stats, "note": note}, "ok"


def ajouter_xg(comp_key: str, match: Dict[str, Any], aujourdhui: Optional[dt.date] = None) -> str:
    """Ajoute les xG à `match["stats"]["all"]` (jamais aux mi-temps : ESPN n'en donne pas) + `xg_source`, `xg_espn_id`
    (+ `xg_note` en cas d'incohérence). Retourne « ok » | « non_termine » | « non_trouve » | « absent » | « erreur ».
    « non_trouve » / « absent » laissent `xg_statut` + `xg_essai` (jour de l'essai) : le rattrapage retente quelques
    jours, puis abandonne ; « erreur » (réseau) ne laisse aucune trace : le prochain passage réessaie. Idempotent."""
    if not match.get("finished"):
        return "non_termine"
    h, a = match["home_team"], match["away_team"]
    ev, statut = trouver_evenement_strict(comp_key, match["date"], [h["name"], h.get("official_name", "")],
                                          [a["name"], a.get("official_name", "")], h["score"], a["score"])
    xg = None
    if ev:
        xg, statut = lire_xg(comp_key, ev)
    if statut == "erreur":
        return "erreur"   # rien n'est modifié : une panne ne détruit pas un xG déjà enregistré
    stats = match.setdefault("stats", {"all": [], "1st": [], "2nd": []})
    stats["all"] = [s for s in stats.get("all", []) if s.get("key") not in XG_CLES]
    for k in ("xg_source", "xg_espn_id", "xg_note", "xg_statut", "xg_essai"):
        match.pop(k, None)
    if xg:
        stats["all"].extend(xg["stats"])
        match["xg_source"] = XG_SOURCE
        match["xg_espn_id"] = ev["event_id"]
        if xg["note"]:
            match["xg_note"] = xg["note"]
        return "ok"
    match["xg_statut"] = statut
    match["xg_essai"] = (aujourdhui or dt.datetime.now(dt.timezone.utc).date()).isoformat()
    return statut


def xg_a_faire(match: Dict[str, Any]) -> bool:
    """Match terminé sans xG à (re)tenter : jamais essayé, ou essayé moins de 3 jours après le match (Opta publie parfois
    après coup). Un essai plus tardif sans résultat est définitif (ESPN n'a pas ce match)."""
    if not match.get("finished") or any(s.get("key") == "xg" for s in (match.get("stats") or {}).get("all", [])):
        return False
    essai, jour = match.get("xg_essai"), match.get("date")
    if not match.get("xg_statut") or not essai or not jour:
        return True
    try:
        return dt.date.fromisoformat(essai) < dt.date.fromisoformat(jour) + dt.timedelta(days=3)
    except ValueError:
        return True


def _test():
    """Tests hors réseau sur des réponses ESPN RÉELLES allégées (tools/fixtures/espn/xg_reponses.json)."""
    import copy
    import json
    import os
    global fetch_json_ex, PAUSE_XG_S
    fx = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools", "fixtures", "espn", "xg_reponses.json"),
                        encoding="utf-8"))
    appels, panne = [], {"on": False}

    def faux(url, retries=3, raw_name=""):
        appels.append(url)
        if panne["on"]:
            return None, "erreur"
        if "/scoreboard?dates=" in url:
            ligue = url.split("/soccer/")[1].split("/scoreboard")[0]
            return fx["scoreboards"].get(f"{ligue}/{url.rsplit('=', 1)[1]}", {"events": []}), "ok"
        ligue = url.split("/leagues/")[1].split("/events/")[0]
        ev, eq = url.split("/events/")[1].split("/")[0], url.split("/competitors/")[1].split("/")[0]
        d = fx["stats"].get(f"{ligue}/{ev}/{eq}")
        return (d, "ok") if d else (None, "absent")
    reel, fetch_json_ex, ancien_pause = fetch_json_ex, faux, PAUSE_XG_S
    PAUSE_XG_S = 0
    try:
        def match(h, ho, hs, a, ao, as_, date="2026-11-24"):
            return {"finished": True, "date": date, "home_team": {"name": h, "official_name": ho, "score": hs},
                    "away_team": {"name": a, "official_name": ao, "score": as_}, "stats": {"all": [{"key": "attempts", "label": "Tirs", "home": 9, "away": 5}], "1st": [], "2nd": []}}
        reinitialiser()
        # LDC : Bodø/Glimt 1-0 LASK (xG 1,228 / 0,265 ; xGC croisés cohérents)
        m = match("Bodø/Glimt", "FK Bodø/Glimt", 1, "LASK", "LASK", 0)
        assert ajouter_xg("ucl", m, dt.date(2026, 11, 25)) == "ok"
        st = {s["key"]: s for s in m["stats"]["all"]}
        assert st["xg"]["home"] == 1.228 and st["xg"]["away"] == 0.265 and st["xgot"]["home"] == 0.556 and st["xa"]["home"] == 1.611
        assert "xg_sans_penalty" not in st            # aucun penalty : identique à l'xG, non gardé
        assert st["attempts"]["home"] == 9 and m["stats"]["1st"] == [] and m["stats"]["2nd"] == []   # reste intact, aucun xG par mi-temps
        assert m["xg_source"] == XG_SOURCE and m["xg_espn_id"] == "401915380" and "xg_note" not in m
        n = len(appels)
        assert ajouter_xg("ucl", m) == "ok" and len(appels) == n      # idempotent, caches : aucune requête de plus
        assert not xg_a_faire(m)
        # nom UEFA différent (Man City / Manchester City FC), score 2-2
        m2 = match("Man City", "Manchester City FC", 2, "Napoli", "SSC Napoli", 2)
        assert ajouter_xg("ucl", m2) == "ok" and {s["key"]: s for s in m2["stats"]["all"]}["xg"]["home"] > 0
        # mauvais score = pas de rapprochement, trace de l'essai ; mauvaises équipes = pas de rapprochement
        m3 = match("Bodø/Glimt", "FK Bodø/Glimt", 2, "LASK", "LASK", 0)
        assert ajouter_xg("ucl", m3, dt.date(2026, 11, 25)) == "non_trouve" and m3["xg_statut"] == "non_trouve" and "xg_source" not in m3
        assert all(s["key"] not in XG_CLES for s in m3["stats"]["all"]) and xg_a_faire(m3)   # essai < 3 jours après le match : à retenter
        m3["xg_essai"] = "2026-11-28"
        assert not xg_a_faire(m3)                                                           # essai tardif : définitif
        m4 = match("Bayern", "FC Bayern München", 1, "Chelsea", "Chelsea FC", 0)
        assert ajouter_xg("ucl", m4) == "non_trouve"
        # équipes inversées (terrain neutre) : identifiants reportés dans l'ordre UEFA, valeurs de la bonne équipe
        m5 = match("LASK", "LASK", 0, "Bodø/Glimt", "FK Bodø/Glimt", 1)
        assert ajouter_xg("ucl", m5) == "ok"
        s5 = {s["key"]: s for s in m5["stats"]["all"]}
        assert s5["xg"]["home"] == 0.265 and s5["xg"]["away"] == 1.228
        # translittération ø et alias Crvena Zvezda / Red Star, København / Copenhagen
        m6 = match("Lillestrøm", "Lillestrøm SK", 0, "Viktoria Plzeň", "FC Viktoria Plzeň", 1, "2026-11-05")
        assert ajouter_xg("uel", m6) == "ok"
        m7 = match("Crvena Zvezda", "FK Crvena Zvezda", 2, "Inter Escaldes", "Inter Club d'Escaldes", 1, "2026-11-05")
        assert ajouter_xg("uecl", m7) == "ok"
        # match non terminé : rien
        m8 = dict(m, finished=False)
        assert ajouter_xg("ucl", m8) == "non_termine"
        # panne ESPN : « erreur », rien n'est modifié (un xG déjà enregistré n'est jamais détruit), pas de trace d'essai
        reinitialiser()
        panne["on"] = True
        avant = copy.deepcopy(m)
        assert ajouter_xg("ucl", m) == "erreur" and m == avant
        m9 = match("Bodø/Glimt", "FK Bodø/Glimt", 1, "LASK", "LASK", 0)
        assert ajouter_xg("ucl", m9) == "erreur" and "xg_statut" not in m9 and xg_a_faire(m9)
        # incohérence xG / xGC : valeurs propres conservées + note
        reinitialiser()
        panne["on"] = False
        cle = "uefa.champions/401915380/4411"
        for cat in fx["stats"][cle]["splits"]["categories"]:
            for s in cat["stats"]:
                if s["name"] == "expectedGoalsConceded":
                    s["value"] = 0.9
        m10 = match("Bodø/Glimt", "FK Bodø/Glimt", 1, "LASK", "LASK", 0)
        assert ajouter_xg("ucl", m10) == "ok" and "écart maximal" in m10["xg_note"] and {s["key"]: s for s in m10["stats"]["all"]}["xg"]["home"] == 1.228
        # disjoncteur : ESPN en panne répétée = plus aucune requête
        reinitialiser()
        panne["on"] = False
        global _ERREURS_DE_SUITE
        _ERREURS_DE_SUITE = MAX_ERREURS_DE_SUITE
        n = len(appels)
        assert _stats_equipe("ucl", "1", "2") == (None, "erreur") and len(appels) == n
    finally:
        fetch_json_ex, PAUSE_XG_S = reel, ancien_pause
        reinitialiser()
    print("[OK] espn.py : tests xG réussis")


if __name__ == "__main__":
    import sys
    if "--test" in sys.argv:
        _test()
