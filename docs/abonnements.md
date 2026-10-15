# Abonnements SunuGestion

Gestion des abonnements des groupements (instances) : essai gratuit, tarif mensuel selon la taille du groupement, paiement PayDunya, lecture seule à l'expiration, suivi par l'administrateur de la plateforme.

## Sommaire

1. [Règles métier](#1-règles-métier)
2. [Cycle de vie d'un abonnement](#2-cycle-de-vie-dun-abonnement)
3. [Modèle de données](#3-modèle-de-données)
4. [API](#4-api)
5. [Paiement PayDunya](#5-paiement-paydunya)
6. [Lecture seule](#6-lecture-seule)
7. [Tâche quotidienne et rappels](#7-tâche-quotidienne-et-rappels)
8. [Frontend](#8-frontend)
9. [Configuration et mise en place](#9-configuration-et-mise-en-place)
10. [Tests](#10-tests)
11. [Limites et évolutions possibles](#11-limites-et-évolutions-possibles)

---

## 1. Règles métier

| Règle | Valeur |
|---|---|
| Essai gratuit | 30 jours à la création du groupement, toutes fonctionnalités |
| Formule | une seule, « Premium », tout inclus, facturée **par mois** |
| Base du prix | membres **actifs** (les comptes en attente d'activation et les comptes suspendus ne comptent pas) |
| Moment du comptage | au moment du paiement (renouvellement) |
| Tolérance | 2 membres au-dessus de chaque seuil, à la hausse uniquement |
| Après l'essai | aucun délai : lecture seule dès le 31ᵉ jour sans paiement |
| Après une période payée | 3 jours de grâce (accès complet, bandeau d'alerte), puis lecture seule |
| Qui paie | le président ou le trésorier, par Wave ou Orange Money via PayDunya |
| Action de secours | l'administrateur peut enregistrer un paiement reçu hors application |

### Grille tarifaire

| Membres actifs | Prix affiché | Prix appliqué avec la tolérance |
|---|---|---|
| jusqu'à 15 | 5 000 FCFA | jusqu'à 17 membres |
| 16 à 34 | 10 000 FCFA | de 18 à 36 membres |
| 35 à 50 | 15 000 FCFA | de 37 à 52 membres |
| plus de 50 | 20 000 FCFA | à partir de 53 membres |

La grille et la tolérance sont définies dans `abonnements/services.py` (`PALIERS`, `TOLERANCE_MEMBRES`). C'est le seul endroit à modifier pour changer un prix : la facturation, la page d'accueil et l'inscription lisent cette même grille. Le délai de grâce est défini dans `abonnements/models.py` (`DELAI_GRACE_JOURS`) et la durée d'essai dans `abonnements/services.py` (`DUREE_ESSAI_JOURS`).

---

## 2. Cycle de vie d'un abonnement

```
Création du groupement
        │
        ▼
     ESSAI (30 jours) ──── paiement ───► ACTIF (1 mois)
        │                                   │
   fin de l'essai                      échéance
   sans paiement                           │
        │                                   ▼
        │                           DÉLAI DE GRÂCE (3 jours)
        │                                   │
        ▼                                   ▼
   LECTURE SEULE ◄──────────────────────────┘
        │
     paiement
        ▼
      ACTIF
```

- Le champ `statut` d'un abonnement indique la nature de la période en cours : `essai` ou `actif` (payée).
- L'**état d'accès** est calculé à partir des dates par `Abonnement.etat()` : `essai`, `actif`, `grace` ou `lecture_seule`. Il ne dépend d'aucune tâche planifiée : un groupement passe en lecture seule même si la tâche quotidienne ne tourne pas.
- La **suspension par l'administrateur** (bouton Activer / Désactiver de l'espace admin) est indépendante de l'abonnement : un groupement suspendu est entièrement bloqué, quel que soit son abonnement.

### Période couverte par un paiement

| Moment du paiement | Nouvelle période |
|---|---|
| Pendant l'essai, la période payée ou le délai de grâce | commence le lendemain de la date de fin actuelle (les jours d'essai restants ne sont pas perdus, le délai de grâce n'est pas offert) |
| En lecture seule | commence le jour du paiement |

Une période dure un mois calendaire (par exemple du 14/11 au 13/12). Plusieurs paiements successifs s'additionnent.

---

## 3. Modèle de données

Application Django : `abonnements`.

### `Abonnement` (table `abonnement`)

| Champ | Description |
|---|---|
| `gie` | groupement (un seul abonnement par groupement) |
| `statut` | `essai` ou `actif` |
| `date_debut`, `date_fin` | période en cours, dates incluses |
| `date_creation`, `date_mise_a_jour` | traçabilité |

Méthodes utiles : `etat()`, `acces_ecriture()`, `jours_restants()`, `delai_grace()`, `date_lecture_seule()`.

### `PaiementAbonnement` (table `paiement_abonnement`)

| Champ | Description |
|---|---|
| `abonnement` | abonnement concerné |
| `montant`, `nombre_membres` | tarif et membres actifs au moment du paiement |
| `mode_paiement` | `wave`, `orange_money` ou `manuel` |
| `statut` | `en_attente`, `valide` ou `echoue` |
| `token_paydunya` | référence de la facture PayDunya |
| `periode_debut`, `periode_fin` | période couverte, renseignée à la validation |
| `initie_par`, `note` | qui a lancé ou enregistré le paiement |

### Fonctions métier (`abonnements/services.py`)

| Fonction | Rôle |
|---|---|
| `calculer_tarif(nombre)` | montant, palier, tolérance, membres avant le palier suivant |
| `obtenir_abonnement(gie)` | abonnement du groupement ; crée un essai de 30 jours s'il n'en a pas |
| `periode_suivante(abonnement)` | période couverte par un nouveau paiement |
| `creer_paiement(gie, mode)` | paiement en attente au tarif actuel |
| `valider_paiement(paiement)` | prolonge l'abonnement ; idempotent (un paiement n'est jamais compté deux fois) |

---

## 4. API

Préfixe : `/api/abonnements/`. Les réponses sont en camelCase, comme le reste de l'API.

| Méthode | Endpoint | Accès | Rôle |
|---|---|---|---|
| GET | `grille/` | public | grille tarifaire, tolérance, durée d'essai et moyens de paiement ; affichée sur la page d'accueil et à l'inscription |
| GET | `mon-abonnement/` | membre du groupement | état de l'abonnement ; pour le président et le trésorier, aussi le tarif, la prochaine période, la grille et les 12 derniers paiements |
| POST | `payer/` | président, trésorier | crée une facture PayDunya ; corps : `{"modePaiement": "wave" \| "orange_money"}` ; répond `paiementId`, `montant`, `urlPaiement` |
| GET | `paiements/<id>/` | président, trésorier du groupement | statut d'un paiement ; interroge PayDunya s'il est encore en attente |
| GET | `admin/instances/` | administrateur | tous les groupements avec leur abonnement, leurs membres actifs et leur prix mensuel |
| GET | `admin/instances/<id>/` | administrateur | détail et historique des paiements d'un groupement |
| POST | `admin/instances/<id>/paiement-manuel/` | administrateur | enregistre un paiement reçu hors application et prolonge d'un mois ; corps : `{"note": "..."}` |

Le paiement PayDunya est confirmé par le callback existant : `POST /api/paiements/paydunya/callback/`.

---

## 5. Paiement PayDunya

L'intégration réutilise `paiements/paydunya_service.py`, déjà utilisé pour les cotisations et les prêts.

1. Le président ou le trésorier clique sur « Payer avec Wave » ou « Payer avec Orange Money » dans Configuration.
2. `POST /api/abonnements/payer/` calcule le montant sur les membres actifs, crée un `PaiementAbonnement` en attente, puis une facture PayDunya de référence `ABONNEMENT-<id>`.
3. L'utilisateur est redirigé vers PayDunya et paie.
4. PayDunya appelle le callback. Le callback reconnaît le jeton du paiement d'abonnement, **revérifie la facture auprès de PayDunya**, contrôle que le montant confirmé correspond, puis valide le paiement et prolonge l'abonnement. Le président et le trésorier reçoivent une notification « Abonnement renouvelé ».
5. PayDunya renvoie l'utilisateur sur `/paiement/retour?type=abonnement&id=<id>`. La page interroge `GET /api/abonnements/paiements/<id>/`, qui vérifie aussi auprès de PayDunya si le callback n'est pas encore arrivé.

Garanties :
- l'abonnement n'est jamais prolongé sur une simple redirection, seulement sur une confirmation PayDunya avec le bon montant ;
- un callback répété est sans effet (validation idempotente) ;
- un paiement annulé ou refusé passe à `echoue`.

---

## 6. Lecture seule

Quand l'état est `lecture_seule` :
- **toutes les consultations restent possibles** (requêtes GET) ;
- **toute nouvelle opération est refusée** (POST, PUT, PATCH, DELETE) avec une erreur 403 : « L'abonnement de votre groupement a expiré : le groupement est en lecture seule jusqu'au renouvellement… ».

Le contrôle est fait dans `authentication/permissions.py` (`gie_utilisable`), utilisé par toutes les permissions des membres d'un groupement (`EstMembreGIE`, `EstPresident`, `EstTresorier`, etc.). Aucun module n'a eu besoin d'être modifié individuellement.

Opérations toujours permises :

| Opération | Mécanisme |
|---|---|
| Payer l'abonnement | `autorise_en_lecture_seule = True` sur `PayerAbonnementView` |
| Modifier son profil, changer son code PIN | `actions_autorisees_en_lecture_seule` sur `MembreViewSet` |
| Connexion, déconnexion, notifications | ces vues n'utilisent pas les permissions de groupement |

Pour permettre une autre opération en lecture seule, ajouter `autorise_en_lecture_seule = True` à la vue, ou le nom de l'action dans `actions_autorisees_en_lecture_seule` pour un ViewSet.

---

## 7. Tâche quotidienne et rappels

Commande : `python manage.py traiter_abonnements`.

Elle envoie une notification au président et au trésorier :

| Moment | Notification |
|---|---|
| 7 jours avant l'échéance, la veille, le jour même | « Abonnement : échéance proche », avec le montant |
| lendemain de l'échéance d'une période payée | « Abonnement expiré », début du délai de grâce |
| premier jour de lecture seule | « Groupement en lecture seule » |

Planification (crontab), par exemple chaque jour à 1 h 45 :

```
45 1 * * * cd /home/fatoumatadrame/Bureau/Django/sunugestion-backend && /home/fatoumatadrame/Bureau/Django/sunugestion-backend/venv/bin/python manage.py traiter_abonnements >> /home/fatoumatadrame/Bureau/Django/sunugestion-backend/logs/abonnements.log 2>&1
```

La tâche ne fait qu'envoyer des rappels : le passage en lecture seule est calculé à chaque requête.

---

## 8. Frontend

| Élément | Fichier | Contenu |
|---|---|---|
| Service | `core/services/abonnement.service.ts` | chargement de l'abonnement, paiement, appels administrateur, texte du bandeau |
| Modèle | `core/models/abonnement.model.ts` | types de l'API |
| Carte « Abonnement » | `features/espace-gie/pages/informations-gie/carte-abonnement/` | page Configuration, président et trésorier : état, date de fin, membres actifs, prix, palier suivant, boutons de paiement, grille, derniers paiements |
| Bandeau d'alerte | `shared/ui/navbar/` | fin d'essai ou d'abonnement dans 7 jours ou moins (président et trésorier), délai de grâce et lecture seule (tous les membres) |
| Retour de paiement | `features/espace-gie/pages/paiement/retour-paiement.ts` | gère `type=abonnement` |
| Page d'accueil | `features/landing-page/` | section « Tarification » (essai, grille, conditions) lue depuis `GET /api/abonnements/grille/`, liens dans la barre du haut, le menu mobile et le pied de page, rappel du prix dans l'encadré final |
| Inscription | `features/inscription/pages/etape-gie/` | mention de l'essai et du prix minimum, avec un lien vers les tarifs (`/#tarification`) |
| Espace administrateur | `features/espace-admin/pages/espaces-gie-list/` | colonnes « Abonnement » et « Prix / mois », fenêtre de détail avec l'historique, action « Enregistrer un paiement reçu » |

---

## 9. Configuration et mise en place

### Variables d'environnement (`.env`)

Les variables PayDunya existantes sont réutilisées :

| Variable | Rôle |
|---|---|
| `PAYDUNYA_MODE`, clés et jeton | identifiants PayDunya (mode `test` en développement) |
| `PAYDUNYA_CALLBACK_URL` | adresse publique du callback : `https://<adresse-ngrok>/api/paiements/paydunya/callback/` |
| `PAYDUNYA_RETURN_URL` | page de retour : `<adresse de l'application>/paiement/retour` |

En développement, le tunnel ngrok pointe vers le serveur Angular, qui transmet `/api` à Django (`proxy.conf.json`) : le callback PayDunya passe donc par la même adresse ngrok.

### Mise en place

1. `python manage.py migrate` : crée les tables, puis ouvre un essai de 30 jours, à partir de la date de migration, pour chaque groupement existant (migration `0002_essai_groupements_existants`).
2. Ajouter la ligne de crontab de `traiter_abonnements`.
3. Vérifier `PAYDUNYA_CALLBACK_URL` et `PAYDUNYA_RETURN_URL`.

---

## 10. Tests

```
python manage.py test abonnements
```

28 tests couvrent :
- la grille tarifaire et la tolérance, avec tous les seuils ;
- l'essai de 30 jours, l'absence de délai après l'essai, les 3 jours de grâce ;
- la période couverte selon le moment du paiement ;
- la validation idempotente et le calcul sur les seuls membres actifs ;
- la lecture seule : consultations permises, opérations refusées dans plusieurs modules, profil, code PIN et paiement toujours permis, autres groupements non affectés ;
- les droits : détails et paiement réservés au président et au trésorier ;
- PayDunya (simulé) : création de la facture, confirmation par le callback, callback répété, montant incohérent, paiement annulé, vérification au retour ;
- l'espace administrateur : accès réservé, liste, détail, paiement manuel ;
- les rappels de la tâche quotidienne ;
- la grille publique, accessible sans connexion.

### Vérification manuelle (mode test PayDunya)

1. Ouvrir Configuration en président : la carte « Abonnement » indique « Essai gratuit » et le prix.
2. Cliquer « Payer avec Wave » : redirection vers PayDunya (mode test), payer, revenir sur la page de retour : « confirmé ».
3. La carte indique « Actif » ; l'historique contient le paiement ; une notification « Abonnement renouvelé » est reçue.
4. Pour tester la lecture seule, mettre une date de fin passée dans l'administration Django (Abonnement), puis tenter une opération : refus avec le message de lecture seule et bandeau rouge.
5. Dans l'espace administrateur, ouvrir l'abonnement d'un groupement et utiliser « Enregistrer un paiement reçu ».

---

## 11. Limites et évolutions possibles

- **Pas de paiement annuel** : une seule période d'un mois par paiement.
- **Pas de remboursement ni de prorata** : un changement de palier s'applique au paiement suivant.
- **Montants arrondis au franc** : PayDunya reçoit un montant entier.
- **Écrans en lecture seule** : les boutons d'action restent affichés ; une action refusée affiche le message du serveur. Masquer les boutons en lecture seule serait une amélioration d'ergonomie.
- **Action de secours** prévue pour la phase de développement : à revoir avant la mise en production.
- **Évolutions envisageables** : paiement annuel avec réduction, factures téléchargeables, tableau des revenus dans l'espace administrateur, limites de fonctionnalités par formule.
