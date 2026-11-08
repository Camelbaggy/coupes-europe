#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Accès HTTP commun (requêtes JSON ordinaires, avec reprises) et petits utilitaires."""

import gzip
import json
import os
import time
import unicodedata
import urllib.error
import urllib.request
from typing import Any, Optional

HEADERS = {
    "User-Agent": "coupes-europe-dashboard/1.0 (+https://github.com/Camelbaggy/coupes-europe)",
    "Accept": "application/json",
}

_RAW_DIR: Optional[str] = None


def set_raw_dir(path: Optional[str]) -> None:
    """Si défini, chaque réponse JSON est aussi sauvegardée dans ce dossier (debug)."""
    global _RAW_DIR
    if path:
        os.makedirs(path, exist_ok=True)
    _RAW_DIR = path


def fetch_json(url: str, retries: int = 3, raw_name: str = "") -> Optional[Any]:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read()
                if body[:2] == b"\x1f\x8b":
                    body = gzip.decompress(body)
                data = json.loads(body.decode("utf-8"))
            if _RAW_DIR and raw_name:
                with open(os.path.join(_RAW_DIR, raw_name), "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
            return data
        except urllib.error.HTTPError as e:
            print(f"[WARN] HTTP {e.code} sur {url}")
            if e.code in (400, 404):
                return None
        except Exception as e:
            print(f"[WARN] Erreur réseau sur {url} : {e}")
        time.sleep(2 ** attempt)
    return None


def normalize(name: str) -> str:
    txt = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    return " ".join(txt.lower().replace(".", " ").split())


def fr(translations: Any, key: str, default: str = "") -> str:
    """Valeur française d'un champ `translations` UEFA ({"name": {"FR": ..., "EN": ...}})."""
    val = ((translations or {}).get(key) or {})
    if isinstance(val, dict):
        return val.get("FR") or val.get("EN") or default
    return val or default


def to_number(val: Any) -> Any:
    try:
        f = float(str(val).replace("%", "").strip())
    except (TypeError, ValueError):
        return None
    return int(f) if f.is_integer() else round(f, 1)
