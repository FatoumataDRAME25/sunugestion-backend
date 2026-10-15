from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from authentication.models import GIE, Utilisateur


class ProfilMembreTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.gie = GIE.objects.create(
            nom='Groupement Alpha', region='Dakar', type_gie='groupement',
            code='ALPHA', statut='actif'
        )
        cls.membre = Utilisateur.objects.create_user(
            telephone='770000002', nom='Fall', prenom='Moussa',
            role='membre', gie=cls.gie, statut='actif', password='1234'
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.membre)

    def changer_pin(self, **donnees):
        # Mêmes clés camelCase que celles envoyées par le frontend
        return self.client.post(
            '/api/membres/membres/changer-pin/', donnees, format='json'
        )

    def test_changement_de_pin(self):
        reponse = self.changer_pin(
            pinActuel='1234', nouveauPin='5678', confirmationPin='5678'
        )

        self.assertEqual(reponse.status_code, 200)
        self.membre.refresh_from_db()
        self.assertTrue(self.membre.check_password('5678'))

    def test_pin_actuel_incorrect(self):
        reponse = self.changer_pin(
            pinActuel='0000', nouveauPin='5678', confirmationPin='5678'
        )

        self.assertEqual(reponse.status_code, 400)
        self.assertIn('incorrect', reponse.json()['erreur'])
        self.membre.refresh_from_db()
        self.assertTrue(self.membre.check_password('1234'))

    def test_champ_manquant(self):
        reponse = self.changer_pin(pinActuel='1234', nouveauPin='5678')

        self.assertEqual(reponse.status_code, 400)
        self.assertIn('obligatoires', reponse.json()['erreur'])

    def test_telephone_non_modifiable(self):
        reponse = self.client.patch(
            f'/api/membres/membres/{self.membre.id}/',
            {'telephone': '781112233', 'email': 'moussa@example.com'},
            format='json'
        )

        self.assertEqual(reponse.status_code, 200)
        self.membre.refresh_from_db()
        self.assertEqual(self.membre.telephone, '770000002')
        self.assertEqual(self.membre.email, 'moussa@example.com')


class ChangerPinAdminTestCase(TestCase):

    def test_changement_de_pin_administrateur(self):
        administrateur = Utilisateur.objects.create_user(
            telephone='770000099', nom='Admin', prenom='Plateforme',
            role='administrateur', statut='actif', password='1234'
        )
        client = APIClient()
        client.force_authenticate(user=administrateur)

        reponse = client.post(
            '/api/auth/changer-pin/',
            {'pinActuel': '1234', 'nouveauPin': '5678', 'confirmationPin': '5678'},
            format='json'
        )

        self.assertEqual(reponse.status_code, 200)
        administrateur.refresh_from_db()
        self.assertTrue(administrateur.check_password('5678'))


# ──────────────────────────────────────────────────────────────────────────
# Gestion des membres par le président : suspension, réactivation, rôles
# ──────────────────────────────────────────────────────────────────────────

BASE = '/api/membres/membres/'


class GestionMembresMixin:

    @classmethod
    def setUpTestData(cls):
        cls.gie = GIE.objects.create(
            nom='Groupement Alpha', region='Dakar', type_gie='groupement',
            code='ALPHA', statut='actif'
        )
        cls.autre_gie = GIE.objects.create(
            nom='Groupement Beta', region='Thiès', type_gie='groupement',
            code='BETA', statut='actif'
        )

        cls.president = cls.creer(cls.gie, '770000001', 'president')
        cls.tresorier = cls.creer(cls.gie, '770000002', 'tresorier')
        cls.secretaire = cls.creer(cls.gie, '770000003', 'secretaire')
        cls.membre = cls.creer(cls.gie, '770000004', 'membre')
        cls.membre2 = cls.creer(cls.gie, '770000005', 'membre')
        # Compte invité qui n'a jamais terminé son activation (pas de PIN)
        cls.invite = cls.creer(
            cls.gie, '770000006', 'membre', statut='en_attente', active=False
        )

        cls.president_beta = cls.creer(cls.autre_gie, '770000011', 'president')
        cls.membre_beta = cls.creer(cls.autre_gie, '770000012', 'membre')

    @staticmethod
    def creer(gie, telephone, role, statut='actif', active=True):
        utilisateur = Utilisateur.objects.create_user(
            telephone=telephone, nom=f'Nom{telephone[-2:]}', prenom='Prenom',
            role=role, gie=gie, statut=statut
        )
        if active:
            # Simule un PIN déjà défini sans payer le coût du hachage
            Utilisateur.objects.filter(pk=utilisateur.pk).update(
                password='hash-de-test'
            )
            utilisateur.refresh_from_db()
        return utilisateur

    def setUp(self):
        self.client = APIClient()

    def appeler(self, utilisateur, methode, url, donnees=None):
        client = APIClient()
        if utilisateur is not None:
            client.force_authenticate(user=utilisateur)
        return getattr(client, methode)(url, donnees, format='json')

    def roles(self, gie, role):
        return Utilisateur.objects.filter(gie=gie, role=role).count()


