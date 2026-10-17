# SunuGestion — Backend

API REST de SunuGestion, l'application de gestion des groupements (GIE, associations) : membres, cotisations, prêts, activités, abonnements et paiements mobiles.

**Stack :** Python 3.12 · Django 6.1 · Django REST Framework · JWT (simplejwt) · PostgreSQL · PaddleOCR · PayDunya · OpenRouter (IA).

Le frontend Angular est un projet séparé. Pour lancer l'ensemble avec Docker, voir `SunuGestion-Docker/README.md`.

---

## Applications

| Application | Rôle |
|---|---|
| `authentication` | Utilisateurs, GIE, connexion par téléphone et PIN, JWT, verrouillage après 5 erreurs |
| `gie` | Informations du groupement et logo |
| `membres` | Membres, invitations et activation, import Excel |
| `cotisations` | Sessions et cotisations |
| `prets` | Demandes, règles, décaissements et remboursements |
| `activites` | Activités et présences |
| `paiements` | Intégration PayDunya (paiements entrants et sortants, notifications) |
| `abonnements` | Essai, grille tarifaire, abonnements (voir `docs/abonnements.md`) |
| `notifications` | Notifications et traitement des retards |
| `historiques` | Journal des opérations |
| `rapports` | Rapports PDF périodiques |
| `diagnostic` | Assistant financier (IA via OpenRouter) |
| `extraction` | Import de membres par photo : OCR (PaddleOCR) puis IA via n8n |

---

## Installation (développement)

Prérequis : Python 3.12, PostgreSQL, et n8n pour l'import par photo.

```bash
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# créer .env avec les variables ci-dessous
python manage.py migrate
python manage.py runserver   # http://localhost:8000
```

Créer un compte administrateur : `python manage.py createsuperuser`.

### Variables du `.env`

| Groupe | Variables |
|---|---|
| Django | `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` (optionnel) |
| Base de données | `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` |
| Adresses | `FRONTEND_URL`, `APP_URL`, `API_URL` |
| OCR et n8n | `N8N_WEBHOOK_URL`, `PADDLEOCR_LANG` |
| IA | `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` |
| E-mail | `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` |
| PayDunya | `PAYMENT_PROVIDER`, `PAYDUNYA_MODE`, `PAYDUNYA_MASTER_KEY`, `PAYDUNYA_PRIVATE_KEY`, `PAYDUNYA_PUBLIC_KEY`, `PAYDUNYA_TOKEN`, `PAYDUNYA_CALLBACK_URL`, `PAYDUNYA_RETURN_URL`, `PAYDUNYA_CANCEL_URL` |
| Derrière un proxy | `NUM_PROXIES` (nombre d'intermédiaires devant Django ; absent en développement) |

`PAYDUNYA_CALLBACK_URL` doit être une adresse publique (ngrok en développement) : `https://<adresse>/api/paiements/paydunya/callback/`.

Ne jamais publier `.env` ni `.env.docker` (exclus par `.gitignore`).

---

## Documentation de l'API

- Swagger : `http://localhost:8000/api/docs/`
- Redoc : `http://localhost:8000/api/redoc/`
- Schéma OpenAPI : `http://localhost:8000/api/schema/`

Toutes les routes sont sous `/api/`, sauf l'OCR (`/ocr/health`, `/api/process-document`) et l'admin (`/admin/`). Les clés JSON sont en camelCase côté client (conversion automatique), mais les paramètres d'adresse restent en snake_case (ex. `?type_periode=mensuel`).

---

## Tests

```bash
python manage.py test
```

Les limites de requêtes sont désactivées pendant les tests. Les fichiers envoyés (logos) sont écrits dans un dossier temporaire.

---

## Tâches planifiées

À lancer chaque jour (cron) :

```bash
python manage.py traiter_abonnements            # rappels d'échéance au président et au trésorier
python manage.py traiter_retards                # cotisations et prêts en retard : statut et notification
python manage.py supprimer_invitations_expirees # comptes jamais activés après expiration du lien
```

---

## Points à connaître

- **Mot de passe = PIN :** le mot de passe d'un compte est son code PIN à 4 chiffres. L'admin Django ne doit jamais être exposé sur internet : sa page de connexion n'a pas de limite de tentatives.
- **Import par photo :** les modèles de l'OCR se téléchargent au premier import (plusieurs minutes), puis environ 5 s par photo. Les analyses passent par un fil d'exécution unique (contrainte de PaddlePaddle). n8n doit tourner avec le workflow « Extraction personnes (OCR -> LLM) » actif.
- **Logos :** vérifiés (JPEG, PNG ou WebP, 2 Mo maximum), puis réencodés en WebP de 512 px au plus, dans `media/gie/logos/`. Servis par Django uniquement avec `DEBUG=True`, sinon par nginx.
- **PayDunya :** une notification n'est jamais crue sur parole : le statut et le montant sont revérifiés auprès de PayDunya avant validation.

---

## Docker

Fichiers propres à Docker dans ce dossier :

- `Dockerfile` : image Python 3.12, une seule version d'OpenCV (headless) ;
- `entrypoint.sh` : attend PostgreSQL, applique les migrations, collecte les fichiers statiques puis lance gunicorn (ou la commande fournie, comme runserver en mode développement) ;
- `.env.docker` : réglages propres à Docker, prioritaires sur `.env` (modèle : `.env.docker.example`).

Utilisation : voir `SunuGestion-Docker/README.md`.
