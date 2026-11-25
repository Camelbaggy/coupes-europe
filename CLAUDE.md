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
python clubs.py --test                                  # fiches de club : extraction, agrégats, alias, valeur absente = absente (sans réseau)
python clubs.py --tous                                  # mise à jour complète de clubs/ (UEFA + Wikidata + Wikipédia, ~10 min)
python clubs.py --clubs 52747,52277                     # certains clubs seulement (identifiants UEFA)
python histoire.py --test                               # historique européen : saison depuis la date, finales / titres (cumul, tirs au but, match rejoué), 7 fixtures réelles, fusion de la saison courante
python clubs.py --historique [--clubs id,…] [--cache DIR]   # historique européen complet (clubs/historique/<id>.json ; reprenable ; ~11 min, 818 Mo téléchargés une fois) ; --saison-courante = mise à jour hebdomadaire
python clubs.py --couleurs                              # couleurs des clubs seules (compositions UEFA -> clubs/couleurs.json + champ `couleurs` de clubs/index.json)
node tools/test_couleurs_ui.js http://localhost:8765 /tmp/caps   # Playwright 390 x 844 : 40 soirées (ΔE, contrastes), rendu compos / stats / momentum / fiche de club, captures (serveur : python -m http.server 8765)
python couleurs.py --test                               # règle des couleurs : ΔE76, contraste, choix, agrégation + parité Python / JS (Node) du bloc COULEURS d'index.html
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
                 ├─ clubs.py (fiches de club clubs/<id UEFA>.json + clubs/index.json : UEFA, Wikidata, Wikipédia FR ; couleurs principales)
                 ├─ histoire.py (historique européen clubs/historique/<id UEFA>.json : tous les matchs UEFA du club, bilans, palmarès calculé ; `clubs.py --historique`)
                 ├─ couleurs.py (règle des couleurs d'équipe, fonctions pures ; jumeau du bloc COULEURS d'index.html)
                 ├─ reconstitution.py (--reconstituer : soirées passées ; --rattraper-ia : résumés Gemini par lots)
                 └─ notify.py (publication JSON ntfy)
