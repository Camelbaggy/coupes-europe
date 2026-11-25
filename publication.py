#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Notification ntfy APRÈS publication vérifiée : le push ne part que lorsqu'on est SÛR que la page publiée est à jour.

`python run_pipeline.py --notifier [AAAA-MM-JJ]` (appelé par update_dashboard.yml après un push réussi) :
  (a) origin/main contient un data.json au moins aussi récent que le local et contenant la soirée ;
  (b) la page publique (`<DASHBOARD_URL>/data.json?t=…`) est à jour : `last_updated` >= celui du data.json local
      ET la soirée figure dans ses `target_dates` ; sondée toutes les 20 s, 10 min au plus ;
  (c) seulement alors, règle de `soirees.doit_notifier` puis envoi du push ;
  (d) la soirée passe à `notifie: true` dans etat_soirees.json (publié ensuite par le workflow).
Page non à jour au bout du délai : aucun push, `notifie` reste faux, sortie en erreur (le battement relance).

Fonctions pures (`url_donnees`, `donnees_a_jour`, `decider`) + I/O injectables ; tests : `python publication.py --test`.
"""

import datetime as dt
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import soirees

PAS_S = 20
DELAI_MAX_S = 600


def url_donnees(dashboard_url, horodatage):
    """URL de data.json à côté de la page (index.html retiré), avec ?t=<horodatage> contre le cache. '' si pas d'URL."""
    base = (dashboard_url or "").strip().split("#")[0].split("?")[0]
    if not base:
        return ""
    if base.endswith("index.html"):
        base = base[: -len("index.html")]
    if not base.endswith("/"):
        base += "/"
    return f"{base}data.json?t={horodatage}"


def donnees_a_jour(distant, local, jour):
    """(ok, raison) : `distant` (data.json publié) est-il au moins aussi récent que `local` et contient-il la soirée ?"""
    if not isinstance(distant, dict):
        return False, "data.json distant illisible ou absent"
    if not isinstance(local, dict) or not local.get("last_updated"):
        return False, "data.json local sans last_updated"
    d = distant.get("last_updated")
    if not d:
        return False, "data.json distant sans last_updated"
    # horodatages ISO 'AAAA-MM-JJTHH:MM:SSZ' : l'ordre lexicographique est l'ordre chronologique
    if str(d) < str(local["last_updated"]):
        return False, f"last_updated distant {d} plus ancien que le local {local['last_updated']}"
    if jour not in (distant.get("target_dates") or []):
        return False, f"soirée {jour} absente de target_dates distant {distant.get('target_dates')}"
    return True, f"last_updated {d} >= {local['last_updated']}, soirée {jour} présente"


def decider(etat_jour, local, jour, maintenant, renotifier=False):
    """('notifier' | 'rien', raison) d'après l'état de la soirée et le data.json local."""
    if not etat_jour:
        return "rien", f"aucun état pour la soirée {jour}"
    if jour not in ((local or {}).get("target_dates") or []):
        return "rien", f"la soirée {jour} n'est pas dans data.json (rien à notifier)"
    if soirees.doit_notifier(etat_jour.get("statut"), bool(etat_jour.get("notifie")), jour, maintenant, renotifier):
        return "notifier", f"soirée {jour} ({etat_jour.get('statut')}) à notifier"
    return "rien", (f"pas de push pour la soirée {jour} ({etat_jour.get('statut')}, "
                    f"{'déjà notifiée' if etat_jour.get('notifie') else 'en attente'})")


def attendre_page(dashboard_url, local, jour, fetch, sleep=time.sleep, horloge=time.monotonic,
                  pas_s=PAS_S, delai_max_s=DELAI_MAX_S):
    """Sonde la page publique jusqu'à ce qu'elle soit à jour. (ok, raison de la dernière tentative)."""
    debut = horloge()
    raison = "aucune tentative"
    while True:
        url = url_donnees(dashboard_url, int(time.time() * 1000))
        ok, raison = donnees_a_jour(fetch(url), local, jour)
        print(f"[PUBLICATION] page publique : {'à jour' if ok else 'pas à jour'} ({raison})")
        if ok:
            return True, raison
        if horloge() - debut + pas_s > delai_max_s:
            return False, raison
        sleep(pas_s)


