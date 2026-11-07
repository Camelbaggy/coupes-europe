#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Étape 3 : Orchestrateur des Sous-Agents Gemini Flash
----------------------------------------------------
Coordonne 3 agents spécialisés utilisant le modèle `gemini-2.5-flash` :
1. Agent Rédacteur : Rédige le résumé (4-5 phrases) pour chaque club français.
2. Agent Contrôleur (Fact-Checker) : Vérifie l'absence totale d'hallucination chiffrée.
3. Agent Notification : Génère l'accroche ultra-concise pour le push `ntfy` de 23h30.

Sécurité supplémentaire : Si l'API Gemini est indisponible ou si le contrôleur rejette
deux fois un texte, un générateur déterministe de secours prend le relais.
"""

import json
import os
import time
import urllib.request
import urllib.error
from typing import Dict, Any, List, Tuple

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_ENDPOINT = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
)


def call_gemini_flash(
    system_instruction: str,
    user_prompt: str,
    temperature: float = 0.2,
    response_mime_type: str = "text/plain",
) -> str:
    """Appelle le modèle Gemini Flash via l'API REST standard (sans dépendance lourde)."""
    if not GEMINI_API_KEY:
        raise RuntimeError("Clé GEMINI_API_KEY absente de l'environnement.")

    url = f"{GEMINI_ENDPOINT}?key={GEMINI_API_KEY}"
    payload = {
        "system_instruction": {"parts": [{"text": system_instruction}]},
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
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = json.loads(resp.read().decode("utf-8"))
        return body["candidates"][0]["content"]["parts"][0]["text"].strip()


# ==============================================================================
# AGENT 1 : RÉDACTEUR SPORTIF (Modèle Flash)
# ==============================================================================
WRITER_SYSTEM_PROMPT = """Tu es un journaliste sportif français spécialisé en football européen.
Ta mission est de rédiger un résumé synthétique de 4 à 5 phrases sur le match d'un club français.

RÈGLES STRICTES (ZÉRO HALLUCINATION) :
1. Utilise EXCLUSIVEMENT les chiffres, scores, buteurs, minutes, statistiques et positions au classement fournis dans le dossier JSON.
2. N'invente AUCUN prénom, AUCUNE minute de jeu, AUCUNE statistique et AUCUN passif qui ne figure pas dans les données fournies.
3. Structure obligatoire en 4 à 5 phrases :
   - Phrase 1 : Résultat final et physionomie générale (possession, tirs).
   - Phrases 2 et 3 : Déroulé des buts (buteurs et minutes exactes) et tournant du match (arrêt décisif, carton rouge, poussée au momentum ou occasion).
   - Phrase 4 (ou 5) : Impact comptable précis au classement (rang exact sur 36 et zone : Top 8 qualificatif, Barrages 9e-24e, ou zone d'élimination 25e-36e).
4. Ton sobre, factuel, fluide, sans jargon inutile ni superlatifs excessifs."""


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
        "score_final": f"{focus_card['home_team']['name']} {focus_card['home_team']['score']} - {focus_card['away_team']['score']} {focus_card['away_team']['name']}",
        "buts_chronologiques": focus_card.get("goals", []),
        "evenements_cles": match_details.get("events", []),
        "statistiques_globales": match_details.get("stats", {}).get("all", []),
        "classement_actuel_sur_36": standings_row,
        "extraits_commentaires_direct": focus_card.get("raw_comments_for_llm", [])[:40],
    }

    prompt = (
        "Voici les données officielles vérifiées du match :\n"
        + json.dumps(facts_bundle, ensure_ascii=False, indent=2)
        + "\n\n"
    )
    if correction_feedback:
        prompt += (
            "ATTENTION - CORRECTION EXIGÉE PAR LE CONTRÔLEUR QUALITÉ :\n"
            + correction_feedback
            + "\n\n"
        )
    prompt += "Rédige maintenant le résumé de 4 à 5 phrases."

    return call_gemini_flash(WRITER_SYSTEM_PROMPT, prompt, temperature=0.25)


# ==============================================================================
# AGENT 2 : CONTRÔLEUR ANTI-HALLUCINATION (Modèle Flash en mode JSON strict)
# ==============================================================================
AUDITOR_SYSTEM_PROMPT = """Tu es un contrôleur qualité implacable chargé de vérifier qu'un résumé de match ne contient aucune hallucination.
Compare chaque chiffre, score, nom de joueur, minute de but et place au classement cités dans le texte candidat avec la source de vérité JSON.

Réponds UNIQUEMENT avec un objet JSON respectant ce format exact :
{
  "is_valid": true,
  "issues": ""
}

Critères de rejet immédiat (is_valid = false) :
- Le score ou l'issue du match (victoire/nul/défaite) est erroné.
- Un buteur ou une minute de but ne correspond pas à la liste officielle.
- Une statistique citée (possession, tirs, arrêts) contredit les chiffres officiels.
- Le rang au classement ou le nombre de points est faux.
- Le texte fait moins de 3 phrases ou plus de 6 phrases."""


