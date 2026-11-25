# Étude : fiches de club et historique des soirées

Mesures réelles du 25/11/2026, faites depuis le conteneur de développement (UEFA et Wikidata étaient joignables en
direct, aucune sonde Actions ni workflow temporaire n'a été nécessaire). Saison 2026-27 = `seasonYear` 2027.
Aucune valeur n'est devinée : ce qui n'est pas donné par une source reste absent.

## 1. Ce qui existe côté API UEFA

Tous les hôtes répondent sans authentification (User-Agent curl ; `urllib` sans en-tête = HTTP 403, passer par `netutil`).

| Besoin | URL exacte (extraits des paramètres utiles) | Mesure |
|---|---|---|
| (a) Matchs d'un club, une compétition, une saison | `match.uefa.com/v5/matches?competitionId=1&seasonYear=2027&teamId=7889&offset=0&limit=500&language=FR` | Liverpool : 8 matchs (4 joués, 4 à venir, dont celui du jour), 197 Ko, ~25 Ko par match (traductions en 9 langues) |
| (a) Idem pour toute la compétition | même URL sans `teamId` | LDC 234 matchs / 6,8 Mo, LE 224, LC 366 ; 3 requêtes pour 824 matchs |
| (a) Tout l'historique UEFA d'un club | `…/v5/matches?teamId=7889&offset=0&limit=500&order=ASC` (sans `competitionId`) | Liverpool : 473 matchs depuis 1964, 12 Mo, pagination par `offset` OK ; compétitions `UCL`, `UEL`, `ECWC`, `Fairs Cup`, `SCUP`, `EUSA` |
| (b) Identité du club | `comp.uefa.com/v2/teams?teamIds=7889` ou `?competitionId=1&seasonYear=2027&limit=50` | `internationalName`, `displayName`/`displayOfficialName` FR, `teamCode`, `countryCode`, logos 70/240/700 px, `associationId`. **Ni ville, ni stade, ni couleurs, ni entraîneur** |
| (b) Stade et ville | dans chaque match : `stadium.{translations.name.FR, capacity, openingDate, geolocation, pitch, city.translations.name.FR}` | Mesuré sur les matchs à domicile de phase de ligue : 108/108 clubs ont un stade, 110 stades distincts, capacité / ouverture / géolocalisation / ville : 110/110. 4 clubs ont deux stades sur la saison (Beşiktaş, Union SG, CSKA Sofia, Egnatia) : garder le plus fréquent et lister l'autre |
| (c) Effectif inscrit | `comp.uefa.com/v2/players?competitionId=1&seasonYear=2027&offset=0&limit=500` | **Le filtre `teamId`/`clubId` est ignoré** : on lit toute la compétition (LDC : 2 717 joueurs, 6 pages de 500, 122 clubs avec les clubs éliminés des tours préliminaires) puis on filtre sur `clubId`. Champs : `id` (= celui de nos `players`), `internationalName`, `clubShirtName`, `clubJerseyNumber`, `fieldPosition` (4 postes), `birthDate`, `age`, `countryCode`, `imageUrl` (324 px), `height` (renseignée pour seulement 7,5 % des joueurs). Liverpool : 49 inscrits (liste A + jeunes), pas seulement l'équipe première |
| (c) Effectif ayant joué | `compstats.uefa.com/v1/player-ranking?competitionId=1&seasonYear=2027&phase=TOURNAMENT&stats=goals&teamId=7889&limit=50&optionalFields=PLAYER,TEAM&order=DESC` | 27 joueurs pour Liverpool (ceux qui ont des statistiques), `player` complet |
| (d) Statistiques cumulées du club | `compstats.uefa.com/v1/team-statistics?competitionId=1&seasonYear=2027&teamId=7889,52692,79946&stats=goals,ball_possession,…` | **Plusieurs `teamId` et plusieurs `stats` par appel.** `stats` est obligatoire (même vocabulaire que `matchstats`, ~430 noms). 36 clubs d'une compétition en une requête |
| (e) Statistiques cumulées des joueurs | `compstats.uefa.com/v1/player-statistics?playerId=a,b,c&competitionId=1&seasonYear=2027&stats=goals,assists,matches_appearance,minutes_played_official,…` | Plusieurs joueurs et stats par appel (27 joueurs = 93 Ko, 0,5 s). Un joueur sans minutes n'a que les cartons (clé absente = absente) |
| Classement | `standings.uefa.com/v1/standings?competitionId=1&seasonYear=2027` | **Toujours l'état actuel** : `matchdayId`, `matchday`, `sequenceNumber`, `date` sont ignorés (réponses identiques). Seul `previousRank` donne le rang de la journée précédente |

Vérifications d'agrégation (Liverpool, LDC 2027, 4 matchs joués) : `compstats` = somme des 4 `matchstats` pour les stats
comptables (buts 14, tirs 83, cadrés 27, passes réussies 1 862, corners 37, tacles 44, distance 358,58 km,
`played_time` 382), moyenne simple pour `ball_possession` (57,5 = (64+54+62+50)/4) et la précision de passes (89),
maximum pour `top_speed` (35,64). `matches_appearance` = 4. Donc les cumuls officiels existent et se recoupent avec une
agrégation de nos `stats` match par match : on prend les cumuls officiels et on garde l'agrégation comme contrôle.
Réserve : certaines stats physiques sont partielles sur certains matchs (distance de 17,9 km sur un match de Liverpool
contre ~110 ailleurs : suivi incomplet) ; ne pas afficher de total physique sans le nombre de matchs concernés.
`wins/draws/losses` ne sont pas des stats `compstats` : V/N/D se calculent à partir des scores (déterministe).
Palmarès européen : calculable depuis l'historique des matchs (matchs `SINGLE` d'un tour « Final », champ
`winner.match.team.id`, `reason` DRAW = tirs au but). Mesuré sur Liverpool : 15 finales trouvées, vainqueur renseigné.
Piège : `seasonYear` n'a pas la même convention avant et après ~2000 (la finale de 1977 est sous 1976, celle de 2019
sous 2019) : dériver l'année d'une édition de la date du match, jamais de `seasonYear`.

