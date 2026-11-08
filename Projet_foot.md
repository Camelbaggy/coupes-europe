# Spécifications Fonctionnelles : Dashboard de Suivi des Coupes d’Europe

## 1. Objectif du Projet
Créer un système automatisé de veille et de restitution pour les soirs de coupes d'Europe de football masculin :
- **Ligue des Champions (LDC / UCL)**
- **Ligue Europa (EL / UEL)**
- **Ligue Conférence (ECL / UECL)**

Le dispositif doit consolider les données fiables de chaque soirée de match, générer des résumés ciblés sur les clubs français, mettre à jour une interface web claire et consultable sur smartphone, puis envoyer une alerte push légère avec accès direct à cette page.

---

## 2. Pousser l'Alerte : Système de Notification
- **Comportement :** Une notification push doit être envoyée automatiquement uniquement les soirs ou matins suivant des rencontres européennes, une fois le traitement des données et la page web actualisés.
- **Canal cible :** Service de notification autonome et léger (type ntfy ou équivalent), sans dépendance à une messagerie communautaire ouverte aux spams (pas de Discord ni de groupe Telegram).
- **Contenu du push :** 
  - Un titre concis indiquant la nature du bilan (ex. « Coupes d'Europe : Résultats et classements à jour »).
  - Un bref texte d'état (ex. « Victoire du PSG, nul de Lyon, classements mis à jour »).
  - Un lien cliquable ouvrant directement la page web du tableau de bord.

---

## 3. Données Requises & Expérience Utilisateur

### A. Navigation Globale (Page Web)
- Interface pensée prioritairement pour la consultation mobile, épurée et sans publicité ni cotes de paris sportifs.
- Navigation par onglets distincts :
  - **Onglet 1 :** Ligue des Champions
  - **Onglet 2 :** Ligue Europa
  - **Onglet 3 :** Ligue Conférence

---

### B. Contenu par Compétition

#### 1. Focus Clubs Français (Mise en avant prioritaire)
Pour chaque équipe française engagée :
- Affiche du match et score final vérifié.
- Chronologie complète des buts : nom du buteur et minute exacte.
- Résumé synthétique du match (4 à 5 phrases) : faits marquants, tournant du match, scénario global et impact comptable. Ce texte est rédigé à partir des statistiques et du fil d'événements/commentaires de la rencontre.
- Indication immédiate de la position du club dans la compétition.

#### 2. Vue d'ensemble des Résultats de la Soirée
- Liste ou grille compacte de l'ensemble des rencontres disputées la veille ou le jour même pour la compétition sélectionnée.
- Chaque match est représenté par une **tuile cliquable**.

#### 3. Détails d'un Match (Affichage au clic sur une tuile)
Le clic sur une rencontre doit ouvrir un panneau latéral ou une fenêtre modale contenant l'équivalent des vues complètes d'une fiche de match moderne :
- **Événements / Déroulé :** Chronologie des buts, remplacements, cartons jaunes et rouges.
- **Graphique de pression / intensité (Momentum) :** Visualisation de la domination territoriale et offensive équipe par équipe tout au long du match (minute par minute).
- **Compositions tactiques :** Disposition visuelle des joueurs sur le terrain avec leurs numéros, leurs positions respectives, leurs éventuelles notes individuelles et remplacements.
- **Statistiques détaillées :** Possession, tirs totaux, tirs cadrés, grosses occasions, arrêts des gardiens, corners, fautes, tacles, passes réussies, cartons (avec filtre global et par mi-temps si disponible).

*(Note : le fil de commentaires texte minute par minute n'est pas affiché dans l'interface, il sert uniquement de matière première en coulisses pour la rédaction du résumé).*

#### 4. Classement Général & Évolution
- **Pendant la phase de ligue / poule unique :**
  - Tableau exhaustif des 36 équipes.
  - Délimitation visuelle explicite des 3 zones stratégiques :
    - **Places 1 à 8 :** Qualification directe pour les 8es de finale.
    - **Places 9 à 24 :** Qualification pour les barrages (16es).
    - **Places 25 à 36 :** Élimination directe.
  - Mise en évidence marquée (texte en gras ou badge) de tous les clubs français dans le tableau.
- **Pendant les phases éliminatoires :**
  - Remplacement automatique du tableau par un tableau d'arborescence (bracket) des confrontations directes aller-retour jusqu'à la finale.

---

## 4. Contraintes & Règles de Fonctionnement
1. **Zéro hallucination sur les chiffres :** Les scores, buteurs, minutes, statistiques et classements doivent provenir exclusivement de données réelles et vérifiées, sans extrapolation statistique par un modèle linguistique.
2. **Autonomie d'exécution :** Le pipeline doit pouvoir s'exécuter de façon programmée (ex. vers 23h30 ou tôt le matin les lendemains de matchs) sans intervention manuelle.
3. **Optimisation des requêtes :** L'architecture doit éviter tout blocage lié à des quotas d'API restreints ou à des protections de sites tiers.
4. **Hébergement statique :** La consultation doit se faire via des fichiers légers (HTML/CSS/JS lisant une structure de données locale), garantissant un temps de chargement immédiat sur smartphone.
