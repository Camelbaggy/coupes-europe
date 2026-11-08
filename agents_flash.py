#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agents Gemini Flash : rédaction et contrôle des résumés des matchs des clubs français.

1. On prépare un « dossier de match » factuel : score à la mi-temps, phases de domination
   (calculées depuis le momentum), moments clés tirés du fil de commentaires, statistiques
   nommées par équipe, classement.
2. L'agent rédacteur raconte le match en 4-5 phrases à partir de ce dossier uniquement.
3. L'agent contrôleur vérifie chaque fait cité ; en cas de rejet, le rédacteur corrige (3 essais).
4. Sans clé ou en cas d'échec, un résumé narratif déterministe est construit à partir des mêmes faits.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
FALLBACK_MODELS = ["gemini-flash-latest", "gemini-2.5-flash"]
_MODELS_CACHE: List[str] = []
AI_BUDGET_SECONDS = int(os.environ.get("AI_BUDGET_SECONDS", "900"))  # budget global de la phase IA
_DEADLINE: Optional[float] = None


# ==============================================================================
# Appel Gemini
# ==============================================================================
def _model_rank(name: str) -> Tuple[float, int, int]:
    """Tri : version la plus haute d'abord, stable avant preview, Flash avant Flash-Lite."""
    m = re.search(r"(\d+(?:\.\d+)?)", name)
    version = float(m.group(1)) if m else 0.0
    return (-version, 1 if ("preview" in name or "exp" in name) else 0, 1 if "lite" in name else 0)


def get_flash_models() -> List[str]:
    """Liste les modèles Flash réellement accessibles avec la clé (ListModels)."""
    global _MODELS_CACHE
    if _MODELS_CACHE:
        return _MODELS_CACHE
    found: List[str] = []
    try:
        req = urllib.request.Request(f"{API_ROOT}/models?pageSize=200", headers={"x-goog-api-key": GEMINI_API_KEY})
        with urllib.request.urlopen(req, timeout=15) as resp:
            for m in json.loads(resp.read().decode("utf-8")).get("models", []):
                name = m.get("name", "").replace("models/", "")
                if ("generateContent" in m.get("supportedGenerationMethods", []) and "flash" in name
                        and not any(x in name for x in ("tts", "image", "live", "audio", "embedding", "thinking"))):
                    found.append(name)
    except urllib.error.HTTPError as e:
        print(f"[GEMINI] ListModels HTTP {e.code} : {e.read().decode('utf-8', 'ignore')[:300]}")
    except Exception as e:
        print(f"[GEMINI] ListModels impossible : {e}")
    aliases = [n for n in found if n.endswith("-latest")]
    versioned = sorted((n for n in found if not n.endswith("-latest")), key=_model_rank)
    _MODELS_CACHE = (versioned + aliases) or FALLBACK_MODELS
    print(f"[GEMINI] Modèles Flash disponibles (ordre d'essai) : {_MODELS_CACHE[:5]}")
    return _MODELS_CACHE


def call_gemini_flash(system_instruction: str, user_prompt: str, temperature: float = 0.4,
                      response_mime_type: str = "text/plain") -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY absente.")
    if _DEADLINE and time.monotonic() > _DEADLINE:
        raise RuntimeError("budget de temps IA épuisé")
    last_err = "aucun modèle"
    for model in get_flash_models()[:2]:
        payload = {
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {"temperature": temperature, "responseMimeType": response_mime_type},
        }
        req = urllib.request.Request(
            f"{API_ROOT}/models/{model}:generateContent",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY},
            method="POST",
        )
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=75) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                cand = (body.get("candidates") or [{}])[0]
                parts = cand.get("content", {}).get("parts", [])
                text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
                if not text:
                    raise RuntimeError(f"réponse vide (finishReason={cand.get('finishReason')}, "
                                       f"promptFeedback={body.get('promptFeedback')})")
                return text
            except urllib.error.HTTPError as e:
                last_err = f"{model} HTTP {e.code} : {e.read().decode('utf-8', 'ignore')[:300]}"
                print(f"[GEMINI] {last_err}")
                if e.code in (429, 500, 503) and attempt == 0:
                    time.sleep(8)
                    continue
                break
            except Exception as e:
                last_err = f"{model} : {e}"
                print(f"[GEMINI] {last_err}")
                break
    raise RuntimeError(f"Échec Gemini ({last_err})")


