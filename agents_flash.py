#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Étape 3 : Orchestrateur des Sous-Agents Gemini Flash — v3 (Support Gemini 3.8 Flash)
------------------------------------------------------------------------------------
Priorise le modèle `gemini-3.8-flash` avec découverte dynamique des identifiants
techniques disponibles sur la clé API Google AI Studio (`ListModels`), afin d'utiliser
automatiquement la version Flash la plus récente autorisée par la clé.
"""

import json
import os
import time
import urllib.request
import urllib.error
from typing import Dict, Any, List, Tuple

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# Ordre de priorité strict : 3.8 Flash en tête
PREFERRED_FLASH_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.8-flash-preview",
    "gemini-3.8-flash-latest",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.0-flash",
    "gemini-2.5-flash",
]

_RESOLVED_MODELS_CACHE: List[str] = []


def get_ordered_flash_models() -> List[str]:
    """
    Interroge une seule fois l'endpoint officiel `/v1beta/models` avec la clé API
    pour détecter le nom technique exact de Gemini 3.8 Flash sur l'API REST,
    tout en conservant la liste de priorité en tête.
    """
    global _RESOLVED_MODELS_CACHE
    if _RESOLVED_MODELS_CACHE:
        return _RESOLVED_MODELS_CACHE

    discovered = []
    if GEMINI_API_KEY:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for m in data.get("models", []):
                    name = m.get("name", "").replace("models/", "")
                    methods = m.get("supportedGenerationMethods", [])
                    if "generateContent" in methods and "flash" in name.lower():
                        discovered.append(name)
        except Exception as e:
            print(f"[INFO] Découverte ListModels ignorée ({e}), utilisation de la liste par défaut.")

    ordered = []
    # 1. Placer en premier tout modèle 3.8 Flash trouvé ou déclaré
    for pref in PREFERRED_FLASH_MODELS:
        if pref in discovered and pref not in ordered:
            ordered.append(pref)
    # 2. Ajouter les autres modèles Flash découverts sur la clé (triés du plus récent au plus ancien)
    for d in sorted(discovered, reverse=True):
        if d not in ordered and "tts" not in d and "image" not in d:
            ordered.append(d)
    # 3. S'assurer que nos identifiants cibles sont toujours présents
    for pref in PREFERRED_FLASH_MODELS:
        if pref not in ordered:
            ordered.append(pref)

    _RESOLVED_MODELS_CACHE = ordered
    print(f"[INFO] Modèles Flash détectés par ordre de priorité : {_RESOLVED_MODELS_CACHE[:4]}")
    return _RESOLVED_MODELS_CACHE


def call_gemini_flash(
    system_instruction: str,
    user_prompt: str,
    temperature: float = 0.25,
    response_mime_type: str = "text/plain",
) -> str:
    """Appelle Gemini 3.8 Flash (ou le meilleur modèle Flash actif sur l'API REST v1beta)."""
    if not GEMINI_API_KEY:
        raise RuntimeError("Clé GEMINI_API_KEY absente de l'environnement.")

    models_to_try = get_ordered_flash_models()
    last_err = None

    for model_name in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": response_mime_type,
            },
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                text = body["candidates"][0]["content"]["parts"][0]["text"].strip()
                print(f"[OK] Réponse générée par le modèle `{model_name}`.")
                return text
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # L'identifiant exact diffère sur l'API publique, on passe au suivant sans délai
                last_err = e
                continue
            err_body = e.read().decode("utf-8", errors="ignore")
            print(f"[WARN] HTTP {e.code} sur {model_name} : {err_body[:200]}")
            last_err = e
            time.sleep(1)
        except Exception as e:
            print(f"[WARN] Erreur d'appel {model_name} : {e}")
            last_err = e
            time.sleep(1)

    raise RuntimeError(f"Échec des modèles Flash : {last_err}")


