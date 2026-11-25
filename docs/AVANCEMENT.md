# Avancement du projet Coupes d'Europe (point de reprise)

Dernière mise à jour : 25 novembre 2026 (midi). À lire avec `CLAUDE.md` (règles, architecture, méthodes), `docs/etude_fiches_clubs.md`
(étude et décisions des étapes 1 à 5) et `docs/histoire_europeenne.md` (historique européen).

## Où on en est

Tout ce qui suit est fusionné sur `main` et en ligne (https://camelbaggy.github.io/coupes-europe/).

- **Mises à jour automatiques fiables** (PR #3 à #9) : état par soirée `etat_soirees.json`, une seule notification ntfy par soirée, envoyée
  seulement après vérification de la page publique ; alerte ntfy distincte en cas d'échec (une par soirée et par cause) ; `battement.yml`
  (toutes les 10 min les soirs de match) + `veille_secours.yml` (cron horaire) relancent la mise à jour si GitHub saute le cron. Premier
  passage réel complet : soirée du 24/11 (LDC, 9 matchs), notifiée une fois.
- **Fiche de match** : onglets Déroulé · Compos · Stats (momentum en tête des Stats), compos sans chevauchement, stats lisibles par rubriques,
  glissement gauche / droite entre onglets, fermeture des fiches (match, joueur, club) par glissement vers le bas, feuilles pleine hauteur,
  textes d'aide rangés dans des info-bulles ⓘ.
- **Étape 1, historique des soirées** : `soirees/<date>.json` + `soirees/index.json` ; menu des journées / tours PAR COUPE (`?c=ucl&tour=j5`) ;
  glissement entre coupes sur l'accueil.
- **Étape 2, reconstitution** : 40 soirées de la saison 2026-27 reconstituées (tours préliminaires compris), classement recalculé depuis les
  scores (égal au classement UEFA : 108 clubs, 0 écart). Rattrapage des résumés Gemini (phase de ligue seulement, décision du propriétaire) :
  10 faits au 25/11 matin, 17 restants, continue seul (cron 6 h 17 et 15 h 17 UTC).
- **Étape 3, fiches de club** (108 clubs) : aperçu (stade, Wikidata, Wikipédia), matchs de la saison, stats, effectif.
- **Étape 4, couleurs des équipes** : maillot porté dans le match, sinon couleur du club, sinon bleu / rouge ; garde-fou de proximité et contraste.
  Décision du 25/11 : PAS de couleurs dans la liste des résultats de l'accueil (PR #17).
- **Étape 5, historique européen et palmarès** (PR #18) : onglet « Histoire » des fiches de club, 22 616 matchs depuis 1955, palmarès calculé
  (0 écart avec les vainqueurs UEFA ; cas connus vérifiés : Real Madrid 15 C1, Liverpool, Marseille 1993, PSG C2 1996).
- **xG** (PR #19, 25/11) : l'UEFA n'en publie pas ; xG / xGOT / xA du modèle Opta lus sur ESPN pour tous les matchs terminés, bloc
  « Buts attendus (xG) » sous la possession. Couverture mesurée : phase de ligue 207/207, préliminaires 369/428. Rattrapage des soirées passées
  lancé le 25/11 à 11 h 55 UTC (`completer_xg.yml`, run 45608925767, ~25 min, se relance seul s'il reste des matchs).
- **Documentation** (25/11) : `CLAUDE.md` complété (vue d'ensemble des sources / workflows / secrets, collecte pas à pas, méthodes de calcul :
  momentum, mi-temps, notes), README remis à jour.

## À vérifier à la reprise

1. `completer_xg.yml` : run terminé en succès, soirées avec xG (ouvrir une fiche de match d'une soirée passée, onglet Stats).
2. Soirée du 25/11 (LDC) puis du 26/11 (LE + LC) : notification unique reçue, xG présents dès le passage du soir.
3. Rattrapage IA : nombre de cartes encore `deterministe` (`soirees/index.json`, `resumes.a_rattraper`).
4. Lundi 30/11 : premier passage de `clubs.yml` avec l'historique (`--historique --saison-courante`).

## Décisions du propriétaire à retenir

- Une seule notification par soirée, seulement quand la page est vérifiée à jour ; alerte spéciale en cas d'échec.
- Livraison ntfy instantanée NON activée sur le téléphone (batterie) : une notification peut n'apparaître qu'en rafraîchissant l'appli.
- Résumés IA rattrapés pour la phase de ligue seulement cette saison (les tours préliminaires des saisons suivantes seront traités en direct).
- Entraîneur non affiché dans les fiches de club ; 5 alias Wikidata validés (Como, Sunderland, Torreense, Mjällby, Sint-Truidense).
- Couleurs des équipes partout où deux équipes sont opposées, SAUF la liste des résultats de l'accueil.
- Menu des soirées par coupe (journées / tours), pas un menu global.

## Pistes possibles (non demandées)

- xG par joueur (ESPN les donne par joueur dans les rosters de l'API core : non exploité).
- Phase finale (février-mai) : vérifier le menu des tours, le tableau, la finale du samedi (cron de mai-juin).
- Les 59 matchs de tours préliminaires sans xG (ESPN ne les couvre pas ou sans statistiques) : rien à faire, valeur absente = absente.
