# Historique européen des clubs (étape 5)

Livré le 25/11/2026 : `histoire.py`, `clubs/historique/<id UEFA>.json` (108 fichiers), onglet « Histoire » de la fiche de club.
Décision du propriétaire (étude, § Décisions n° 4) : historique complet des 108 clubs + palmarès européen calculé.

## Source et collecte

- **Une seule requête paginée par club** : `match.uefa.com/v5/matches?teamId=<id>&offset=<0,500,…>&limit=500&order=ASC&language=FR`, SANS `competitionId`
  (tous les matchs UEFA du club depuis l'origine : Bayern 561 matchs, Real Madrid 633). Compétitions rencontrées (code API -> clé) : `UCL` C1,
  `ECWC` C2, `UEL` C3 (Coupe UEFA puis Ligue Europa), `UECL` LC, `SCUP` SE (Supercoupe d'Europe), `Fairs Cup` VF, `UIC` IT (Intertoto), `EUSA` IC
  (Coupe intercontinentale Europe / Amérique du Sud : `EUSA` n'est PAS la Supercoupe, `SCUP` l'est).
- **Mise à jour** : `fromDate` / `toDate` sont acceptés avec `teamId` seul. `python clubs.py --historique --saison-courante` ne relit que les matchs depuis le
  20 juin de la saison courante et remplace les éditions de cette saison ; le reste du fichier est conservé tel quel. Mesure : le résultat est
  IDENTIQUE à une reconstruction complète (testé sur 5 clubs, réseau réel, `diff` vide).
- **Poids mesurés (25/11/2026)** : téléchargement unique = **818 Mo de JSON non compressé** (86 Mo en gzip, 108 clubs, ~11 min avec 1 s entre requêtes) ;
  publié `clubs/historique/` = **1,40 Mo** (108 fichiers de 0,8 Ko à 34,8 Ko, médiane 11,8 Ko), **0,43 Mo compressé** (gzip) ; 22 616 matchs, 3 848 éditions,
  62 octets par match. La fiche `clubs/<id>.json` ne change pas (chargement à la demande). Le JSON brut n'est jamais commité : `--cache DIR` le garde HORS du dépôt.
- `python clubs.py --historique [--clubs id,…] [--cache DIR] [--refaire]` : reprenable (un club qui a déjà son fichier est sauté, une page illisible = club
  repris au passage suivant, jamais une liste tronquée). `clubs.yml` (lundi) : remplissage de ce qui manque puis saison courante, sans bloquer la publication.

## Règles de calcul (versionnées : `histoire.REGLE`)

1. **Saison européenne = du 20 juin au 19 juin**, dérivée de la DATE (jamais de `seasonYear` : convention « année de début » jusqu'en 2007, « année de fin » ensuite,
   et incohérences). Libellé `1964-65`. Exceptions mesurées sur les données réelles :
   - une finale de C1 / C2 / C3 / LC jouée en juillet-septembre appartient à la saison précédente (finale d'août 2020 ; finale de Coupe des coupes rejouée le 5/9/1962) ;
   - depuis 2008, un match dont `seasonYear` vaut l'année de DÉBUT calculée appartient à la saison précédente (8es, quarts, demies d'août 2020, COVID) ;
   - Coupe Intertoto (juin-août) : année du match ; Coupe des villes de foires : groupée par `seasonYear` (éditions pluriannuelles 1955-58, 1958-60, finales en
     septembre), libellé tiré des dates des matchs (`1955-58`).
2. **Score** : `score.total` (prolongation comprise) vu du club, `score.penalty` = tirs au but, `a.p.` si le total diffère du temps réglementaire. V / N / D sur le score hors
   tirs au but (tirs au but : un nul, comme `clubs.vnd`). Matchs annulés (37), arrêtés (5) et forfaits (23, score attribué par l'UEFA) : listés, JAMAIS comptés au bilan.
3. **Finale** (tour « Finale » de l'édition ; Supercoupe et Coupe intercontinentale : tous les matchs de l'édition, y compris le 3e match d'appui) :
   - match rejoué (type `REPLAY` ou tour « Match d'appui ») : seul lui décide (finale de C1 1973-74 : 1-1 a.p. puis 4-0) ;
   - match unique : score, puis tirs au but ; égalité sans tirs au but : `?` ;
   - deux manches : CUMUL des deux scores ; égalité : tirs au but de la 2e manche, puis seulement le vainqueur que l'UEFA indique (`winner.aggregate`, raison conservée :
     buts à l'extérieur, prolongation, tirs au but, tirage au sort), sinon `?` (« issue non déterminée ») ;
   - tout désaccord entre le calcul et le vainqueur UEFA est consigné dans `ecarts` : **0 écart et 0 issue non déterminée sur les 108 clubs**.
   - Les finales à match unique n'ont pas de D / E (l'UEFA désigne une équipe « à domicile » mais le lieu n'est pas neutre pour autant : stade et ville sont gardés dans `lieu`).
4. **Titres comptés** : C1, C2, C3, LC, SE (une finale gagnée = un titre). VF, IT, IC sont listées à part (« autres coupes, hors titres UEFA »).
5. **Tour atteint** d'une édition : tour le plus avancé joué (`NIVEAUX`) ; **meilleur parcours** d'une compétition : vainqueur > finaliste > tour atteint ; l'ordre entre tours
   numérotés d'autrefois et phases de groupes est INDICATIF (écrit dans l'info-bulle). Édition de la saison courante : « À ce jour · <tour> ».
6. **Noms d'époque** : Coupe des clubs champions (< 1992-93) / Ligue des champions ; Coupe UEFA (< 2009-10) / Ligue Europa ; pour les autres, un seul nom. Dérivés de la saison
   (l'API ne donne que le nom actuel).

## Format `clubs/historique/<id>.json`

`{id, regle, maj, source, depuis, comp{clé: {nom, court, titre}}, noms[], tours[], adv{id: [nom, drapeau, pays]}, ed[], bilan{clé: {ed, j, v, n, d, bp, bc}}, meilleurs{clé: {lib, niv, s[]}},
pal{clé: {V, D, ?}}, ecarts?}`. Une édition `ed[i]` = `{s: saison, c: compétition, n: index de noms[], t: index de tours[] (tour atteint), nv: niveau, i?: V / D / ? (issue de finale),
ec?: 1 (saison courante), f?: finale {r: V / D / ?, adv, m: [[date, lieu, pour, contre(, tab pour, tab contre)(, 1 = prolongation)]], cumul?, dep?, rejoue?, lieu?, pourquoi?},
m: [[date, index de tours[], id adversaire, lieu (0 ext, 1 dom, 2 non précisé), pour, contre(, {tab, ap, st})]]}`. Aucun champ inventé : un champ absent est absent.

## Vérifications sur cas connus (calcul = histoire officielle ; fixtures réelles allégées dans `tools/fixtures/histoire/`)

| Cas | Attendu | Calculé |
|---|---|---|
| Real Madrid C1 | 15 titres (1956-60, 1966, 1998, 2000, 2002, 2014, 2016-18, 2022, 2024), 3 finales perdues (1962, 1964, 1981) | identique (15 / 3) ; SE 6 / 3, IC 3 / 2, C3 2 / 0, C2 0 / 2 |
| Liverpool | C1 6 titres + 4 perdues ; UEFA 1973 (3-0, 0-2), 1976 (3-2, 1-1), 2001 (5-4 but en or) + 2016 perdue ; SE 1977 (1-1, 6-0), 2001, 2005, 2019 (2-2 a.p., 5-4 t.a.b.), perdues 1978 et 1985 | identique ; cumuls 3-2, 4-3, 7-1 ; aucun titre compté pour la Coupe intercontinentale (0 / 2) |
| Marseille | C1 1993 (1-0 Milan), finale 1991 perdue aux tirs au but (0-0, 3-5) ; finales UEFA perdues 1999, 2004, 2018 | identique ; Intertoto 2005 : V (cumul 5-3), non compté parmi les titres |
| PSG | Coupe des coupes 1996 (1-0 Rapid Vienne), finale 1997 perdue ; C1 2020 perdue | identique ; les finales 2025 et 2026 sont celles de l'API |
| Bayern 1973-74 | 1-1 a.p. puis rejoué 4-0 : titre | V, finale rejouée |
| COVID 2019-20 | 8es à finale d'août 2020 dans la saison 2019-20 | Bayern V 2019-20, finale du 23/08/2020 |
| Barcelone VF | 1958 (cumul 8-2), 1960 (4-1), 1962 perdue (3-7, finale en septembre 1962), 1966 (4-3) | identique, éditions `1955-58`, `1958-60`, `1961-62`, `1965-66` |
| Vainqueurs de la C1 | un seul club par saison parmi les 108 | 65 saisons, aucun doublon ; C2 19, C3 30, LC 3 (clubs hors des 108 absents, évidemment) |

Écarts / limites connues : Coupe des villes de foires (non reconnue par l'UEFA, éditions pluriannuelles) ; ordre des tours numérotés d'autrefois indicatif ; la finale de C2 1961-62
est donnée par l'UEFA comme deux manches (1-1 puis 3-0, cumul 4-1) alors que la seconde était un match rejoué : même vainqueur, présentation « cumul » ; stade de la 2e manche seulement
pour les finales à match unique ; un club sorti des 108 (non listé dans `clubs/index.json`) n'a pas d'historique.

## Tests

`python histoire.py --test` (saison depuis la date, exceptions, résolution de finales sur cas fictifs, normalisation d'un match brut : forfait / annulé / à venir / tirs au but,
3 matchs d'une finale intercontinentale, 7 fixtures réelles, fusion de la saison courante = reconstruction complète) ; `node tools/test_histoire_ui.js` (Playwright 390 × 844 tactile).
Fixtures : `python tools/fixtures_histoire.py <dossier de cache brut>`.
