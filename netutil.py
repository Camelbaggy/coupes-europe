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


# Code pays FIFA/UEFA -> code drapeau flagcdn.com (ISO 3166-1 ; sous-divisions pour le Royaume-Uni).
# Les 55 fédérations UEFA + les nationalités les plus fréquentes hors d'Europe.
FLAG_CODES = {
    "ALB": "al", "AND": "ad", "ARM": "am", "AUT": "at", "AZE": "az", "BLR": "by", "BEL": "be", "BIH": "ba",
    "BUL": "bg", "CRO": "hr", "CYP": "cy", "CZE": "cz", "DEN": "dk", "ENG": "gb-eng", "EST": "ee", "FRO": "fo",
    "FIN": "fi", "FRA": "fr", "GEO": "ge", "GER": "de", "GIB": "gi", "GRE": "gr", "HUN": "hu", "ISL": "is",
    "IRL": "ie", "ISR": "il", "ITA": "it", "KAZ": "kz", "KOS": "xk", "LVA": "lv", "LIE": "li", "LTU": "lt",
    "LUX": "lu", "MLT": "mt", "MDA": "md", "MNE": "me", "NED": "nl", "MKD": "mk", "NIR": "gb-nir", "NOR": "no",
    "POL": "pl", "POR": "pt", "ROU": "ro", "RUS": "ru", "SMR": "sm", "SCO": "gb-sct", "SRB": "rs", "SVK": "sk",
    "SVN": "si", "ESP": "es", "SWE": "se", "SUI": "ch", "TUR": "tr", "UKR": "ua", "WAL": "gb-wls", "MON": "mc",
    # Amériques
    "ARG": "ar", "BRA": "br", "URU": "uy", "PAR": "py", "CHI": "cl", "COL": "co", "ECU": "ec", "PER": "pe",
    "VEN": "ve", "BOL": "bo", "MEX": "mx", "USA": "us", "CAN": "ca", "JAM": "jm", "CRC": "cr", "HON": "hn",
    "PAN": "pa", "HAI": "ht", "SUR": "sr", "CUW": "cw", "GUA": "gt", "SLV": "sv", "TRI": "tt", "DOM": "do",
    "CUB": "cu", "GRN": "gd", "MTQ": "mq", "GLP": "gp", "GUF": "gf",
    # Afrique
    "MAR": "ma", "ALG": "dz", "TUN": "tn", "EGY": "eg", "LBY": "ly", "SEN": "sn", "CIV": "ci", "CMR": "cm",
    "NGA": "ng", "GHA": "gh", "MLI": "ml", "BFA": "bf", "GUI": "gn", "COD": "cd", "CGO": "cg", "GAB": "ga",
    "GAM": "gm", "CPV": "cv", "ZAM": "zm", "ZIM": "zw", "RSA": "za", "ANG": "ao", "MOZ": "mz", "KEN": "ke",
    "TOG": "tg", "BEN": "bj", "NIG": "ne", "GNB": "gw", "SLE": "sl", "LBR": "lr", "MTN": "mr", "MAD": "mg",
    "COM": "km", "CTA": "cf", "EQG": "gq", "BDI": "bi", "RWA": "rw", "TAN": "tz", "UGA": "ug", "ETH": "et",
    "SUD": "sd", "MWI": "mw", "NAM": "na", "BOT": "bw",
    # Asie / Océanie
    "JPN": "jp", "KOR": "kr", "CHN": "cn", "AUS": "au", "NZL": "nz", "IRN": "ir", "IRQ": "iq", "KSA": "sa",
    "QAT": "qa", "UAE": "ae", "UZB": "uz", "JOR": "jo", "SYR": "sy", "LBN": "lb", "PLE": "ps", "IND": "in",
    "IDN": "id", "THA": "th", "VIE": "vn", "PHI": "ph", "KGZ": "kg", "TJK": "tj", "TKM": "tm",
}