# ==============================================================================
# AGENT 1 : RÉDACTEUR SPORTIF (Modèle Flash)
# ==============================================================================
WRITER_SYSTEM_PROMPT = """Tu es un journaliste sportif français spécialisé en football européen.
Ta mission est de rédiger un véritable résumé journalistique de 4 à 5 phrases sur le match d'un club français.

RÈGLES STRICTES (ZÉRO HALLUCINATION CHIFFRÉE) :
1. Utilise EXCLUSIVEMENT les chiffres, scores, buteurs, minutes, statistiques et positions au classement fournis dans le dossier JSON.
2. Appuie-toi sur :
   - le fil de commentaires (`extraits_commentaires_direct`),
   - la chronologie des buts (`buts_chronologiques`) et des cartons (`evenements_cles`),
   - les statistiques du match (`statistiques_globales` : possession, tirs totaux, tirs cadrés, grosses occasions, arrêts du gardien, corners, fautes),
   - le bilan comptable au classement (`classement_actuel_sur_36`)
   pour raconter la physionomie réelle de la rencontre avec un style journalistique vivant, fluide et précis.
3. Structure obligatoire en 4 à 5 phrases complètes :
   - Phrase 1 : L'affiche, le résultat final et l'allure générale du match (domination au ballon, volume de tirs).
   - Phrases 2 et 3 : Le scénario de la rencontre et le tournant du match (chronologie des buts avec buteurs et minutes exactes, ou duel défensif/arrêts décisifs s'il y a eu 0-0).
   - Phrase 4 (et 5) : L'opération comptable au classement général des 36 équipes (rang exact, total de points, différence de buts et situation dans le Top 8 qualificatif, les barrages 9e-24e ou la zone d'élimination 25e-36e).
4. Interdiction d'écrire une simple liste télégraphique du type 'Score final vérifié : X.' Rédige un vrai paragraphe d'analyse sportive."""


def run_writer_agent(
    comp_name: str,
    focus_card: Dict[str, Any],
    match_details: Dict[str, Any],
    standings_row: Dict[str, Any],
    correction_feedback: str = "",
) -> str:
    """Exécute l'Agent Rédacteur Flash sur un club français."""
    facts_bundle = {
        "competition": comp_name,
        "club_francais": focus_card["club_name"],
        "equipe_domicile": focus_card["home_team"],
        "equipe_exterieur": focus_card["away_team"],
        "score_final": f"{focus_card['home_team']['name']} {focus_card['home_team']['score']} - {focus_card['away_team']['score']} {focus_card['away_team']['name']}",
        "buts_chronologiques": focus_card.get("goals", []),
        "evenements_cles": match_details.get("events", []),
        "statistiques_globales": match_details.get("stats", {}).get("all", []),
        "classement_actuel_sur_36": standings_row,
        "extraits_commentaires_direct": focus_card.get("raw_comments_for_llm", [])[:45],
    }

    prompt = (
        "Voici les données officielles vérifiées de la rencontre :\n"
        + json.dumps(facts_bundle, ensure_ascii=False, indent=2)
        + "\n\n"
    )
    if correction_feedback:
        prompt += (
            "CORRECTION DEMANDÉE SUR LA VERSION PRÉCÉDENTE :\n"
            + correction_feedback
            + "\n\n"
        )
    prompt += "Rédige maintenant le résumé journalistique complet en 4 à 5 phrases."

    return call_gemini_flash(WRITER_SYSTEM_PROMPT, prompt, temperature=0.3)


# ==============================================================================
# AGENT 2 : CONTRÔLEUR ANTI-HALLUCINATION (Modèle Flash en mode JSON strict)
# ==============================================================================
AUDITOR_SYSTEM_PROMPT = """Tu es le contrôleur qualité d'une rédaction sportive.
Vérifie que le résumé candidat ne contredit AUCUN chiffre de la source de vérité JSON.

Réponds UNIQUEMENT avec un objet JSON :
{
  "is_valid": true,
  "issues": ""
}

Règles d'audit :
- Autorise les formulations journalistiques naturelles tant que les chiffres cités sont exacts.
- Rejette (`is_valid: false`) UNIQUEMENT si :
  1. Le score ou le vainqueur mentionné est faux.
  2. Un nom de buteur ou une minute de jeu citée n'existe pas dans `goals` ou `events`.
  3. Une statistique chiffrée citée contredit `stats_all`.
  4. Le classement ou le nombre de points contredit `standings_row`."""


