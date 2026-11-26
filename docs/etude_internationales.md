# Étude : compétitions internationales (Coupe du monde, Euro, Ligue des nations, Coupe du monde des clubs)

Date : 26 novembre 2026. Demande du propriétaire : après les coupes d'Europe et les championnats, ajouter les compétitions internationales,
en commençant par la Coupe du monde, l'Euro, la Ligue des nations et la Coupe du monde des clubs ; ensuite les équivalents de l'Euro sur
les autres continents (CAN, Copa América, Coupe d'Asie…), puis réflexion sur les matchs amicaux.

Tout ce qui suit a été **mesuré sur les API réelles le 26/11/2026 depuis le conteneur de développement** (UEFA, ESPN et FIFA y répondent ;
Wikipédia répond HTTP 429). Ce qui reste à vérifier est marqué « à vérifier ». Aucune valeur n'est supposée.

## 1. Calendrier : ce qui se joue, ce qui est fini

| Compétition | Dernière édition | Prochain match | Remarque |
|---|---|---|---|
| Coupe du monde | 2026 (11/06 → 19/07, 104 matchs, 48 équipes, finale Espagne - Argentine 1-0) | éliminatoires 2030 : pas encore au calendrier UEFA / ESPN | édition entière à reconstituer |
| Euro | 2024 (51 matchs de phase finale + 230 d'éliminatoires + 9 barrages chez l'UEFA) | éliminatoires de l'Euro 2028 : **aucun match publié** par l'UEFA au 26/11 (à vérifier après le tirage) | |
| Ligue des nations | 2026-27 : phase de ligue finie le 17/11 (14 groupes, ligues A à D) | **mars 2027** : 8 quarts de finale + 16 matchs de barrages (déjà au calendrier UEFA) ; finale à 4 en juin 2027 | édition EN COURS |
| Coupe du monde des clubs | 2025 (États-Unis, finale Chelsea - Paris SG 3-0) | 2029 | |
| Coupe intercontinentale FIFA (annuelle, depuis 2024) | 2026 en cours | **9/12, 12/12, puis finale le 16/12/2026 : Paris SG contre le vainqueur** | seul match international « français » avant mars 2027 |

Conséquence : il n'y a aucun match de sélection avant mars 2027. Le chantier peut se construire sur des éditions FINIES (reconstitution),
puis être prêt pour la Ligue des nations de mars 2027. La finale intercontinentale du PSG (16/12) est la seule échéance proche.

## 2. Sources mesurées

### UEFA (même API que les coupes d'Europe, sans clé)

| Identifiant UEFA | Contenu | Données mesurées |
|---|---|---|
| `3` | Euro (phase finale ET éliminatoires, même identifiant ; type de tour `QUALIFYING`, `GROUP_STANDINGS`, `ROUND_OF_16`…) | Euro 2024 : 290 matchs ; Autriche - France : 126 actions `events?filter=ALL` (tirs, arrêts, corners, fautes…), 382 stats d'équipe, 50 joueurs, compos avec maillot porté ; classement en 6 groupes. Historique : **toutes les éditions depuis 1960** (1960 : 30 matchs) |
| `2014` | Ligue des nations | 2026-27 : 142 matchs de phase de ligue (2019 : 142), 198 actions, 195 stats d'équipe, 45 joueurs, compos ; classement en **14 groupes** (A1 … D2) ; mars 2027 déjà publié |
| `17` | Coupe du monde : éliminatoires de la zone Europe ET phase finale | éliminatoires 2026 : Azerbaïdjan - France 174 actions, 193 stats ; **phase finale 2026 : les 104 matchs sont là, mais 10 à 20 actions par match (buts, cartons, remplacements) et AUCUNE statistique** (ni équipe ni joueur), y compris pour les matchs de la France |
| `19` | Matchs amicaux (sélections européennes) | 17 à 23 par jour de fenêtre internationale (à étudier avec les amicaux) |
| `18`, `13`, `23`, `24`… | Euro féminin, Espoirs, U17, U19 | hors périmètre |

Pièges déjà connus des coupes (`CLAUDE.md`, § API UEFA) valables tels quels. Sélections : `countryCode` = code pays (France = `FRA`) ;
`confederationType` donne la confédération (UEFA, CONMEBOL…).

### ESPN (même flux que les championnats)

| Ligue ESPN | Édition | Actions (`plays`) | xG | Statut |
|---|---|---|---|---|
| `fifa.world` | 2026 | 1 450 à 1 970 par match (Opta complet) | **oui** (xG, xGOT, xA…) | flux complet, comme le big 5 |
| `fifa.world` | 2022 | 287 (ancien flux) | non | réduit |
| `uefa.nations` | 2026-27 (nov.) | 1 340 à 1 620 | **non** (157 stats, aucune `expected*`) | complet sans xG (comme Portugal / Pays-Bas) |
| `uefa.nations` | 2024-25 | ~210 | non | ancien flux |
| `uefa.euro` | 2024 | 179 à 190 | non | ancien flux |
| `fifa.worldq.uefa` | éliminatoires 2026 | 170 à 215 | non | ancien flux |
| `fifa.cwc` | 2025 | 186 à 191 | non | ancien flux |
| `fifa.intercontinental_cup` | 2026 | 20 | non | actions clés seulement |
| `fifa.friendly` | 2026 | 0 à 1 400 selon le match | non | inégal |

Compos placées (`formationPlace`), maillot porté, commentaires et `keyEvents` présents partout. Autres continents (pour plus tard) :
ESPN a aussi `caf.nations`, `conmebol.america`, `afc.asian.cup`, `concacaf.gold` (à mesurer à l'étape « autres continents »).

### FIFA (`api.fifa.com/api/v3`, publique, sans clé, en français)

- Saisons de la Coupe du monde depuis **1930** (23 éditions ; 1930 : 18 matchs, finale Uruguay 4-2 Argentine) ; Coupe du monde des clubs
  2007-2023 et Coupe intercontinentale 2024-2026 (identifiant 107). La Coupe du monde des clubs 2025 n'apparaît pas sous 107 (à vérifier).
- Calendrier 2026 : 104 matchs, noms français officiels (« Espagne », « Argentine »), tours (`StageName`), groupes, programme de la
  Coupe intercontinentale (finale PSG le 16/12).
- Fiche de match (`live/football/…`) : compos (26 joueurs, système « 4-1-2-3 »), arbitres, affluence, stade, possession ; déroulé
  (`timelines/…`) : 128 événements pour la finale 2026 (fautes, tentatives, arrêts, corners, buts, cartons) mais 6 pour la finale 1930.
- Pas de statistique détaillée par joueur mesurée. Cette API n'est pas documentée publiquement : même nature que celle d'uefa.com
  (servie au site officiel, sans clé, sans protection) → **décision du propriétaire** (§ 6, question 3).

### Wikipédia / Wikidata

Comme pour les clubs : fiches des sélections (fondation de la fédération, surnom, extrait). Palmarès : calculé depuis les matchs
officiels (UEFA, FIFA), jamais recopié.

## 3. Source retenue par compétition (proposition)

| Compétition | Source principale | Complément |
|---|---|---|
| Euro (2024 et éliminatoires 2028) | UEFA (`3`) : données riches, comme les coupes | — (ESPN n'a ni xG ni flux complet pour 2024) |
| Ligue des nations | UEFA (`2014`) | ESPN pour le direct de la page |
| Éliminatoires de la Coupe du monde, zone Europe | UEFA (`17`) | |
| Coupe du monde (phase finale 2026) | **ESPN `fifa.world`** (Opta complet + xG) : l'UEFA n'a aucune statistique | UEFA ou FIFA pour contrôler les scores ; FIFA pour les noms français |
| Coupe du monde des clubs 2025, Coupe intercontinentale | ESPN (flux réduit) ou FIFA | |
| Historique (palmarès, bilans) | UEFA (Euro depuis 1960, Ligue des nations depuis 2019) ; FIFA (Coupe du monde depuis 1930) | |

Les deux collecteurs existent déjà : `collector.build_match` (UEFA) et `ligues.py` (ESPN, schéma des coupes, momentum, notes,
`flux: "reduit"` quand les actions manquent). Momentum, stats par mi-temps et notes restent calculés par les mêmes fonctions (notes
calibrées PAR COMPÉTITION). Une Coupe du monde des clubs 2025 en flux réduit n'aura ni momentum ni notes (règle de la Ligue 2).

## 4. Ce qui est NOUVEAU par rapport aux coupes et aux championnats

1. **Édition plutôt que saison** : Euro 2024, Coupe du monde 2026, Ligue des nations 2026-27 ; une page = une édition, avec ses phases
   (éliminatoires, phase de groupes / de ligue, phase finale).
2. **Classements à plusieurs groupes** (6 à l'Euro, 12 à la Coupe du monde 2026, 14 en Ligue des nations, groupes d'éliminatoires) et
   **meilleurs troisièmes** (Euro, Coupe du monde 2026) : classements officiels quand l'API les donne (UEFA : oui pour l'Euro et la Ligue
   des nations ; vide pour la Coupe du monde), sinon recalculés avec le règlement de la compétition (`classement.py` étendu : départage à
   vérifier par compétition, jamais deviné : égalité non départagée = même rang + « = »).
3. **Tableau final** (huitièmes → finale ; seizièmes en 2026) : nouveau composant, aucun équivalent dans la page (la phase finale des
   coupes d'Europe n'a pas encore été affichée non plus : il servira aux deux).
4. **Équipe = sélection** : drapeau au lieu du logo, **focus « Équipe de France »** (carte et surlignage) à la place des clubs français,
   fiche de sélection (effectif de l'édition, matchs, statistiques, palmarès calculé, historique depuis 1930 / 1960), joueurs reliés aux
   fiches de club existantes quand l'identifiant UEFA est le même (à vérifier : les `id` de joueurs UEFA sont communs aux compétitions).
5. **Coupe du monde des clubs** : des CLUBS (fiches de club existantes réutilisées, focus clubs français comme les coupes d'Europe).

## 5. Plan proposé (livraison par étapes, chacune testée sur données réelles)

1. **Collecteur et reconstitution** (`internationales.py`, `run_internationales.py`) : une compétition / édition -> fichiers par jour au
   schéma des coupes (plus `groupe`, `phase`), classements par groupe, programme ; reconstitution de l'Euro 2024, de la Coupe du monde 2026,
   de la Ligue des nations 2024-25 et 2026-27 (phase de ligue), de la Coupe du monde des clubs 2025 et de la Coupe intercontinentale 2026.
   Stockage proposé : dépôt **donnees-football**, `internationales/<compétition>/<édition>/` (même modèle que `championnats/`).
2. **Interface** : 4 tuiles sur l'accueil (« Sélections » : Coupe du monde, Euro, Ligue des nations ; « Clubs » : Coupe du monde des clubs /
   Coupe intercontinentale), menu des éditions et des tours, classements par groupe, tableau final, focus France, URL `?c=cdm&ed=2026&tour=…`.
3. **Collecte des soirs de match** (fenêtres internationales de mars, juin, septembre, octobre, novembre ; tournois d'été) : veille, état,
   intégration à la notification commune du jour, bloc « En direct » de la page, alertes ntfy en direct pour les matchs de l'équipe de France
   (extension de `direct_clubs.py`) et de la finale intercontinentale du PSG.
4. **Fiches de sélection et historique** : palmarès et bilans calculés depuis 1930 (FIFA) / 1960 (UEFA), effectifs, liens vers les fiches
   de club.
5. **Éliminatoires** Euro 2028 / Coupe du monde 2030 dès leur publication par l'UEFA.

Ensuite : autres continents (CAN, Copa América, Coupe d'Asie, Gold Cup : ESPN, à mesurer), puis amicaux (UEFA `19` pour les sélections
européennes, ESPN `fifa.friendly` inégal).

## 6. Décisions demandées au propriétaire

1. **Périmètre** : phases finales seulement, ou aussi les **éliminatoires** (Euro, Coupe du monde zone Europe) ? Recommandation : oui, ce
   sont la plupart des matchs de l'équipe de France hors tournoi, et les données UEFA y sont riches.
2. **Coupe intercontinentale** (annuelle) rangée avec la Coupe du monde des clubs (« compétitions mondiales de clubs ») et livrée en premier
   pour la finale du PSG le 16/12 ? Recommandation : oui.
3. **API de la FIFA** (publique, sans clé, non documentée, même nature que celle d'uefa.com) : l'utiliser pour l'historique de la Coupe du
   monde depuis 1930, les noms français et le contrôle des scores ? Sans elle : historique de la Coupe du monde à reconstruire depuis
   Wikipédia (plus fragile) et ESPN seul pour 2026.
4. **Résumés IA** (Gemini, comme les clubs français en coupe d'Europe) pour les matchs de l'équipe de France ? ~10 à 17 matchs par an.
   Recommandation : oui.
5. **Notification** : compétitions internationales dans la notification commune du jour (« Nouveaux résultats disponibles en Ligue des
   nations et Ligue 1 ») ? Toutes, ou seulement les jours où joue la France ?
6. **Alertes en direct** (coup d'envoi, buts, fin) pour les matchs de l'équipe de France, comme pour les clubs français ?
7. **Stockage** dans donnees-football (`internationales/`) plutôt que dans ce dépôt ? Recommandation : donnees-football.
8. **Profondeur de la reconstitution détaillée** (fiches de match complètes) : seulement les éditions récentes listées à l'étape 1, l'historique
   ancien se limitant aux résultats (palmarès, bilans) ? Recommandation : oui.

## 7. Réponses du propriétaire (26/11/2026)

1. **Éliminatoires** : oui (Euro, Coupe du monde zone Europe).
2. **Coupe intercontinentale** : compétition À PART, rangée comme la Coupe du monde des clubs **avec les coupes européennes** (compétitions de
   clubs), pas avec les sélections.
3. **API de la FIFA** : oui.
4. **Résumés** : IA (Gemini) pour les nouveaux matchs de l'équipe de France ; résumé automatique (déterministe) pour les anciens quand les
   données le permettent.
5. **Notification commune du jour** : les jours où joue la France, et les compétitions majeures (phases finales de l'Euro et de la Coupe du
   monde) ; pas la Ligue des nations ni les éliminatoires sans la France.
6. **Alertes en direct** des matchs de l'équipe de France : oui.
7. **Stockage** : donnees-football.
8. **Profondeur** : fiches de match complètes pour les éditions récentes seulement ; résultats seuls pour l'historique ancien.

Conséquences sur le plan : deux familles. (a) **Sélections** : Coupe du monde (`cdm`), Euro (`euro`), Ligue des nations (`ldn`), avec leurs
éliminatoires. (b) **Clubs, monde** : Coupe du monde des clubs (`cdmc`), Coupe intercontinentale (`ci`), affichées avec les coupes d'Europe
(focus clubs français, fiches de club existantes). Même collecteur pour les deux (`internationales.py`), même dépôt de données
(`donnees-football/internationales/<compétition>/<édition>/`).

## 8. Étape 1 livrée : collecteur et reconstitution (26/11/2026)

`internationales.py` (sources, listes d'édition, collecte d'un jour, classements, programme ; `--test`) et `run_internationales.py` (fichiers de
donnees-football, reconstitution ; `--test`). Essais réels depuis le conteneur (26/11/2026) :

| Cas | Résultat |
|---|---|
| Listes d'édition | CdM 2026 : 308 matchs (204 éliminatoires UEFA + 104 FIFA) ; Euro 2024 : 290 ; Ligue des nations 2026-27 : 180 (dont 24 en mars 2027) ; CdMC 2025 : 63 ; CI 2026 : 5 (finale PSG le 16/12, adversaire « W4 ») |
| Finale CdM 2026 (ESPN) | Espagne 1-0 Argentine (but de Ferran Torres, 106e), 1 966 actions, momentum, 33 stats dont xG 2,29 - 0,22, 34 joueurs notés (moyenne 6,88), stade officiel FIFA « Stade de New York/New Jersey » |
| CdM 2026, 16/06 | France 3-1 Sénégal et 2 autres matchs : 1 470-1 580 actions, 80 joueurs notés (6,99 ± 0,72) |
| Euro 2024, 17/06 (UEFA) | Autriche 0-1 France et 2 autres : momentum, 22 stats, ~31 joueurs, 2 s par match |
| CdMC 2025, finale | Chelsea 3-0 Paris SG : 191 actions -> flux réduit (ni momentum ni notes), drapeaux par le pays FIFA, PSG `is_french` |
| CI 2026 | 2 jours reconstitués (14-20 actions, flux réduit) ; programme des 3 matchs de décembre avec places à déterminer |
| Classements | CdM 2026 : 12 groupes d'éliminatoires (UEFA) + 12 groupes (ESPN, zones) ; Euro 2024 : 10 + 6 ; Ligue des nations 2026-27 : 14 ; CdMC 2025 : 8 |

Limites connues : classement d'une date passée non recalculé (seul l'état final / actuel des groupes est publié) ; pas de tirs au but relevés
dans la phase finale 2026 chez la FIFA (aucune séance ? à vérifier sur l'interface) ; les joueurs des matchs ESPN ont des identifiants `espn-…`,
ceux des matchs UEFA les identifiants UEFA (rapprochement à faire avec les fiches de sélection, étape 4).

## 9. Étapes 2 et 3 livrées (26/11/2026)

- **Interface** : espace « Sélections nationales » (cdm, euro, ldn) ; cdmc et ci dans l'espace des coupes (« Coupes de clubs », 5 onglets) ;
  menu des tours par édition (id `<édition>-<tour>`, ex. `?c=cdm&tour=2026-finale`), tableaux de groupe repliables (groupe de la France
  d'abord), tableau final, programme (« À déterminer (W4) »), direct ESPN. Essai `tools/test_internationales_ui.js` : 51 contrôles verts.
- **Collecte du jour** : `run_internationales.py --date J --etat` (toutes compétitions ; éditions candidates = édition de la date + 1 à 4
  années pour cdm / euro), `etat_internationales.json` (`france`, `phase_finale` par compétition) ; veille dans `veille_ligues.py` (famille
  « internationales » : ne lance rien un jour sans match international).
- **Notification commune** : cdmc / ci toujours ; cdm / euro / ldn si la France joue ou phase finale (groupes / élimination directe) de
  l'Euro ou de la Coupe du monde. Un jour sans état international n'est jamais attendu.
- **Alertes en direct** : Euro, Ligue des nations, Coupe du monde (UEFA) pour l'équipe de France ; cdmc / ci (ESPN + liste FIFA pour
  reconnaître un club français). Rejeu simulé : France 2-1 Turquie (Ligue des nations, 15/11/2026), Chelsea 3-0 PSG (finale CdMC 2025).

## 10. Étape 4 livrée : historique, résultats seuls (26/11/2026)

`histoire_internationale.py` (+ `tools/fixtures_histoire_internationale.py`, fixtures réelles allégées dans `tools/fixtures/histoire_internationale/`, workflow
`historique_internationales.yml` de donnees-football). Décision 8 du propriétaire : fiches de match complètes pour les éditions récentes seulement ; pour toutes les
autres, RÉSULTATS (score, tirs au but, tour, groupe, statut), palmarès et bilans calculés. Format et règles : docstring du module et CLAUDE.md.

**Sources mesurées.** FIFA : Coupe du monde (compétition 17) 23 éditions 1930-2026 avec 18 / 17 / 18 / 22 / 26 / 35 / 32 / 32 / 32 / 38 / 38 / 52 ×4 / 64 ×7 / 104 matchs
(nombres exacts de l'histoire) ; Coupe du monde des clubs 2000, 2005-2023 (107) et 2025 (10005) ; Coupe intercontinentale 2024-2026 (107). UEFA : Euro (3) 17 éditions,
`seasonYear` = année NOMINALE (Euro 2020 joué en 2021 : 2020 ; 0 match publié pour 2028) ; Ligue des nations (2014) 2019, 2021, 2023, 2025, 2027 (`seasonYear` = année de fin
de saison).

**`ResultType` FIFA** (vérifié sur des cas connus) : 1 = temps réglementaire (finales 1998, 2018) ; 2 = tirs au but (finales 1994, 2006, 2022) ; 3 = prolongation (finales
1966, 1978, 2010, 2014, 2026 ; 1934 ; Brésil - Pologne 1938) ; 8 = but en or (France - Paraguay 1998, Sénégal - Suède, Corée - Italie, Sénégal - Turquie en 2002). Le score est
APRÈS prolongation, tirs au but exclus ; `HomeTeamPenaltyScore` vaut 0 / 0 en l'absence de séance (d'où le test sur `ResultType`). `Winner` est un `IdTeam` (absent sur un nul,
y compris les matchs à rejouer de 1934 / 1938). `MatchStatus` 9 n'apparaît qu'une fois (Coupe du monde des clubs 2020, Al Duhail - Auckland City 3-0, Auckland s'étant retiré) :
traité en forfait (jamais compté).

**Pièges de source.**
- Libellés de tour FIFA hétérogènes (« Matches de groupes », « Group Stage », « 1er tour », « Premier tour », « 2e tour », « Deuxième tour », « 5e place », « Bronze final »,
  libellés anglais de la Coupe intercontinentale 2025) : ramenés à ceux de l'UEFA ; un libellé inconnu reste tel quel (jamais inventé).
- UEFA : `round.phase = TOURNAMENT` contient, de 1960 à 1976, les huitièmes et quarts de finale à DEUX MANCHES, qui sont des éliminatoires (la phase finale n'a que 4 équipes) ;
  la règle (`deux_manches_q`) ne vaut que pour l'Euro (les quarts à deux manches de la Ligue des nations 2025 sont bien de la compétition).
- UEFA : `kickOffTime.date` est la date LOCALE (décalage de 6 h pour une éliminatoire en Asie centrale) : le jour UTC est lu dans `dateTime`.
- UEFA : la source dit « nul » sans désigner d'équipe quand une finale se joue aux tirs au but (1976, 1980) ; seul `score.penalty` tranche. Finale de 1960 : raison UEFA
  « WIN_REGULAR » alors que le score est 1-1 après le temps réglementaire et 2-1 après prolongation (l'équipe désignée est la bonne).
- FIFA : clubs d'une même nation sous deux noms (« Real Madrid CF » / « Real Madrid C.F. ») : l'identifiant `IdTeam` est stable, le nom est celui de l'édition.
- Pays disparus : codes d'ÉPOQUE de la source, identiques entre FIFA et UEFA (URS, FRG, GDR, TCH, YUG, SCG), plus CIS (UEFA 1992), ZAI et INH (FIFA). `FLAG_CODES` n'a ni ces
  codes (voulu : drapeau vide) ni KUW / PRK / PNG, pays existants ajoutés à `FLAGS_COMPLEMENT` ; reste sans drapeau le club de Tahiti (AS Pirae, code pays TAH).

**Résultats de l'essai réel complet** (77 requêtes, 58 s, 69 éditions, 5 388 matchs : cdm 1 068, euro 3 233, ldn 848, cdmc 224, ci 15 ; 1,4 Mo bruts / 0,5 Mo gzip pour 201
équipes) : vainqueurs de la Coupe du monde 1930-2022 (URU, ITA, ITA, URU, RFA, BRA, BRA, ENG, BRA, RFA, ARG, ITA, ARG, RFA, BRA, FRA, BRA, ITA, ESP, ALL, FRA, ARG) et de l'Euro
1960-2024 (URS, ESP, ITA, RFA, TCH, RFA, FRA, PAYS-BAS, DAN, ALL, FRA, GRE, ESP, ESP, POR, ITA, ESP) conformes à l'histoire ; finalistes et troisièmes aussi ; Coupe du monde 1950 =
Uruguay par la poule finale (5 points contre 4 au Brésil). Aucun `ecarts` entre le calcul et la source. Un seul `?` : Coupe du monde des clubs 2019, source FIFA défaillante
(6 matchs sur 8 à 0-0 sans vainqueur ni tirs au but, dont la finale Liverpool - Flamengo et la demi-finale Monterrey - Liverpool) : vainqueur `?`, `avertissement`, scores affichés tels que
la source les donne ; ses bilans sont donc faux pour cette édition. Bilan de la France : Coupe du monde 17 participations, 2 titres, 4 finales, 3 tirs au but perdus (1982, 2006,
2022) ; Euro 11 phases finales, 2 titres (1984, 2000), 3 finales ; Ligue des nations 1 titre (2021), 3e en 2025. Les éditions 2026 (Coupe du monde, Espagne - Argentine 1-0 a.p.) et la
3e place anglaise de la Coupe du monde 2026 viennent des sources telles quelles.

**Limites.** Hôte de l'Euro et de la Ligue des nations absent (aucune donnée d'époque fiable dans l'API) ; Allemagne (GER) et Allemagne de l'Ouest (FRG) sont deux équipes (la FIFA
et l'UEFA les distinguent par code d'époque) ; ordre des tours de formats anciens indicatif (`NIVEAUX`) ; éliminatoires de la Coupe du monde absents (hors décision) ; pas de
classement de groupe, pas de buteurs ; une édition publiée avec des scores faux par la source l'est telle quelle.

### 10 bis. Décisions du propriétaire du 26/11/2026 (REGLE 2)

1. **Lignées** (`lignees_selections.json`) : équipes distinctes mais reliées, jamais fusionnées. Preuves : identifiants d'équipe UEFA identiques avant / après (West Germany -> Germany = 47 ; USSR -> CIS = 141 ; Yugoslavia -> Serbia and Montenegro -> Serbia = 147, relevé sur les Euro 1960-2024) ; pour TCH -> CZE, CIS / URS -> RUS, ZAI -> COD, INH -> IDN, attribution des records par la FIFA / l'UEFA (marquée `records_officiels`, non lisible dans nos données). Pas de lien pour la RDA. Slovaquie, Croatie, Slovénie, Bosnie, Macédoine du Nord, Monténégro : « issues de ».
2. **Coupe du monde des clubs 2019** : la FIFA donne 0-0 sans vainqueur pour 6 matchs (le 2-6 de la 5e place et le 2-2 / t.a.b. 4-3 de la 3e place sont déjà exacts). Corrections ESPN du 26/11/2026 : Al Sadd 3-1 Hienghène a.p. ; Al-Hilal 1-0 Espérance ; Monterrey 3-2 Al Sadd ; Flamengo 3-1 Al-Hilal ; Monterrey 1-2 Liverpool ; Liverpool 1-0 Flamengo a.p. Résultat : Liverpool, Flamengo, Monterrey (3e). Mécanisme générique `corrections_internationales.json` (voir CLAUDE.md).
3. **Hôtes UEFA** (pays des stades ; Final Four pour la Ligue des nations) : Euro 1960 FRA, 1964 ESP, 1968 ITA, 1972 BEL, 1976 YUG (Belgrade, Zagreb : `HOTES_EPOQUE`), 1980 ITA, 1984 FRA, 1988 FRG (`HOTES_EPOQUE`), 1992 SWE, 1996 ENG, 2000 BEL + NED, 2004 POR, 2008 SUI + AUT, 2012 POL + UKR, 2016 FRA, 2020 ITA, AZE, DEN, RUS, ENG, ROU, NED, SCO, ESP, HUN, GER (11 pays), 2024 GER ; Ligue des nations 2019 POR, 2021 ITA, 2023 NED, 2025 GER (2027 : pas encore de tour final). Conforme à l'histoire.
4. **Drapeaux d'époque** : `h-urs`, `h-frg`, `h-gdr`, `h-tch`, `h-yug`, `h-scg`, `h-cis`, `h-zai` (fichiers Commons du modèle cyclisme, domaine public revérifié par l'API le 26/11/2026) ; Indes orientales néerlandaises (INH) : aucun fichier propre à l'équipe (le drapeau colonial était le drapeau néerlandais, source de confusion) -> vide, `a_verifier`.
5. « Russie* » : l'astérisque (renvoi de note UEFA) est retiré des noms.