class SuspensionReactivationTestCase(GestionMembresMixin, TestCase):

    def suspendre(self, auteur, cible):
        return self.appeler(auteur, 'patch', f'{BASE}{cible.id}/suspendre/')

    def reactiver(self, auteur, cible):
        return self.appeler(auteur, 'patch', f'{BASE}{cible.id}/reactiver/')

    def test_suspension_puis_reactivation(self):
        reponse = self.suspendre(self.president, self.membre)

        self.assertEqual(reponse.status_code, 200)
        self.membre.refresh_from_db()
        self.assertEqual(self.membre.statut, 'inactif')
        self.assertFalse(self.membre.is_active)

        # Déjà suspendu
        self.assertEqual(self.suspendre(self.president, self.membre).status_code, 400)

        reponse = self.reactiver(self.president, self.membre)

        self.assertEqual(reponse.status_code, 200)
        self.membre.refresh_from_db()
        self.assertEqual(self.membre.statut, 'actif')
        self.assertTrue(self.membre.is_active)

        # Déjà actif
        self.assertEqual(self.reactiver(self.president, self.membre).status_code, 400)

    def test_le_president_ne_peut_pas_se_suspendre(self):
        reponse = self.suspendre(self.president, self.president)

        self.assertEqual(reponse.status_code, 403)
        self.president.refresh_from_db()
        self.assertEqual(self.president.statut, 'actif')
        self.assertTrue(self.president.is_active)

    def test_le_tresorier_ne_peut_pas_etre_suspendu(self):
        reponse = self.suspendre(self.president, self.tresorier)

        self.assertEqual(reponse.status_code, 403)
        self.assertIn('trésorier', reponse.json()['erreur'])
        self.tresorier.refresh_from_db()
        self.assertEqual(self.tresorier.statut, 'actif')
        self.assertTrue(self.tresorier.is_active)

    def test_un_compte_jamais_active_ne_peut_pas_etre_suspendu(self):
        reponse = self.suspendre(self.president, self.invite)

        self.assertEqual(reponse.status_code, 400)
        self.invite.refresh_from_db()
        self.assertEqual(self.invite.statut, 'en_attente')

    def test_un_compte_jamais_active_ne_peut_pas_etre_reactive(self):
        reponse = self.reactiver(self.president, self.invite)

        self.assertEqual(reponse.status_code, 400)
        self.assertIn('jamais été activé', reponse.json()['erreur'])
        self.invite.refresh_from_db()
        self.assertEqual(self.invite.statut, 'en_attente')

    def test_ancien_compte_suspendu_sans_activation_non_reactive(self):
        # Donnée héritée : compte jamais activé mais marqué « inactif »
        Utilisateur.objects.filter(pk=self.invite.pk).update(statut='inactif')

        reponse = self.reactiver(self.president, self.invite)

        self.assertEqual(reponse.status_code, 400)
        self.invite.refresh_from_db()
        self.assertEqual(self.invite.statut, 'inactif')

    def test_seul_le_president_peut_suspendre_ou_reactiver(self):
        for auteur in (self.membre2, self.tresorier, self.secretaire):
            with self.subTest(role=auteur.role):
                self.assertEqual(self.suspendre(auteur, self.membre).status_code, 403)
                self.assertEqual(self.reactiver(auteur, self.membre).status_code, 403)

        self.assertEqual(self.suspendre(None, self.membre).status_code, 401)
        self.membre.refresh_from_db()
        self.assertEqual(self.membre.statut, 'actif')

    def test_cloisonnement_entre_gie(self):
        self.assertEqual(self.suspendre(self.president, self.membre_beta).status_code, 404)
        self.assertEqual(self.suspendre(self.president_beta, self.membre).status_code, 404)
        self.assertEqual(self.reactiver(self.president_beta, self.membre).status_code, 404)

        for utilisateur in (self.membre, self.membre_beta):
            utilisateur.refresh_from_db()
            self.assertEqual(utilisateur.statut, 'actif')

    def test_identifiant_invalide(self):
        for action in ('suspendre', 'reactiver', 'modifier-role'):
            with self.subTest(action=action):
                reponse = self.appeler(
                    self.president, 'patch', f'{BASE}abc/{action}/',
                    {'role': 'membre'}
                )
                self.assertEqual(reponse.status_code, 404)

        self.assertEqual(
            self.appeler(self.membre, 'get', f'{BASE}abc/').status_code, 404
        )
        self.assertEqual(
            self.appeler(self.membre, 'get', f'{BASE}999999/').status_code, 404
        )