# ==============================================================================
# Dossier de match factuel
# ==============================================================================
KEY_MOMENT_RE = re.compile(
    r"^(Goal!|Own Goal|Attempt saved|Attempt missed|Attempt blocked|Penalty|VAR|Second yellow|"
    r"Dismissal|Red card)|hits the (bar|left post|right post|post)|misses the|saves", re.I)


def _side_names(card: Dict[str, Any]) -> Dict[str, str]:
    return {"home": card["home_team"]["name"], "away": card["away_team"]["name"]}


def _minute_of(label: str) -> int:
    nums = re.findall(r"\d+", label or "")
    return int(nums[0]) if nums else 0


def halftime_score(goals: List[Dict[str, Any]]) -> str:
    h = sum(1 for g in goals if g["team"] == "home" and _minute_of(g["minute"]) <= 45)
    a = sum(1 for g in goals if g["team"] == "away" and _minute_of(g["minute"]) <= 45)
    return f"{h}-{a}"


def goals_complete(card: Dict[str, Any]) -> bool:
    """Vrai si la liste des buts correspond exactement au score officiel."""
    goals = card.get("goals", [])
    final = f"{card['home_team']['score']}-{card['away_team']['score']}"
    return (goals[-1]["score_after"] == final) if goals else final == "0-0"


def dominance_phases(momentum: List[Dict[str, Any]], names: Dict[str, str]) -> List[str]:
    """Résumé par quart d'heure : qui a eu le plus d'actions offensives (tirs, corners...)."""
    if not momentum or "home" not in momentum[0]:
        return []
    out = []
    windows = [(0, 15), (15, 30), (30, 45), (45, 60), (60, 75), (75, 200)]
    for lo, hi in windows:
        pts = [p for p in momentum if lo < p["minute"] <= hi]
        h = sum(p["home"] for p in pts)
        a = sum(p["away"] for p in pts)
        label = f"{lo + 1}'-{hi if hi < 200 else 'fin'}'"
        if h + a < 2:
            verdict = "peu d'actions offensives"
        elif h >= 1.8 * max(a, 0.5):
            verdict = f"temps fort de {names['home']}"
        elif a >= 1.8 * max(h, 0.5):
            verdict = f"temps fort de {names['away']}"
        else:
            verdict = "équilibré"
        out.append(f"{label} : {verdict}")
    return out


def key_moments(comments: List[str], limit: int = 60) -> List[str]:
    kept = [c for c in comments if KEY_MOMENT_RE.search(c.split("] ", 1)[-1])]
    return kept[:limit]


def named_stats(stats: List[Dict[str, Any]], names: Dict[str, str]) -> Dict[str, Dict[str, Any]]:
    return {s["label"]: {names["home"]: s["home"], names["away"]: s["away"]} for s in stats}


ACTION_FR = {
    "GOAL": "But", "SHOT_ON_GOAL": "Tir cadré", "SHOT_WIDE": "Tir non cadré", "SHOT_BLOCKED": "Tir contré",
    "SAVE": "Arrêt", "VAR": "Intervention VAR", "RED_CARD": "Carton rouge", "YELLOW_CARD": "Carton jaune",
    "SUBSTITUTION": "Remplacement", "PENALTY_MISSED": "Penalty manqué", "OFFSIDE": "Hors-jeu",
}
NOISE_ACTIONS = {"FOUL", "FREE_KICK", "CORNER", "OFFSIDE", "THROW_IN", "GOAL_KICK"}