index.html  : page unique (CSS + JS inline), lit soirees/index.json + soirees/<date>.json (repli : data.json) + clubs/ ; aucune étape de build
```

- `update_dashboard.yml` tourne mardi/mercredi/jeudi à 22h30 UTC (et le samedi en mai-juin pour la finale de LDC) et **commit `data.json` directement sur `main`** (GitHub retarde ce cron de plusieurs heures, passages réels vers 2 h-4 h UTC : sans `--date`, `run_pipeline.date_soiree_par_defaut` vise la soirée de la VEILLE avant 12 h UTC)
  (commits « chore: mise à jour automatique… »). Une branche de travail se retrouve donc vite derrière `main` ;
  ne pas committer `data.json`, `soirees/` ni `clubs/` à la main.
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

### Historique européen et palmarès (`histoire.py`, `clubs/historique/`, étape 5)

Détail, règles, cas vérifiés et mesures : `docs/histoire_europeenne.md`. En bref : `clubs/historique/<id UEFA>.json` (108 fichiers, 1,40 Mo bruts / 0,43 Mo gzip, 62 octets par
match, chargés à la demande par l'onglet **Histoire** de la fiche de club ; la fiche `clubs/<id>.json` ne grossit pas). Source : `match.uefa.com/v5/matches?teamId=<id>` SANS
`competitionId` (C1, C2, C3, LC, Supercoupe `SCUP`, villes de foires, Intertoto, Coupe intercontinentale `EUSA`). Saison européenne = 20 juin -> 19 juin dérivée de la DATE
(`seasonYear` incohérent, deux exceptions documentées : finales d'été et août 2020). Finale : match rejoué = le rejoué décide, match unique = score puis tirs au but, deux manches
= CUMUL puis tirs au but puis vainqueur donné par l'UEFA, sinon `?` (« non déterminé », jamais deviné) ; `ecarts` consigne tout désaccord avec le vainqueur UEFA (0 sur les 108 clubs).
Titres = C1 / C2 / C3 / LC / Supercoupe ; villes de foires, Intertoto, Coupe intercontinentale à part. Matchs annulés / arrêtés / forfaits : listés, jamais comptés. Toute la logique
(palmarès, bilan, meilleur parcours) est en Python et testée ; `index.html` ne fait que regrouper (décennies) et afficher. **Collecte** : `python clubs.py --historique` (reprenable,
`--cache DIR` garde le JSON brut HORS du dépôt) puis `--historique --saison-courante` (matchs depuis le 20 juin ; résultat identique à une reconstruction complète) ; les deux
tournent dans `clubs.yml` (lundi) sans bloquer la publication. Ne pas committer `clubs/historique/` à la main. Interface : 5e onglet « Histoire » (`attachTabSwipe` inchangé,
`CLUB_VIEWS`), palmarès, liste des finales repliable, bilan par compétition, saisons par décennie repliables (matchs rendus à l'ouverture), info-bulles `infoBtn`, accent `--club-ink` ;
`python tools/test_histoire_ui.js <url> <dossier>` (Playwright). Un glissement CDP vers la droite déclenche le retour arrière du navigateur headless (sans rapport avec la page) :
les tests de glissement utilisent de vrais `TouchEvent` dans la page.

### Fiches de club (`clubs.py`, `clubs/`, étape 3)

Décisions du propriétaire du 25/11/2026 (`docs/etude_fiches_clubs.md`) : entraîneur non affiché ; historique européen complet = étape 5 (livrée, voir la section ci-dessus) ;
couleurs = étape 4 (§ Couleurs des équipes) ; 5 alias Wikidata validés. Règle cardinale inchangée : valeur absente = absente (pas d'extrait, pas de stade : rien n'est affiché).
- **Fichiers** (JSON compact, jamais édités à la main) : `clubs/index.json` `{saison, maj, clubs[]}` (108 clubs = les 36 du classement de chaque coupe : `id` UEFA, `nom`,
  `nom_officiel`, `nom_court`, `pays`, `code_pays`, `drapeau`, `francais`, `logos{70,240,700}` (liens UEFA, rien n'est copié dans le dépôt), `competitions[]`, `qid` si
  rapproché, `fichier`) et `clubs/<id UEFA>.json` : `stade` (le plus fréquent à domicile : nom, ville, capacité, ouverture, coordonnées, `source: "UEFA"`), `wikidata`
  (`qid`, `preuve` = `P7361` ou `alias`, `fondation_annee`, `ville_siege`, `site`, `surnom`, `titre_wikipedia`, `maj`), `wikipedia` (`extrait`, `titre`, `url`, licence CC BY-SA 4.0,
  `maj`), `saison.matchs[]` (tous les matchs UEFA de la saison, tours préliminaires compris : `match_id`, `date`, `heure_utc`, `comp`, `stage`, `tour`, `journee`, `manche`,
  `domicile`, `adversaire{id,nom,logo,pays,drapeau}`, `pour` / `contre` (point de vue du club), `tab`, `resultat` V/N/D calculé, `statut`, `stade`, et `soiree` = date si
  `soirees/<date>.json` existe) + `saison.forme` (5 derniers résultats) + `saison.prochain`, `rang[]` (classement UEFA actuel par coupe, `rang_precedent`, `tendance`),
  `stats{comp}` (`matchs`, `cumul` = cumuls officiels `compstats`, `par_match` CALCULÉ = cumul / matchs (la possession, la précision et la vitesse ne sont pas divisées),
  `vnd` calculé, `moyenne_competition{valeurs, clubs, maj}` CALCULÉE = moyenne simple des valeurs par match des clubs du classement), `effectif[]` (inscrits UEFA : `id`
  = celui des `players` des soirées, numéro, âge, nationalité, photo, poste ; `joue` et `stats{comp}` (matchs, minutes, buts, passes, cartons, gardiens : arrêts / clean sheets)
  seulement pour qui a des minutes), `maj`. `alias_clubs_wikidata.json` (racine, MANUEL) : `{id UEFA: {qid, valide_le, note}}` pour les clubs sans P7361 (Como, Sunderland,
  Torreense, Mjällby, Sint-Truidense, validés le 25/11/2026) ; jamais de rapprochement automatique sans P7361 ni alias.
- **Collecte** (`python clubs.py --tous | --clubs id,id | --test`, Python stdlib) : listes de saison UEFA (3 requêtes, `uefa.fetch_season_matches`, cache vidé avant lecture),
  classements, cumuls d'équipe (`compstats team-statistics`, tous les clubs d'une coupe en 1-2 requêtes), effectif inscrit (`comp.uefa.com/v2/players` : le filtre par club est
  IGNORÉ, on lit toute la compétition puis on filtre `clubId` ; seulement en mise à jour complète, sinon l'effectif précédent est gardé), stats des joueurs (`player-statistics`
  par lots de 50). Wikidata : UNE requête SPARQL (P7361 + alias) pour tous les clubs à rafraîchir ; Wikipédia FR : API MediaWiki `action=query&prop=extracts|info|pageprops&exintro&explaintext` par LOTS DE 20 titres (titres lus dans le
  lien Wikidata, redirections suivies, pages d'homonymie écartées ; extrait = paragraphes entiers jusqu'à 250 caractères, 900 au plus). **Ne pas utiliser `rest_v1/page/summary`
  page par page** : mesuré le 25/11/2026, l'API REST répond HTTP 429 quasi systématiquement (4 résumés en 15 min, `Retry-After` qui s'allonge si on redemande trop tôt) alors que
  le lot MediaWiki passe (6 requêtes pour 108 clubs). 2,2 s entre requêtes, `Retry-After` respecté, **3 échecs de suite = on laisse le reste au passage suivant** ;
  fichiers écrits au fur et à mesure (l'index aussi, même si Wikipédia échoue). Cache : `wikidata` / `wikipedia` relus seulement après 30 jours ou s'ils manquent ; un échec ne remplace JAMAIS une valeur obtenue ;
  un fichier n'est réécrit que si son contenu change (hors horodatage `maj`, sauf ceux des blocs Wikidata / Wikipédia qui servent de cache). La fondation = année seulement
  (la précision d'une date Wikidata n'est pas lue : un 1er janvier peut être un défaut). Surnom : 1 club sur 108 en français (rien n'est inventé).
- **Mise à jour** : (1) chaque passage de soirée (`run_pipeline.py`, après `historique.publier_soiree`) appelle `clubs.apres_soiree` : fiches des clubs qui ont joué +
  ceux de `clubs/etat.json` `{a_refaire}` (clubs d'un passage précédent dont la mise à jour a échoué) ; **jamais bloquant** (exception, UEFA illisible : journal, les clubs restent
  « à refaire », la notification part quand même) ; sans `clubs/index.json` (premier remplissage pas encore fait) : ignoré. Les fichiers partent dans le même commit que `data.json`
  (`publier.sh` ajoute `clubs/`). (2) `clubs.yml` : cron lundi 5 h 17 UTC + dispatch, groupe `clubs`, 40 min, `python clubs.py --tous` puis `publier.sh --clubs` (clubs/ seul : jamais
  `data.json`, `soirees/` ni `etat_soirees.json`, donc aucun effet sur le battement / la notification). Sert à rattraper effectifs, prochains matchs, soirées reconstituées depuis
  (champ `soiree`), Wikidata / Wikipédia. La moyenne de compétition d'une fiche date de sa dernière mise à jour (affichée dans l'info-bulle).
- **Interface** (`index.html`) : feuille `#club-sheet` (même tiroir que match / joueur : `attachSheetDrag`, pleine hauteur, fermeture vers le bas) à 4 onglets Aperçu · Matchs · Stats ·
  Effectif, glissement par `attachTabSwipe` (3e usage du composant) ; textes de méthode / sources / crédits dans des `infoBtn` (le crédit Wikipédia CC BY-SA reste visible en une
  ligne). **Empilement dynamique** : `bringToFront(el)` donne un z-index croissant à l'ouverture (club au-dessus du match qui l'ouvre, match ouvert depuis un club au-dessus du club,
  joueur au-dessus de tout), chaque fermeture (bouton, glissement, fond, Échap = `closeTopSheet`) ne ferme que la feuille du dessus ; `syncBodyLock` gère le blocage du défilement
  de la page ; `#info-pop` est à 100000. Points d'entrée (`clubLink(id, html)` : bouton seulement si le club est dans `clubIndex`, sinon texte simple) : noms de l'en-tête de la
  fiche de match, lignes du classement (`tr.clickable`), étiquette de club des cartes françaises, en-têtes des compos, nom du club dans la fiche joueur, adversaires dans l'onglet
  Matchs. **Matchs** : groupés par tour ; un score encadré (`soiree` renseignée) appelle `openMatchFromClub` : charge `soirees/<date>.json` (`soireeCache`) et ouvre
  `openMatchModal(id, data, compKey)` (la soirée affichée en arrière-plan ne change pas). **Effectif** par poste (inscrits avec numéro ou minutes seulement, le reste compté dans
  l'info-bulle) ; un joueur ouvre la fiche complète (`openPlayer(pid, match)`) s'il figure dans la soirée chargée, sinon une fiche RÉDUITE bâtie sur `clubs/<id>.json` (sans note :
  elle se calcule match par match). `dateEnToutesLettres` : « Soirée du 2026-11-04 » devient « Soirée du mercredi 4 novembre » à l'affichage (libellés enregistrés inchangés).
- **Poids mesuré** : voir la section « Mesures » de `docs/etude_fiches_clubs.md` (étape 3).
- **Premier lancement après fusion** : `gh workflow run clubs.yml --ref main` seulement si `clubs/` n'a pas été commité (il l'est avec cette étape ; le cron du lundi suit).