class JetonsCompteSuspenduTestCase(GestionMembresMixin, TestCase):

    def test_jetons_refuses_pendant_la_suspension(self):
        from rest_framework_simplejwt.tokens import RefreshToken

        jeton = RefreshToken.for_user(self.membre)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {jeton.access_token}')

        # Avant la suspension : accès et renouvellement possibles
        self.assertEqual(client.get(BASE).status_code, 200)

        self.appeler(self.president, 'patch', f'{BASE}{self.membre.id}/suspendre/')

        # Jeton d'accès déjà émis : refusé sur une API protégée
        self.assertEqual(client.get(BASE).status_code, 401)
        self.assertEqual(client.get('/api/historiques/solde/').status_code, 401)

        # Renouvellement des jetons : refusé
        reponse = APIClient().post(
            '/api/auth/refresh/', {'refresh': str(jeton)}, format='json'
        )
        self.assertEqual(reponse.status_code, 401)
        self.assertNotIn('access', reponse.json())

        # Après réactivation, le même jeton d'accès fonctionne à nouveau
        self.appeler(self.president, 'patch', f'{BASE}{self.membre.id}/reactiver/')
        self.assertEqual(client.get(BASE).status_code, 200)

    def test_les_autres_membres_ne_sont_pas_affectes(self):
        from rest_framework_simplejwt.tokens import RefreshToken

        jeton = RefreshToken.for_user(self.membre2)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {jeton.access_token}')

        self.appeler(self.president, 'patch', f'{BASE}{self.membre.id}/suspendre/')

        self.assertEqual(client.get(BASE).status_code, 200)
        reponse = APIClient().post(
            '/api/auth/refresh/', {'refresh': str(jeton)}, format='json'
        )
        self.assertEqual(reponse.status_code, 200)
        self.assertIn('access', reponse.json())

    def test_message_de_connexion_d_un_compte_suspendu(self):
        self.membre.set_password('1234')
        self.membre.save()
        self.appeler(self.president, 'patch', f'{BASE}{self.membre.id}/suspendre/')

        reponse = APIClient().post(
            '/api/auth/connexion/',
            {'telephone': self.membre.telephone, 'pin': '1234'},
            format='json'
        )

        self.assertEqual(reponse.status_code, 400)
        self.assertIn('suspendu', str(reponse.json()))
        self.assertNotIn('tokens', reponse.json())

    def test_connexion_normale_inchangee(self):
        self.membre.set_password('1234')
        self.membre.save()

        reponse = APIClient().post(
            '/api/auth/connexion/',
            {'telephone': self.membre.telephone, 'pin': '1234'},
            format='json'
        )

        self.assertEqual(reponse.status_code, 200)
        self.assertIn('tokens', reponse.json())