**Volumes et coût pour les 108 clubs** (36 par compétition, `standings` 2027 ; 39 pays) :
- matchs de la saison : 3 requêtes (listes de compétition) = 21 Mo, ~3 s ; on n'en garde que ~15 champs par match ;
- stats cumulées club : 3 compétitions × ~6 paquets de 50 stats = ~20 requêtes de quelques Ko ;
- effectifs : 3 compétitions × 6 pages = ~18 requêtes (~15 Mo au total) ;
- stats joueurs : 108 requêtes `player-ranking?teamId=` (liste des joueurs) puis ~60 requêtes `player-statistics` par paquets
  de 50 ids (~3 000 joueurs) ; ~150 Ko par club avant filtrage, ~6 Ko après ;
- historique européen (une seule fois, hors saison courante) : 108 requêtes, 2 à 12 Mo chacune, ~0,5 Go au total,
  ~5 minutes ; on ne conserve que date / compétition / tour / adversaire / score (~100 octets par match).
Total d'une mise à jour complète : ~210 requêtes, ~60 Mo téléchargés, 3 à 5 minutes (aucune pause nécessaire, les hôtes
UEFA n'ont opposé aucune limite pendant les mesures).

## 2. Wikidata et Wikipédia FR

- **Propriété d'identifiant : P7361 « UEFA team ID »** (valeur numérique = l'`id` d'équipe UEFA, ex. 7889). Requête SPARQL
  unique (`query.wikidata.org`, User-Agent honnête, ~5 s) sur nos 108 ids : **103 clubs rapprochés par identifiant, aucun
  doublon d'élément, 0 erreur de rapprochement** (les 17 noms Wikidata différents du nom UEFA sont de simples variantes :
  « Manchester City F.C. » / « Man City », etc., pays concordant). Les 5 absents n'ont pas de P7361 : Como (Q1120838),
  Sunderland (Q18739), Torreense (Q1853273), Mjällby (Q749138), Sint-Truidense (Q138248). Chacun a un unique candidat par
  libellé ; à valider à la main dans un fichier `alias_clubs_wikidata.json` (même principe que `alias_equipes.json` de
  courses-cyclistes), jamais rapproché automatiquement sans preuve nom + pays + club de football.
- Couverture sur les 103 clubs rapprochés : libellé FR 103, fondation (P571) 103, stade (P115) 102, capacité du stade
  (P1083) 100, ville du siège (P159) 101, site officiel (P856) 102, article Wikipédia FR 103, entraîneur (P286) 103
  (valeur à dater : Wikidata est en retard sur les changements de poste, ne l'afficher qu'avec la date d'extraction ou pas
  du tout), **surnom (P1449) 34 seulement**, **couleurs (P462) 1 seulement** (inutilisable : les couleurs ne viendront pas
  de Wikidata), logo (P154) 49 sur 103.
