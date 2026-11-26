# Avancement du projet Coupes d'Europe + championnats (point de reprise)

Dernière mise à jour : 26 novembre 2026 (7 h 15 UTC). À lire avec `CLAUDE.md` (règles, architecture, méthodes, une section par fonction),
`docs/etude_fiches_clubs.md` (étapes 1 à 5 des coupes), `docs/etude_championnats.md` (championnats), `docs/histoire_europeenne.md`,
`docs/historique_classements.md`, `docs/cahier_des_charges_sources.md` (sources à trouver par le propriétaire).

## Où on en est

Tout ce qui suit est fusionné sur `main` et en ligne (https://camelbaggy.github.io/coupes-europe/). Données des championnats : dépôt
`Camelbaggy/donnees-football` (Pages), écrit par ses workflows avec le code de `main` d'ici.

**Coupes d'Europe**
- Mises à jour automatiques fiables (état par soirée, page vérifiée avant notification, alertes d'échec, battement + veille de secours).
- Historique des soirées (41 soirées, menu des journées par coupe), reconstitution, classement recalculé, fiches de club (108), couleurs,
  historique européen et palmarès, xG ESPN (Opta). Rattrapage IA : 21 résumés Gemini faits, 9 restants au 26/11 (2 passages / jour).
- 26/11 : **journées à venir** dans le menu (groupe « À venir », la prochaine juste au-dessus de la dernière jouée) avec le **programme**
  (date, heure de Paris, stade) : `clubs/programme.json` (UEFA).
- 26/11 : **alertes ntfy en direct des clubs français** (`direct_clubs.py`, `direct_clubs.yml` lancé par la veille 20 min avant le coup
  d'envoi) : coup d'envoi, chaque but (buteur, minute, passeur), but annulé, fin. Validé sur des matchs du 25/11 rejoués ; **premier soir réel
  le 26/11** (Marseille, Monaco 17 h 45 UTC ; Lyon, Rennes 20 h UTC).

**Championnats** (big 5 + Ligue 2 = principaux, notifiés ; Portugal, Pays-Bas, Belgique, Turquie, Autriche, Grèce, Norvège = secondaires)
- Collecte quotidienne (battement de donnees-football), reconstitution de la saison faite (principaux et secondaires : 0 restant),
  classement recalculé, fiches de club et de joueur (Wikidata, Wikipédia, historique européen), historique des classements (460/466 saisons),
  vue « Saisons passées », notification commune du jour.
- Journées : Wikipédia FR / IT / ES, pages locales NO et TR (306/306, 240/240) ; **journées DÉDUITES du calendrier** pour Portugal, Pays-Bas,
  Belgique, Grèce (`journees_ordre.py`, idée du propriétaire ; 0 erreur sur 850 matchs joués de contrôle) : toute la saison jouée numérotée.
- Programme des matchs à venir par journée (`programme.json` de chaque saison, ESPN).
- **Pastilles européennes** dans les classements (LDC / LE / LC, en lice / barrée = éliminé / 🏆) : `clubs/europe.json` ; légende dans
  l'info-bulle du classement.
- Encyclopédie : clubs norvégiens et turcs reliés (modèle `{{fk}}` développé ; 13/16 clubs norvégiens avec id UEFA).

**Suivi en direct (page)** : bloc « En direct » (accueil et compétition, ESPN depuis le navigateur), fiche de match provisoire, pastilles
« En direct · N » sur les tuiles et point rouge sur les onglets. Pas encore vu sur un vrai match en cours (premier soir : 26/11).

## Chantier en cours : compétitions internationales (26/11/2026)

Étude et décisions du propriétaire : `docs/etude_internationales.md` (§ 6-9). Fait et fusionné :
- Étape 1 : collecteur (`internationales.py` ; UEFA, FIFA + ESPN), `run_internationales.py`, reconstitution des 6 éditions récentes
  (`reconstitution_internationales.yml` de donnees-football, lancée le 26/11, se relance seule).
- Étape 2 : interface (accueil « Coupes de clubs » avec CdM des clubs et Coupe intercontinentale, « Sélections nationales », menu des
  tours par édition, groupes, tableau final, focus France ; `tools/test_internationales_ui.js`).
- Étape 3 : collecte du jour (`collecte_internationales.yml` lancé par la veille de donnees-football), `etat_internationales.json`,
  notification commune (France, phases finales Euro / CdM, toujours CdM des clubs et Coupe intercontinentale), alertes en direct des Bleus
  et des clubs français en CdM des clubs / Coupe intercontinentale (`direct_clubs.py`, ESPN pour ces deux-là).
À vérifier : fin de la reconstitution (tableau final complet de la CdM 2026 à regarder sur la page), premier passage réel de la veille
internationale ; **16/12/2026, finale intercontinentale du PSG** : événement ESPN pas encore programmé au 26/11 (alertes à confirmer le jour
même : `python direct_clubs.py --veille` vers 15 h 40 UTC) ; Ligue des nations en mars 2027. Reste à faire : résumés (IA pour les nouveaux
matchs de la France, déterministes pour les anciens), fiches de sélection et historique (FIFA depuis 1930, UEFA depuis 1960), classement
d'un groupe à une date passée, alerte ntfy d'échec de la collecte internationale, éliminatoires Euro 2028 / CdM 2030 quand l'UEFA les publie,
puis autres continents et amicaux.

## À vérifier à la reprise

1. **Soir du 26/11** (tâches programmées dans cette session : 15 h 35, 17 h 47, 17 h 52, 20 h 02 UTC) : page en direct pendant Mjällby-Kairat,
   puis alertes `direct_clubs.yml` (valeur réelle du statut UEFA « en direct », buts, anti-doublon) ; analyse de `tools/sonde_direct.py`, puis
   SUPPRIMER cette sonde (temporaire) ; proposer l'étape 2 du direct (momentum en direct, port JS avec test de parité) au propriétaire.
2. Week-end du 28-30/11 : notification commune avec les championnats ; journées déduites sur les nouveaux jours (por / ned / bel / gre).
3. Lundi 30/11 : `clubs.yml` (fiches, historique, `programme.json`, `europe.json`).
4. Deux matchs à venir mal placés par la déduction des journées seraient possibles (reports reprogrammés) : rien à faire, ils se recalent une
   fois joués ; à surveiller sur le programme.
5. Reconstitution et collecte partagent le groupe de concurrence `championnats` : une reconstitution qui se relance annule une collecte en
   attente (vu le 26/11 sur des collectes manuelles ; la veille relance la collecte quotidienne). À revoir seulement si une nouvelle
   reconstitution longue est lancée.

## En attente du propriétaire

- API de la LFP (Ligue 2 en flux complet) : adresses `ma-api.ligue1.fr` relevées sur une page de match (Eruda / F12, onglet Réseau, filtre
  « ma-api ») + confirmation de l'accord. Jamais de découverte par rétro-ingénierie ni de faux navigateur.
- Secret `NTFY_TOPIC` dans donnees-football (alertes d'échec des championnats ; Claude ne peut pas vérifier les secrets de ce dépôt).
- Renommage des dépôts (coupes-europe -> football, courses-cyclistes -> cyclisme) : prévenir Claude ensuite (liens, workflows,
  `DASHBOARD_URL`, dépôts de redirection).
- Réponses aux demandes d'accord SofaScore / FotMob ; décision sur les API payantes (clés gratuites API-Football / DataSportsAPI à tester,
  puis éventuellement API-Football Pro 16 $/mois, pass Football Charts 49 €) ; football-data.org (gratuit) si besoin d'une 2e source de journées.
- Accord écrit de l'ÖFBL (Autriche) seulement si on veut leurs journées (Wikipédia les donne déjà).
- Décisions : historique de la D2 (36/87 saisons lisibles : chercher une autre source ?), historique des classements des secondaires,
  formules à poules finales (Belgique, Autriche, Grèce) avant le printemps.

## Décisions du propriétaire à retenir

- Une seule notification commune par jour (toutes compétitions jouées), après vérification de la page ; alerte distincte en cas d'échec.
  Les alertes en direct des clubs français (26/11) sont une catégorie à part, demandée explicitement.
- Livraison ntfy instantanée NON activée sur le téléphone (batterie).
- Principaux (notifiés, alertes) = big 5 + Ligue 2 ; tout autre championnat est secondaire (collecté, affiché, jamais notifié).
- Accueil : « Championnats majeurs » puis « Autres championnats » ; drapeau devant le nom de chaque ligue ; « Derniers résultats » sans les
  secondaires ; « Saisons passées » = vue dédiée par championnat.
- Toute légende / aide dans une info-bulle ⓘ, jamais en texte permanent.
- Couleurs des équipes partout où deux équipes s'opposent, SAUF la liste des résultats de l'accueil.
- Résumés IA rattrapés pour la phase de ligue seulement cette saison ; entraîneur non affiché ; 5 alias Wikidata validés.
- Sources : aucun contournement anti-robot, aucun faux navigateur, aucune API non documentée sans accord ; clés jamais dans le chat (formulaire
  sécurisé, secrets du dépôt).

## Pistes possibles (non demandées)

- xG par joueur (ESPN, API core : non exploité).
- Phase finale (février-mai) : vérifier menu des tours, tableau, finale du samedi.