class ModificationRoleTestCase(GestionMembresMixin, TestCase):

    def modifier(self, auteur, cible, **donnees):
        return self.appeler(
            auteur, 'patch', f'{BASE}{cible.id}/modifier-role/', donnees
        )

    def verifier_un_seul_president(self):
        self.assertEqual(self.roles(self.gie, 'president'), 1)
        self.assertEqual(self.roles(self.autre_gie, 'president'), 1)

    def test_changement_de_role_simple(self):
        # Libérer le poste de secrétaire, puis le réattribuer
        self.assertEqual(
            self.modifier(self.president, self.secretaire, role='membre').status_code, 200
        )
        reponse = self.modifier(self.president, self.membre, role='secretaire')

        self.assertEqual(reponse.status_code, 200)
        self.membre.refresh_from_db()
        self.assertEqual(self.membre.role, 'secretaire')
        self.verifier_un_seul_president()

    def test_passation_de_presidence_reussie(self):
        reponse = self.modifier(
            self.president, self.membre,
            role='president', roleAncienPresident='membre'
        )

        self.assertEqual(reponse.status_code, 200)
        self.membre.refresh_from_db()
        self.president.refresh_from_db()
        self.assertEqual(self.membre.role, 'president')
        self.assertEqual(self.president.role, 'membre')
        self.assertEqual(reponse.json()['ancienPresident']['role'], 'membre')
        self.verifier_un_seul_president()

        # L'ancien président n'a plus les droits du président
        self.assertEqual(
            self.modifier(self.president, self.membre2, role='membre').status_code, 403
        )

    def test_passation_avec_echange_de_fonction(self):
        # Le trésorier devient président, l'ancien président devient trésorier
        reponse = self.modifier(
            self.president, self.tresorier,
            role='president', roleAncienPresident='tresorier'
        )

        self.assertEqual(reponse.status_code, 200)
        self.tresorier.refresh_from_db()
        self.president.refresh_from_db()
        self.assertEqual(self.tresorier.role, 'president')
        self.assertEqual(self.president.role, 'tresorier')
        self.assertEqual(self.roles(self.gie, 'tresorier'), 1)
        self.verifier_un_seul_president()

    def test_passations_invalides(self):
        cas = [
            ('rôle de l\'ancien président absent', self.membre, {'role': 'president'}),
            ('ancien président reste président', self.membre,
             {'role': 'president', 'roleAncienPresident': 'president'}),
            ('rôle de l\'ancien président invalide', self.membre,
             {'role': 'president', 'roleAncienPresident': 'administrateur'}),
            ('rôle de l\'ancien président non textuel', self.membre,
             {'role': 'president', 'roleAncienPresident': 3}),
            ('poste de trésorier déjà occupé', self.membre,
             {'role': 'president', 'roleAncienPresident': 'tresorier'}),
            ('nouveau président jamais activé', self.invite,
             {'role': 'president', 'roleAncienPresident': 'membre'}),
            ('président vers lui-même', self.president,
             {'role': 'president', 'roleAncienPresident': 'membre'}),
        ]

        for libelle, cible, donnees in cas:
            with self.subTest(cas=libelle):
                reponse = self.modifier(self.president, cible, **donnees)
                self.assertEqual(reponse.status_code, 400)
                self.president.refresh_from_db()
                self.assertEqual(self.president.role, 'president')
                self.verifier_un_seul_president()

    def test_passation_vers_un_membre_suspendu_refusee(self):
        self.appeler(self.president, 'patch', f'{BASE}{self.membre.id}/suspendre/')

        reponse = self.modifier(
            self.president, self.membre,
            role='president', roleAncienPresident='membre'
        )

        self.assertEqual(reponse.status_code, 400)
        self.verifier_un_seul_president()
        self.president.refresh_from_db()
        self.assertEqual(self.president.role, 'president')

    def test_le_president_ne_peut_pas_se_retrograder_seul(self):
        for role in ('membre', 'tresorier', 'secretaire'):
            with self.subTest(role=role):
                reponse = self.modifier(self.president, self.president, role=role)
                self.assertEqual(reponse.status_code, 400)
                self.president.refresh_from_db()
                self.assertEqual(self.president.role, 'president')

        self.verifier_un_seul_president()

    def test_unicite_du_tresorier_et_du_secretaire(self):
        for role in ('tresorier', 'secretaire'):
            with self.subTest(role=role):
                reponse = self.modifier(self.president, self.membre, role=role)
                self.assertEqual(reponse.status_code, 400)
                self.assertIn('déjà', reponse.json()['erreur'])
                self.assertEqual(self.roles(self.gie, role), 1)

        self.membre.refresh_from_db()
        self.assertEqual(self.membre.role, 'membre')

        # Réattribuer le même rôle à son titulaire n'est pas un doublon
        self.assertEqual(
            self.modifier(self.president, self.tresorier, role='tresorier').status_code, 200
        )
        # Plusieurs membres simples restent possibles
        self.assertEqual(
            self.modifier(self.president, self.secretaire, role='membre').status_code, 200
        )

    def test_fonction_du_bureau_refusee_a_un_membre_suspendu(self):
        self.modifier(self.president, self.secretaire, role='membre')
        self.appeler(self.president, 'patch', f'{BASE}{self.membre.id}/suspendre/')

        reponse = self.modifier(self.president, self.membre, role='secretaire')

        self.assertEqual(reponse.status_code, 400)
        self.membre.refresh_from_db()
        self.assertEqual(self.membre.role, 'membre')

    def test_roles_et_types_invalides(self):
        for valeur in ('administrateur', 'chef', '', None, 5, True, ['membre'], {'a': 1}):
            with self.subTest(valeur=valeur):
                reponse = self.modifier(self.president, self.membre, role=valeur)
                self.assertEqual(reponse.status_code, 400)

        self.assertEqual(
            self.appeler(
                self.president, 'patch', f'{BASE}{self.membre.id}/modifier-role/', {}
            ).status_code,
            400
        )
        self.membre.refresh_from_db()
        self.assertEqual(self.membre.role, 'membre')
        self.assertFalse(Utilisateur.objects.filter(gie=self.gie, role='administrateur').exists())

    def test_seul_le_president_modifie_les_roles(self):
        for auteur in (self.membre2, self.tresorier, self.secretaire):
            with self.subTest(role=auteur.role):
                reponse = self.modifier(auteur, self.membre, role='membre')
                self.assertEqual(reponse.status_code, 403)

        self.assertEqual(self.modifier(None, self.membre, role='membre').status_code, 401)

        # Un membre ne peut pas se promouvoir lui-même
        reponse = self.modifier(
            self.membre, self.membre, role='president', roleAncienPresident='membre'
        )
        self.assertEqual(reponse.status_code, 403)
        self.verifier_un_seul_president()

    def test_cloisonnement_entre_gie(self):
        reponse = self.modifier(self.president, self.membre_beta, role='tresorier')
        self.assertEqual(reponse.status_code, 404)

        reponse = self.modifier(
            self.president_beta, self.membre,
            role='president', roleAncienPresident='membre'
        )
        self.assertEqual(reponse.status_code, 404)

        self.membre_beta.refresh_from_db()
        self.assertEqual(self.membre_beta.role, 'membre')
        self.verifier_un_seul_president()

        # Le trésorier d'un autre GIE ne bloque pas l'attribution du poste
        self.assertEqual(
            self.modifier(self.president_beta, self.membre_beta, role='tresorier').status_code,
            200
        )