### Couleurs des équipes (`couleurs.py`, bloc `COULEURS` d'`index.html`, étape 4)

Règle validée par le propriétaire le 25/11/2026 (`docs/etude_fiches_clubs.md`, § Couleurs et § Décisions) : couleur d'une équipe dans un match = (1) maillot PORTÉ
dans ce match (`shirt_color` de `home_team` / `away_team`) ; sinon (2) couleur principale du club (`clubs/index.json` → `couleurs`) ; sinon (3) repli neutre (bleu
`#38bdf8` domicile, rouge `#f43f5e` extérieur, les anciennes couleurs). Jamais de couleur inventée : le repli est une couleur d'interface, pas une donnée.
- **Garde-fou de proximité** : ΔE76 (CIELAB D65) < 25 entre les deux couleurs d'un match : l'équipe à l'EXTÉRIEUR prend sa secondaire (maillot `pl02`), à défaut le repli
  neutre (rouge, puis bleu si le rouge est lui aussi trop proche) ; le domicile ne change jamais. Mesuré : avec les maillots portés le seuil ne se déclenche jamais sur les
  40 soirées ; il sert aux soirées sans `shirt_color` (couleurs « club ») et aux données futures.
- **Lisibilité** (WCAG 2.x, calculée à l'exécution contre les fonds réels `--bg-card` / `--bg-main` / `--bg-elevated`, jamais figée dans le JSON) : `texte` = blanc ou NOIR PUR sur
  l'aplat (le pire fond, luminance 0,179, donne 4,58 : >= 4,5 toujours ; avec `#111` ce serait 4,34) ; `bord` (liseré) seulement pour un aplat quasi blanc (luminance > 0,85) ou
  quasi noir (< 0,04), choisi parmi `#e2e8f0` / `#7c8799` / `#1e293b` pour le meilleur contraste au pire avec l'aplat et la page ; `encre` = la couleur éclaircie (mélange par pas de
  5 % vers le texte de la page) jusqu'à 4,5 sur tous les fonds, pour les chiffres et noms colorés (`--home-ink` / `--away-ink`).
