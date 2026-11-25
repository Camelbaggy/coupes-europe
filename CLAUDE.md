# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Projet

Dashboard mobile des soirées de Coupes d'Europe (LDC, Ligue Europa, Ligue Conférence) centré sur les clubs
français : collecte de données → résumés IA → `data.json` → page statique GitHub Pages → push ntfy.
Spécification fonctionnelle : `Projet_foot.md`. Tout est en français : interface, logs, messages de commit,
commentaires.

**Règle cardinale : zéro hallucination sur les chiffres.** Scores, buteurs, minutes, statistiques et classements
viennent uniquement des API. Les seules valeurs dérivées (momentum, stats par mi-temps, notes des joueurs) sont
calculées de façon déterministe et documentées. Un champ absent reste vide : on n'invente jamais de valeur de
substitution (une ancienne version simulait un momentum, c'est précisément ce qui est proscrit).

## Commandes

Python 3 bibliothèque standard uniquement (aucune dépendance) ; la CI tourne en **Python 3.11**, donc pas de
syntaxe 3.12+ (ex. guillemets identiques imbriqués dans une f-string).

```bash
python run_pipeline.py --date 2026-11-05 --no-notify   # une soirée, sans push ntfy
python run_pipeline.py --week --save-raw raw            # mardi→jeudi de la semaine courante, JSON bruts sauvegardés
python collector.py --date 2026-11-05                   # collecte seule -> data_raw.json
python agents_flash.py                                  # résumés seuls : data_raw.json -> data.json
python tools/inspect_data.py data.json                  # résumé lisible (notes, momentum, drapeaux manquants…)
python -m http.server 8000                              # voir index.html (il lit data.json via fetch)
python -m py_compile *.py tools/*.py                    # contrôle statique
python soirees.py --test && python publication.py --test && bash tools/test_veille.sh && python tools/verifier_workflows.py   # tests locaux : état / notification unique, veille.sh (faux gh), `bash -n` de chaque bloc `run:` des workflows
```

`AI_BUDGET_SECONDS=0` désactive tout appel Gemini (résumés de repli déterministes). Sans `GEMINI_API_KEY`, même
effet.

### Tester sur de vraies données

Les API (UEFA, ESPN, Gemini) sont joignables depuis GitHub Actions ; un environnement de développement peut ne pas
y avoir accès. Le workflow `test_pipeline.yml` rejoue tout le pipeline sur la semaine du 3 au 5 novembre 2026 (sans
push ntfy ni commit) quand un commit poussé sur une branche `ccr-*` contient `[test]` (avec Gemini) ou `[sans-ia]`
(sans Gemini, pour ne pas consommer le quota gratuit). Lire ensuite les logs du job : `tools/inspect_data.py` y
affiche les résultats. Pour découvrir la forme d'une réponse d'API inconnue, écrire une petite sonde dans `tools/` +
un workflow temporaire déclenché sur la branche, puis les supprimer.

## Architecture

```
run_pipeline.py ─┬─ collector.py ── uefa.py   (source principale, officielle)
                 │                ├ espn.py   (fil de commentaires texte, pour l'IA uniquement)
                 │                ├ ratings.py (notes des joueurs, appelée après la collecte, par compétition)
                 │                └ netutil.py (fetch_json avec reprises, normalize, fr(), to_number, FLAG_CODES)
                 ├─ agents_flash.py (dossier factuel → Gemini rédacteur → Gemini contrôleur, repli déterministe)
                 └─ notify.py (publication JSON ntfy)
index.html  : page unique (CSS + JS inline), lit data.json ; aucune étape de build
```

- `update_dashboard.yml` tourne mardi/mercredi/jeudi à 22h30 UTC (et le samedi en mai-juin pour la finale de LDC) et **commit `data.json` directement sur `main`** (GitHub retarde ce cron de plusieurs heures, passages réels vers 2 h-4 h UTC : sans `--date`, `run_pipeline.date_soiree_par_defaut` vise la soirée de la VEILLE avant 12 h UTC)
  (commits « chore: mise à jour automatique… »). Une branche de travail se retrouve donc vite derrière `main` ;
  ne pas committer `data.json` à la main.
- `data_raw.json` (sortie collecteur, avec `raw_comments_for_llm` et `matches[].actions`) n'est pas versionné ;
  `agents_flash` retire ces champs avant d'écrire `data.json`.

### Fiabilité des passages : état par soirée, notification unique, battement

GitHub retarde ou saute les crons ; plusieurs mécanismes garantissent une mise à jour sans intervention.
- **État par soirée** `etat_soirees.json` (racine, commité avec `data.json` par `update_dashboard.yml`, 60 jours gardés ; logique pure dans
  `soirees.py`) : `{"AAAA-MM-JJ": {statut, notifie, maj, matchs, termines}}`, `statut` = `complet` (≥ 1 match, tous terminés) / `partiel`
  (matchs non terminés ou liste UEFA illisible) / `aucun_match`. Écrit par `run_pipeline.py` à chaque passage, jamais avec `--week` ni
  `--no-notify`. Un état `complet` n'est écrit qu'après la réussite de `data.json`.
- **Notification après publication vérifiée** (`publication.py`, `python run_pipeline.py --notifier [SOIRÉE] [--renotifier]`) : `run_pipeline.py`
  ne notifie plus (hors `--week`) : il écrit `data.json` + `etat_soirees.json` (`notifie` inchangé, faux pour une nouvelle soirée). Le workflow
  enchaîne collecte -> `.github/scripts/publier.sh` (commit + push robuste, échec = job en échec, aucune notification) -> `--notifier`
  (`if: success()`) -> republication de `etat_soirees.json` (`publier.sh --etat-seul`). `--notifier` : (a) `origin/main:data.json` doit avoir un
  `last_updated` >= celui du local et la soirée dans `target_dates` ; (b) la page publique `<DASHBOARD_URL sans index.html>/data.json?t=…` est
  sondée toutes les 20 s pendant 10 min max jusqu'au même critère ; (c) seulement alors `soirees.doit_notifier` puis push ; (d) `notifie: true`.
  Page non à jour : pas de push, `notifie` reste faux, sortie en erreur (le battement relance). Sans `DASHBOARD_URL` : erreur si `NTFY_TOPIC`
  est défini, vérification ignorée en simulation. `--week` / `--no-notify` : ni état ni vérification. Les passages sur une soirée `complet` déjà
  dans `data.json` mais non notifiée sautent la collecte (`soirees.a_notifier_sans_collecte`, aucun Gemini) et vont à la vérification +
  notification. La soirée visée est calculée une seule fois par le workflow (étape `cible`) et passée à toutes les étapes.
- **Notification unique** : push ntfy seulement si la soirée est `complet` et non notifiée ; une soirée restée `partiel` est notifiée une fois
  à partir de 12 h UTC le lendemain ; `aucun_match` jamais ; `--renotifier` force. Un passage sur une soirée `complet` + notifiée + déjà dans
  `data.json` s'arrête avant toute collecte (sans Gemini) sauf `--forcer`. Sans `NTFY_TOPIC` (simulation), la soirée est marquée notifiée.
  Limite connue : si le push de l'état « notifié » échoue après l'envoi, le passage suivant renotifie (job en échec, alerte).
- **Alerte d'échec** (`python run_pipeline.py --alerte SOIRÉE --cause collecte|push|page_non_a_jour`, étape `if: failure()` du workflow, jamais pour
  `--week` ni une soirée `aucun_match`) : ntfy distinct « Échec de mise à jour Coupes d'Europe » (priorité 4, tag `rotating_light`) avec la soirée,
  l'étape en cause et le lien du run. Une seule alerte par soirée et par cause, mémorisée dans le champ `alertes` (`{cause: horodatage}`) de
  `etat_soirees.json` (`soirees.doit_alerter` / `marquer_alerte`, conservé par `enregistrer`) et publiée au mieux (`publier.sh --etat-seul || true`) ;
  une cause différente déclenche une nouvelle alerte. Tests : `python publication.py --test`.
