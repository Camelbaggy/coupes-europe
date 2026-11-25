# Historique des classements finaux des championnats (big 5)

Demande du propriétaire (25/11/2026) : « pour les saisons précédentes, seul l'historique du classement des clubs
m'intéresse » ; « Wikipédia devrait avoir l'historique complet, une page par saison ; prendre les pages locales si les
données FR ne sont pas complètes ». Module : `historique_classements.py` (Python 3.11, bibliothèque standard).
Workflow : `historique_classements.yml` du dépôt **donnees-football** (dispatch, entrées `ligues` et `ref`, budget 40 min,
auto-relance tant qu'il reste des saisons ET que le passage a progressé, groupe `historique-classements`).

## Sources, par saison

| Période | Source | Lecture |
|---|---|---|
| 2002-03 → dernière saison terminée | ESPN `site.api.espn.com/apis/v2/sports/soccer/<slug>/standings?season=<année de début>` | classement final, pénalités comprises (Serie A 2005-06 = Inter 76 pts) ; `espn_id` du club |
| avant 2002-03 | Wikipédia FR, page de la saison (« Championnat de France de football 1933-1934 »…) | modèle `{{Foot classement|rang|club|pts|j|g|n|p|bp|bc}}` ou `wikitable` à en-têtes |
| secours (page FR illisible) | page LOCALE : IT « Serie A 1934-1935 », ES « Primera División de España 1929-30 », DE « Fußball-Bundesliga 1971/72 » | `wikitable` (en-têtes `{{Descrizione comando|Pt|…}}`, clubs `{{Calcio X}}`) ; DE : modèle `{{Fußballtabelle/Zeile|Rang=|S=|U=|N=|ET=|GT=|Siegpunkte=|Abzug=|Verein=}}` |

Angleterre : secours EN « 1911–12 Football League » (siècle complet au passage : « 1899–1900 »), d'abord l'article propre
« … Football League First Division » s'il existe, puis la page de saison (seul le tableau `section=First Division` est gardé) ;
ES / EN : module Lua `{{#invoke:Sports table}}` / `{{#invoke:Football table}}` (paramètres `win_X` / `ganados_X`…, points
AFFICHÉS par le module = V x victoires + nuls + ajustement publié, refaits ici : `pts_calcule: true` ; un paramètre de points
inconnu = tableau refusé). Ligue 1 : la page FR est la page locale. Une saison ESPN illisible (Serie A 2007-08 : 970 buts
marqués, 972 encaissés) passe aussi par Wikipédia.

Début des séries (championnat à poule unique) : Ligue 1 1933-34 (1932-33 = deux poules + finale : illisible, à dessein),
première division anglaise 1888-89, Liga 1929 (libellé « 1929 »), Serie A 1929-30, Bundesliga 1963-64.
Saisons sans championnat officiel (`SAISONS_ABSENTES`) : France 1939-40 → 1944-45 ; Angleterre 1915-16 → 1918-19 et
1939-40 → 1945-46 ; Espagne 1936-37 → 1938-39 ; Italie 1943-44 et 1944-45.

## Contrôles (rien n'est corrigé ni inventé)

- `j = g + n + p` pour chaque club, somme des buts marqués = somme des buts encaissés, rangs croissants, au moins 6 clubs :
  sinon `illisible` (avec `controles.erreur`) ;
- matchs joués inégaux : noté (`controles.matchs_inegaux`), pas bloquant ;
- points = g × V + n selon le barème de l'époque (3 points : Ligue 1 1994-95, Angleterre 1981-82, Liga 1995-96,
  Serie A 1994-95, Bundesliga 1995-96 ; 2 avant) : un écart est CONSERVÉ tel que publié et listé dans
  `controles.ecarts_points = [{club, publie, bareme}]`, statut `ecarts_points` (pénalités, bonus offensif français
  1973-1976, points retirés…) ;
- plusieurs tableaux sains différents (poules) : `illisible`, on ne choisit jamais.
- Allemand : la page ne publie pas les points, le modèle `Fußballtabelle` les AFFICHE en calculant
  `S × Siegpunkte + U − Abzug` ; on refait ce calcul (ligne marquée `pts_calcule: true`, `penalite` = Abzug). Exemple :
  Bielefeld 1971-72, Abzug 19 (points retirés après le scandale de 1971) → 0 point, écart listé.

Reprise : une saison lisible n'est plus relue (sauf la dernière saison terminée, relue à chaque passage) ; une saison
`illisible` porte `essai` (date) et n'est retentée qu'après 30 jours (`RETENTE_JOURS`) : pas de relance sans fin.
Un échec ne remplace jamais une saison lue. `GITHUB_OUTPUT` : `traites` (saisons lues hors dernière), `restants`.

## Format des fichiers (`championnats/historique/` de donnees-football, servi par Pages)

`<ligue>.json` (`fl1`, `pl`, `liga`, `sa`, `bl`) :

