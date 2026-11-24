#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
État par soirée de matchs (etat_soirees.json, racine du dépôt, commité avec data.json par update_dashboard.yml).

  {"AAAA-MM-JJ": {"statut": "complet" | "partiel" | "aucun_match", "notifie": bool,
                  "maj": "horodatage UTC", "matchs": n, "termines": n}}

- complet      : au moins un match et tous les matchs européens de la soirée sont terminés ;
- partiel      : des matchs non terminés, ou données UEFA incomplètes (liste de matchs illisible) ;
- aucun_match  : aucun match européen ce jour-là.

Une seule notification ntfy par soirée (`doit_notifier`). Lu aussi par .github/scripts/veille.sh (battement).
Fonctions pures + lecture/écriture JSON ; tests : `python soirees.py --test`.
"""

import datetime as dt
import json
import os
import sys

FICHIER = "etat_soirees.json"
GARDE_JOURS = 60
# Au-delà de ce délai (12 h UTC le lendemain), une soirée encore partielle est notifiée quand même, une fois.
HEURE_LIMITE_PARTIEL = 12


def statut_soiree(matchs, termines, incomplet=False):
    """Statut d'une soirée d'après le nombre de matchs, de matchs terminés et un drapeau de données incomplètes."""
    if incomplet:
        return "partiel"
    if matchs <= 0:
        return "aucun_match"
    return "complet" if termines >= matchs else "partiel"


def limite_partiel(jour):
    """Instant (UTC) à partir duquel une soirée partielle est notifiée quand même : 12 h UTC le lendemain."""
    d = dt.date.fromisoformat(jour) + dt.timedelta(days=1)
    return dt.datetime(d.year, d.month, d.day, HEURE_LIMITE_PARTIEL, tzinfo=dt.timezone.utc)


def doit_notifier(statut, notifie, jour, maintenant, renotifier=False):
    """Faut-il envoyer le push ntfy de la soirée `jour` ? (`maintenant` : datetime UTC conscient.)"""
    if statut == "aucun_match":
        return False
    if renotifier:
        return True
    if notifie:
        return False
    if statut == "complet":
        return True
    return maintenant >= limite_partiel(jour)  # partiel : seulement une fois la limite dépassée


def deja_traitee(etat, jour, dates_data_json):
    """Passage inutile : soirée complète, notifiée, et déjà présente dans data.json (économie de Gemini)."""
    e = (etat or {}).get(jour) or {}
    return e.get("statut") == "complet" and bool(e.get("notifie")) and jour in (dates_data_json or [])


def a_notifier_sans_collecte(etat, jour, dates_data_json):
    """Soirée complète déjà dans data.json mais pas encore notifiée (publication ou push ntfy échoué) : inutile de
    recollecter ni de relancer Gemini, il suffit de retenter la vérification de publication + la notification."""
    e = (etat or {}).get(jour) or {}
    return e.get("statut") == "complet" and not e.get("notifie") and jour in (dates_data_json or [])


def doit_alerter(etat_jour, cause):
    """Alerte d'échec de publication : une seule par soirée et par cause (`alertes` de l'état), jamais pour une soirée
    sans match. Soirée absente de l'état (échec avant son écriture) : on alerte, un échec est un échec."""
    if (etat_jour or {}).get("statut") == "aucun_match":
        return False
    return cause not in ((etat_jour or {}).get("alertes") or {})


def marquer_alerte(etat, jour, cause, maintenant, chemin=FICHIER):
    """Mémorise l'alerte `cause` pour `jour` (entrée créée « partiel » si la soirée n'a pas encore d'état)."""
    e = etat.get(jour) or {"statut": "partiel", "notifie": False, "matchs": 0, "termines": 0}
    e = dict(e)
    e["alertes"] = dict(e.get("alertes") or {}, **{cause: maintenant.strftime("%Y-%m-%dT%H:%M:%SZ")})
    etat[jour] = e
    etat = purger(etat, maintenant)
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(etat.items())), f, ensure_ascii=False, indent=2)
        f.write("\n")
    return etat


def charger(chemin=FICHIER):
    try:
        with open(chemin, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def purger(etat, maintenant, garde_jours=GARDE_JOURS):
    seuil = (maintenant.date() - dt.timedelta(days=garde_jours)).isoformat()
    return {j: v for j, v in etat.items() if j >= seuil}


def enregistrer(etat, jour, statut, matchs, termines, maintenant, notifie=None, chemin=FICHIER):
    """Met à jour la soirée `jour` (notifie inchangé si None), purge les vieilles entrées, écrit le fichier trié."""
    ancien = etat.get(jour) or {}
    alertes = ancien.get("alertes")
    etat[jour] = {
        "statut": statut,
        "notifie": bool(ancien.get("notifie")) if notifie is None else bool(notifie),
        "maj": maintenant.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "matchs": int(matchs),
        "termines": int(termines),
    }
    if alertes:
        etat[jour]["alertes"] = alertes
    etat = purger(etat, maintenant)
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(etat.items())), f, ensure_ascii=False, indent=2)
        f.write("\n")
    return etat