- **Battement** `battement.yml` (dispatch seul, job ~330 min, se relance lui-même, groupe `battement` sans annulation, même modèle que
  courses-cyclistes) exécute toutes les 10 min `.github/scripts/veille.sh` : pour les soirées de match (mar-mer-jeu, samedi en mai-juin) entre
  22 h 15 UTC et 13 h UTC le lendemain, si `etat_soirees.json` (lu sur main via `gh api`) n'est pas `aucun_match` / notifié, qu'aucun passage
  d'`update_dashboard.yml` n'est en file ou en cours et que le dernier a démarré il y a ≥ 25 min :
  `gh workflow run update_dashboard.yml --ref main -f mode_test_semaine=false -f date_specifique=<soirée>`. Les scripts sont lus au
  démarrage d'un battement : après modification, relancer `battement.yml`. **Secours** : `veille_secours.yml` (cron horaire à :52) exécute le
  même `veille.sh` et relance `battement.yml` s'il ne tourne pas ; le cron 22 h 30 de `update_dashboard.yml` est conservé. Premier lancement
  (ou après arrêt) : `gh workflow run battement.yml --ref main`.

### Schéma de `data.json` (ce que lit `index.html`)

`competitions.{ucl,uel,uecl}` → `matches[]`, `standings[]` (36 lignes, `zone` = top8 / playoff / eliminated),
`french_clubs_focus[]` (une carte par club français, avec `ai_summary` et `summary_source`).
Chaque match : `home_team`/`away_team` (`flag`, `is_french`, `formation`…), `events[]` et `goals[]` (avec
`player_id`, `scorer_id`, `assist_id`), `momentum[]` (un point par minute : `minute`, `label`, `phase`, `home`,
`away`, `value` ∈ [-100, 100]), `stats.{all,1st,2nd}`, `lineups` (positions x/y en %, `id` des joueurs) et
`players` (dictionnaire par id : stats UEFA brutes sélectionnées, `rating`, `factors`, minutes, entrée/sortie,
nationalité, photo). La compo et le déroulé référencent les joueurs par `id` ; la fiche joueur lit `players[id]`.