```json
{"ligue": "fl1", "nom": "Ligue 1", "maj": "2026-11-25T17:00:00Z",
 "saisons": {
   "1992-93": {"source": "Wikipédia FR", "titre": "Championnat de France de football 1992-1993",
               "url": "https://fr.wikipedia.org/wiki/…", "statut": "ok",
               "controles": {"clubs": 20, "points_victoire": 2, "buts": 812},
               "rows": [{"rang": 1, "club": "Olympique de Marseille", "club_wiki": "Olympique de Marseille",
                         "mention": "… déclassé …", "pts": 53, "j": 38, "g": 22, "n": 9, "p": 7, "bp": 71, "bc": 36,
                         "espn_id": "176"}]},
   "2005-06": {"source": "ESPN", "url": "https://site.api.espn.com/…", "statut": "ok", "controles": {…},
               "rows": [{"rang": 1, "club": "…", "espn_id": "…", "pts": …, "j": …, "g": …, "n": …, "p": …, "bp": …, "bc": …,
                         "penalite": 0}]},
   "1971-72": {"source": "Wikipédia DE", "statut": "ecarts_points", "rows": [{…, "pts_calcule": true, "penalite": 19}]},
   "1932-33": {"source": "Wikipédia FR", "statut": "illisible", "controles": {"erreur": "…"}, "rows": [], "essai": "2026-11-25"}}}
```

- clé de saison : `"AAAA-AA"` (Liga 1929 : `"1929"`) ; triées ;
- `rows` dans l'ordre publié ; `rang` tel que publié (ex æquo possibles : Serie A 1934-35, trois 7es) ;
- `club` = nom affiché par la source ; `club_wiki` = cible du lien Wikipédia (identifiant de rapprochement possible avec
  les fiches) ; `espn_id` seulement quand il est SÛR : ligne ESPN, ou nom Wikipédia normalisé IDENTIQUE à un nom ESPN du même
  championnat (`index_noms_espn`) ; jamais de rapprochement approché ;
- `mention` = texte hors lien de la cellule du club (« déclassé », (P), (M), (N)…), tel quel.

`index.json` : `{maj, ligues: {lg: {nom, fichier, saisons, lisibles, premiere, derniere, ok, ecarts_points, illisibles[],
sources[], maj}}}`.

## Titres contestés (documentés, jamais tranchés)

- **Marseille 1992-93** : la page FR publie l'OM 1er avec une mention de titre retiré (« déclassé ») ; la ligne est gardée
  telle quelle, l'interface peut afficher `mention`.
- **Juventus 2004-05 et 2005-06, Inter 2005-06** (Calciopoli) : saisons ESPN, gardées telles que publiées.
  2004-05 : Juventus 1re, 86 pts, aucune marque (titre révoqué en 2006, non réattribué : ESPN ne le signale pas).
  2005-06 : Inter 1er (76 pts) ; Juventus classée 20e avec 91 points (relégation administrative), sans champ de pénalité ;
  Milan 58 (pénalité 30), Fiorentina 44 (30), Lazio 32 (30) → statut `ecarts_points`. L'interface doit donc afficher le
  RANG publié (pas un tri par points) et peut signaler « rang ≠ ordre des points ».
- Autres écarts notables (tous gardés tels que publiés) : Ligue 1 1973-74 → 1975-76 (bonus offensif), 1988-89 (point
  supplémentaire aux tirs au but après un nul, RC Lens 17 au lieu de 14), Portsmouth 2009-10 (−9), Everton / Nottingham
  Forest 2023-24, Juventus 2022-23 (−10), Bielefeld 1971-72 (DE, 0 point après Abzug 19).

## Commandes

```bash
python historique_classements.py --test                        # sans réseau, 10 fixtures réelles (tools/fixtures/historique_classements/)
python historique_classements.py --donnees DIR [--ligues bl] [--budget-min 40]
python historique_classements.py --valider [--ligues …]       # ESPN vs Wikipédia FR, 2002-2010 (réseau)
```

## Mesures (passages réels du 25/11/2026, donnees-football)

1er passage (tout à faire) : 461 saisons traitées en 160 s, 42 requêtes Wikipédia + 120 ESPN, aucun 429 depuis Actions.
Deux passages `retenter` ensuite (lecteurs EN / ES / DE / IT ajoutés), quelques secondes chacun.

| Championnat | Saisons | Lisibles | ok | écarts de points | Sources (lisibles) | Illisibles |
|---|---|---|---|---|---|---|
| Ligue 1 | 87 (1933-34 → 2025-26) | 86 | 79 | 7 | FR 62, ESPN 24 | 1961-62 (page FR : 1137 buts pour, 1132 contre) |
| Angleterre | 127 (1888-89 →) | 127 | 116 | 11 | FR 76, EN 27, ESPN 24 | — |
| Liga | 94 (1929 →) | 90 | 86 | 4 | FR 57, ES 9, ESPN 24 | 1929 (FR incohérente, pas de page ES à ce titre) ; 1950-51, 1951-52, 1954-55 (deux tableaux : championnat + poule de promotion, jamais choisis) |
| Serie A | 95 (1929-30 →) | 94 | 79 | 15 | FR 63, IT 8, ESPN 23 | 1945-46 (vraies poules Nord / Sud + tour final) |
| Bundesliga | 63 (1963-64 →) | 63 | 59 | 4 | FR 38, DE 1, ESPN 24 | — |

Total : 460 classements finaux lisibles sur 466 saisons. Poids : 1,2 Mo bruts (pl.json 300 Ko, 43 Ko gzip).
`--valider` (recouvrement ESPN / Wikipédia 2002-2010) n'a pas été lancé : le conteneur de développement reçoit des 429 de Wikipédia.
