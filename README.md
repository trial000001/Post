# Vidéo quotidienne automatique (YouTube Shorts / TikTok / Instagram Reels)

Chaque jour, GitHub Actions :
1. choisit un sujet (histoire, psychologie, science…) et écrit un script de ~70 s en anglais (API Claude, modèle Haiku : quelques centimes par mois) ;
2. génère la voix (edge-tts, gratuit) ;
3. récupère des vidéos verticales libres de droits (Pexels, gratuit) ;
4. monte la vidéo 1080x1920 avec sous-titres animés (ffmpeg) ;
5. la dépose dans une « release » GitHub (URL publique) ;
6. envoie titre + légende + URL à un webhook Make, qui publie sur les 3 plateformes.

## Mise en place (≈ 30 min)

### 1. Dépôt GitHub
- Crée un dépôt **public** (l'URL de la vidéo doit être accessible à Make) et pousse ce dossier dedans.
- Settings > Actions > General > Workflow permissions : **Read and write**.

### 2. Clés (Settings > Secrets and variables > Actions > New repository secret)
| Secret | Où l'obtenir |
|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com (quelques centimes/mois) |
| `PEXELS_API_KEY` | pexels.com/api (gratuit, instantané) |
| `WEBHOOK_URL` | étape 3 |

### 3. Scénario Make (make.com, offre gratuite : 1000 opérations/mois)
1. Module **Webhooks > Custom webhook** : copie l'URL dans le secret `WEBHOOK_URL`. Lance une première fois le workflow pour que Make détecte les champs (`title`, `caption`, `video_url`, `hashtags`…).
2. Module **HTTP > Get a file** avec `video_url` (télécharge le mp4).
3. **YouTube > Upload a video** : titre `title`, description `caption`.
4. **TikTok** (module TikTok Posts) : vidéo + `caption`.
5. **Instagram for Business > Create a Reel** : `video_url` + `caption` (compte Pro relié à une Page Facebook).

Limites à connaître :
- TikTok : tant que l'app n'a pas été auditée, les posts via API peuvent être forcés en « privé ».
- Instagram : compte Professionnel obligatoire.
- YouTube : pense à bien déclarer le contenu (voix de synthèse). Le contenu 100 % automatisé et répétitif peut être déprécié : varie les sujets et relis de temps en temps.

### 4. Test
Onglet Actions > **Daily video** > Run workflow. Le workflow tourne ensuite tous les jours à 15:00 UTC (modifiable dans `.github/workflows/daily-video.yml`).

## Personnalisation (variables d'environnement)
- `TTS_VOICE` : voix edge-tts (ex. `en-US-GuyNeural`, `en-GB-RyanNeural`). Liste : `edge-tts --list-voices`.
- `CLAUDE_MODEL` : modèle utilisé pour le script.
- Catégories et prompt : en haut de `generate.py`.

## Test local sans réseau
`python generate.py --offline` (nécessite ffmpeg) → `output/video.mp4`.