## API UEFA : pièges vérifiés sur les données réelles

Endpoints et identifiants dans `uefa.py` (compétitions 1 = LDC, 14 = EL, 2019 = ECL ; `seasonYear` = année de fin
de saison, ex. 2027 pour 2026-27).

- `events?filter=ALL` : `limit` > 500 renvoie HTTP 400 → pagination par 500.
- `GOAL.totalScore` contient le **score final**, pas le score au moment du but : la chronologie se reconstruit avec
  l'équipe du buteur + `playerEvents.scorers[].goalType` (même `id` que l'événement GOAL) pour penalty / csc.
- `GOAL.secondaryActor` = gardien battu ; le passeur est dans un événement `ASSIST` séparé.
- `SUBSTITUTION` : `primaryActor` = joueur qui **sort**, `secondaryActor` = joueur qui entre.
- `SAVE` : `primaryActor` = défenseur ou gardien (créditer l'adversaire pour le momentum) ; `FOUL` : acteur = fautif.
- `VAR` : la plupart sont des vérifications silencieuses ; ne garder que `varInfo.status` CHANGED / CONFIRMED.
- `team-statistics` n'est **pas** ordonné domicile/extérieur : associer par `teamId`.
- `player-statistics` pèse ~4,7 Mo par match ; on n'en conserve que `PLAYER_STAT_KEYS`. Pas de touches,
  d'interceptions ni de duels aériens au niveau joueur.
- Clubs français = `countryCode == "FRA"` (Monaco inclus) ; aucune liste de noms.

ESPN ne sert qu'au fil de commentaires (anglais, Opta) des matchs de clubs français, rapproché du match UEFA par
date + score + recouvrement de mots du nom d'équipe (`espn.find_espn_event`).

FotMob et SofaScore ont été écartés : leurs protections anti-robots bloquent GitHub Actions et ne doivent pas être
contournées (pas d'usurpation d'empreinte TLS, pas de reconstitution d'en-tête signé).

## Résumés IA (`agents_flash.py`)

- `build_match_dossier` est la **seule** source de faits donnée au modèle : date en toutes lettres, score à la
  pause (seulement si les buts reconstitués égalent le score officiel), actions UEFA traduites, joueurs en vue
  (issus des notes), phases de domination (dérivées du momentum), stats, fil ESPN, classement.
- Rédacteur sur Flash, contrôleur sur Flash-Lite (quotas séparés sur l'offre gratuite) ; 3 essais avec le retour du
  contrôleur ; HTTP 429 → modèle suivant ; budget global `AI_BUDGET_SECONDS` (900 s par défaut) ; sinon
  `build_deterministic_fallback_summary`. Les modèles sont découverts via ListModels (ne pas coder d'identifiant
  en dur).
- Le quota Gemini gratuit s'épuise vite lors de tests répétés : privilégier `[sans-ia]`.

## Notes des joueurs (`ratings.py`)

Méthode détaillée dans la docstring du module et le README (Ball, Huynh & Varley 2025 + Wolf et al. 2020).
Points à préserver lors d'une modification : standardisation et calibrage **par compétition** ; calibrage
appliqué à la seule partie « statistiques » (buts, passes décisives et cartons ajoutés tels quels) ; gardiens sur
échelle fixe ; z-scores bornés à ±3 ; compression au-delà de 9 ; pas de note sous 10 min. Après tout changement,
vérifier dans les logs `[NOTES]` la moyenne (~6,9), l'écart-type (~0,75), l'équilibre entre postes et le taux
d'accord avec l'homme du match UEFA (renseigné pour les matchs de LDC uniquement).

## Interface (`index.html`)

Page autonome sans dépendance : toute donnée insérée dans le HTML passe par `esc()`. Drapeaux via flagcdn.com
(`flag()` attend un objet avec `flag` / `country_name`). Liens joueurs via `plink(id, texte)` et `openPlayer(id)`
(nécessitent `activeMatch.players`). La page doit rester lisible sur mobile (~390 px) ; vérifier le rendu avec le
Chromium/Playwright préinstallé et un `data.json` de test servi en local.
