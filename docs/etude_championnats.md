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

## 10. Réponses du propriétaire (25/11/2026) et compléments mesurés

1. **Accueil : option B** (une seule application, URL actuelles conservées).
2. **Journée : Wikipédia d'abord** (football-data.org seulement en secours, avec accord). Mesuré le 25/11 :
   - Wikipédia FR, Ligue 1, Premier League, Liga, Bundesliga : matrice `{{Foot résultat}}` ; chaque case d'un match NON joué vaut `Jnn`
     (journée), un match joué vaut son score. Comptage : PL 281 `Jnn` + 99 scores = 380, Liga 251 + 129 = 380, Bundesliga 216 + 90 = 306,
     L1 idem. Un match reporté garde sa journée d'origine (ex. Rennes `J06` encore non joué).
   - Wikipédia FR, Serie A : pas de matrice ; **Wikipédia IT** (`Serie A 2026-2027`, § Calendario) donne le calendrier complet par
     « giornata », matchs joués compris.
   - Méthode : la journée d'un match est lue AVANT qu'il soit joué (relecture quotidienne, une page par championnat) puis conservée ; pour les
     matchs déjà joués de 2026-27 (reconstitution), lecture d'une révision d'avant le début de la saison (API MediaWiki `prop=revisions`),
     où tous les matchs sont encore `Jnn`. Contrôle déterministe : chaque club joue au plus une fois par journée et une journée a au plus
     N/2 matchs ; rapprochement ESPN ↔ Wikipédia par les deux équipes (alias manuels si besoin) ; incohérence = journée absente, jamais
     devinée. Wikipédia est modifiable par tous : la valeur lue est enregistrée avec la révision (`journee_source`).
   - Wikidata : aucune donnée par match (pas d'élément « match » pour ces saisons) ; inutile ici.
   - Débit : Wikipédia répond HTTP 429 au conteneur de développement après quelques requêtes rapprochées (IP partagée) ; en production,
     5 pages par jour, `Retry-After` respecté (règle de `clubs.py`).
3. **Place** (estimation, JSON non compressé, ~42 Ko par match complet mesuré) :
   | Ensemble | Matchs / saison | Données ESPN | Poids / saison |
   |---|---|---|---|
   | Big 5 | 1 752 | Opta complet + xG | ~75 Mo |
   | Championship (`eng.2`) | 552 | Opta complet + xG (mesuré) | ~23 Mo |
   | Ligue 2, LaLiga 2, Serie B, 2. Bundesliga | ~1 450 | **léger** : ~20 événements, pas d'xG ni de stats Opta (mesuré) : pas de notes ni de momentum | ~15 Mo |
   | Eredivisie (`ned.1`) | 306 | actions complètes, PAS d'xG (mesuré) | ~13 Mo |
   | Belgique, Écosse, Turquie… | — | léger (mesuré sur `bel.1`, `sco.1`, `tur.1`) | ~5 Mo chacun |
   Soit ~110-130 Mo par saison avec les 2es divisions, plus les réécritures dans l'historique git. GitHub recommande moins de 1 Go par dépôt
   et par site Pages : **recommandation : dépôt de données séparé** (publié sur Pages, lu par la page, comme `courses-cyclistes-archives`),
   le code et les coupes restant ici ; un nouveau dépôt d'archives quand il approche de la limite.
4. **Notification : une par jour où des matchs ont été joués**, « Nouveaux résultats disponibles » ; l'accueil met en avant les derniers
   résultats et mène aux pages correspondantes.
5. Momentum : entrée dans la surface adverse remplace « attaque dangereuse » (poids 2). Accordé.
6. Stats par mi-temps : on en ajoute (comptées sur les actions Opta).
7. **Une fiche par club et par joueur** (coupes et championnats réunis).
8. **Saisons passées : historique du classement des clubs seulement.** ESPN donne le classement final officiel (pénalités comprises :
   Serie A 2005-06 = Inter 76 pts) **depuis 2002-03** pour les 5 championnats (mesuré ; rien en 2001-02). Avant 2002-03 : à décider
   (football-data.co.uk depuis 1993, classement recalculé SANS les pénalités de points, donc à signaler comme tel, ou rien).

### Suite des réponses (25/11/2026, après-midi)

- **Dépôt de données : `Camelbaggy/donnees-football`** (créé par le propriétaire), servi par GitHub Pages ; le code reste ici. Ses workflows
  prennent le code de `main` de ce dépôt (public), comme `courses-cyclistes-archives`.
- **Notification commune** coupes + championnats : UNE par jour où des matchs ont été joués, titre qui nomme les compétitions (« Nouveaux
  résultats disponibles en LDC et Ligue 1 »). Remplace la notification par soirée de coupe (étape 3).
- **Historique des classements** : pour le big 5, Wikipédia a une page par saison depuis l'origine (ex. « Championnat d'Allemagne de
  football 1902-1903 ») ; pages locales (DE, IT, ES, EN) si la page FR est incomplète. Étape 6.