- **UNE fonction JS `couleursMatch(m)`** → `{home, away}` = `{fond, texte, bord, encre, source}` (`source` : `maillot` / `club` / `secondaire` / `neutre`) ; `couleurClub(id)` pour une
  fiche de club. Utilisée PARTOUT où deux équipes sont colorées, par variables CSS `--home-color/-ink/-on/-bord` et `--away-…` posées en ligne (`coulPoserMatch(el, m)` sur
  `#match-modal`, `coulStyleMatch(m)` sur les cartes françaises ; pas de couleurs dans la liste des résultats, choix du propriétaire du 25/11/2026) : pastilles des compos (`.player-dot`, classe `lis` = liseré), momentum (dégradés, traits de but, légende ; trait de
  contour des aires si liseré), barres / valeurs / en-tête des stats, pastilles `.sw-eq` (légende des compos), bandeau `.duo-bar` (en-tête de fiche, cartes françaises).
  Une nouvelle vue à deux équipes lit ces variables, jamais de couleur codée. **Fiche de club** : `coulPoserClub` pose `--club-color/-ink/-on/-bord` sur `#club-sheet`
  (bandeau d'en-tête, soulignement de l'onglet actif, rang, pastille D / E) avec la même règle de lisibilité ; sans couleur : accent bleu de la page.
