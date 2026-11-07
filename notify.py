#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Étape 5 : Module de Notification Push Légère (ntfy.sh)
------------------------------------------------------
Envoie une alerte push à 23h30 uniquement si `notification.match_night` vaut True.
Inclut le titre, le résumé des clubs français et le bouton d'ouverture directe du Dashboard.
"""

import json
import os
import urllib.request
import urllib.error

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "https://TON-PSEUDO.github.io/coupes-europe/")


def send_ntfy_notification(data_path: str = "data.json", force_test: bool = False) -> bool:
    """Lit `data.json` et pousse l'alerte sur le canal ntfy configuré."""
    if not os.path.exists(data_path):
        print(f"[WARN] Fichier {data_path} introuvable. Aucune notification envoyée.")
        return False

    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    notif = data.get("notification", {})
    if not notif.get("match_night", False) and not force_test:
        print("[INFO] Aucun match ce soir (match_night=False). Pas de push ntfy.")
        return False

    if not NTFY_TOPIC:
        print("[INFO] Variable NTFY_TOPIC non définie. Simulation de l'envoi push :")
        print(f"  -> Titre   : {notif.get('title')}")
        print(f"  -> Message : {notif.get('summary')}")
        print(f"  -> Lien    : {DASHBOARD_URL}")
        return False

    url = f"{NTFY_SERVER}/{NTFY_TOPIC}"
    title = notif.get("title", "Coupes d'Europe : Résultats et classements à jour")
    summary = notif.get(
        "summary", "Résultats et classements des 36 équipes mis à jour."
    )

    headers = {
        "Title": title.encode("utf-8"),
        "Priority": "default",
        "Tags": "soccer,trophy,fr",
        "Click": DASHBOARD_URL,
        "Actions": f"view, Ouvrir le Dashboard, {DASHBOARD_URL}, clear=true".encode("utf-8"),
    }

    req = urllib.request.Request(
        url,
        data=summary.encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"[OK] Notification push ntfy envoyée (HTTP {resp.status}).")
            return True
    except urllib.error.URLError as e:
        print(f"[ERREUR] Échec de l'envoi ntfy : {e}")
        return False


if __name__ == "__main__":
    send_ntfy_notification()