def official_actions(match: Dict[str, Any], names: Dict[str, str], limit: int = 150) -> List[str]:
    """Actions officielles UEFA lisibles : « 23' — Tir cadré : X (Équipe) »."""
    out = []
    for a in match.get("actions", []):
        if a["type"] in NOISE_ACTIONS:
            continue
        label = ACTION_FR.get(a["type"], a["type"].replace("_", " ").lower())
        team = names.get(a.get("team") or "", "")
        who = a.get("player") or ""
        txt = f"{a['minute']} — {label} : {who}" + (f" ({team})" if team else "")
        if a["type"] == "SUBSTITUTION" and a.get("other"):
            txt = f"{a['minute']} — Remplacement ({team}) : {a['other']} remplace {who}"
        out.append(txt)
    return out[:limit]


def standout_players(match: Dict[str, Any], names: Dict[str, str]) -> List[Dict[str, Any]]:
    """Joueurs aux statistiques marquantes (buts, passes déc., tirs, passes clés, arrêts)."""
    players = []
    lu = match.get("lineups") or {}
    for side in ("home", "away"):
        for p in (lu.get(side) or []) + (lu.get(f"{side}_subs") or []):
            st = p.get("stats") or {}
            score = (st.get("buts", 0) * 5 + st.get("passes_dec", 0) * 4 + st.get("arrets", 0) * 1.5
                     + st.get("tirs_cadres", 0) * 1.5 + st.get("passes_cles", 0) + st.get("tirs", 0) * 0.5)
            if score >= 3 or p.get("potm"):
                players.append((score, {"joueur": p.get("name"), "equipe": names[side],
                                        "homme_du_match": bool(p.get("potm")), **st}))
    players.sort(key=lambda x: -x[0])
    return [p for _, p in players[:8]]


def build_match_dossier(comp_name: str, card: Dict[str, Any], match: Dict[str, Any],
                        standings_row: Dict[str, Any]) -> Dict[str, Any]:
    names = _side_names(card)
    goals = card.get("goals", [])
    comments = card.get("raw_comments_for_llm", [])
    return {
        "competition": comp_name,
        "journee": match.get("matchday", ""),
        "club_suivi": card["club_name"],
        "domicile": names["home"],
        "exterieur": names["away"],
        "stade": match.get("venue", ""),
        "affluence": match.get("attendance"),
        "score_final": f"{names['home']} {card['home_team']['score']} - {card['away_team']['score']} {names['away']}",
        "score_mi_temps": halftime_score(goals) if goals_complete(card) else None,
        "tirs_au_but": match.get("penalties") or None,
        "buts": [{"minute": g["minute"], "buteur": g["scorer"], "passeur": g.get("assist"),
                  "equipe": names[g["team"]], "type": {"pen": "penalty", "csc": "contre son camp"}.get(g.get("kind"), ""),
                  "score_apres": g["score_after"]} for g in goals],
        "homme_du_match": match.get("player_of_match") or None,
        "joueurs_en_vue": standout_players(match, names),
        "phases_de_domination": dominance_phases(match.get("momentum", []), names),
        "actions_officielles_uefa": official_actions(match, names),
        "statistiques": named_stats(match.get("stats", {}).get("all", []), names),
        "statistiques_par_mi_temps": {
            "1re": named_stats(match.get("stats", {}).get("1st", []), names),
            "2e": named_stats(match.get("stats", {}).get("2nd", []), names),
        },
        "fil_commentaires_espn_en_anglais": key_moments(comments),
        "classement_apres_match": {k: standings_row.get(k) for k in ("rank", "points", "played", "won", "drawn", "lost", "gd", "zone")}
        if standings_row else None,
    }


