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


if __name__ == "__main__":
    send_ntfy_notification()
