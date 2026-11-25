# Cahier des charges : sources de données pour les championnats

Rédigé le 26/11/2026. Remplir une fiche (§ 3) par source trouvée : une source peut couvrir un ou plusieurs pays, ou seulement
une partie des données. Les sources sont ensuite combinées si besoin, sans jamais deviner une valeur manquante.

## Championnats concernés

- **Sans aucune source** : Tchéquie, Slovaquie, Ukraine, Azerbaïdjan.
- **À enrichir** (ESPN ne donne que les buts, cartons et remplacements : 15 à 20 actions par match, pas d'xG) : Ligue 2,
  Belgique, Turquie, Autriche, Grèce, Norvège.
- Pour mémoire, xG absent aussi pour le Portugal et les Pays-Bas (le reste est complet chez ESPN).

---

## 1. Données recherchées, par niveau

### Niveau A : indispensable (sans lui, le championnat ne peut pas s'afficher)

- [ ] Calendrier et résultats de la saison en cours, depuis la 1re journée : date, heure, domicile / extérieur, score, statut
      (terminé, reporté, annulé).
- [ ] Numéro de journée de chaque match.
- [ ] Classement officiel à jour : rang, matchs joués, victoires, nuls, défaites, buts pour / contre, points.
- [ ] Un identifiant stable par club (pas seulement le nom).
- [ ] Logo des clubs.

### Niveau B : fiche de match

- [ ] Buteurs avec la minute (penalty et contre son camp signalés) et passeurs décisifs.
- [ ] Cartons jaunes et rouges avec la minute.
- [ ] Remplacements : qui entre, qui sort, minute.
- [ ] Compositions : titulaires et remplaçants, numéro, poste, formation (4-3-3…).
- [ ] Stats d'équipe du match : possession, tirs, tirs cadrés, corners, fautes, hors-jeu, passes.
- [ ] Stade (et affluence si possible).

### Niveau C : données avancées (momentum, stats par mi-temps, notes des joueurs)

- [ ] Liste de toutes les actions du match, avec minute, équipe et type : tir, tir cadré, corner, entrée dans la surface, arrêt,
      hors-jeu, faute. Il en faut plusieurs centaines par match ; 15 à 20 ne suffisent pas.
- [ ] Stats individuelles par joueur et par match : minutes, buts, passes réussies / tentées, passes clés, tirs, dribbles, duels,
      tacles, interceptions, dégagements, arrêts pour les gardiens.
- [ ] xG (buts attendus), et si possible xGOT et xA.

### Niveau D : effectifs et fiches joueurs

- [ ] Joueurs de chaque club : nom, date de naissance complète, nationalité, poste, numéro, photo.

### Niveau E : historique

- [ ] Classements finaux des saisons passées, idéalement depuis la création du championnat.

---

## 2. Accès et conditions (à vérifier pour chaque source)

- [ ] **Format** : API JSON, fichiers CSV, ou pages web (dans cet ordre, du plus simple et fiable au moins fiable).
- [ ] **Clé ou compte** : aucun / clé gratuite / payant. Quotas (requêtes par minute et par jour).
- [ ] **Conditions d'utilisation** : réutilisation et affichage autorisés pour un projet personnel non commercial ? Crédit à afficher ?
      Si c'est flou : accord écrit de l'éditeur (comme pour les sources du cyclisme).
- [ ] **robots.txt** : les pages utiles sont-elles autorisées aux robots ?
- [ ] **Accès depuis un serveur** : pas de protection anti-robot (page « Vérification que vous êtes humain », Cloudflare…). La collecte
      tourne sur GitHub Actions et ne contourne jamais ces protections (raison de l'exclusion de FotMob et SofaScore).
- [ ] **Délai** : combien de temps après la fin d'un match les données sont-elles complètes ?
- [ ] **Profondeur** : toute la saison en cours est-elle disponible, ou seulement les derniers matchs ?

---

## 3. Fiche à remplir pour chaque source

```
Source : (nom + adresse)
Pays couverts :
Niveaux couverts : A ☐  B ☐  C ☐  D ☐  E ☐   (préciser ce qui manque)
Format : API JSON / CSV / pages web
Clé ou compte : non / gratuit / payant — quotas :
Conditions d'utilisation (lien) :
Réutilisation autorisée : oui / non / à demander
Crédit à afficher :
Anti-robot constaté : non / oui (lequel)
Délai après match :
Profondeur (saison complète ? saisons passées ?) :
Exemple d'adresse d'un match terminé :
Remarques :
```

**Le plus utile : l'exemple d'adresse d'un match terminé.** Il permet de vérifier tout de suite ce que la source contient vraiment.
Pour la relever : Eruda sur téléphone ou F12 sur ordinateur, onglet Réseau (comme pour l'API de la LFP).