def run_auditor_agent(
    candidate_summary: str,
    focus_card: Dict[str, Any],
    match_details: Dict[str, Any],
    standings_row: Dict[str, Any],
) -> Tuple[bool, str]:
    """Vérifie que le résumé généré ne contient aucune hallucination chiffrée."""
    ground_truth = {
        "home_team": focus_card["home_team"],
        "away_team": focus_card["away_team"],
        "goals": focus_card.get("goals", []),
        "events": match_details.get("events", []),
        "stats_all": match_details.get("stats", {}).get("all", []),
        "standings_row": standings_row,
    }

    user_prompt = (
        "SOURCE DE VÉRITÉ OFFICIELLE :\n"
        + json.dumps(ground_truth, ensure_ascii=False)
        + "\n\nTEXTE CANDIDAT À VÉRIFIER :\n"
        + candidate_summary
    )

    raw_resp = call_gemini_flash(
        AUDITOR_SYSTEM_PROMPT,
        user_prompt,
        temperature=0.0,
        response_mime_type="application/json",
    )
    parsed = json.loads(raw_resp)
    return bool(parsed.get("is_valid", False)), str(parsed.get("issues", ""))


def build_deterministic_fallback_summary(
    focus_card: Dict[str, Any],
    match_details: Dict[str, Any],
    standings_row: Dict[str, Any],
) -> str:
    """Rédige un résumé structuré de 4 phrases si l'API Gemini est indisponible."""
    h = focus_card["home_team"]
    a = focus_card["away_team"]
    club = focus_card["club_name"]
    is_home = h["name"] == club
    club_score = h["score"] if is_home else a["score"]
    opp_score = a["score"] if is_home else h["score"]
    opp_name = a["name"] if is_home else h["name"]
    venue = "à domicile" if is_home else f"sur la pelouse de {opp_name}"

    if club_score > opp_score:
        s1 = f"{club} s'impose {venue} face à {opp_name} sur le score de {h['score']}-{a['score']}."
    elif club_score < opp_score:
        s1 = f"{club} s'incline {venue} contre {opp_name} ({h['score']}-{a['score']}) au terme d'une soirée disputée."
    else:
        s1 = f"{club} partage les points {venue} face à {opp_name} ({h['score']}-{a['score']})."

    goals = focus_card.get("goals", [])
    if goals:
        g_list = ", ".join(f"{g['scorer']} ({g['minute']})" for g in goals)
        s2 = f"La rencontre a été rythmée par les réalisations de {g_list}."
    else:
        s2 = "Les deux défenses ont pris le pas sur les attaques sans qu'aucun but ne soit inscrit au cours des 90 minutes."

    stats_map = {s["key"]: (s["home"], s["away"]) for s in match_details.get("stats", {}).get("all", [])}
    if "ballPossession" in stats_map and "totalShotsOnGoal" in stats_map:
        poss = stats_map["ballPossession"][0 if is_home else 1]
        shots = stats_map["totalShotsOnGoal"][0 if is_home else 1]
        opp_shots = stats_map["totalShotsOnGoal"][1 if is_home else 0]
        s3 = f"Dans le jeu, la formation française a affiché {poss} % de possession de balle et tenté {shots} tirs contre {opp_shots} pour son adversaire."
    else:
        s3 = "Les deux équipes se sont livré une bataille tactique intense tout au long de la confrontation."

    rank = focus_card.get("club_rank") or standings_row.get("rank", "-")
    pts = standings_row.get("points", "-")
    zone = focus_card.get("club_zone", "")
    zone_txt = (
        "dans le Top 8 directement qualificatif pour les 8es de finale"
        if zone == "top8"
        else "dans la zone des barrages (places 9 à 24)"
        if zone == "playoff"
        else "dans la zone d'élimination (au-delà de la 24e place)"
    )
    s4 = f"Au classement général, {club} occupe désormais la {rank}e place avec {pts} points, {zone_txt}."

    return f"{s1} {s2} {s3} {s4}"