class DetailMembreTestCase(GestionMembresMixin, TestCase):

    def test_detail_inchange_et_cloisonne(self):
        reponse = self.appeler(self.membre, 'get', f'{BASE}{self.tresorier.id}/')

        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(
            set(reponse.json()),
            {'id', 'prenom', 'nom', 'telephone', 'email', 'role', 'fonctionBureau', 'statut', 'invitationExpiration'}
        )
        self.assertEqual(
            self.appeler(self.membre, 'get', f'{BASE}{self.membre_beta.id}/').status_code,
            404
        )
        self.assertEqual(
            self.appeler(None, 'get', f'{BASE}{self.tresorier.id}/').status_code, 401
        )


class FonctionBureauTestCase(GestionMembresMixin, TestCase):

    def modifier(self, auteur, cible, valeur):
        return self.appeler(
            auteur, 'patch', f'{BASE}{cible.id}/modifier-fonction/',
            {'fonctionBureau': valeur}
        )

    def test_attribuer_et_retirer_une_fonction(self):
        reponse = self.modifier(self.president, self.membre, 'vice_president')

        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.json()['membre']['fonctionBureau'], 'vice_president')
        self.membre.refresh_from_db()
        self.assertEqual(self.membre.fonction_bureau, 'vice_president')
        # La fonction ne change pas le rôle ni les droits
        self.assertEqual(self.membre.role, 'membre')

        reponse = self.modifier(self.president, self.membre, '')

        self.assertEqual(reponse.status_code, 200)
        self.membre.refresh_from_db()
        self.assertEqual(self.membre.fonction_bureau, '')

    def test_une_seule_personne_par_fonction(self):
        self.modifier(self.president, self.membre, 'tresorier_adjoint')

        reponse = self.modifier(self.president, self.membre2, 'tresorier_adjoint')

        self.assertEqual(reponse.status_code, 400)
        self.assertIn('déjà occupée', reponse.json()['erreur'])
        self.assertEqual(
            Utilisateur.objects.filter(gie=self.gie, fonction_bureau='tresorier_adjoint').count(),
            1
        )
        # Plusieurs membres sans fonction restent possibles
        self.assertEqual(self.modifier(self.president, self.membre2, '').status_code, 200)

    def test_fonctions_invalides(self):
        for valeur in ('president', 'tresorier', 'chef', None, 5, ['vice_president']):
            with self.subTest(valeur=valeur):
                reponse = self.modifier(self.president, self.membre, valeur)
                self.assertEqual(reponse.status_code, 400)

        self.membre.refresh_from_db()
        self.assertEqual(self.membre.fonction_bureau, '')

    def test_fonction_refusee_a_un_membre_suspendu(self):
        self.appeler(self.president, 'patch', f'{BASE}{self.membre.id}/suspendre/')

        self.assertEqual(
            self.modifier(self.president, self.membre, 'secretaire_adjoint').status_code,
            400
        )

    def test_seul_le_president_modifie_et_cloisonnement(self):
        for auteur in (self.membre2, self.tresorier, self.secretaire):
            with self.subTest(role=auteur.role):
                self.assertEqual(
                    self.modifier(auteur, self.membre, 'vice_president').status_code, 403
                )

        self.assertEqual(
            self.modifier(self.president, self.membre_beta, 'vice_president').status_code, 404
        )
        self.assertEqual(
            self.modifier(self.president_beta, self.membre, 'vice_president').status_code, 404
        )
        # La même fonction peut exister dans deux GIE différents
        self.modifier(self.president, self.membre, 'vice_president')
        self.assertEqual(
            self.modifier(self.president_beta, self.membre_beta, 'vice_president').status_code,
            200
        )

    def test_la_fonction_ne_peut_pas_etre_modifiee_par_le_profil(self):
        self.appeler(
            self.membre, 'patch', f'{BASE}{self.membre.id}/',
            {'fonctionBureau': 'vice_president'}
        )

        self.membre.refresh_from_db()
        self.assertEqual(self.membre.fonction_bureau, '')


