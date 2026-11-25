# Étude : dashboard des championnats nationaux (big 5)

Date : 25 novembre 2026. Demande du propriétaire : le même dashboard que les Coupes d'Europe pour Ligue 1, Premier League, Liga, Serie A et
Bundesliga (puis d'autres championnats), sous une page d'accueil commune ; mêmes données (matchs, classements, historique des journées,
effectifs, notes, momentum, statistiques détaillées dont xG, fiches clubs et joueurs) SAUF les résumés IA ; collecte quotidienne très fiable.

Tout ce qui suit a été **mesuré sur les API réelles le 25/11/2026** depuis le conteneur de développement (ESPN, OpenLigaDB, football-data.co.uk,
Wikidata y répondent ; l'UEFA non). Aucune valeur n'est supposée : ce qui reste à vérifier est marqué « à vérifier ».

## 1. Source principale : ESPN (flux Opta), la même que pour l'xG actuel

L'UEFA ne couvre pas les championnats. ESPN, déjà utilisé (`espn.py`) pour le fil de commentaires et l'xG, couvre les 5 championnats avec
**le même flux Opta détaillé** pour toute la saison 2026-27 (contrôlé sur un match d'août et un de novembre de chaque championnat).

| Besoin | Endpoint ESPN (sans clé) | Mesuré |
|---|---|---|
| Matchs d'un jour, scores, statut | `site.api.espn.com/apis/site/v2/sports/soccer/<ligue>/scoreboard?dates=AAAAMMJJ` | ligues `fra.1`, `eng.1`, `esp.1`, `ita.1`, `ger.1` |
| Liste de la saison | `sports.core.api.espn.com/v2/sports/soccer/leagues/<ligue>/seasons/2026/types/1/events?limit=400` | 306 matchs en Ligue 1 (18 clubs) |
| Fiche de match | `site.web.api.espn.com/apis/site/v2/sports/soccer/<ligue>/summary?event=<id>` | `keyEvents` (buts, cartons, remplacements), `commentary` (~110 lignes, avec coordonnées X/Y), `boxscore` (28 stats d'équipe), `rosters` (compo, `formation`, `formationPlace`, poste, entrée / sortie, **couleur du maillot porté** `uniform.color`), `gameInfo.venue`, `standings` |
| Toutes les actions | core `…/events/<id>/competitions/<id>/plays?limit=1000` (paginé) | **~1 400 à 1 600 actions Opta par match** : passes, tirs (cadré, non cadré, contré, poteau), arrêts, corners, centres, tacles, interceptions, dégagements, duels aériens, hors-jeu, fautes, cartons, avec équipe, joueurs, minute, score courant |
| Stats d'équipe + xG | core `…/competitors/<équipe>/statistics` | déjà utilisé : `expectedGoals`, `expectedGoalsOnTarget`, `expectedAssists`… |
| Stats d'un joueur dans un match | core `…/competitors/<équipe>/roster/<joueur>/statistics/0` | **~110 stats Opta** : minutes, passes (réussies, longues, dans le dernier tiers), tacles, interceptions, récupérations, duels (sol, air), dribbles, touches, xG, xGOT, xA, grosses occasions créées / manquées, gardiens (arrêts, xG concédés, buts évités, sorties aériennes). Plus riche que l'UEFA (qui n'a ni duels aériens ni interceptions par joueur) |
| Classement | `site.api.espn.com/apis/v2/sports/soccer/<ligue>/standings` | 18 lignes L1 : points, J, G-N-P, buts, rang, variation, zone (`note` : Ligue des champions…) |
| Club | `…/teams/<id>` et `…/teams/<id>/roster` | nom, logos, couleurs ; effectif : âge, date de naissance, nationalité, taille, poids, numéro, poste, blessures |

**Saisons passées** : avant 2026-27 le flux ESPN est l'ancien (≈ 200 actions par match, pas d'xG ni de stats Opta détaillées : mesuré sur
2019, 2022, 2023, 2024, 2025). Conséquence : notes, momentum riche et xG seulement à partir de 2026-27 ; pour les saisons antérieures,
résultats et événements principaux seulement (voir § 4).

### Ce qui manque chez ESPN

- **Numéro de journée** : absent partout (scoreboard, summary, core). Or un match reporté garde sa journée d'origine : on ne peut pas le
  déduire des dates sans risque d'erreur. Sources de la journée :
  - **football-data.org** (API v4, clé GRATUITE à demander, 10 requêtes / min, couvre exactement les 5 championnats avec `matchday`) : une
    requête par championnat et par jour suffit. Recommandé (secret `FOOTBALL_DATA_TOKEN`).
  - **OpenLigaDB** (Bundesliga, ouvert, sans clé) : `api.openligadb.de/getmatchdata/bl1/2026` = 306 matchs avec `groupOrderID` (journée).
  - Les API officielles des ligues (Premier League, LFP, LaLiga, Serie A) existent mais sont réservées à leurs sites (clé dans la page, en-têtes
    d'origine) : **écartées** (même règle que FotMob / SofaScore).
  Rapprochement d'un match ESPN avec la journée : date ±1 jour + les deux équipes (même règle stricte que l'xG : un seul candidat, sinon journée
  absente, jamais devinée).
- **Arbitre, affluence** : souvent vides (affluence 0 mesurée) ; non affichés quand absents.

## 2. Sources secondaires

| Source | Usage | Conditions |
|---|---|---|
| **football-data.co.uk** (CSV, sans clé) | (1) **contrôle croisé** des scores, scores à la pause, tirs, corners, cartons (et xG d'un autre fournisseur, colonnes `HxG` / `AxG`, pour comparer seulement) ; (2) **historique** des championnats depuis 1993 (résultats de toutes les saisons, 22 divisions) pour les classements finaux et palmarès des fiches club | fichier mis à jour ~2 fois par semaine : contrôle a posteriori, pas le soir même. Colonnes de cotes ignorées. Page `mmz4281/<saison>/<division>.csv` (redirection vers `football-data.co.uk`) |
| football-data.org | journée (ci-dessus), 2e source de scores en direct | clé gratuite |
| OpenLigaDB | journée Bundesliga, 2e source de scores Bundesliga | ouvert |
| Wikidata / Wikipédia FR | fiches club (fondation, ville, surnom, extrait), comme `clubs.py` | inchangé |

Écartées : FBref (HTTP 403 : protection anti-robots), Understat (pas de robots.txt lisible, page d'erreur ; données en JS dans la page), FotMob,
SofaScore (règle du projet : aucun contournement), API officielles des ligues (clés internes).

## 3. Ce qui se réutilise du projet actuel

| Brique | Réutilisation | Adaptation |
|---|---|---|
| Momentum (`uefa.compute_momentum`) | même méthode (poids, lissage σ = 2 min par période, normalisation) | les actions viennent des `plays` ESPN : correspondance des types Opta (Goal, Shot On Target, Shot Off Target, Shot Blocked, Shot Hit Woodwork, Save → adversaire, Corner Awarded, Offside, Foul → adversaire = coup franc obtenu). Pas d'« attaque dangereuse » chez Opta : remplacée par **entrée dans la surface / centre / passe dans le dernier tiers** ? → **décision** |
| Stats par mi-temps (`half_stats`) | même principe | comptage sur `plays` : on peut en faire beaucoup plus (passes, tacles…) puisque le flux est complet → **décision** (garder les 4 stats actuelles ou étendre) |
| Notes (`ratings.py`) | même méthode (Ball, Huynh & Varley 2025, standardisation par compétition, calibrage) | clés Opta ESPN au lieu des clés UEFA ; plus de variables disponibles (duels aériens, interceptions) mais les coefficients publiés portent sur un jeu précis : on garde la correspondance la plus proche et on documente. Standardisation **par championnat** |
| Classement recalculé (`classement.py`) | oui, pour l'historique des journées | **départage propre à chaque championnat** : L1 (différence de buts générale, puis…), Liga et Serie A (confrontations directes d'abord), PL (différence de buts, buts marqués, puis confrontations), Bundesliga (différence de buts, buts marqués…) : règlement 2026-27 de chaque ligue à relire et coder, validé contre le classement ESPN (comme les 108 clubs UEFA) |
| Couleurs (`couleurs.py`) | oui | maillot porté = `rosters[].uniform.color` (+ `alternateColor`) |
| xG (`espn.py`) | oui, direct (pas de rapprochement UEFA ↔ ESPN à faire : le match EST le match ESPN) | — |
| Fiches club (`clubs.py`) | structure et interface | données ESPN (club, effectif) + Wikidata / Wikipédia ; rapprochement ESPN ↔ Wikidata : `P13590` (identifiant ESPN, seulement 41 clubs renseignés) sinon alias manuel validé (règle actuelle : jamais de rapprochement automatique flou) |
| Historique / reconstitution / état / battement / notification | oui (modèle éprouvé) | unité = **journée de championnat** (et non soirée de coupe) ; collecte quotidienne (ci-dessous) |
| `index.html` (fiche de match, compos, stats, momentum, joueur, club) | oui, mêmes composants | positions des compos : `formation` + `formationPlace` (grille Opta par formation) au lieu des x/y UEFA → à écrire |

**Clubs présents dans les deux mondes** (PSG, Marseille, Real…) : rapprochement ESPN ↔ UEFA PROUVÉ par les matchs de coupe déjà rapprochés
pour l'xG (même date, même score, deux équipes reconnues) ; une seule fiche club avec ses matchs européens ET de championnat → **décision**
(fiche unique ou deux fiches).

## 4. Historique et fiches

- **Historique des journées** : saison 2026-27 complète reconstituée depuis ESPN (journées 1 à 13 déjà jouées, ~600 matchs, notes / momentum /
  xG compris), comme les 40 soirées de coupe.
- **Saisons passées** (palmarès, classements finaux, bilan du club en championnat) : football-data.co.uk depuis 1993-94 (résultats) ; classement
  final recalculé par le départage de l'époque → à **décider** si l'on va jusque-là dès le départ (étape séparée, comme l'historique européen).
- **Fiches joueurs** : ESPN (bio + stats de chaque match de la saison, cumulées) ; photo ESPN (`headshot`).

## 5. Volume et coût

Par match : summary 1 + plays 2 + stats d'équipe 2 + stats des joueurs ~30 = **~35 requêtes** (0,3 s de pause : ~15 s par match).
Saison : 1 752 matchs (380 × 3 + 306 × 2) ≈ 61 000 requêtes ; un week-end chargé (~50 matchs) ≈ 1 750 requêtes ≈ 12 min, réparties sur
plusieurs passages dans la journée. Reconstitution des 13 premières journées : ~21 000 requêtes, ~1 h 30 sur 2-3 passages.

Poids : ~42 Ko par match publié aujourd'hui (mesuré sur `soirees/`) → **~75 Mo par saison** pour les 5 championnats (contre ~26 Mo pour
les coupes). Le dépôt GitHub Pages grossit d'autant chaque saison (et chaque réécriture d'une journée reste dans l'historique git) :
**décision** : même dépôt, ou dépôt de données séparé publié sur Pages (comme `courses-cyclistes-archives`) ; le code resterait ici.

## 6. Collecte quotidienne fiable

Les championnats jouent du vendredi au lundi, et en semaine certaines journées (mardi-mercredi-jeudi) : **tous les jours** sont possibles.

- **Calendrier connu d'avance** : chaque jour, liste des matchs du jour et des 7 jours suivants (scoreboard ESPN par date, 5 requêtes / jour) →
  `etat_journees.json` (par championnat et par date : `statut` complet / partiel / aucun_match, `notifie`, `matchs`, `termines`, heure du dernier
  coup d'envoi prévu).
- **Battement** : le `battement.yml` existant (toutes les 10 min) gagne une 2e règle : pour CHAQUE jour (plus seulement mar-mer-jeu), dès qu'un
  match d'un championnat est terminé depuis ≥ 15 min et pas encore collecté (heure de fin estimée = coup d'envoi + 115 min), il lance
  `update_championnats.yml` pour ce jour. Plusieurs passages par jour (matchs de 13 h à 23 h) : chaque passage ne collecte QUE les matchs
  terminés non encore collectés (pas de re-collecte, pas de journée réécrite inutilement).
- **Secours** : `veille_secours.yml` (cron horaire) inchangé dans son principe ; il relance aussi le battement s'il ne tourne pas.
- **Rattrapage** : si un passage échoue (API indisponible), le match reste « à collecter » et le passage suivant le reprend ; un jour reste
  `partiel` jusqu'au lendemain 13 h UTC, puis est notifié tel quel (règle actuelle).
- **Contrôle croisé différé** : chaque jour, comparaison des scores publiés avec football-data.co.uk (et football-data.org si la clé est
  donnée) ; tout écart = alerte ntfy distincte (jamais de correction automatique).
- **Groupes de concurrence distincts** (`update-championnats` ≠ `update-dashboard`) : un week-end de championnat et une soirée de coupe ne se
  bloquent pas ; `publier.sh` (commit + push robuste) déjà prévu pour plusieurs auteurs sur `main`.
- **Notification** : une par jour et par championnat, une par jour tous championnats confondus, ou une par journée complète → **décision**.

## 7. Page d'accueil

Nouvelle page racine : tuiles « Coupes d'Europe » (LDC, LE, LC) et « Championnats » (L1, PL, Liga, Serie A, Bundesliga), chacune avec le
dernier résultat / prochain match, le club français ou le leader, la journée en cours. Chaque tuile mène au dashboard de la compétition (même
interface : menu des journées, résultats, classement, fiches).

**Point d'attention** : aujourd'hui `index.html` (racine) EST le dashboard des coupes, et les notifications ntfy pointent dessus
(`?c=ucl&tour=j5`). Deux options → **décision** :
- (A) page d'accueil à la racine, coupes déplacées sous `coupes/` (les anciennes URL `?c=…` redirigées vers `coupes/?c=…`) ;
- (B) UNE seule page (la même application) : l'accueil devient la première vue, les onglets LDC / LE / LC actuels deviennent les sections d'une
  compétition choisie ; les URL actuelles restent valides. Recommandé : aucun lien cassé, composants partagés sans copie.

## 8. Plan proposé (livraison par étapes, chacune testée sur données réelles via Actions)

1. **Collecteur championnats** (`espn_ligues.py` + `championnats.py`) : matchs, événements, compos, stats d'équipe et de joueur, xG, momentum,
   stats par mi-temps, notes, classement ; journée via football-data.org / OpenLigaDB. Sortie `championnats/<ligue>/<journée>.json` + index.
   Workflow de test `[test-ligues]`.
2. **Page d'accueil + interface** des championnats (réutilisation des composants) ; option B ci-dessus.
3. **Collecte quotidienne fiable** : état par jour, battement tous les jours, notification, alertes, contrôle croisé.
4. **Reconstitution** des journées 1 à 13 de 2026-27.
5. **Fiches club et joueur** des 96 clubs (rapprochement ESPN ↔ UEFA ↔ Wikidata, alias validés).
6. (option) **Historique des championnats** depuis 1993 (football-data.co.uk) : classements finaux, palmarès.
7. Élargissement à d'autres championnats (ESPN : `por.1`, `ned.1`, `bel.1`, `fra.2`… à vérifier un par un : le flux Opta détaillé n'est
   peut-être pas présent partout).

## 9. Décisions demandées au propriétaire

1. Page d'accueil : option A (coupes sous `coupes/`) ou **B (une seule application, URL actuelles conservées)** ?
2. Clé gratuite football-data.org pour la journée des 4 championnats hors Bundesliga (sinon : journée absente, matchs groupés par date) ?
3. Dépôt : données des championnats dans ce dépôt ou dans un dépôt de données séparé (~75 Mo par saison) ?
4. Notification : par jour tous championnats confondus, par championnat et par jour, ou à la fin de chaque journée ? Contenu : tous les
   résultats, ou seulement la Ligue 1 + les affiches des autres championnats ?
5. Momentum : remplacer « attaque dangereuse » (absente chez Opta) par entrée dans la surface adverse (poids 2) ?
6. Stats par mi-temps : garder les 4 actuelles (tirs, cadrés, corners, jaunes) ou étendre (passes, possession calculée…) ?
7. Fiche club unique pour un club présent en coupe et en championnat (recommandé) ?
8. Historique des saisons passées (depuis 1993) : dès maintenant ou plus tard ?
