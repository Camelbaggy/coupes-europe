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
python run_pipeline.py --reconstituer --dossier-soirees /tmp/soirees --du 2026-11-04 --au 2026-11-04   # reconstitution locale d'une soirée passée (sans Gemini)
python run_pipeline.py --rattraper-ia --max-cartes 10   # remplace par Gemini des résumés déterministes de la phase de ligue (clé requise)
python -m http.server 8000                              # voir index.html (il lit data.json et soirees/ via fetch)
python -m py_compile *.py tools/*.py                    # contrôle statique
python soirees.py --test && python publication.py --test && bash tools/test_veille.sh && python tools/verifier_workflows.py   # tests locaux : état / notification unique, veille.sh (faux gh), `bash -n` de chaque bloc `run:` des workflows
python classement.py --test && python historique.py --test && python reconstitution.py --test   # classement recalculé (cas réel LDC), soirees/ + index + data.json, reconstitution et rattrapage IA (doublures, sans réseau)
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
                 ├─ historique.py (soirees/<date>.json + soirees/index.json ; data.json = soirée la plus récente)
                 ├─ classement.py (classement de phase de ligue RECALCULÉ depuis les scores, pour une soirée passée)
                 ├─ reconstitution.py (--reconstituer : soirées passées ; --rattraper-ia : résumés Gemini par lots)
                 └─ notify.py (publication JSON ntfy)
index.html  : page unique (CSS + JS inline), lit soirees/index.json + soirees/<date>.json (repli : data.json) ; aucune étape de build
```

- `update_dashboard.yml` tourne mardi/mercredi/jeudi à 22h30 UTC (et le samedi en mai-juin pour la finale de LDC) et **commit `data.json` directement sur `main`** (GitHub retarde ce cron de plusieurs heures, passages réels vers 2 h-4 h UTC : sans `--date`, `run_pipeline.date_soiree_par_defaut` vise la soirée de la VEILLE avant 12 h UTC)
  (commits « chore: mise à jour automatique… »). Une branche de travail se retrouve donc vite derrière `main` ;
  ne pas committer `data.json` ni `soirees/` à la main.
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
- **Alerte d'échec** (`python run_pipeline.py --alerte SOIRÉE --cause collecte|push|page_non_a_jour|workflow`, étape `if: failure()` du workflow
  déclenchée par TOUT échec du job, étape préparatoire comprise (soirée recalculée si l'étape `cible` n'a rien produit), jamais pour
  la semaine de test ni une soirée `aucun_match`) : ntfy distinct « Échec de mise à jour Coupes d'Europe » (priorité 4, tag `rotating_light`) avec la soirée,
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

### Historique des soirées, reconstitution, rattrapage IA

Décisions du propriétaire du 25/11/2026 : `docs/etude_fiches_clubs.md` (§ Décisions). Ordre de livraison : soirées + menu, reconstitution,
fiches club, couleurs, historique européen.
- **`soirees/`** (jamais purgé ; `etat_soirees.json` garde 60 jours mais n'est lu que par le battement, qui ignore `soirees/`) :
  `soirees/<AAAA-MM-JJ>.json` = même contenu que `data.json` pour UNE soirée (JSON compact, `last_updated` / `target_dates` en tête) et
  `soirees/index.json` = liste LÉGÈRE triée par date décroissante (`date`, `statut`, `matchs`, `termines`, `competitions.{ucl,…}.{matchs,
  stage, tour}` avec `tour` = `J5` / `T2 aller` / `Barrages retour`, `francais[]` = matchs de clubs français avec score, `resumes.{gemini,
  deterministe,a_rattraper}`, `reconstituee`, `maj`, `fichier`). L'index se dérive des fichiers (`historique.reindexer`).
  `run_pipeline.py` (passage normal, hors `--week`) appelle `historique.publier_soiree` : amorçage éventuel (data.json d'une seule soirée
  sans fichier = conservé dans `soirees/` avant d'être remplacé), écriture de la soirée + ligne d'index, puis `data.json` = copie de la soirée
  SI elle est la plus récente de l'index et de data.json (`doit_remplacer_data_json` : une soirée plus ancienne ne le remplace jamais ; une
  reconstitution non plus, même à date égale). État / notification / alerte INCHANGÉS : `--notifier` vérifie toujours `data.json` (origin, puis
  page publique) ; `deja_traitee` regarde data.json ET l'index (`dates_connues`). `publier.sh` ajoute `soirees/` au commit de data.json ;
  `--soirees` (reconstitution, rattrapage) ajoute `soirees/` + data.json mais JAMAIS `etat_soirees.json` ; après un `pull --rebase -X theirs`
  il reconstruit l'index et rétablit data.json (`historique.py --reindexer` : deux passages concurrents ont pu perdre la ligne de l'autre).
- **Classement d'une soirée** (`classement.py`, `collector.choisir_classement`) : l'API UEFA ne donne que le classement ACTUEL. Passage du
  soir (avant 13 h UTC le lendemain, `classement.officiel_valable`) : officiel, `standings_source: "officiel"`. Plus tard (relance tardive,
  reconstitution) : RECALCULÉ depuis les scores des matchs de phase de ligue terminés jusqu'à la date, `calcule` ; aucun match de phase de ligue
  terminé = `absent` (rien pour les préliminaires). Départage appliqué : points, différence de buts, buts marqués, buts à l'extérieur, victoires,
  victoires à l'extérieur, puis points / différence de buts / buts marqués des adversaires affrontés. NON appliqués (données absentes par date) :
  points disciplinaires, coefficient. Égalité résiduelle = même rang + `ex_aequo`. Pas de zone. Validé : sur les matchs réels le calcul égale
  le classement UEFA (108 clubs, 0 écart ; fixture `tools/fixtures/classement_ldc_2027.json`). Si la liste de saison est illisible, aucune
  soirée n'est écrite (jamais de classement sur une liste tronquée).
- **Reconstitution** (`historique_soirees.yml`, dispatch seul, groupe `historique-soirees` distinct de `update-dashboard`, 55 min, auto-relance
  tant qu'il reste des soirées ET que le passage a progressé ; à lancer sur main) : `run_pipeline.py --reconstituer [--du --au]
  --budget-min 40 --publier-tous 4`. Dates = listes de saison UEFA (3 requêtes, pas de liste codée), phase de ligue ET tours préliminaires,
  du plus récent au plus ancien, seulement si le créneau normal de la soirée est fini (13 h UTC le lendemain : avant, la soirée appartient au
  workflow du soir) et si `soirees/<date>.json` n'existe pas (reprenable ; un échec reste « à faire »). Même pipeline que le soir (notes,
  momentum, stats, classement calculé) mais SANS Gemini ni ESPN (résumés déterministes : `summary_source: "deterministe"`), `reconstituee: true`.
  Ne touche JAMAIS à `etat_soirees.json` ni à ntfy : le battement (qui lit l'état et ne relance que `update_dashboard.yml`) l'ignore.
  Le résumé déterministe n'invente pas de zone : sans `zone`, il ne parle pas de zone de classement.
- **Rattrapage IA** (`rattrapage_ia.yml`, cron 6 h 17 et 15 h 17 UTC + dispatch, groupe `rattrapage-ia`) : `run_pipeline.py --rattraper-ia
  --max-cartes 10` remplace par un résumé Gemini contrôlé (même rédacteur + contrôleur) les cartes de clubs français de PHASE DE LIGUE encore en
  `deterministe`, de la soirée la plus récente à la plus ancienne ; actions UEFA et fil ESPN sont relus pour le dossier (data.json ne les
  garde pas). Jamais les tours préliminaires de cette saison (aux saisons suivantes ils sont traités en direct). Reprenable (carte enregistrée
  aussitôt, data.json suivi si c'est la même soirée), HTTP 429 / budget épuisé = arrêt propre, 3 rejets du contrôleur = `ia_tentatives` + 1
  (3 essais au plus, `MAX_TENTATIVES_IA`). Sans carte à rattraper le passage ne fait rien ; le cron peut rester en place.
- **Premier lancement après fusion** : (1) `gh workflow run historique_soirees.yml --ref main` (puis il se relance seul), (2) `gh workflow run
  rattrapage_ia.yml --ref main` (puis le cron, 2 passages par jour), (3) relancer `battement.yml` seulement si `.github/scripts/veille.sh` a changé
  (ce n'est pas le cas ici).

### Schéma de `data.json` (ce que lit `index.html`)

`competitions.{ucl,uel,uecl}` → `matches[]`, `standings[]` (36 lignes, `zone` = top8 / playoff / eliminated ; absente d'un
classement `calcule`), `standings_source` (`officiel` : classement UEFA actuel, défaut si absent ; `calcule` : recalculé par
`classement.py`, avec `standings_at` = date de calcul, lignes sans `zone` ni `trend`, `ex_aequo` ; `absent` : aucun classement, tours
préliminaires), `french_clubs_focus[]` (une carte par club français, avec `ai_summary`, `summary_source` = `gemini` / `deterministe`
et `ia_tentatives` pour le rattrapage). Niveau soirée : `reconstituee` / `reconstituee_le` (soirée rejouée a posteriori),
`amorcee` (data.json conservé tel quel dans `soirees/`).
Chaque match porte aussi `stage` (`league` / `qualifying` / `knockout`), `round` (`name`, `type` UEFA), `matchday_short`, `leg`, et, dans
`home_team` / `away_team`, `shirt_color` (hex du maillot PORTÉ dans ce match, compositions UEFA) et `kit_image` quand l'UEFA les donne
(collectés pour la future règle des couleurs, pas encore affichés ; absents = absents).
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

### Accueil : menu des soirées, glissement entre coupes

- **Menu des soirées** (`#soiree-select`, dans l'en-tête, masqué sans index) : options de `soirees/index.json` (plus récente d'abord, défaut), libellé
  `soireeLabel` = « mardi 24 novembre 2026 · LDC J5 » (coupes de même tour regroupées : `LDC/LE J4`, `LDC/LC Barrages retour`, « (partielle) » si le
  statut l'est). `showSoiree(date)` charge `data.json` pour la plus récente (copie de sa soirée), sinon `soirees/<date>.json` (cache mémoire, jeton
  contre les réponses périmées, `main.loading`). URL partageable : `?soiree=AAAA-MM-JJ` (posée par `chooseSoiree`, `replaceState`) ou `#soiree=` /
  `#AAAA-MM-JJ` en lecture ; date inconnue = plus récente ; pas d'index (404) = `data.json` seul, sans menu. Changer de soirée choisit la première coupe
  qui a des matchs si la coupe courante n'en a pas (`pickCompetition`).
- **Classement** (`renderCompetition`) : `standings_source` `officiel` (ou absent) = tableau + légende des zones comme avant ; `calcule` = titre « Classement
  Phase de Ligue · calculé » + info-bulle (`standingsInfoHtml` : critères appliqués / non appliqués, date de calcul), sans légende ni zones, `=` après le rang d'un
  ex æquo ; `absent` = section masquée. Sans `zone`, la pastille de rang des cartes est neutre (`rank-pill none`, rang seul). Badge d'en-tête « Reconstituée »
  et note + info-bulle sous le menu pour une soirée reconstituée.
- **Glissement entre onglets : composant UNIQUE `attachTabSwipe({zone, stop, tabs, current, go})` + `slideIn(el, 'slide-l' | 'slide-r')`**, utilisé par l'accueil
  (zone `#main-zone`, onglets LDC / LE / LC, `switchCompetition(clé, slide)`) et par la fiche de match (`#modal-body-content`, Déroulé / Compos / Stats,
  `switchModalView`). Toute nouvelle feuille à onglets (fiche club) l'appelle avec sa zone, sa liste d'onglets et sa fonction de changement. Règles communes :
  seuil 56 px, |dx| >= 1,5 |dy| (le défilement vertical n'est jamais gêné : écoute en fin de geste, aucun `preventDefault`), pas de boucle aux extrémités, ignoré sur
  un élément défilant en X, `data-noswipe` et les champs de saisie (le menu des soirées est dans l'en-tête, hors zone), `touchcancel` annule, `prefers-reduced-motion`
  supprime la transition (`.slide-l` / `.slide-r`). `html, body { overscroll-behavior-x: none }` empêche le retour arrière du navigateur par-dessus un balayage.
  `main` a une hauteur minimale (`--app-h`) pour que la zone de glissement couvre l'écran. Les feuilles (fiche de match, fiche joueur) sont hors de `<main>` : un geste
  dans une feuille ne change jamais la coupe de l'accueil.

### Fiche de match : onglets, compos, stats, gestes

- Onglets **Déroulé · Compos · Stats** (le momentum est le premier bloc de Stats, `momentumHtml` / `bindMomentum`). Les DEUX feuilles (match et joueur) ont la même hauteur fixe quel que soit l'onglet : `calc(var(--app-h) - var(--sheet-gap))`, `--sheet-gap` = 10 px + `env(safe-area-inset-top)` (mince espace laissant deviner la feuille), `.modal-body` / `.player-body` défilent. `--app-h` = `100vh` puis `100dvh` (`@supports`), recalée en px par `syncAppHeight` à chaque `resize` / `visualViewport.resize` (hauteur réellement visible, barre d'adresse mobile comprise) ; les fonds (`.modal-backdrop`, `.player-backdrop`) utilisent aussi `--app-h`, jamais `inset: 0` / `vh`.
- **Info-bulle unique** (`infoBtn(html, label)` + `#info-pop`, `openInfo` / `closeInfo`) : tout texte d'aide, de légende, de méthode ou de source passe par ce composant, jamais par un paragraphe permanent (momentum : légende + méthode ; compos : légende © ⭐ ↓ + méthode des notes ; stats : source UEFA / note par mi-temps ; fiche joueur : méthode de la note et facteurs ; source du résumé des cartes de club ; aide de la grille). `infoBtn` rend un bouton ⓘ 32 px (`aria-label`, `aria-expanded`, `aria-haspopup`) ; le HTML du texte (déjà échappé par l'appelant) est gardé dans `INFO_TEXTS`, le bouton ne porte que l'indice. Bulle `position: fixed` bornée à l'écran (largeur <= 320 px, 8 px de marge, au-dessous du bouton sinon au-dessus) ; fermeture : re-toucher le bouton, toucher ailleurs, Échap (avant la fermeture d'une feuille), début d'un glissement de feuille, resize. Écouteur de clic en capture : le bouton ne déclenche pas la carte qui le contient. Les crédits / sources de données obligatoires y restent affichés : ne jamais les supprimer, seulement les y ranger.
- **Compos** (`lineupRows` + `layoutPitch`) : une ligne par nombre de la formation UEFA (gardien d'abord) ; les joueurs sont triés par profondeur `y` UEFA puis découpés selon la formation (si la somme ne colle pas aux 10 joueurs de champ : regroupement par écart de `y`), répartis régulièrement dans la ligne dans l'ordre de leur `x` UEFA (un joueur seul garde son `x`). Pas de joueur déplacé d'une ligne à l'autre. Positions en px, puis passe anti-collision sur les boîtes mesurées dans le DOM (pastille, nom, note, minute de sortie) ; si un chevauchement subsiste, la hauteur du terrain augmente. Nom : nom court, puis initiale + nom, puis réduction de police, ellipse en dernier recours. Note = badge accroché au coin haut-droit de la pastille, minute de sortie en pastille sous le nom.
- **Stats** (`statsHtml`) : bascule Match complet / 1re / 2e mi-temps, en-tête collant des deux équipes, possession en grand (barre partagée), puis rubriques `STAT_GROUPS` (Tirs, Construction / passes, Attaque, Défense / gardien, Discipline, Physique, « Autres » pour toute clé inconnue : aucune donnée perdue). Ligne : valeurs aux extrémités, libellé centré, valeur dominante en gras et couleur `--home-ink` / `--away-ink`, barre divergente depuis le centre (part de chaque équipe dans le total de la ligne, côté minoritaire atténué). `(%)` du libellé devient un « % » sur les valeurs.
- **Gestes** (écouteurs passifs, sauf `touchmove` de `attachSheetDrag`) : glissement horizontal entre onglets par `attachTabSwipe` (règles ci-dessus ; `data-noswipe` sur le graphique momentum) ; fermeture des feuilles par glissement vers le bas via `attachSheetDrag` (fiche de match et fiche joueur, poignée `.sheet-handle` ou en-tête, ou contenu à `scrollTop = 0` ; suit le doigt, ferme au-delà de 25 % de la hauteur ou geste rapide, sinon retour animé ; la fiche joueur, au-dessus, se ferme seule). **Propriété du geste** : dès que le geste est reconnu comme un glissement de feuille, il le possède jusqu'au relâchement : `touchmove` non passif avec `preventDefault()` (seulement pendant un glissement actif), `overflow-y: hidden` posé sur le conteneur et `scrollTop` rétabli à chaque mouvement, translateY bornée à >= 0 ; remonter le doigt pour annuler ne fait donc pas défiler le contenu. Un geste qui ne devient pas un glissement (défilement vers le haut, horizontal) reste natif. `prefers-reduced-motion` désactive les transitions.