## 11. Étape 1 livrée : collecteur des championnats (25/11/2026)

Modules (Python stdlib) : `ligues.py` (ESPN), `journees_wiki.py` (journées), `run_ligues.py` (collecte d'un jour -> dépôt de données),
`tools/inspect_ligues.py` (résumé), workflow d'essai `test_ligues.yml` (`[test-ligues]`) ; côté données :
`donnees-football/.github/workflows/collecte_championnats.yml` (dispatch : jour ou plage).

**Format** : chaque match a EXACTEMENT le schéma des coupes (`collector.build_match`) pour que la page, `ratings.py`, les couleurs et le
momentum servent tels quels ; identifiants `espn-<id>` (matchs, clubs, joueurs) pour ne jamais se confondre avec les ids UEFA.
`championnats/<ligue>/<saison>/<AAAA-MM-JJ>.json` = une « soirée » d'un seul championnat (jour de Paris), `index.json` des jours (avec les
journées présentes), `journees.json` (cache Wikipédia + calendrier ESPN de la saison). Ligues : `fl1`, `pl`, `liga`, `sa`, `bl`.

**Mesuré sur la journée du 22/11/2026** (16 matchs, 5 championnats, depuis le conteneur) :
- ~35 requêtes ESPN et ~18 s par match (stats individuelles comprises) ; 2e passage du même jour : 3 requêtes par championnat, aucun fichier
  réécrit ; ~54 Ko par match publié (JSON compact ; 32 Ko pour les joueurs) -> **~95 Mo par saison** pour le big 5.
- Comptages par mi-temps sur les actions Opta = totaux ESPN du match (tirs, cadrés, contrés, corners, fautes, tacles, interceptions,
  dégagements, hors-jeu ; 10 équipes, écart ≤ 1).