def fetch_http(url):
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache", "Pragma": "no-cache",
                                               "User-Agent": "coupes-europe-publication"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(f"[PUBLICATION] lecture de la page impossible : {e}")
        return None


def lire_origin(branche=None, chemin="data.json"):
    """data.json tel que publié sur origin/<branche> (après git fetch), ou None."""
    branche = branche or os.environ.get("GITHUB_REF_NAME") or "main"
    try:
        subprocess.run(["git", "fetch", "-q", "origin", branche], check=True, timeout=120)
        sortie = subprocess.run(["git", "show", f"origin/{branche}:{chemin}"], check=True, capture_output=True,
                                timeout=60).stdout
        return json.loads(sortie.decode("utf-8"))
    except (subprocess.SubprocessError, OSError, ValueError) as e:
        print(f"[PUBLICATION] lecture de origin/{branche}:{chemin} impossible : {e}")
        return None


def _lire_json(chemin):
    try:
        with open(chemin, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def notifier(jour, renotifier=False, maintenant=None, data_chemin="data.json", etat_chemin=soirees.FICHIER,
             dashboard_url=None, topic=None, origin=None, fetch=None, sleep=time.sleep, horloge=time.monotonic,
             envoyer=None, pas_s=PAS_S, delai_max_s=DELAI_MAX_S):
    """Vérifie la publication puis notifie. Retourne le code de sortie (0 = rien à faire ou notifié, 1 = erreur)."""
    import notify
    maintenant = maintenant or dt.datetime.now(dt.timezone.utc)
    dashboard_url = notify.DASHBOARD_URL if dashboard_url is None else dashboard_url
    topic = notify.NTFY_TOPIC if topic is None else topic
    origin = origin or lire_origin
    fetch = fetch or fetch_http
    envoyer = envoyer or (lambda: notify.send_ntfy_notification(data_path=data_chemin))

    etat = soirees.charger(etat_chemin)
    local = _lire_json(data_chemin)
    if not etat.get(jour):
        print(f"[ERREUR] Aucun état pour la soirée {jour} dans {etat_chemin} : notification impossible.")
        return 1
    action, raison = decider(etat.get(jour), local, jour, maintenant, renotifier)
    print(f"[PUBLICATION] {raison}")
    if action != "notifier":
        return 0

    ok, raison = donnees_a_jour(origin(), local, jour)
    if not ok:
        print(f"[ERREUR] origin ne contient pas encore data.json de la soirée {jour} : {raison}. Pas de push.")
        return 1
    print(f"[PUBLICATION] origin à jour ({raison})")

    if not dashboard_url:
        if topic:
            print("[ERREUR] DASHBOARD_URL absent : impossible de vérifier la page publique, pas de push.")
            return 1
        print("[WARN] DASHBOARD_URL absent (simulation, pas de NTFY_TOPIC) : vérification de la page ignorée.")
    else:
        ok, raison = attendre_page(dashboard_url, local, jour, fetch, sleep, horloge, pas_s, delai_max_s)
        if not ok:
            print(f"[ERREUR] Page publique non à jour après {delai_max_s // 60} min ({raison}) : pas de push, "
                  "la soirée reste non notifiée (le battement relancera).")
            return 1

    envoye = envoyer()
    # sans NTFY_TOPIC (simulation), on marque quand même : sinon le battement relancerait à vide
    if not envoye and topic:
        print("[ERREUR] Échec de l'envoi ntfy : la soirée reste non notifiée.")
        return 1
    e = etat[jour]
    soirees.enregistrer(etat, jour, e.get("statut"), e.get("matchs", 0), e.get("termines", 0), maintenant,
                        notifie=True, chemin=etat_chemin)
    print(f"[OK] Soirée {jour} marquée notifiée dans {etat_chemin}.")
    return 0


ETAPES = {
    "collecte": "Collecte et résumés (étape pipeline)",
    "push": "Publication git : push de data.json en échec après 5 essais",
    "page_non_a_jour": "Vérification de publication : page publique non à jour, ou notification en échec",
    "workflow": "Workflow : étape préparatoire ou inattendue en échec (voir le run)",
}


def alerter(jour, cause, url_run="", maintenant=None, etat_chemin=soirees.FICHIER, envoyer=None):
    """Alerte ntfy d'échec de publication, une seule par soirée et par cause (mémorisée dans etat_soirees.json,
    publié ensuite en tentative best-effort par le workflow). Retourne toujours 0 : une alerte ne doit pas échouer."""
    import notify
    maintenant = maintenant or dt.datetime.now(dt.timezone.utc)
    envoyer = envoyer or notify.send_ntfy_alert
    etat = soirees.charger(etat_chemin)
    if not soirees.doit_alerter(etat.get(jour), cause):
        print(f"[ALERTE] Soirée {jour}, cause « {cause} » : pas d'alerte (sans match ou déjà alertée).")
        return 0
    etape = ETAPES.get(cause, cause)
    message = f"Soirée : {jour}\nÉtape en cause : {etape}\nLien du run : {url_run or '(inconnu)'}"
    if envoyer("Échec de mise à jour Coupes d'Europe", message, url_run):
        soirees.marquer_alerte(etat, jour, cause, maintenant, chemin=etat_chemin)
        print(f"[ALERTE] Alerte « {cause} » envoyée pour la soirée {jour} et mémorisée.")
    return 0


def url_run_actions():
    e = os.environ
    if e.get("GITHUB_SERVER_URL") and e.get("GITHUB_REPOSITORY") and e.get("GITHUB_RUN_ID"):
        return f"{e['GITHUB_SERVER_URL']}/{e['GITHUB_REPOSITORY']}/actions/runs/{e['GITHUB_RUN_ID']}"
    return ""


def _test():
    import tempfile
    U = dt.timezone.utc
    J = "2026-11-24"
    assert url_donnees("https://x.github.io/coupes/index.html", 5) == "https://x.github.io/coupes/data.json?t=5"
    assert url_donnees("https://x.github.io/coupes", 5) == "https://x.github.io/coupes/data.json?t=5"
    assert url_donnees("https://x.github.io/coupes/?a=1#b", 5) == "https://x.github.io/coupes/data.json?t=5"
    assert url_donnees("", 5) == ""
    loc = {"last_updated": "2026-11-25T01:00:00Z", "target_dates": [J]}
    # à jour (égal, plus récent), pas à jour, sans la soirée, plus ancien, illisible
    assert donnees_a_jour(dict(loc), loc, J)[0] is True
    assert donnees_a_jour({"last_updated": "2026-11-25T01:05:00Z", "target_dates": [J, "x"]}, loc, J)[0] is True
    assert donnees_a_jour({"last_updated": "2026-11-25T00:59:59Z", "target_dates": [J]}, loc, J)[0] is False
    assert donnees_a_jour({"last_updated": "2026-11-25T01:00:00Z", "target_dates": ["2026-11-23"]}, loc, J)[0] is False
    assert donnees_a_jour({"last_updated": "2026-11-25T01:00:00Z"}, loc, J)[0] is False
    assert donnees_a_jour({"target_dates": [J]}, loc, J)[0] is False
    assert donnees_a_jour(None, loc, J)[0] is False
    assert donnees_a_jour(loc, {"target_dates": [J]}, J)[0] is False
    # décision
    t = dt.datetime(2026, 11, 25, 1, 0, tzinfo=U)
    comp = {"statut": "complet", "notifie": False}
    assert decider(comp, loc, J, t)[0] == "notifier"
    assert decider({"statut": "complet", "notifie": True}, loc, J, t)[0] == "rien"
    assert decider({"statut": "complet", "notifie": True}, loc, J, t, True)[0] == "notifier"
    assert decider({"statut": "partiel", "notifie": False}, loc, J, t)[0] == "rien"
    assert decider({"statut": "partiel", "notifie": False}, loc, J, t.replace(hour=12))[0] == "notifier"
    assert decider({"statut": "aucun_match", "notifie": False}, loc, J, t, True)[0] == "rien"
    assert decider(comp, {"target_dates": ["autre"]}, J, t)[0] == "rien"
    assert decider(None, loc, J, t)[0] == "rien"

    # bout en bout avec fetch simulé
    with tempfile.TemporaryDirectory() as d:
        dc, ec = os.path.join(d, "data.json"), os.path.join(d, "etat.json")

        def prepare():
            with open(dc, "w", encoding="utf-8") as f:
                json.dump(loc, f)
            soirees.enregistrer({}, J, "complet", 7, 7, t, chemin=ec)

        envois = []
        pauses = []
        horloge = {"t": 0.0}

        def sleep(s):
            pauses.append(s)
            horloge["t"] += s

        def courant(reponses):
            it = iter(reponses)
            return lambda url: next(it, reponses[-1])

        kw = dict(maintenant=t, data_chemin=dc, etat_chemin=ec, dashboard_url="https://x/p/index.html", topic="t",
                  origin=lambda: dict(loc), sleep=sleep, horloge=lambda: horloge["t"],
                  envoyer=lambda: envois.append(1) or True)
        ancienne = {"last_updated": "2026-11-24T22:00:00Z", "target_dates": ["2026-11-23"]}
        # 1. page à jour au 3e essai -> push, notifie vrai
        prepare()
        assert notifier(J, fetch=courant([ancienne, None, loc]), **kw) == 0
        assert len(envois) == 1 and pauses == [20, 20] and soirees.charger(ec)[J]["notifie"] is True
        # 2. déjà notifiée -> aucun nouveau push
        assert notifier(J, fetch=courant([loc]), **kw) == 0 and len(envois) == 1
        # 3. page jamais à jour -> erreur, pas de push, notifie reste faux
        prepare(); pauses.clear(); horloge["t"] = 0.0
        assert notifier(J, fetch=courant([ancienne]), **kw) == 1
        assert len(envois) == 1 and soirees.charger(ec)[J]["notifie"] is False
        assert len(pauses) == DELAI_MAX_S // PAS_S  # sondes à 0, 20 ... 600 s
        # 4. origin sans la soirée -> erreur, la page n'est même pas sondée
        sonde = []
        k2 = dict(kw, origin=lambda: ancienne)
        assert notifier(J, fetch=lambda u: sonde.append(u) or loc, **k2) == 1 and not sonde and len(envois) == 1
        # 5. échec ntfy -> erreur, notifie reste faux
        k3 = dict(kw, envoyer=lambda: False)
        assert notifier(J, fetch=courant([loc]), **k3) == 1 and soirees.charger(ec)[J]["notifie"] is False
        # 6. DASHBOARD_URL absent : erreur avec topic, simulation sans topic
        k4 = dict(kw, dashboard_url="")
        assert notifier(J, fetch=courant([loc]), **k4) == 1
        assert notifier(J, fetch=courant([loc]), **dict(k4, topic="")) == 0
        assert soirees.charger(ec)[J]["notifie"] is True
        # 7. état absent
        assert notifier("2026-01-01", fetch=courant([loc]), **kw) == 1
        # 8. alertes : envoyée une fois par cause, nouvelle si la cause change, jamais sans match
        recus = []
        env = lambda titre, msg, click: recus.append((titre, msg, click)) or True
        soirees.enregistrer({}, J, "partiel", 7, 3, t, chemin=ec)
        assert alerter(J, "push", "https://run/1", t, ec, env) == 0 and len(recus) == 1
        assert recus[0][0] == "Échec de mise à jour Coupes d'Europe" and J in recus[0][1] and "https://run/1" in recus[0][1]
        alerter(J, "push", "https://run/2", t, ec, env); assert len(recus) == 1
        alerter(J, "page_non_a_jour", "https://run/3", t, ec, env); assert len(recus) == 2
        soirees.enregistrer({}, "2026-11-30", "aucun_match", 0, 0, t, chemin=ec)
        alerter("2026-11-30", "collecte", "", t, ec, env); assert len(recus) == 2
        alerter("2026-12-05", "collecte", "", t, ec, env); assert len(recus) == 3   # état absent : alerte
        alerter("2026-12-06", "push", "", t, ec, lambda *a: False)                 # envoi raté : non mémorisée
        assert soirees.doit_alerter(soirees.charger(ec).get("2026-12-06"), "push") is True
    print("[OK] publication.py : tests réussis")


if __name__ == "__main__":
    if "--test" in sys.argv:
        _test()
    else:
        sys.exit(notifier(sys.argv[1] if len(sys.argv) > 1 else dt.datetime.now(dt.timezone.utc).date().isoformat()))