# ==============================================================================
# Agent 1 : rédacteur
# ==============================================================================
WRITER_SYSTEM_PROMPT = """Tu es journaliste sportif pour un quotidien français. Tu écris le compte rendu d'un match européen d'un club français, en 4 à 5 phrases, dans un français vivant et précis.

CE QUE TU DOIS RACONTER : le DÉROULÉ du match, pas une fiche technique.
- Phrase 1 : le résultat et ce qui a caractérisé la rencontre (qui a dominé, comment).
- Phrases 2-3 : le récit chronologique — l'entame et la première période, le score à la pause, ce qui change en seconde période, le tournant (but, occasion manquée, arrêt décisif, expulsion, temps fort, entrée d'un remplaçant). Appuie-toi sur `actions_officielles_uefa`, `phases_de_domination`, `statistiques_par_mi_temps`, `joueurs_en_vue` et le fil ESPN.
- Phrase 4 (et éventuellement 5) : la conséquence au classement, en UNE phrase courte.

INTERDIT :
- énumérer les buts sous forme de liste (« buts de X (9'), Y (12'), Z (50') ») ; intègre-les au récit, au besoin en n'en citant que les plus importants ;
- toute phrase commençant par « Score final vérifié » ou « Chronologie des buts » ;
- tout chiffre, nom ou minute absent du dossier ; n'invente ni ambiance, ni blessure, ni déclaration.

Le fil ESPN est en anglais : traduis-le naturellement. En cas de désaccord entre le fil ESPN et les données UEFA, les données UEFA font foi.
Réponds uniquement avec le texte du résumé."""


def run_writer_agent(dossier: Dict[str, Any], correction: str = "") -> str:
    prompt = "DOSSIER DU MATCH (seule source autorisée) :\n" + json.dumps(dossier, ensure_ascii=False, indent=1)
    if correction:
        prompt += "\n\nTA VERSION PRÉCÉDENTE A ÉTÉ REJETÉE PAR LE CONTRÔLEUR POUR CES RAISONS :\n" + correction
        prompt += "\nRéécris le résumé en corrigeant ces points."
    return call_gemini_flash(WRITER_SYSTEM_PROMPT, prompt, temperature=0.5)


# ==============================================================================
# Agent 2 : contrôleur
# ==============================================================================
AUDITOR_SYSTEM_PROMPT = """Tu es le contrôleur qualité d'une rédaction sportive. Tu compares un résumé de match à son dossier factuel.

Réponds UNIQUEMENT avec un objet JSON : {"is_valid": true|false, "issues": "explication courte et précise de chaque erreur"}

Rejette (is_valid=false) si :
1. un score, un vainqueur, une minute, un buteur, un passeur ou un joueur cité est absent du dossier (buts, actions_officielles_uefa, joueurs_en_vue, fil ESPN) ou le contredit ;
2. une statistique chiffrée contredit `statistiques`, `statistiques_par_mi_temps` ou `joueurs_en_vue` ;
3. le rang, les points ou la zone contredisent `classement_apres_match` ;
4. le texte affirme un fait précis introuvable dans le dossier (blessure, déclaration, record...) ;
5. le texte n'est qu'une liste de buts et de classement, sans récit du déroulé.

N'objecte PAS au style, aux traductions des moments du fil, ni aux formulations interprétatives raisonnables (« a dominé », « a souffert », « temps fort ») cohérentes avec `phases_de_domination`, les statistiques ou le fil."""


def run_auditor_agent(summary: str, dossier: Dict[str, Any]) -> Tuple[bool, str]:
    prompt = ("DOSSIER :\n" + json.dumps(dossier, ensure_ascii=False) + "\n\nRÉSUMÉ À CONTRÔLER :\n" + summary)
    raw = call_gemini_flash(AUDITOR_SYSTEM_PROMPT, prompt, temperature=0.0, response_mime_type="application/json")
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    parsed = json.loads(raw)
    return bool(parsed.get("is_valid", False)), str(parsed.get("issues", ""))


# ==============================================================================
# Résumé narratif déterministe (sans IA)
# ==============================================================================
def _pl(n: Any, word: str) -> str:
    return f"{n} {word}{'s' if isinstance(n, (int, float)) and n > 1 else ''}"