- Notes : moyenne 6,96, écart-type 0,73 à 0,78 selon le championnat (cible ~6,9 / ~0,75).
- Buts reconstitués = score officiel sur les 16 matchs (piège vérifié : un « Own Goal » ESPN porte l'équipe qui BÉNÉFICIE du but).

**Règles propres aux championnats** :
- Momentum : `uefa.compute_momentum` inchangé ; types Opta convertis (`ligues.TYPES`) ; « attaque dangereuse » remplacée par
  `BOX_ENTRY` = passe ou centre partant hors de la surface adverse et y arrivant (coordonnées Opta x ≥ 83, 21,1 ≤ y ≤ 78,9 ; sens d'attaque
  de l'équipe), poids 2 ; faute = coup franc obtenu (0,5) pour l'adversaire de l'équipe fautive (l'action ESPN porte l'équipe FAUTIVE).
- Stats par mi-temps (`ligues.MI_TEMPS`, 14 lignes) : tirs, cadrés, contrés, passes tentées, passes et centres vers la surface, centres,
  corners, hors-jeu, tacles, interceptions, dégagements, arrêts du gardien, fautes, cartons jaunes. Pas de possession ni d'xG par mi-temps.
- Stats d'équipe (`ligues.STATS_EQUIPE`, ~33 lignes, clés UEFA quand elles existent, sinon nouvelles clés rangées dans « Autres » par la
  page jusqu'à l'étape 2) : possession, tirs, xG / xGOT / xA, grosses occasions, passes, entrées dans la surface et dans le dernier tiers,
  duels (dont aériens), PPDA…
- Notes : clés ESPN converties en clés UEFA (`ligues.JOUEUR_CLES`) ; deux substituts documentés : passes courtes réussies = passes réussies
  − longs ballons réussis ; « passes vers l'avant » = passes réussies dans le dernier tiers. Standardisation par championnat ET par jour
  (comme les coupes par soirée). Gardiens : arrêts, buts encaissés pendant son temps de jeu (Opta), clean sheet.
- Compos : positions déduites du poste Opta du match (`G`, `CD-L`, `RB`, `DM`, `AM-R`, `CF-L`…) : ligne (profondeur) + largeur, même
  échelle que les compos UEFA (domicile : droite = x petit, vérifié sur Hakimi / Nuno Mendes) ; formation ESPN.
- Maillot porté : `rosters[].uniform.color` du résumé ESPN -> `shirt_color` (règle des couleurs inchangée).
- Classement : ESPN actuel (`officiel`) tant qu'aucun match du championnat postérieur au jour n'a commencé (calendrier ESPN), sinon celui
  déjà enregistré ; zones ESPN (`ucl`, `uel`, `uecl`, `barrage`, `relegation`) avec leur libellé. Recalcul pour les jours passés : étape 4
  (départages propres à chaque championnat).

**Journées (Wikipédia), mesuré le 25/11/2026** :
- Ligue 1 : 300/306 matchs (18 clubs dont 3 rapprochés par les scores : Auxerre, Lyon, Brest) ; 6 sans journée : la page met Troyes deux
  fois en J33 (erreur de la page, écartée par le contrôle) et une case J30 / J6 contredite par une révision plus récente.
- Premier League : 380/380 ; Serie A (Wikipédia IT) : 380/380 ; Bundesliga : 306/306 (un club, Elversberg, a changé de lien d'une révision
  à l'autre : les noms inconnus d'une ancienne révision sont rapprochés des seuls clubs ESPN absents de cette révision).
- Liga : 371/379. Les 8 matchs sans journée (J1-J3, J8, août 2026) : la page FR n'avait pas encore les journées avant qu'ils soient joués ;
  complément prévu par la page locale (Wikipédia ES, « Primera División de España 2026-27 ») à l'étape 4 (reconstitution). ESPN ne liste que
  379 matchs de Liga sur 380 (à vérifier). Un écart de score Wikipédia / ESPN (Málaga-Villarreal 1-2 contre 1-3) : signalé, à recouper à
  l'étape 3 (football-data.co.uk) ; au-delà de 2 % d'écarts, la correspondance des clubs serait rejetée.
- Essai GitHub Actions du 25/11 (`test_ligues.yml`, run 45622687373) : 16 matchs du 22/11 en 6 min, 0 alerte, xG 16/16 ; classement
  `officiel` pour la Ligue 1, `absent` pour les autres (des matchs postérieurs avaient déjà commencé : règle `classement_valable`).
- Rapprochement des clubs : noms (indice de Jaccard des mots distinctifs, réciproque), puis scores (≥ 3 matchs joués identiques, aucun
  contraire, candidat unique), puis alias manuels `alias_equipes_wiki.json` (aucun nécessaire à ce jour).
- Wikipédia répond souvent HTTP 429 depuis le conteneur de développement (attentes de 40 à 50 s respectées) : ~10 révisions par
  championnat au premier calcul, puis une lecture par jour.

## 12. Étape 2 livrée : accueil et interface des championnats (25/11/2026)

Option B (décision du 25/11) : UNE seule application (`index.html`), aucune URL cassée.
- **Aiguillage** (`route`) : sans paramètre = **accueil** ; `?c=<ucl|uel|uecl>[&tour=]` et `?soiree=AAAA-MM-JJ` = coupes comme avant ;
  `?c=<fl1|pl|liga|sa|bl>[&tour=jN]` = championnat. Entrer dans une compétition depuis l'accueil ajoute une entrée d'historique
  (`entrer`, `history.pushState`) : le retour du téléphone, ou le bouton « ‹ Football » de l'en-tête (`goAccueil`), ramène à l'accueil ;
  les changements de tour / d'onglet restent en `replaceState`.
- **Accueil** (`afficherAccueil`) : « Derniers résultats » = la date la plus récente ayant au moins un match terminé, toutes compétitions
  confondues (index des soirées + `index.json` de chaque championnat) ; un bloc par compétition jouée ce jour-là (tous ses matchs ; un match
  ouvre directement sa fiche, l'en-tête mène à la compétition sur le bon tour), puis une tuile par compétition (3 coupes, 5 championnats :
  tour par défaut, dates, nombre de matchs ; « Données bientôt disponibles » tant qu'un championnat n'a rien publié).
- **Championnats** : mêmes composants que les coupes (menu des tours = journées, liste des résultats, fiche de match, compos, stats,
  momentum, fiche joueur). En-tête « ‹ ⚽ Football · Championnats », 5 onglets (`LIGUE_COURT`), glissement entre championnats
  (`attachTabSwipe`, onglets de l'espace courant ; aucun sur l'accueil). Journées : `buildToursLigue` depuis `index.json`
  (`par_journee` {n: matchs} de chaque jour, `sans_journee`) ; un jour qui mêle deux journées (match reporté) est filtré par `journee` ;
  tour « Autres matchs » pour les matchs sans journée. Pas de focus clubs français ni de surlignage « FRA » (tous les clubs sont du même
  pays) ; **le logo du club remplace le drapeau** (demande du 25/11 : `flag()` rend le logo ESPN réduit à 40 px par le service
  `a.espncdn.com/combiner` pour tout club dont le logo est chez ESPN ; les coupes gardent le drapeau). Classement : légende construite depuis les zones ESPN (`legendeLigue`, `ZONES_FR`, plages de rangs lues), séparateur entre
  zones ; info-bulle de source. Sources affichées selon le match (`m.source`) : « ESPN (données Opta) » au lieu de « UEFA » (stats,
  momentum, compos, méthode de la note). Nouvelles stats Opta rangées dans les rubriques (`STAT_GROUPS`, `PLAYER_STAT_GROUPS` : xG / xGOT /
  xA en 2 décimales, grosses occasions, ballons touchés, interceptions, duels, buts évités…) ; aucune clé dans « Autres ».
- **Données** : `DONNEES` = `https://camelbaggy.github.io/donnees-football/` (ou `?donnees=<url|dossier>` pour un essai local),
  `championnats/<clé>/<saison>/` avec la saison calculée (1er juillet -> 30 juin).
- **Vérifié** (Playwright 390 x 844 tactile, `node tools/test_accueil_ui.js <url> <dossier> [donnees/]`, données réelles des 21-22/11 :
  48 matchs) : accueil (8 tuiles, derniers résultats, fiche ouverte depuis l'accueil), Ligue 1 J11 (onglets, journée, classement à zones),
  fiche de match (xG, momentum, 22 titulaires, fiche joueur), menu des journées, retour à l'accueil, anciens liens `?c=ucl&tour=j5` et
  `?soiree=` ; 0 erreur console, 0 débordement. Tests existants (`test_couleurs_ui.js`, `test_histoire_ui.js`) inchangés et verts
  (ils ouvrent désormais `index.html?c=ucl`).

## 13. Étape 3 livrée : collecte quotidienne et notification commune (25/11/2026)

**Notification commune** (`notification_jour.py`) : une par jour où des matchs ont été joués, toutes compétitions, titre « Nouveaux résultats
disponibles », message « Nouveaux résultats disponibles en LDC et Ligue 1 », lien vers l'accueil (`DASHBOARD_URL`).
- Coupes : la chaîne actuelle (collecte, publication, vérification de la page) est inchangée jusqu'à la vérification ; elle REMET ensuite la soirée
  (`notifie: true` = remise, d'où l'arrêt des relances de `veille.sh`) et tente la notification du jour au lieu de pousser son propre message.
- Championnats : `etat_championnats.json` (racine de donnees-football) `{jour: {statut, ligues: {clé: {statut, matchs, termines}}, maj, alertes?}}` ;
  la notification vérifie en plus que l'`index.json` publié sur Pages compte les mêmes matchs terminés.
- Règle `decider` (pure, testée) : toutes les compétitions jouées le jour J prêtes (complètes et publiées ; partielles admises à partir de 12 h UTC
  le lendemain) ; une famille sans état est attendue jusqu'à 13 h UTC le lendemain, puis réputée sans match ; une seule notification par jour
  (`etat_notifications.json`, 60 jours). Déclencheurs : la chaîne des coupes après sa vérification, et la veille du battement des coupes
  (`veille_notification.sh`, toutes les 10 min, + `veille_secours.yml`) qui relance `notification_jour.yml` pour un jour prêt (hier, avant-hier,
  aujourd'hui) ; ce workflow refait la décision sur une copie fraîche de main avant de pousser.

**Collecte quotidienne** (dépôt donnees-football, code d'ici) : `battement.yml` (~330 min, toutes les 10 min, se relance) + `veille_secours.yml`
(cron horaire :37, relance le battement s'il ne tourne pas) exécutent `veille_ligues.py` : pour aujourd'hui (Paris) et hier jusqu'à 12 h UTC,
relance `collecte_championnats.yml -f date=J` (1) pour le premier relevé du jour à partir de 9 h UTC (le jour existe alors dans l'état, au besoin
`aucun_match` : la notification sait qu'elle n'a pas à attendre), (2) dès qu'ESPN compte plus de matchs prêts que l'état publié. Un match est
« prêt » 2 h après son coup d'envoi s'il est terminé (`DELAI_APRES_COUP_MIN` : Opta complète ses statistiques après le coup de sifflet ; un match
collecté n'est jamais recollecté) ; reportés et annulés ne bloquent pas un jour. Garde-fous : aucun passage en cours, 15 min entre deux passages.
Coût : 10 requêtes ESPN par passage de veille (2 par championnat). Échec de la collecte : alerte ntfy « Échec de mise à jour des championnats »
(une par jour et par cause), avec le secret `NTFY_TOPIC` à ajouter dans donnees-football (sans lui : simulation dans le journal).

**Premier lancement** : donnees-football : « Run workflow » de `battement.yml` (puis il se relance seul) ; coupes-europe : relancer `battement.yml`
(ses scripts ont changé : `veille_notification.sh`).

## 14. Étape 4 livrée : classement recalculé et reconstitution de la saison (25/11/2026)

**Classement recalculé** (`classement_ligue.py`) : ESPN ne donne que le classement actuel ; pour une journée passée il est recalculé depuis
les scores des matchs terminés jusqu'au jour inclus (heure de Paris), `standings_source: "calcule"` + `standings_at`.
- Départage (`CRITERES`) : Premier League, Bundesliga, Ligue 1 : points, différence de buts, buts marqués ; Liga et Serie A : points, puis
  confrontations directes (points puis différence de buts des matchs entre clubs à égalité) SEULEMENT si l'aller et le retour ont été joués,
  puis différence de buts, buts marqués. Critères suivants (fair-play, etc.) non appliqués : égalité résiduelle = même rang, `ex_aequo`, « = »
  à l'écran. Pas de zone ni de pénalité de points (un écart avec ESPN la révélerait : `comparer`).
- **Validé** (`python classement_ligue.py --valider`, 25/11) : calcul à la date du jour = classement officiel ESPN pour les 5 championnats
  (96 clubs, 0 écart de rang, points, matchs joués, différence de buts) ; et au 22/11 = classement officiel relevé ce jour-là (Ligue 1,
  Bundesliga : 0 écart).
- Utilisé par la collecte du jour quand le classement ESPN n'est plus valable (au lieu de recopier un classement plus ancien) et par la
  reconstitution.

**Reconstitution** (`run_ligues.py --reconstituer --budget-min 40`, workflow `reconstitution_championnats.yml` de donnees-football,
auto-relancé tant qu'il reste des jours et que le passage progresse) : jours (heure de Paris) ayant au moins un match terminé, antérieurs à
aujourd'hui, sans fichier publié, du plus récent au plus ancien ; même collecte que le jour même, classement recalculé, `reconstituee: true`
(fichier et ligne d'index) ; jamais d'état du jour ni de notification ; complète aussi le classement des jours collectés en direct sans
classement valable (`standings_source: "absent"`). Estimation : ~650 matchs à rejouer (13 journées x 5 championnats), ~18 s par match :
~3 h 30, soit 5 à 6 passages de 40 min.

**Journées de la Liga** : page locale de secours (`journees_wiki.SECOURS`, Wikipédia ES « Primera División de España 2026-27 », § Resultados,
une table « Jornada N » par journée, matchs joués compris ; `calendrier_es`) lue pour les seuls matchs encore sans journée après la page FR ;
adoptée seulement si ses journées concordent avec celles de la page FR (au plus 2 % d'écart sur les matchs communs), puis le contrôle « un club
une fois par journée » s'applique. Mesuré le 25/11 : 8 journées ajoutées (J1-J3, J8), 372/372 concordantes avec la page FR -> Liga 380/380.

**Interface** : titre « Classement · calculé » + info-bulle propre au championnat (critères, date), « = » des ex æquo ; info-bulle
« Reconstituée » adaptée aux championnats (`RECONSTITUEE_LIGUE_INFO`).