- Doublons stade / ville : UEFA (stade du jour du match, capacité de l'homologation UEFA) et Wikidata peuvent différer
  (capacité, stade temporaire). Règle proposée : stade et capacité **UEFA** (ce que voit le joueur dans la fiche de match),
  Wikidata en complément (fondation, surnom, site, ville du siège), toujours avec la source affichée.
- **Wikipédia FR** : résumé via `fr.wikipedia.org/api/rest_v1/page/summary/<titre>` (titre lu dans le sitelink Wikidata,
  jamais deviné). Mesuré : 103 titres via Wikidata ; au premier passage à 1 requête / s, 65 extraits obtenus (longueur moyenne 255 caractères, de 57 à 944), **37 réponses HTTP 429** et 1 HTTP 404 : la couverture réelle dépend du rythme (≥ 2-3 s entre requêtes, respecter `Retry-After`, deuxième passage pour les manquants ; un seul remplissage par mois suffit). Texte sous licence CC BY-SA 4.0 : afficher « Source : Wikipédia (CC BY-SA 4.0) » avec lien vers
  l'article et l'historique ; un extrait fait ~250 caractères, c'est un résumé d'introduction, pas une fiche complète.
  Limite : l'API Wikimedia a répondu 429 à 36 % des requêtes à 1 / s (constaté) : User-Agent explicite, pause, reprise sur 429.
- Palmarès européen depuis Wikidata (P166) : non retenu, il faudrait des classes d'éléments de récompense fragiles ; le
  calcul à partir de l'historique des finales UEFA (section 1) est plus sûr.

## 3. Logos

- **UEFA (recommandé)** : `https://img.uefa.com/imgml/TP/teams/logos/{70,240,700}x{n}/<id>.png` : 108/108 clubs
  disponibles aux 3 tailles (HTTP 200, image/png), 240 px = 18 Ko en moyenne (max 62 Ko). Déjà utilisé par le projet
  (`logo` dans `team_info`, mediumLogoUrl). Aucune licence ouverte : ce sont des marques ; l'usage reste le lien direct
  vers l'image de l'UEFA (hotlink) comme aujourd'hui, avec repli sur les initiales si le chargement échoue. Ne pas copier
  les fichiers dans le dépôt (redistribution non couverte).
- Commons : 49 logos sur 103 clubs, licence déclarée « Public domain » (19) / CC BY-SA (8) / CC0 (3) sur l'échantillon de
  30 vérifié par l'API `extmetadata` ; plus de la moitié des clubs n'en ont pas et le statut domaine public d'un logo ne
  lève pas la marque. Sert au mieux de repli avec crédit, pas de source principale.
- Écusson national (`associationLogoUrl`, SVG UEFA) disponible pour le drapeau / la fédération.

## 3 bis. Couleurs des clubs (demande : remplacer bleu domicile / rouge extérieur)

Sources mesurées sur les 108 clubs (207 matchs de phase de ligue joués, `…/v5/matches/{id}/lineups`) :

| Source | Couverture | Qualité mesurée |
|---|---|---|
| **(a) UEFA, compositions** : `homeTeam/awayTeam.shirtColor` (hex) + `kitImageUrl` (`img.uefa.com/imgml/teamkits/<comp>/2027/<teamId>/Kits/pl01.png`, `pl02`, `pl03`, `gk01`) | **108/108 clubs, 207/207 matchs**, aucune requête de plus (déjà dans les compositions collectées ; le code ne lit pas encore ces champs). Maillot domicile `pl01` vu pour 106 clubs (LASK et Freiburg : seulement `pl02`/`pl03`), extérieur `pl02` 63 clubs, 3e maillot `pl03` 35 clubs | **Maillot réellement porté dans le match.** Dans les 207 matchs, les deux couleurs portées ne se ressemblent jamais (ΔE76 minimal 44, 0 match sous 40 ; l'arbitrage des maillots est fait par l'UEFA). Réserve : la valeur est saisie à la main : pour un même maillot, le hex change selon les matchs dans 50 des 208 couples club-maillot (écart médian ΔE 41, ex. Liverpool `pl01` #c63349 puis #ff0000) ; 32 % des maillots portés sont quasi blancs (94 / 414) et 9 % quasi noirs (39) |
| (a bis) Couleur dominante calculée de l'image du maillot (`Kits/pl01.png`, 178×166, PNG transparent, 16 Ko ; quantification 16 niveaux, pixel opaque le plus fréquent) | 106/106 `pl01`, 208/208 maillots lus | Médiane ΔE 3,7 par rapport au hex déclaré (73 clubs sous 15) mais **faux sur les maillots rayés / à deux couleurs** (Inter, Club Brugge : noir au lieu de bleu ; Porto : blanc) : 24 % des maillots écartés de plus de 30 |
| (b) Wikidata P6364 (couleur officielle) via P7361 | 64 clubs / 103 (63 avec code hex P465) ; P462 : 1 club | Valeurs **non ordonnées** (jusqu'à 4 couleurs par club, ex. 007FFF, 77B5FE, B2FFFF, FFFFFF pour l'id 52919), médiane ΔE 84 par rapport au maillot domicile : inutilisable comme couleur principale ; peut servir de couleur secondaire documentaire seulement |
| (c) Couleur dominante calculée du logo UEFA 240 px (pixels opaques, blanc / noir neutres écartés, quantification 16 niveaux) | 108/108 | Médiane ΔE 39 par rapport au maillot domicile (22 clubs sous 15, 45 sous 30) : trop approximatif, dernier recours |

**Règle proposée** (déterministe, zéro valeur inventée) :
1. **Couleur d'une équipe dans un match** = `shirtColor` de la composition de CE match (maillot porté ; disponible dès la
   publication de la composition, ~1 h avant le coup d'envoi). C'est aussi la couleur que le téléspectateur voit.
2. Avant la composition (match à venir, fiche club, classement) : **couleur principale du club** = hex modal des matchs
   joués avec le maillot `pl01` (à défaut `pl02`, puis `pl03`) ; couleur secondaire = hex modal du maillot `pl02`. Stocker le
   nombre de matchs qui fondent chaque valeur (`n`) et la liste des variantes vues.
3. Aucun match joué / aucune composition : repli neutre (bleu domicile / rouge extérieur actuels). Pas de P6364, pas de
   logo en production sauf validation (voir points à décider).
4. **Garde-fou de proximité** (nécessaire pour les couleurs « club » des cas 2-3, car 24 matchs sur 199 auraient des
   couleurs principales proches avec ΔE76 < 25 : Bayern / Arsenal ΔE 2, Real Madrid / Leipzig 0, Atleti / Man Utd 20…) :
   convertir en CIELAB, ΔE76 (ou CIEDE2000 avec seuil ~12) ; si ΔE < 25, l'équipe à l'extérieur prend sa couleur `pl02`
   modale (puis `pl03`), sinon le repli neutre. Avec les couleurs portées (cas 1) le garde-fou ne se déclenche jamais
   sur les 207 matchs mesurés ; il reste actif par sécurité (même ΔE).
5. **Contraste** (WCAG 2.x) : texte sur la couleur = blanc ou `#111` selon le meilleur ratio (≥ 4,5:1 exigé ; sinon texte
   `#111`/blanc le plus contrasté + liseré) ; couleur utilisée comme aplat sur le fond de la page (barres, pastilles,
   momentum) : ratio ≥ 3:1 face à `--bg`/`--card` du thème actif, sinon liseré 1 px de la couleur du texte du thème ou
   mélange vers le thème (une couleur quasi blanche en thème clair, quasi noire en thème sombre). Les deux thèmes sont
   évalués à l'exécution (`prefers-color-scheme` / `data-theme`), jamais figés dans le JSON.
6. **Stockage** : `clubs/index.json` → `couleurs: {principale, secondaire, maillots: {pl01: {hex, n, variantes}, pl02: …},
   source: "uefa_compositions", maj}` ; couleur d'un match déjà joué = `home_team.shirt_color` / `away_team.shirt_color`
   dans la soirée (donnée brute UEFA, absente si non fournie). Un hex invalide est ignoré. Aucune dépendance : calcul Lab et
   contraste en une cinquantaine de lignes JS ; l'agrégation modale se fait en Python lors de la mise à jour des clubs.
7. Utilisations : pastilles et positions des compositions, courbe de momentum, barres de stats (domicile / extérieur),
   en-têtes de fiche de match et de club, point de la forme. Légende explicite car les couleurs ne disent plus
   « domicile / extérieur » : garder le nom ou le sigle de l'équipe à côté de chaque aplat (accessibilité daltonisme).

## 4. Historique de nos soirées (décisions du propriétaire : tout garder, menu déroulant, reconstitution)

### 4.1 Soirées à reconstituer (mesure : matchs `FINISHED` de la saison 2027 au 24/11/2026)

**40 dates, 635 matchs** (LDC 171, LE 152, LC 312) ; 34 matchs de clubs français sur 21 dates.
- **Phase de ligue : 15 dates, 207 matchs, 28 matchs de clubs français** (un français joue à chaque date).
  LDC : 08/09, 09/09, 10/09, 13/10, 14/10, 20/10, 21/10, 03/11, 04/11, 24/11 (6+6+6+9+9+9+9+9+9+9 matchs).
  LE : 16/09 (9), 17/09 (9), 15/10 (18), 22/10 (18), 04/11 (1), 05/11 (17). LC : 15/10 (18), 22/10 (18), 05/11 (18).
  (La soirée du 03-05/11 est déjà dans `data.json` du dépôt pour la semaine de test ; la soirée du 24/11 est celle de `data.json` actuel.)
- **Tours préliminaires : 25 dates, 428 matchs, 6 matchs de clubs français** (4/08, 11/08, 18/08, 26/08, 20/08, 27/08 pour les français) :
  07/07 → 27/08 (le plus gros jour : 42 matchs de LC le 30/07, 40 le 23/07). Les 635 matchs ont tous événements,
  compositions, `team-statistics` et `player-statistics` (testé sur un match de chaque tour de chaque compétition :
  73 à 208 événements, 11 titulaires par équipe, 40 à 46 joueurs). **Différence** : 28 stats d'équipe seulement (au lieu
  de ~430) pour les matchs de tours préliminaires et certains matchs de LE / LC en phase de ligue (194-205 stats) :
  l'interface affiche déjà « absent = absent » ; les notes `ratings.py` se calculent sur `PLAYER_STAT_KEYS` : à vérifier
  sur un tour préliminaire (non fait, pas d'écriture de code de production dans cette étude).
- À venir hors périmètre (déjà dans l'API en `UPCOMING`) : 25-26/11 (LDC 9 matchs, LE 18, LC 18), puis janvier et les tours à élimination.
- Pas de joueur hors UEFA : les matchs des tours préliminaires n'ont pas de fil ESPN fiable (ESPN couvre les clubs
  français : 6 matchs seulement ici) ; repli attendu : pas de fil, `summary_source: "deterministe"` comme aujourd'hui.

### 4.2 Limites de la reconstitution (règle cardinale)

- **Classement du soir** : l'API ne sait donner que le classement actuel. Pour une soirée passée, **ne pas** recopier le
  classement actuel. Deux options (à trancher) : A) `standings: []` et `standings_source: "absent"` (la carte « Classement »
  de la soirée n'est pas affichée) ; B) classement **calculé** à partir des scores des matchs terminés jusqu'à ce soir
  (J, V, N, D, BP, BC, diff., points exacts ; rang par points, diff., buts marqués, puis buts à l'extérieur, victoires, victoires
  extérieur ; les critères suivants de l'UEFA, coefficients et fair-play, non reproduits : rang marqué « provisoire » en cas
  d'égalité résiduelle), avec `standings_source: "calcule"` et une mention visible. **Recommandation : B** pour les 15 soirées de phase de
  ligue, A pour les tours préliminaires (pas de classement). Le dossier donné à Gemini omet le classement dans les deux cas
  sauf calcul B.
- Zone `top8 / playoff / eliminated` : n'a de sens qu'après la dernière journée ; pour une soirée passée, zone absente.
- `ratings`, `momentum`, stats par mi-temps : déterministes à partir des mêmes entrées, donc identiques à ce qu'aurait
  produit la soirée à l'époque.

### 4.3 Coût de la reconstitution

- Par match : événements 1-2 requêtes, compositions 1, `team-statistics` 1 (0,35 Mo), `player-statistics` 1 (**5,3 Mo**,
  0,7 s), soit ~5 requêtes, ~6 Mo, ~2 s mesurées en séquence ; 635 matchs = ~3 200 requêtes, ~3,8 Go téléchargés,
  **~25 min de collecte pure** ; avec notes, momentum, résumés et pauses, estimation 40 à 60 min, soit 1 à 2 passages
  du workflow dédié (budget 50 min, reprenable). Aucune limite de débit rencontrée côté UEFA.
- ESPN : seulement pour les 34 matchs de clubs français (1 recherche de scoreboard par date + 1 requête par match).
- **Gemini** : résumés uniquement pour `french_clubs_focus` (une carte par match de club français) : 34 cartes. Chaque carte
  = 1 à 3 essais, chacun = 1 appel rédacteur + 1 appel contrôleur : 68 appels au minimum, ~120 en moyenne, 204 au pire.
  Les quotas gratuits Flash / Flash-Lite sont séparés par modèle et par jour ; ce volume tient dans un quota quotidien
  de l'ordre de 250 requêtes (valeur à vérifier dans AI Studio, non mesurée) mais pas à côté d'un passage normal ni de tests
  `[test]`. **Proposition** : première passe `[sans-ia]` (repli déterministe, `summary_source: "deterministe"`), puis passes de
  « rattrapage IA » qui ne retraitent que les cartes en repli, 15 cartes par passe (≈ 60 appels), dans l'ordre des dates,
  `AI_BUDGET_SECONDS` borné, sans jamais écrire de résumé non contrôlé ; étaler sur 2-3 jours.

### 4.4 Format de stockage

```
soirees/index.json            [{"date","statut","matchs","competitions":{"ucl":9,…},"francais":n,"resume_ia":bool,"fichier":"soirees/2026-11-04.json"}] trié par date décroissante
soirees/<AAAA-MM-JJ>.json    même schéma que data.json, une seule soirée (competitions.{ucl,uel,uecl}.matches[], standings, french_clubs_focus)
data.json                     = copie de la soirée la plus récente (compatibilité : index.html, notify, publication.py, battement)
```
- `index.json` ne contient pas les matchs : ~200 octets par soirée, ~8 Ko pour 40 soirées ; une soirée par fichier (`players`
  pèse ~60 % d'un match).
- **Poids mesuré** : `data.json` actuel = 1,0 Mo pour 9 matchs de LDC (matchs = 54,7 Ko chacun, classements 38 Ko,
  cartes françaises 2,5 Ko) ; **85 Ko compressés (gzip x12)**, ce que GitHub Pages sert. Les 635 matchs : ~35 Mo bruts,
  **~3 Mo gzip** (matchs de tours préliminaires plus petits : 28 stats). Une saison complète (824 matchs jusqu'à
  la finale) : ~45 Mo bruts, ~4 Mo gzip, soit ~+4 Mo par saison dans le dépôt git (chaque soirée écrite une fois, jamais
  réécrite). Pages : limite de 1 Go de site et 100 Go / mois de bande passante, loin d'être atteintes ; l'utilisateur
  ne télécharge que `index.json` (8 Ko) + une soirée (40-90 Ko gzip).
- Option de réduction (non nécessaire) : retirer `players[].stats` des soirées de plus de 30 jours ; à éviter, la fiche
  joueur en dépend.

### 4.5 Écriture à chaque passage et articulation avec le workflow / le battement

- `run_pipeline.py` (hors `--week` et `--no-notify`) écrit, en plus de `data.json` : `soirees/<date>.json` et la ligne de
  `soirees/index.json` (réécrite si la soirée change, comme `_dump_if_changed`). Tout reste dans le **même commit
  atomique** que `data.json` / `etat_soirees.json` (`publier.sh` ajoute `soirees/` ; `--etat-seul` inchangé), donc la
  vérification de publication de `publication.py` (`last_updated` de `origin/main:data.json`) reste valable ; le fichier
  `soirees/<date>.json` est publié avant la notification, la fiche d'une soirée ouverte depuis le push existe toujours.
- Le battement et `veille.sh` ne changent pas : ils lisent `etat_soirees.json`. `GARDE_JOURS = 60` de `etat_soirees.json`
  ne s'applique pas à `soirees/` (conservation illimitée) ; vérifier que `soirees.py` ne purge que l'état.
- **Reconstitution** : workflow dédié `historique_soirees.yml` (`workflow_dispatch`, concurrency `group: update-dashboard`
  pour ne jamais courir en parallèle d'un passage normal, `timeout-minutes: 55`, auto-relance par `gh workflow run` tant que
  `soirees/index.json` ne couvre pas la liste des dates, même modèle que `battement.yml`). Entrée `python run_pipeline.py --reconstituer
  [--du AAAA-MM-JJ --au …] [--sans-ia] --budget-min 50` : liste les dates à partir de `match.uefa.com` (3 listes de saison), saute
  toute soirée dont `soirees/<date>.json` existe avec statut `complet` (reprenable), écrit chaque soirée au fur et à mesure
  (commit tous les N soirées avec la boucle de 5 essais de `publier.sh`), **ne touche ni `data.json`, ni `etat_soirees.json`,
  ni ntfy** (une soirée reconstituée n'est jamais notifiée). `data.json` n'est remplacé que si la date est postérieure à
  la sienne.
- Une soirée reconstituée porte `reconstituee: true` et `reconstituee_le` ; ses résumés portent `summary_source`.
  Le passage « rattrapage IA » les remplace sans changer le reste.

## 5. Conception recommandée des fiches de club

### 5.1 Fichiers

```
clubs/index.json         108 entrées {id, nom, nom_court, pays, drapeau, logo, competition(s), francais}   ~25 Ko (6 Ko gzip)
clubs/<id UEFA>.json     ~15-25 Ko par club (4-6 Ko gzip) ; total ~2,5 Mo (0,5 Mo gzip)
clubs/historique.json    (une fois) par club : matchs européens [date, comp, tour, adversaire id, score, domicile] ~ +250 Ko
```
Contenu de `clubs/<id>.json` : `identite` (noms, pays, ville / stade / capacité / ouverture / coordonnées **UEFA**, `source`),
`wikidata` (QID, fondation, surnom, site, ville du siège, source P7361 / alias manuel), `wikipedia` (extrait, titre, URL, licence),
`logo` (3 URL UEFA), `saison` (liste des matchs de la saison : `match_id`, date, compétition, tour, domicile / extérieur,
adversaire {id, nom, logo}, score, statut, `soiree` = date si le fichier `soirees/<date>.json` existe), `rang` (classement actuel
de la compétition + `previousRank`), `stats` (cumuls officiels `compstats`, V/N/D calculés, moyennes par match = cumul /
`matches_appearance`, moyenne de la compétition = moyenne des 36 clubs, **calculée** et marquée comme telle), `effectif` (inscrits
par poste avec numéro, âge, nationalité, photo ; `joue: true` et stats cumulées pour ceux qui ont des minutes),
`palmares_europeen` (finales gagnées / perdues calculées depuis `historique.json`), `maj`.

### 5.2 Mise à jour

- **Fin de chaque passage de soirée** (écrit par `run_pipeline.py` à la suite de la collecte) : seuls les clubs dont un
  match a eu lieu (≈ 18 à 36 clubs) : `saison`, `stats`, joueurs, rang ; ~15 à 30 requêtes ajoutées, +1 min. Pas de nouveau
  commit séparé : même commit que `data.json`.
- **Hebdomadaire** (cron lundi, ou `workflow_dispatch`, sans notification) : tout le reste (Wikidata, Wikipédia, effectifs
  complets, prochains matchs, historique) ; ~210 requêtes UEFA + 1 SPARQL + ~103 requêtes Wikipédia à 1 / s (~2 min) ;
  Wikidata et Wikipédia n'ont besoin d'un rafraîchissement que tous les 30 jours (même logique `besoin_*` que le cache
  Wikidata de courses-cyclistes). Mise en cache : un échec d'une source n'écrase jamais la valeur précédente (champ absent
  si jamais obtenu).
- Fusion avec la soirée : le « prochain match » d'un club (UEFA `UPCOMING`) ne dépend pas d'un passage de soirée.

### 5.3 Fiche en onglets (même geste que la fiche de match / joueur)

Tiroir `club-sheet` bâti sur `attachSheetDrag` (fermeture en glissant vers le bas depuis la poignée / l'en-tête ou le
haut de la zone défilante), même pile que `player-sheet` : au-dessus de la fiche de match si ouvert depuis elle. Glissement
horizontal entre onglets : à ajouter à `attachSheetDrag` (aujourd'hui vertical seul ; lignes 1394-1432) ou en second
gestionnaire dx > 1,5 dy qui change d'onglet et ignore les éléments `data-noswipe`. Onglets :
1. **Aperçu** : logo 240 px, nom officiel, pays + drapeau, ville, stade (capacité, ouverture), fondation, surnom,
   extrait Wikipédia + crédit CC BY-SA, position dans la compétition (rang, points, tendance `rankTrend`), forme (5 derniers
   matchs V/N/D calculés), prochain match.
2. **Matchs** : tous les matchs de la saison, groupés par tour, score cliquable → fiche de match si
   `soirees/<date>.json` existe (toutes les soirées, grâce à la reconstitution) ; tours préliminaires inclus ; matchs à venir.
3. **Stats** : cumul et moyenne par match (buts, tirs, tirs cadrés, possession moyenne, passes %, corners, fautes, cartons),
   comparés à la moyenne des 36 clubs de la compétition (barre ou écart signé) ; nombre de matchs sur lequel porte chaque
   statistique ; stats physiques seulement avec la mention « sur N matchs ».
4. **Effectif** : par poste (gardiens, défenseurs, milieux, attaquants), numéro, âge, nationalité (drapeau), buts / passes
   décisives / minutes (UEFA) ; chaque joueur ayant joué ouvre la fiche joueur via `openPlayer` (qui lit aujourd'hui
   `activeMatch.players` : prévoir `openPlayerClub(pid)` qui prend le dernier match joué du joueur) ; les inscrits sans
   minute restent listés sans valeur.
Palmarès européen : encart de l'Aperçu seulement si l'historique est chargé.

### 5.4 Points d'entrée

Nom du club dans l'en-tête de la fiche de match (`modal-home-name` / `modal-away-name`), lignes du classement,
cartes « clubs français » (`fr-card`), compositions (équipe) et fiche joueur (club du joueur). Accueil : menu déroulant
des soirées (`soirees/index.json`, défaut = la plus récente) ; la fiche club suit la soirée choisie pour ses liens de matchs,
et le menu n'affiche que les soirées ayant des matchs.

### 5.5 Coût d'implémentation et risques

- Nouveaux modules : `clubs.py` (collecte UEFA + Wikidata + Wikipédia, tests `--test` hors réseau sur fixtures), changement
  de `run_pipeline.py`, `index.html` (~400 lignes), `historique_soirees.yml`, extension de `verifier_workflows.py`.
- Risques : (1) hotlink des logos UEFA (comportement inchangé mais le nombre d'images augmente) ; (2) effectifs
  `comp.uefa.com` incluant jeunes et joueurs hors équipe première : n'afficher « Effectif » que sur les ids ayant des
  minutes **ou** un numéro de club dans la compétition, avec la mention « inscrits UEFA » ; (3) clubs sans P7361 (5) :
  fiche sans bloc Wikidata/Wikipédia tant que l'alias n'est pas validé ; (4) entraîneur absent de l'UEFA, dépassé sur Wikidata :
  non affiché par défaut ; (5) conventions `seasonYear` incohérentes avant 2000 ; (6) soirées reconstituées sans classement
  d'époque (option B calculée, étiquetée) ; (7) Wikipédia limite le débit ; (8) quota Gemini ; (9) clubs à deux stades :
  afficher le stade le plus fréquent ; (10) un match reporté / rejoué change de date : la clé de soirée est la date UEFA
  `kickOffTime.date` du moment du fichier, `soirees/` n'est donc jamais purgé automatiquement.

## 6. Points à décider

1. Classement des soirées passées : option A (absent) ou B (calculé, étiqueté) ?
2. Reconstituer aussi les tours préliminaires (25 dates, 428 matchs, 6 matchs français) ou seulement la phase de ligue (15 dates, 207 matchs) ?
3. Résumés IA des 34 matchs français passés : tout de suite, par lots étalés sur 2-3 jours, ou repli déterministe définitif ?
4. Historique européen complet des clubs (+0,5 Go téléchargés une fois, ~250 Ko publiés) ou saison courante seulement ?
5. Entraîneur et couleurs : non affichés (non fiables / absents). D'accord ?
6. Valider les 5 alias Wikidata (Como, Sunderland, Torreense, Mjällby, Sint-Truidense).
7. Couleurs : valider la règle (couleur portée du match, puis principale du club, puis neutre), le seuil ΔE 25, et ne pas utiliser P6364 ni la couleur du logo ?
8. Ordre de livraison proposé : (1) `soirees/` + écriture à chaque passage + menu, (2) workflow de reconstitution,
   (3) `clubs/` + fiche club, (4) couleurs (`shirt_color` collecté dès l'étape 1, coût nul), (5) palmarès et historique.