- **Parité Python / JS** : `couleurs.py` et le bloc `// ===== COULEURS : début / fin =====` d'`index.html` sont deux implémentations de la même règle ; `python couleurs.py --test`
  extrait le bloc, l'exécute avec Node et compare des centaines de couleurs et de matchs. Toute modification se fait des deux côtés.
- **Couleur principale d'un club** (`clubs.py`, `couleurs.couleurs_clubs`) : depuis les compositions UEFA (`lineups`) des matchs TERMINÉS de la saison (tours préliminaires compris) :
  `shirtColor` + code du maillot lu dans `kitImageUrl` (`…/Kits/pl01.png`). `principale` = hex le plus fréquent des maillots `pl01` (à défaut `pl02`, puis `pl03` ; à égalité le
  plus récent), `secondaire` = idem pour `pl02` (seulement si la principale vient de `pl01` ; sinon `pl03`), `maillot` = code d'origine, `nb_matchs` = matchs qui fondent la
  principale, `source: "compositions_uefa"`. Un club sans maillot lisible n'a pas de `couleurs`. Cache `clubs/couleurs.json` `{match_id: {d, e: {club: [maillot|null, hex|null]}}}` :
  chaque composition n'est lue qu'une fois (passage de soirée : 60 au plus, les plus récentes d'abord ; `--tous` / `--couleurs` : toutes). Mises à jour avec les fiches (`apres_soiree`,
  `clubs.yml`) ; `python clubs.py --couleurs` ne touche ni aux fiches ni à Wikidata / Wikipédia. Le hex d'un même maillot varie d'un match à l'autre (saisie manuelle UEFA : Liverpool
  #c63349 puis #ff0000) : on prend le mode, et les maillots rayés restent approximatifs (c'est l'hex déclaré, pas un calcul sur l'image).
- **Vérifié** (Playwright 390 x 844 tactile, 40 soirées) : aucune paire de couleurs d'un match sous ΔE 25, contraste du texte posé sur un aplat >= 4,5, encre >= 4,5 sur la page, 0 erreur
  console, 0 débordement horizontal.

### Schéma de `data.json` (ce que lit `index.html`)

`competitions.{ucl,uel,uecl}` → `matches[]`, `standings[]` (36 lignes, `zone` = top8 / playoff / eliminated ; absente d'un
classement `calcule`), `standings_source` (`officiel` : classement UEFA actuel, défaut si absent ; `calcule` : recalculé par
`classement.py`, avec `standings_at` = date de calcul, lignes sans `zone` ni `trend`, `ex_aequo` ; `absent` : aucun classement, tours
préliminaires), `french_clubs_focus[]` (une carte par club français, avec `ai_summary`, `summary_source` = `gemini` / `deterministe`
et `ia_tentatives` pour le rattrapage). Niveau soirée : `reconstituee` / `reconstituee_le` (soirée rejouée a posteriori),
`amorcee` (data.json conservé tel quel dans `soirees/`).
Chaque match porte aussi `stage` (`league` / `qualifying` / `knockout`), `round` (`name`, `type` UEFA), `matchday_short`, `leg`, et, dans
`home_team` / `away_team`, `shirt_color` (hex du maillot PORTÉ dans ce match, compositions UEFA) et `kit_image` quand l'UEFA les donne
(utilisés par la règle des couleurs, § Couleurs des équipes ; absents = absents).
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