class CotisationsMembreTestCase(GestionMembresMixin, TestCase):

    def setUp(self):
        super().setUp()
        from datetime import timedelta
        from cotisations.models import Cotisation, SessionCotisation

        aujourd_hui = timezone.localdate()

        def session(libelle, montant, debut, fin):
            return SessionCotisation.objects.create(
                createur=self.tresorier, libelle=libelle, montant=montant,
                date_debut=debut, date_fin=fin
            )

        passee = session('Janvier', 5000, aujourd_hui - timedelta(days=60), aujourd_hui - timedelta(days=30))
        echue = session('Février', 3000, aujourd_hui - timedelta(days=29), aujourd_hui - timedelta(days=1))
        ouverte = session('Mars', 2000, aujourd_hui - timedelta(days=5), aujourd_hui + timedelta(days=20))

        Cotisation.objects.create(
            session=passee, membre=self.membre, statut='paye',
            date_paiement=timezone.now(), mode_paiement='especes'
        )
        # Session échue, statut pas encore mis à jour par la tâche planifiée
        Cotisation.objects.create(session=echue, membre=self.membre, statut='en_cours')
        Cotisation.objects.create(session=ouverte, membre=self.membre, statut='en_cours')
        # Cotisation d'un autre membre : jamais incluse
        Cotisation.objects.create(session=ouverte, membre=self.membre2, statut='paye')

    def test_cotisations_d_un_membre(self):
        reponse = self.appeler(self.membre2, 'get', f'{BASE}{self.membre.id}/cotisations/')

        self.assertEqual(reponse.status_code, 200)
        donnees = reponse.json()
        self.assertEqual(
            [(c['session'], c['statut']) for c in donnees['cotisations']],
            [('Mars', 'en_cours'), ('Février', 'en_retard'), ('Janvier', 'paye')]
        )
        self.assertEqual(int(donnees['totalPaye']), 5000)
        self.assertEqual(int(donnees['totalEnRetard']), 3000)
        self.assertEqual(int(donnees['totalEnCours']), 2000)
        self.assertEqual(donnees['nombrePayees'], 1)
        self.assertEqual(donnees['nombreEnRetard'], 1)
        self.assertEqual(donnees['cotisations'][2]['modePaiement'], 'especes')

    def test_membre_sans_cotisation(self):
        donnees = self.appeler(
            self.membre, 'get', f'{BASE}{self.secretaire.id}/cotisations/'
        ).json()

        self.assertEqual(donnees['cotisations'], [])
        self.assertEqual(int(donnees['totalPaye']), 0)

    def test_acces_et_cloisonnement(self):
        url = f'{BASE}{self.membre.id}/cotisations/'

        self.assertEqual(self.appeler(None, 'get', url).status_code, 401)
        self.assertEqual(self.appeler(self.president_beta, 'get', url).status_code, 404)
        self.assertEqual(
            self.appeler(self.membre, 'get', f'{BASE}abc/cotisations/').status_code, 404
        )


