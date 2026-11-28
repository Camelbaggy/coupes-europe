#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Notification push légère via ntfy.sh.
Utilise la publication JSON de ntfy (POST sur la racine du serveur) : les accents et
apostrophes du titre passent sans souci, contrairement aux en-têtes HTTP.
"""

import json
import os
import urllib.error
import urllib.request

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "").strip()


def send_ntfy_notification(data_path: str = "data.json", force_test: bool = False) -> bool:
    if not os.path.exists(data_path):
        print(f"[WARN] {data_path} introuvable. Aucune notification envoyée.")
        return False

    with open(data_path, "r", encoding="utf-8") as f:
        notif = json.load(f).get("notification", {})

    if not notif.get("match_night", False) and not force_test:
        print("[INFO] Aucun match ce soir. Pas de push ntfy.")
        return False

    payload = {
        "topic": NTFY_TOPIC,
        "title": notif.get("title") or "Coupes d'Europe : Résultats et classements à jour",
        "message": notif.get("summary") or "Résultats et classements mis à jour.",
        "tags": ["soccer", "trophy"],
    }
    if DASHBOARD_URL:
        payload["click"] = DASHBOARD_URL
        payload["actions"] = [{"action": "view", "label": "Ouvrir le dashboard", "url": DASHBOARD_URL, "clear": True}]

    if not NTFY_TOPIC:
        print("[INFO] NTFY_TOPIC non défini. Simulation du push :")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return False

    return _poster(payload)


def _poster(payload) -> bool:
    req = urllib.request.Request(
        NTFY_SERVER,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"[OK] Push ntfy envoyé (HTTP {resp.status}).")
            return True
    except urllib.error.URLError as e:
        print(f"[ERREUR] Échec de l'envoi ntfy : {e}")
        return False


def send_ntfy_alert(titre: str, message: str, click: str = "") -> bool:
    """Alerte d'échec de publication : priorité haute, tag d'alerte, lien vers le run Actions. Sans NTFY_TOPIC : simulation."""
    payload = {"topic": NTFY_TOPIC, "title": titre, "message": message, "priority": 4,
               "tags": ["rotating_light", "warning"]}
    if click:
        payload["click"] = click
        payload["actions"] = [{"action": "view", "label": "Ouvrir le run", "url": click, "clear": True}]
    if not NTFY_TOPIC:
        print("[INFO] NTFY_TOPIC non défini. Simulation de l'alerte :")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return False
    return _poster(payload)


def build_football_webhook_event(
    event_key: str,
    event_type: str,
    title: str,
    body: str,
    spoiler_safe_title: str = "",
    spoiler_safe_body: str = "",
    match_id: str = "",
    competition: str = "ucl",
    home_name: str = "",
    away_name: str = "",
    home_country: str = "",
    away_country: str = "",
    phase: str = "poules",
) -> dict:
    """Construit un événement Football conforme au contrat ingest-event de Sport Hub."""
    mid = str(match_id).strip() if match_id is not None else ""
    comp = (competition or "ucl").strip().lower()
    h_name = (home_name or "").strip()
    a_name = (away_name or "").strip()
    h_country = (home_country or "").strip().upper()
    a_country = (away_country or "").strip().upper()
    raw_phase = (phase or "").strip().lower()
    norm_phase = "finale" if any(
        k in raw_phase for k in ("finale", "final", "knockout", "quart", "demi", "huit", "barrage", "playoff")
    ) else "poules"
    teams = [
        {"name": n, "country": c}
        for n, c in ((h_name, h_country), (a_name, a_country))
        if n or c
    ]
    equipe = [n for n in (h_name, a_name) if n]
    return {
        "event_key": event_key,
        "sport": "football",
        "event_type": event_type,
        "title": title,
        "body": body,
        "spoiler_safe_title": spoiler_safe_title or title,
        "spoiler_safe_body": spoiler_safe_body or body,
        "deep_link": f"sporthub://football/match/{mid}" if mid else "sporthub://football",
        "is_live": event_type in ("kickoff", "goal", "goal_cancelled"),
        "attributes": {
            "competition": comp,
            "teams": teams,
            "equipe": equipe,
            "phase": norm_phase,
        },
    }


def send_app_webhooks(events: list[dict]) -> bool:
    """Envoie les événements vers Sport Hub si configuré. 100 % optionnel et non-bloquant."""
    try:
        url = os.environ.get("APP_WEBHOOK_URL", "").strip()
        secret = os.environ.get("APP_WEBHOOK_SECRET", "").strip()
        if not url or not secret or not events:
            return False
        req = urllib.request.Request(
            url,
            data=json.dumps({"events": events}, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Secret": secret,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"[WEBHOOK] {len(events)} événement(s) envoyé(s) (HTTP {resp.status}).")
            return True
    except Exception as e:
        print(f"[WEBHOOK] Échec non-bloquant : {e}")
        return False


if __name__ == "__main__":
    send_ntfy_notification()
