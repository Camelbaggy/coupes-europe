# coupes-europe

Tableau de bord mobile des soirées de Coupes d'Europe (Ligue des Champions, Ligue Europa, Ligue Conférence),
avec focus sur les clubs français. Spécifications : `Projet_foot.md`.

## Fonctionnement

| Étape | Fichier | Rôle |
|---|---|---|
| 1 | `collector.py` (+ `uefa.py`, `espn.py`, `netutil.py`) | Collecte déterministe → `data_raw.json` |
| 2 | `agents_flash.py` | Résumés des matchs des clubs français (Gemini rédacteur + contrôleur), repli sans IA |
| 3 | `notify.py` | Push ntfy avec lien vers le dashboard |
| — | `run_pipeline.py` | Enchaîne les 3 étapes |
| — | `index.html` | Dashboard statique (GitHub Pages) qui lit `data.json` |

Le workflow `update_dashboard.yml` tourne mardi, mercredi et jeudi à 22h30 UTC (23h30 à Paris en hiver)
et commit `data.json`.

## Sources de données

**UEFA (source principale, officielle, en français)** : l'API publique qui alimente uefa.com, accessible sans
clé depuis GitHub Actions :

- matchs, scores, homme du match, stade, affluence ;
- toutes les actions du match (`events?filter=ALL`) : buts, passes décisives, tirs cadrés / non cadrés / contrés,
  arrêts, corners, cartons, remplacements, décisions VAR, avec minute et seconde ;
- environ 430 statistiques par équipe et 380 par joueur (possession, tirs, passes clés, distance, vitesse…) ;
- compositions avec position sur le terrain, entraîneurs ;
- classement des 36 équipes.

Les **clubs français** sont reconnus par leur code pays UEFA (`FRA`) : aucune liste à maintenir.
Ce même code pays affiche le **drapeau de chaque club** (résultats, fiches, classements), via les images de
flagcdn.com. Angleterre, Écosse, pays de Galles et Irlande du Nord ont leur propre drapeau.

**ESPN (complément)** : fil de commentaires texte (Opta, en anglais) des matchs des clubs français, rapproché du
match UEFA par date, score et nom d'équipe. Il sert uniquement de matière première au récit de l'IA.

**Valeurs calculées (jamais inventées)** :
- *momentum* : indice de pression minute par minute. Les actions officielles (buts, tirs, attaques dangereuses,
  corners, arrêts adverses, hors-jeu, coups francs obtenus) sont pondérées et créditées à l'équipe qui attaque,
  puis lissées sur environ 5 minutes ;
- *statistiques par mi-temps* : comptage des actions officielles de chaque période.

FotMob et SofaScore ont été écartés : leurs protections anti-robots (en-tête signé, Cloudflare) bloquent les
serveurs de GitHub Actions, et les contourner irait contre leurs conditions d'utilisation.

## Notes des joueurs (`ratings.py`)

Chaque joueur ayant joué au moins 10 minutes reçoit une note sur 10, calculée à partir des statistiques officielles
UEFA :

1. **Joueurs de champ** : chaque statistique est standardisée sur l'ensemble des joueurs de champ de la collecte,
   puis pondérée par les coefficients qui expliquent les notes FotMob dans Ball, Huynh & Varley (2025),
   *Journal of Sports Sciences* 43:7 (Table 2) : tirs cadrés, passes clés, ballons récupérés, dribbles réussis,
   dégagements, duels, passes courtes, fautes obtenues, pertes de balle… Les variables absentes chez l'UEFA
   (xG, touches, interceptions) sont exclues ou remplacées par une variable proche.
2. **Contributions directes**, que l'étude retire de son modèle : bonus pour les buts et les passes décisives,
   malus pour les cartons.
3. **Gardiens** (exclus de l'étude) : arrêts, buts encaissés, clean sheet, jeu au pied.
4. **Résultat pendant le temps de jeu**, d'après Wolf, Schmitt & Schuller (2020), *Journal of Sports Analytics* 6 :
   écart de buts de l'équipe quand le joueur était sur le terrain, comparé au résultat attendu. Les défenseurs
   reçoivent aussi un bonus de clean sheet.
5. **Calibrage** sur la distribution observée dans l'étude (moyenne 6,85, écart-type 0,75, bornes 3-10). Pour les
   entrées tardives, la partie « statistiques » est ramenée vers la moyenne, mais pas les buts ni les passes
   décisives.

La fiche de chaque joueur (cliquable sur la compo, dans le déroulé et sur les buteurs) affiche sa note, les
facteurs qui l'expliquent et ses statistiques. Contrôle : la collecte journalise à quelle fréquence le joueur le
mieux noté est l'homme du match désigné par l'UEFA.

## Résumés

`agents_flash.py` construit un dossier factuel par match : date, score à la pause, buts et passeurs, actions
officielles traduites, joueurs en vue, homme du match, phases de domination, statistiques globales et par
mi-temps, fil ESPN, classement. Gemini (Flash) rédige un récit de 4-5 phrases. Un second appel (Flash-Lite, quota
distinct) vérifie chaque fait, avec jusqu'à 3 essais. Les rejets et erreurs API sont écrits en clair dans les logs.
Sans clé, après 3 rejets ou au-delà du budget de 15 min, un résumé narratif est construit sans IA.

## Lancer en local

```bash
python run_pipeline.py --date 2026-11-05 --no-notify   # une soirée
python run_pipeline.py --week --save-raw raw            # mardi→jeudi, réponses brutes sauvegardées
python tools/inspect_data.py data.json                  # contrôle lisible du résultat
python -m http.server 8000                              # puis http://localhost:8000
```

Aucune dépendance externe (bibliothèque standard Python 3.9+).

## Tests sur une branche

Le workflow `test_pipeline.yml` exécute tout le pipeline sur la semaine du 3 au 5 novembre 2026, sans push ntfy
ni commit, lorsqu'un commit de la branche contient `[test]` dans son message (ou `[sans-ia]` pour un test sans appel à
Gemini). C'est fait ainsi pour économiser le quota Gemini.

## Secrets GitHub Actions

- `GEMINI_API_KEY` (optionnel) : sans clé, les résumés sont générés de façon déterministe.
- `NTFY_TOPIC` : topic ntfy (un nom long et difficile à deviner).
- `DASHBOARD_URL` : URL GitHub Pages du dashboard.