class InvitationsTestCase(GestionMembresMixin, TestCase):

    def setUp(self):
        super().setUp()
        self.invite.generer_token_invitation()
        self.ancien_token = self.invite.token_invitation

    def activer(self, token, pin='1234'):
        return APIClient().post(
            f'{BASE}activation-compte/', {'token': token, 'pin': pin}, format='json'
        )

    def expirer(self, utilisateur):
        from datetime import timedelta
        Utilisateur.objects.filter(pk=utilisateur.pk).update(
            token_expiration=timezone.now() - timedelta(minutes=1)
        )

    def test_un_lien_est_valable_72_heures(self):
        from datetime import timedelta

        delai = self.invite.token_expiration - timezone.now()

        self.assertGreater(delai, timedelta(hours=71, minutes=59))
        self.assertLessEqual(delai, timedelta(hours=72))

    def test_activation_avant_expiration(self):
        reponse = self.activer(self.ancien_token)

        self.assertEqual(reponse.status_code, 200)
        self.invite.refresh_from_db()
        self.assertEqual(self.invite.statut, 'actif')
        self.assertIsNone(self.invite.token_invitation)
        self.assertIsNone(self.invite.token_expiration)

    def test_activation_refusee_apres_expiration(self):
        self.expirer(self.invite)

        reponse = self.activer(self.ancien_token)

        self.assertEqual(reponse.status_code, 400)
        self.assertIn('expiré', reponse.json()['erreur'])
        self.invite.refresh_from_db()
        self.assertEqual(self.invite.statut, 'en_attente')

    def test_renvoyer_l_invitation(self):
        self.expirer(self.invite)

        reponse = self.appeler(
            self.secretaire, 'post', f'{BASE}{self.invite.id}/renvoyer-invitation/'
        )

        self.assertEqual(reponse.status_code, 200)
        nouveau_token = reponse.json()['tokenInvitation']
        self.assertNotEqual(nouveau_token, self.ancien_token)
        self.assertIsNotNone(reponse.json()['membre']['invitationExpiration'])

        # L'ancien lien ne fonctionne plus, le nouveau oui
        self.assertEqual(self.activer(self.ancien_token).status_code, 404)
        self.assertEqual(self.activer(nouveau_token).status_code, 200)

    def test_renvoi_reserve_au_president_et_au_secretaire(self):
        url = f'{BASE}{self.invite.id}/renvoyer-invitation/'

        self.assertEqual(self.appeler(self.president, 'post', url).status_code, 200)
        for auteur in (self.tresorier, self.membre):
            with self.subTest(role=auteur.role):
                self.assertEqual(self.appeler(auteur, 'post', url).status_code, 403)
        self.assertEqual(self.appeler(None, 'post', url).status_code, 401)

    def test_renvoi_impossible_pour_un_compte_deja_active_ou_d_un_autre_gie(self):
        self.assertEqual(
            self.appeler(self.president, 'post', f'{BASE}{self.membre.id}/renvoyer-invitation/').status_code,
            400
        )
        self.assertEqual(
            self.appeler(self.president_beta, 'post', f'{BASE}{self.invite.id}/renvoyer-invitation/').status_code,
            404
        )

    def test_import_excel_fixe_aussi_l_expiration(self):
        reponse = self.appeler(
            self.president, 'post', f'{BASE}importer/',
            {'membres': [{'prenom': 'Aminata', 'nom': 'Sow', 'telephone': '771234567', 'role': 'membre'}]}
        )

        self.assertEqual(reponse.status_code, 201)
        importe = Utilisateur.objects.get(telephone__endswith='771234567')
        self.assertIsNotNone(importe.token_expiration)


