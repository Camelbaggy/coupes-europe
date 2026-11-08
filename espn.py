#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Source complémentaire ESPN : fil de commentaires texte (Opta, en anglais) des matchs.
Sert uniquement de matière première pour le récit des agents Gemini.
"""

import re
from typing import Any, Dict, List, Optional

from netutil import fetch_json, normalize

ESPN_SITE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
ESPN_SLUGS = {"ucl": "uefa.champions", "uel": "uefa.europa", "uecl": "uefa.europa.conf"}

_SCOREBOARDS: Dict[str, List[Dict[str, Any]]] = {}


def _clock_label(display: str) -> str:
    nums = [int(n) for n in re.findall(r"\d+", display or "")]
    if not nums:
        return ""
    return f"{nums[0]}'+{nums[1]}" if len(nums) > 1 else f"{nums[0]}'"


def _sort_key(display: str) -> float:
    nums = [int(n) for n in re.findall(r"\d+", display or "")]
    return (nums[0] + (nums[1] / 100 if len(nums) > 1 else 0)) if nums else 0.0


def _scoreboard(comp_key: str, ymd: str) -> List[Dict[str, Any]]:
    key = f"{comp_key}_{ymd}"
    if key not in _SCOREBOARDS:
        data = fetch_json(f"{ESPN_SITE}/{ESPN_SLUGS[comp_key]}/scoreboard?dates={ymd}",
                          raw_name=f"espn_scoreboard_{key}.json") or {}
        _SCOREBOARDS[key] = data.get("events", []) or []
    return _SCOREBOARDS[key]


def _words(*names: str) -> set:
    out = set()
    for n in names:
        out |= {w for w in normalize(n).replace("/", " ").replace("-", " ").split() if len(w) > 2}
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