def _test():
    import tempfile
    U = dt.timezone.utc
    t = lambda *a: dt.datetime(*a, tzinfo=U)
    assert statut_soiree(0, 0) == "aucun_match"
    assert statut_soiree(7, 7) == "complet"
    assert statut_soiree(7, 3) == "partiel"
    assert statut_soiree(7, 0) == "partiel"
    assert statut_soiree(0, 0, incomplet=True) == "partiel"   # liste UEFA illisible : jamais « aucun match »
    assert statut_soiree(7, 7, incomplet=True) == "partiel"
    J = "2026-11-24"
    # complet non notifié -> envoie ; déjà notifié -> rien
    assert doit_notifier("complet", False, J, t(2026, 11, 24, 23, 0)) is True
    assert doit_notifier("complet", True, J, t(2026, 11, 25, 3, 0)) is False
    # partiel avant 12 h le lendemain -> rien ; après -> envoie une fois
    assert doit_notifier("partiel", False, J, t(2026, 11, 25, 11, 59)) is False
    assert doit_notifier("partiel", False, J, t(2026, 11, 25, 12, 0)) is True
    assert doit_notifier("partiel", True, J, t(2026, 11, 25, 13, 0)) is False
    # aucun_match -> rien, même forcé
    assert doit_notifier("aucun_match", False, J, t(2026, 11, 25, 15, 0)) is False
    assert doit_notifier("aucun_match", False, J, t(2026, 11, 25, 15, 0), renotifier=True) is False
    # --renotifier force
    assert doit_notifier("complet", True, J, t(2026, 11, 25, 15, 0), renotifier=True) is True
    assert doit_notifier("partiel", False, J, t(2026, 11, 24, 23, 0), renotifier=True) is True
    # économie
    etat = {J: {"statut": "complet", "notifie": True}}
    assert deja_traitee(etat, J, [J]) is True
    assert deja_traitee(etat, J, ["2026-11-23"]) is False
    assert deja_traitee(etat, J, []) is False
    assert deja_traitee({J: {"statut": "complet", "notifie": False}}, J, [J]) is False
    assert deja_traitee({J: {"statut": "partiel", "notifie": False}}, J, [J]) is False
    assert deja_traitee({}, J, [J]) is False
    assert a_notifier_sans_collecte({J: {"statut": "complet", "notifie": False}}, J, [J]) is True
    assert a_notifier_sans_collecte({J: {"statut": "complet", "notifie": False}}, J, []) is False
    assert a_notifier_sans_collecte({J: {"statut": "complet", "notifie": True}}, J, [J]) is False
    assert a_notifier_sans_collecte({J: {"statut": "partiel", "notifie": False}}, J, [J]) is False
    # fichier : écriture, notifie conservé, purge à 60 jours
    with tempfile.TemporaryDirectory() as d:
        ch = os.path.join(d, "e.json")
        e = {"2026-01-01": {"statut": "complet", "notifie": True}}
        e = enregistrer(e, J, "partiel", 7, 3, t(2026, 11, 24, 23, 0), chemin=ch)
        assert "2026-01-01" not in e and e[J]["notifie"] is False
        e = enregistrer(e, J, "complet", 7, 7, t(2026, 11, 25, 0, 0), notifie=True, chemin=ch)
        e = enregistrer(e, J, "complet", 7, 7, t(2026, 11, 25, 1, 0), chemin=ch)
        lu = charger(ch)
        assert lu[J]["notifie"] is True and lu[J]["statut"] == "complet" and lu[J]["termines"] == 7
    # alertes : une par cause, pas pour aucun_match, conservées par enregistrer
    with tempfile.TemporaryDirectory() as d:
        ch = os.path.join(d, "e.json")
        assert doit_alerter(None, "push") is True
        assert doit_alerter({"statut": "aucun_match"}, "push") is False
        e = {J: {"statut": "complet", "notifie": False, "matchs": 7, "termines": 7}}
        assert doit_alerter(e[J], "push") is True
        e = marquer_alerte(e, J, "push", t(2026, 11, 25, 1, 0), chemin=ch)
        assert doit_alerter(e[J], "push") is False and doit_alerter(e[J], "page_non_a_jour") is True
        e = enregistrer(e, J, "complet", 7, 7, t(2026, 11, 25, 2, 0), chemin=ch)
        assert "push" in charger(ch)[J]["alertes"] and doit_alerter(charger(ch)[J], "push") is False
        e = marquer_alerte(e, "2026-12-01", "collecte", t(2026, 12, 2, 1, 0), chemin=ch)
        assert e["2026-12-01"]["statut"] == "partiel" and doit_alerter(e["2026-12-01"], "collecte") is False
    assert charger("/inexistant/etat.json") == {}
    print("[OK] soirees.py : tests réussis")


if __name__ == "__main__":
    if "--test" in sys.argv:
        _test()