class SuppressionInvitationsExpireesTestCase(GestionMembresMixin, TestCase):

    def lancer(self, *arguments):
        from io import StringIO
        from django.core.management import call_command

        sortie = StringIO()
        call_command('supprimer_invitations_expirees', *arguments, stdout=sortie)
        return sortie.getvalue()

    def test_supprime_uniquement_les_invitations_expirees(self):
        from datetime import timedelta
        from notifications.models import Notification

        passe = timezone.now() - timedelta(hours=1)
        futur = timezone.now() + timedelta(hours=10)

        expire = self.invite
        Utilisateur.objects.filter(pk=expire.pk).update(token_expiration=passe)

        encore_valide = self.creer(self.gie, '770000007', 'membre', statut='en_attente', active=False)
        Utilisateur.objects.filter(pk=encore_valide.pk).update(token_expiration=futur)

        sans_date = self.creer(self.gie, '770000008', 'membre', statut='en_attente', active=False)

        # Comptes actif et suspendu avec une vieille date : jamais supprimés
        Utilisateur.objects.filter(pk=self.membre.pk).update(token_expiration=passe)
        Utilisateur.objects.filter(pk=self.membre2.pk).update(statut='inactif', token_expiration=passe)

        sortie = self.lancer()

        self.assertIn('1 compte(s) supprimé(s)', sortie)
        self.assertFalse(Utilisateur.objects.filter(pk=expire.pk).exists())
        for conserve in (encore_valide, sans_date, self.membre, self.membre2):
            self.assertTrue(Utilisateur.objects.filter(pk=conserve.pk).exists())

        # Le président du groupement est prévenu, pas les autres
        notification = Notification.objects.get(type='invitation_expiree')
        self.assertIn(expire.nom, notification.message)
        self.assertEqual(list(notification.destinataires.all()), [self.president])

    def test_mode_simulation(self):
        from datetime import timedelta

        Utilisateur.objects.filter(pk=self.invite.pk).update(
            token_expiration=timezone.now() - timedelta(hours=1)
        )

        sortie = self.lancer('--simulation')

        self.assertIn('seraient supprimé(s)', sortie)
        self.assertTrue(Utilisateur.objects.filter(pk=self.invite.pk).exists())

    def test_rien_a_supprimer(self):
        self.assertIn('aucun compte expiré', self.lancer())


class ImportExcelValidationTestCase(GestionMembresMixin, TestCase):

    URL = '/api/membres/membres/analyser-excel/'

    def envoyer(self, contenu, nom='membres.xlsx'):
        client = APIClient()
        client.force_authenticate(user=self.president)
        return client.post(self.URL, {'fichier': SimpleUploadedFile(nom, contenu)}, format='multipart')

    def test_fichier_corrompu_renvoie_400_et_non_500(self):
        reponse = self.envoyer(b'ceci n est pas un fichier excel')

        self.assertEqual(reponse.status_code, 400)
        self.assertIn('illisible', str(reponse.json()))

    def test_fichier_trop_volumineux_refuse(self):
        reponse = self.envoyer(b'0' * (5 * 1024 * 1024 + 1))

        self.assertEqual(reponse.status_code, 400)
        self.assertIn('volumineux', str(reponse.json()))

    def test_fichier_valide_toujours_analyse(self):
        import io
        import openpyxl

        classeur = openpyxl.Workbook()
        feuille = classeur.active
        feuille.append(['prenom', 'nom', 'telephone', 'role'])
        feuille.append(['Awa', 'Diop', '781234567', 'membre'])
        tampon = io.BytesIO()
        classeur.save(tampon)

        reponse = self.envoyer(tampon.getvalue())

        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.json()['totalValides'], 1)
