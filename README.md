# coupes-europe

Tableau de bord mobile des soirées de Coupes d'Europe (LDC, Ligue Europa, Ligue Conférence),
avec focus sur les clubs français. Spécifications : voir `Projet_foot.md`.

## Fonctionnement

| Étape | Fichier | Rôle |
|---|---|---|
| 1 | `collector.py` | Collecte déterministe via l'API publique **ESPN** → `data_raw.json` |
| 2 | `agents_flash.py` | Résumés des matchs des clubs français (Gemini Flash rédacteur + contrôleur), repli déterministe sans IA |
| 3 | `notify.py` | Push ntfy avec lien vers le dashboard |
| — | `run_pipeline.py` | Enchaîne les 3 étapes |
| — | `index.html` | Dashboard statique (GitHub Pages) qui lit `data.json` |

Le workflow `.github/workflows/update_dashboard.yml` tourne mardi, mercredi et jeudi à 22h30 UTC
(23h30 heure de Paris en hiver) et commit `data.json`.

### Pourquoi ESPN et pas FotMob / SofaScore ?

- **FotMob** : l'endpoint `/api/matches` exige un en-tête signé (`x-mas`), donc les appels simples sont rejetés.
- **SofaScore** : protégé par Cloudflare, qui bloque les IP des runners GitHub Actions (HTTP 403).
- **ESPN** (`site.api.espn.com`) : sans clé ni blocage depuis GitHub Actions. Fournit les scores, buteurs,
  cartons, remplacements, compositions et formations, statistiques d'équipe, fil de commentaires et classement
  des 36 équipes.

Ce que ESPN ne fournit pas : les notes des joueurs et les statistiques par mi-temps (les onglets correspondants
se masquent). Le **momentum** est calculé à partir du fil de commentaires (tirs, tirs cadrés, poteaux, corners,
coups francs obtenus dans le camp adverse, par tranche de 5 min). Si le fil est absent, le graphique n'est pas affiché.

### Clubs français

Pas de liste codée en dur : à chaque exécution, le collecteur récupère les effectifs de la Ligue 1 et de la
Ligue 2 sur ESPN (`fra.1`, `fra.2`) et reconnaît les clubs français par identifiant d'équipe.

### Résumés

`agents_flash.py` construit un dossier factuel par match (score à la pause, phases de domination, moments clés
du fil, statistiques, classement). Gemini rédige un récit de 4-5 phrases, un second appel vérifie chaque fait,
avec jusqu'à 3 essais. Les rejets et erreurs API sont écrits en clair dans les logs du workflow. Sans clé ou après
3 rejets, un résumé narratif est généré sans IA à partir du même dossier.

## Lancer en local

```bash
python run_pipeline.py --date 2026-11-05 --no-notify   # une soirée
python run_pipeline.py --week --save-raw raw_espn       # mardi→jeudi de la semaine, réponses brutes sauvegardées
python -m http.server 8000                              # puis http://localhost:8000
```

Aucune dépendance externe (bibliothèque standard Python 3.9+).

## Secrets GitHub Actions

- `GEMINI_API_KEY` (optionnel) : sans clé, les résumés sont générés de façon déterministe.
- `NTFY_TOPIC` : topic ntfy (choisis un nom long et difficile à deviner).
- `DASHBOARD_URL` : URL GitHub Pages du dashboard.
