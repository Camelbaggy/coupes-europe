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