def run_auditor_agent(
    candidate_summary: str,
    focus_card: Dict[str, Any],
    match_details: Dict[str, Any],
    standings_row: Dict[str, Any],
) -> Tuple[bool, str]:
    """Vérifie que le résumé généré respecte à 100 % la vérité terrain."""
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
    focus_card: Dict[str, Any], standings_row: Dict[str, Any]
) -> str:
    """
    Filet de sécurité 100 % déterministe (sans IA) si la clé API est absente
    ou si l'Agent Contrôleur rejette le texte. Garantit que le dashboard est toujours complet.
    """
    h = focus_card["home_team"]
    a = focus_card["away_team"]
    goals = focus_card.get("goals", [])
    goals_txt = (
        ", ".join(f"{g['scorer']} ({g['minute']})" for g in goals)
        if goals
        else "aucun but inscrit"
    )
    rank = focus_card.get("club_rank") or standings_row.get("rank", "-")
    pts = standings_row.get("points", "-")
    return (
        f"Score final vérifié : {h['name']} {h['score']} - {a['score']} {a['name']}. "
        f"Chronologie des buts : {goals_txt}. "
        f"Au classement général de la compétition, {focus_card['club_name']} occupe la {rank}e place ({pts} pts)."
    )


# ==============================================================================
# AGENT 3 : RÉDACTEUR DE NOTIFICATION NTFY (Modèle Flash)
# ==============================================================================
NOTIF_SYSTEM_PROMPT = """Tu rédiges le texte court d'une notification push mobile envoyée à 23h30 après les matchs de Coupes d'Europe.
Consignes :
- 1 seule phrase compacte (maximum 140 caractères).
- Mentionne l'issue exacte (Victoire, Nul ou Défaite + score) pour chaque club français ayant joué ce soir.
- Termine par 'classements à jour'.
- Exemple : 'Victoire de Monaco (0-1), nul du PSG (1-1), classements à jour.'"""


def run_notif_agent(french_results_summary: List[str]) -> str:
    """Génère le texte d'accroche du push ntfy à partir des scores vérifiés."""
    if not french_results_summary:
        return "Résultats de la soirée européenne et classements des 36 équipes mis à jour."

    prompt = "Résultats officiels des clubs français ce soir :\n" + "\n".join(
        french_results_summary
    )
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
    """
    Lit `data_raw.json`, exécute les Agents Flash sur chaque club français,
    purge les commentaires bruts et écrit le fichier final `data.json`.
    """
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not data.get("notification", {}).get("match_night", False):
        print("[INFO] Pas de soirée européenne à traiter par les agents Flash.")
        return data

    french_evening_recap = []

    for comp_key, comp in data.get("competitions", {}).items():
        comp_name = comp.get("name", "")
        matches_by_id = {m["match_id"]: m for m in comp.get("matches", [])}
        standings_by_team = {s["team"]: s for s in comp.get("standings", [])}

        for focus in comp.get("french_clubs_focus", []):
            m_id = focus["match_id"]
            club_name = focus["club_name"]
            match_details = matches_by_id.get(m_id, {})
            standings_row = standings_by_team.get(club_name, {})

            h = focus["home_team"]
            a = focus["away_team"]
            french_evening_recap.append(f"{h['short']} {h['score']}-{a['score']} {a['short']}")

            # Si un résumé vérifié est déjà présent (ex: jeu de test), on le conserve si pas de clé API
            if focus.get("ai_summary") and focus.get("ai_verified") and not GEMINI_API_KEY:
                focus.pop("raw_comments_for_llm", None)
                continue

            summary_validated = False
            feedback = ""

            if GEMINI_API_KEY:
                for attempt in range(1, 3):  # Jusqu'à 2 tentatives avec boucle de rétroaction
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
                print(f"[FALLBACK] Utilisation du résumé déterministe pour {club_name}.")
                focus["ai_summary"] = build_deterministic_fallback_summary(focus, standings_row)
                focus["ai_verified"] = True

            # Purge obligatoire du fil de commentaires minute par minute (Contrainte 3.B.3 & 4.4)
            focus.pop("raw_comments_for_llm", None)

    # Génération du message push ntfy par le 3e Agent Flash
    if GEMINI_API_KEY or not data["notification"].get("summary"):
        data["notification"]["summary"] = run_notif_agent(french_evening_recap)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[OK] Orchestration des agents Flash terminée -> {output_path} prêt.")
    return data


if __name__ == "__main__":
    source = "data_raw.json" if os.path.exists("data_raw.json") else "data_schema_sample.json"
    orchestrate_flash_agents(input_path=source, output_path="data.json")