- **Menu des journées / tours, un par coupe** (plus de menu global des soirées) : en tête du contenu de chaque onglet LDC / LE / LC, bouton `#tour-btn` (`renderTourBar`,
  titre court « Journée 5 » + sous-titre « 24-25 nov. · 18 matchs ») qui ouvre une feuille du bas `#tour-modal` (`openTourMenu` / `closeTourMenu` / `chooseTour`, poignée +
  `attachSheetDrag`, tour courant surligné `aria-selected`, `role=dialog` / `listbox` / `option`, flèches / Début / Fin, Tab piégé, Échap, focus rendu au bouton ; elle est dans
  `SHEET_IDS`, donc `closeTopSheet` et le verrou de défilement la gèrent). Les tours viennent de `soirees/index.json` (`buildTours` : paire `competitions.<clé>.{stage, tour}`
  regroupée sur toutes les soirées ; id = slug du `tour`, ex. `j5`, `barrages-retour`, `t3-retour`). Groupes (`GROUPES`, du plus récent au plus ancien) : Phase finale (`knockout`),
  Phase de ligue, Barrages (`qualifying` dont le tour commence par « Barrages »), Tours préliminaires ; dans un groupe, date de fin décroissante. Libellés `tourTitre` : `J5` ->
  « Journée 5 », `T3 retour` -> « 3e tour retour ». Défaut = tour le plus récent dont une soirée a des matchs terminés (`defaultTour`).
  `showTour(coupe, id, slide)` charge les `soirees/<date>.json` du tour (`loadSoiree` : data.json pour la plus récente, cache `soireeCache`) et les fusionne (`loadTour`, cache
  `tourCache`) : matchs par soirée puis heure (`_soiree` posé sur chaque match / carte, sans doublon de `match_id`), intertitres de date `.date-sep` si le tour a plusieurs
  soirées (`_multi`), cartes des clubs français = celles de ces soirées, classement / `standings_source` / `standings_at` = ceux de la soirée la plus récente du tour. `appData` n'est
  plus une soirée mais une vue `{competitions: {clé: fusion}}` : `openMatchModal`, `openPlayerFromClub` etc. continuent de lire `appData.competitions[clé]`. Chaque coupe garde son
  tour (`tourChoice`) quand on change d'onglet ou qu'on glisse (`switchCompetition`). Badge d'en-tête « Reconstituée » + info-bulle discrète (`RECONSTITUEE_INFO`, à côté du bouton)
  si au moins une soirée du tour est reconstituée. URL partageable : `?c=ucl&tour=j5` (`syncUrl`, `replaceState`) ; l'ancien `?soiree=AAAA-MM-JJ` (ou `#soiree=` / `#AAAA-MM-JJ`)
  reste lu : il ouvre la coupe (`c` si la soirée la joue, sinon la première) et le tour de cette soirée ; tour inconnu = défaut ; pas d'index (404) = `data.json` seul, sans menu.
- **Classement** (`renderCompetition`) : `standings_source` `officiel` (ou absent) = tableau + légende des zones comme avant ; `calcule` = titre « Classement
  Phase de Ligue · calculé » + info-bulle (`standingsInfoHtml` : critères appliqués / non appliqués, date de calcul), sans légende ni zones, `=` après le rang d'un
  ex æquo ; `absent` = section masquée. Sans `zone`, la pastille de rang des cartes est neutre (`rank-pill none`, rang seul). Badge d'en-tête « Reconstituée »
  (voir ci-dessus).