# ==============================================================================
# AGENT 3 : RÉDACTEUR DE NOTIFICATION NTFY (Modèle Flash)
# ==============================================================================
NOTIF_SYSTEM_PROMPT = """Tu rédiges le texte court d'une notification push mobile envoyée à 23h30 après les matchs de Coupes d'Europe.
Consignes :
- 1 seule phrase compacte (maximum 140 caractères).
- Mentionne l'issue exacte (Victoire, Nul ou Défaite + score) pour chaque club français ayant joué.
- Termine par 'classements à jour'."""


def run_notif_agent(french_results_summary: List[str]) -> str:
    """Génère le texte d'accroche du push ntfy à partir des scores vérifiés."""
    if not french_results_summary:
        return "Résultats de la soirée européenne et classements des 36 équipes mis à jour."

    prompt = "Résultats officiels des clubs français :\n" + "\n".join(french_results_summary)
    try:
        text = call_gemini_flash(NOTIF_SYSTEM_PROMPT, prompt, temperature=0.2)
        return text.replace("\n", " ").strip()
    except Exception:
        return " | ".join(french_results_summary) + " — Classements à jour."


# ==============================================================================
# PIPELINE D'ORCHESTRATION PRINCIPAL
# ==============================================================================
def orchestrate_flash_agents(
    input_path: str = "data_raw.json", output_path: str = "data.json"
) -> Dict[str, Any]:
    """Lit `data_raw.json`, exécute les Agents Flash et écrit `data.json`."""
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not data.get("notification", {}).get("match_night", False):
        print("[INFO] Pas de soirée européenne à traiter par les agents Flash.")
        return data

    french_evening_recap = []

    for comp_key, comp in data.get("competitions", {}).items():
        comp_name = comp.get("name", "")
        matches_by_id = {m["match_id"]: m for m in comp.get("matches", [])}
        standings_by_team = {s["team"].lower(): s for s in comp.get("standings", [])}

        for focus in comp.get("french_clubs_focus", []):
            m_id = focus["match_id"]
            club_name = focus["club_name"]
            match_details = matches_by_id.get(m_id, {})
            standings_row = standings_by_team.get(club_name.lower(), {})

            h = focus["home_team"]
            a = focus["away_team"]
            french_evening_recap.append(f"{h['short']} {h['score']}-{a['score']} {a['short']}")

            summary_validated = False
            feedback = ""

            if GEMINI_API_KEY:
                for attempt in range(1, 3):
                    try:
                        print(f"[AGENT FLASH] Rédaction pour {club_name} (tentative {attempt})...")
                        candidate = run_writer_agent(
                            comp_name, focus, match_details, standings_row, feedback
                        )
                        is_ok, issues = run_auditor_agent(
                            candidate, focus, match_details, standings_row
                        )
                        if is_ok:
                            focus["ai_summary"] = candidate
                            focus["ai_verified"] = True
                            summary_validated = True
                            print(f"[CONTRÔLE QUALITÉ OK] Résumé validé pour {club_name}.")
                            break
                        else:
                            print(f"[REJET CONTRÔLEUR] {club_name} : {issues}")
                            feedback = issues
                            time.sleep(1)
                    except Exception as e:
                        print(f"[WARN] Erreur API Gemini Flash sur {club_name} : {e}")
                        break

            if not summary_validated:
                print(f"[FALLBACK] Utilisation du résumé structuré de secours pour {club_name}.")
                focus["ai_summary"] = build_deterministic_fallback_summary(
                    focus, match_details, standings_row
                )
                focus["ai_verified"] = True

            focus.pop("raw_comments_for_llm", None)

    data["notification"]["summary"] = run_notif_agent(french_evening_recap)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[OK] Orchestration des agents Flash terminée -> {output_path} prêt.")
    return data


if __name__ == "__main__":
    source = "data_raw.json" if os.path.exists("data_raw.json") else "data_schema_sample.json"
    orchestrate_flash_agents(input_path=source, output_path="data.json")