def build_deterministic_fallback_summary(card: Dict[str, Any], match: Dict[str, Any],
                                         standings_row: Dict[str, Any]) -> str:
    names = _side_names(card)
    club = card["club_name"]
    is_home = names["home"] == club
    me, opp = ("home", "away") if is_home else ("away", "home")
    sc = {"home": card["home_team"]["score"], "away": card["away_team"]["score"]}
    goals = card.get("goals", [])
    score_txt = f"{sc['home']}-{sc['away']}"
    where = f"face à {names[opp]}" if is_home else f"sur la pelouse de {names[opp]}"
    stats = {s["key"]: s for s in match.get("stats", {}).get("all", [])}

    if sc[me] > sc[opp]:
        s1 = f"{club} s'impose {where} ({score_txt})"
    elif sc[me] < sc[opp]:
        s1 = f"{club} s'incline {where} ({score_txt})"
    else:
        s1 = f"{club} fait match nul {where} ({score_txt})"
    if "ball_possession" in stats and "attempts" in stats:
        poss = str(stats["ball_possession"][me]).replace(".", ",")
        shots_me, shots_opp = stats["attempts"][me], stats["attempts"][opp]
        s1 += f", avec {poss} % de possession et {_pl(shots_me, 'tir')} contre {shots_opp}."
    else:
        s1 += "."

    complete = goals_complete(card)  # sinon, on ne raconte pas la chronologie des buts
    ht = halftime_score(goals)
    first = [g for g in goals if _minute_of(g["minute"]) <= 45]
    second = [g for g in goals if _minute_of(g["minute"]) > 45]
    phases = dominance_phases(match.get("momentum", []), names)

    def goal_phrase(gs: List[Dict[str, Any]]) -> str:
        bits = []
        for g in gs:
            who = f"{g['scorer']} ({g['minute']}{', sur penalty' if g.get('kind') == 'pen' else ''}"
            who += ", contre son camp)" if g.get("kind") == "csc" else ")"
            bits.append(who)
        return ", puis ".join(bits) if len(bits) <= 2 else ", ".join(bits[:-1]) + " et " + bits[-1]

    if not complete:
        s2 = ""
    elif first:
        s2 = f"En première période, {goal_phrase(first)} {'fait' if len(first) == 1 else 'font'} évoluer le score, {ht} à la pause."
    else:
        dom1 = [p for p in phases[:3] if "temps fort" in p]
        s2 = "Aucun but n'est inscrit avant la pause" + (f" malgré un {dom1[0].split(' : ')[1]}" if dom1 else "") + "."

    reds = [e for e in match.get("events", []) if e["type"] == "red_card"]
    if not complete:
        s3 = "Le détail des buts n'est pas disponible"
    elif second:
        s3 = f"Après le repos, {goal_phrase(second)} {'trouve' if len(second) == 1 else 'trouvent'} le chemin des filets"
    else:
        s3 = "La seconde période ne change rien au tableau d'affichage"
    if reds:
        r = reds[0]
        s3 += f", marquée par l'expulsion de {r['player']} ({names[r['team']]}, {r.get('minute_label', r['minute'])})"
    s3 += "."

    potm = match.get("player_of_match")
    if potm:
        s3 += f" {potm} est désigné homme du match par l'UEFA."
    s4 = ""
    rank = card.get("club_rank") or (standings_row or {}).get("rank")
    if rank:
        zone = card.get("club_zone") or standings_row.get("zone")
        zone_txt = {"top8": "dans le top 8 qualificatif pour les 8es de finale",
                    "playoff": "en zone de barrages (9e-24e)"}.get(zone, "en zone d'élimination (25e-36e)")
        rank_txt = "1er" if rank == 1 else f"{rank}e"
        pts = (standings_row or {}).get("points")
        s4 = f"Au classement, {club} est {rank_txt}{f' avec {pts} points' if pts is not None else ''}, {zone_txt}."
    return " ".join(x for x in (s1, s2, s3, s4) if x)