- **Glissement entre onglets : composant UNIQUE `attachTabSwipe({zone, stop, tabs, current, go})` + `slideIn(el, 'slide-l' | 'slide-r')`**, utilisé par l'accueil
  (zone `#main-zone`, onglets LDC / LE / LC, `switchCompetition(clé, slide)`) et par la fiche de match (`#modal-body-content`, Déroulé / Compos / Stats,
  `switchModalView`). Toute nouvelle feuille à onglets (fiche club) l'appelle avec sa zone, sa liste d'onglets et sa fonction de changement. Règles communes :
  seuil 56 px, |dx| >= 1,5 |dy| (le défilement vertical n'est jamais gêné : écoute en fin de geste, aucun `preventDefault`), pas de boucle aux extrémités, ignoré sur
  un élément défilant en X, `data-noswipe` et les champs de saisie (le menu des tours est dans la zone mais son bouton ne gêne pas : un toucher n'est pas un geste ; sa feuille est hors de `<main>`), `touchcancel` annule, `prefers-reduced-motion`
  supprime la transition (`.slide-l` / `.slide-r`). `html, body { overscroll-behavior-x: none }` empêche le retour arrière du navigateur par-dessus un balayage.
  `main` a une hauteur minimale (`--app-h`) pour que la zone de glissement couvre l'écran. Les feuilles (fiche de match, fiche joueur) sont hors de `<main>` : un geste
  dans une feuille ne change jamais la coupe de l'accueil.

### Fiche de match : onglets, compos, stats, gestes

- Onglets **Déroulé · Compos · Stats** (le momentum est le premier bloc de Stats, `momentumHtml` / `bindMomentum`). Les DEUX feuilles (match et joueur) ont la même hauteur fixe quel que soit l'onglet : `calc(var(--app-h) - var(--sheet-gap))`, `--sheet-gap` = 10 px + `env(safe-area-inset-top)` (mince espace laissant deviner la feuille), `.modal-body` / `.player-body` défilent. `--app-h` = `100vh` puis `100dvh` (`@supports`), recalée en px par `syncAppHeight` à chaque `resize` / `visualViewport.resize` (hauteur réellement visible, barre d'adresse mobile comprise) ; les fonds (`.modal-backdrop`, `.player-backdrop`) utilisent aussi `--app-h`, jamais `inset: 0` / `vh`.
- **Info-bulle unique** (`infoBtn(html, label)` + `#info-pop`, `openInfo` / `closeInfo`) : tout texte d'aide, de légende, de méthode ou de source passe par ce composant, jamais par un paragraphe permanent (momentum : légende + méthode ; compos : légende © ⭐ ↓ + méthode des notes ; stats : source UEFA / note par mi-temps ; fiche joueur : méthode de la note et facteurs ; source du résumé des cartes de club ; aide de la grille). `infoBtn` rend un bouton ⓘ 32 px (`aria-label`, `aria-expanded`, `aria-haspopup`) ; le HTML du texte (déjà échappé par l'appelant) est gardé dans `INFO_TEXTS`, le bouton ne porte que l'indice. Bulle `position: fixed` bornée à l'écran (largeur <= 320 px, 8 px de marge, au-dessous du bouton sinon au-dessus) ; fermeture : re-toucher le bouton, toucher ailleurs, Échap (avant la fermeture d'une feuille), début d'un glissement de feuille, resize. Écouteur de clic en capture : le bouton ne déclenche pas la carte qui le contient. Les crédits / sources de données obligatoires y restent affichés : ne jamais les supprimer, seulement les y ranger.
- **Compos** (`lineupRows` + `layoutPitch`) : une ligne par nombre de la formation UEFA (gardien d'abord) ; les joueurs sont triés par profondeur `y` UEFA puis découpés selon la formation (si la somme ne colle pas aux 10 joueurs de champ : regroupement par écart de `y`), répartis régulièrement dans la ligne dans l'ordre de leur `x` UEFA (un joueur seul garde son `x`). Pas de joueur déplacé d'une ligne à l'autre. Positions en px, puis passe anti-collision sur les boîtes mesurées dans le DOM (pastille, nom, note, minute de sortie) ; si un chevauchement subsiste, la hauteur du terrain augmente. Nom : nom court, puis initiale + nom, puis réduction de police, ellipse en dernier recours. Note = badge accroché au coin haut-droit de la pastille, minute de sortie en pastille sous le nom.
- **Stats** (`statsHtml`) : bascule Match complet / 1re / 2e mi-temps, en-tête collant des deux équipes, possession en grand (barre partagée), puis rubriques `STAT_GROUPS` (Tirs, Construction / passes, Attaque, Défense / gardien, Discipline, Physique, « Autres » pour toute clé inconnue : aucune donnée perdue). Ligne : valeurs aux extrémités, libellé centré, valeur dominante en gras et couleur `--home-ink` / `--away-ink`, barre divergente depuis le centre (part de chaque équipe dans le total de la ligne, côté minoritaire atténué). `(%)` du libellé devient un « % » sur les valeurs.
- **Gestes** (écouteurs passifs, sauf `touchmove` de `attachSheetDrag`) : glissement horizontal entre onglets par `attachTabSwipe` (règles ci-dessus ; `data-noswipe` sur le graphique momentum) ; fermeture des feuilles par glissement vers le bas via `attachSheetDrag` (fiche de match et fiche joueur, poignée `.sheet-handle` ou en-tête, ou contenu à `scrollTop = 0` ; suit le doigt, ferme au-delà de 25 % de la hauteur ou geste rapide, sinon retour animé ; la fiche joueur, au-dessus, se ferme seule). **Propriété du geste** : dès que le geste est reconnu comme un glissement de feuille, il le possède jusqu'au relâchement : `touchmove` non passif avec `preventDefault()` (seulement pendant un glissement actif), `overflow-y: hidden` posé sur le conteneur et `scrollTop` rétabli à chaque mouvement, translateY bornée à >= 0 ; remonter le doigt pour annuler ne fait donc pas défiler le contenu. Un geste qui ne devient pas un glissement (défilement vers le haut, horizontal) reste natif. `prefers-reduced-motion` désactive les transitions.