# ==============================================================================
# Agent 3 : texte de la notification
# ==============================================================================
NOTIF_SYSTEM_PROMPT = """Tu rédiges le texte d'une notification push envoyée après une soirée de Coupes d'Europe.
- Une seule phrase, 140 caractères maximum.
- Pour chaque club français : Victoire, Nul ou Défaite et le score exact fourni.
- Termine par « classements à jour »."""


def run_notif_agent(lines: List[str]) -> str:
    if not lines:
        return "Résultats de la soirée européenne et classements mis à jour."
    fallback = " | ".join(lines) + " — classements à jour."
    if not GEMINI_API_KEY:
        return fallback
    try:
        text = call_gemini_flash(NOTIF_SYSTEM_PROMPT, "Résultats :\n" + "\n".join(lines), temperature=0.2)
        return text.replace("\n", " ").strip()
    except Exception:
        return fallback


# ==============================================================================
# Orchestration
# ==============================================================================
def summarize_card(comp_name: str, card: Dict[str, Any], match: Dict[str, Any],
                   standings_row: Dict[str, Any], max_attempts: int = 3) -> Optional[str]:
    dossier = build_match_dossier(comp_name, card, match, standings_row)
    feedback = ""
    for attempt in range(1, max_attempts + 1):
        t0 = time.monotonic()
        print(f"[RÉDACTEUR] {card['club_name']} — tentative {attempt}")
        candidate = run_writer_agent(dossier, feedback)
        ok, issues = run_auditor_agent(candidate, dossier)
        print(f"    ({time.monotonic() - t0:.0f} s)")
        if ok:
            print(f"[CONTRÔLEUR OK] {card['club_name']}")
            return candidate
        print(f"[CONTRÔLEUR REJET] {card['club_name']} : {issues}\n    Texte rejeté : {candidate}")
        feedback = issues
    return None


def orchestrate_flash_agents(input_path: str = "data_raw.json", output_path: str = "data.json") -> Dict[str, Any]:
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not data.get("notification", {}).get("match_night", False):
        print("[INFO] Pas de soirée européenne à traiter.")
        return data
    if not GEMINI_API_KEY:
        print("[INFO] GEMINI_API_KEY absente : résumés déterministes.")
    global _DEADLINE
    _DEADLINE = time.monotonic() + AI_BUDGET_SECONDS

    recap: List[str] = []
    for comp in data.get("competitions", {}).values():
        matches = {m["match_id"]: m for m in comp.get("matches", [])}
        standings = {s.get("team_id") or s["team"].lower(): s for s in comp.get("standings", [])}
        for card in comp.get("french_clubs_focus", []):
            match = matches.get(card["match_id"], {})
            row = standings.get(card.get("club_id")) or standings.get(card["club_name"].lower(), {})
            h, a = card["home_team"], card["away_team"]
            line = f"{h['short']} {h['score']}-{a['score']} {a['short']}"
            if line not in recap:
                recap.append(line)

            text = None
            if GEMINI_API_KEY:
                try:
                    text = summarize_card(comp.get("name", ""), card, match, row)
                except Exception as e:
                    print(f"[WARN] Agents Gemini indisponibles pour {card['club_name']} : {e}")
            if text:
                card["summary_source"] = "gemini"
            else:
                print(f"[REPLI] Résumé déterministe pour {card['club_name']}.")
                text = build_deterministic_fallback_summary(card, match, row)
                card["summary_source"] = "deterministe"
            card["ai_summary"] = text
            card["ai_verified"] = True
            card.pop("raw_comments_for_llm", None)

    for comp in data.get("competitions", {}).values():
        for m in comp.get("matches", []):
            m.pop("actions", None)  # matière première de l'IA, inutile côté dashboard
    data["notification"]["summary"] = run_notif_agent(recap)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[OK] Résumés terminés -> {output_path}")
    return data


if __name__ == "__main__":
    orchestrate_flash_agents()
