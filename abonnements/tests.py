from datetime import date, timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from authentication.models import GIE, Utilisateur
from notifications.models import Notification

from .models import PaiementAbonnement
from .services import (
    calculer_tarif,
    obtenir_abonnement,
    periode_suivante,
    valider_paiement,
    creer_paiement,
)


# ─── Tarif ────────────────────────────────────────────────────────────────────

class TarifTestCase(SimpleTestCase):

    def test_grille_avec_tolerance_de_deux_membres(self):
        attendus = {
            0: 2900, 1: 2900, 15: 2900,
            16: 2900, 17: 2900,          # tolérance au-dessus de 15
            18: 3900, 34: 3900,
            35: 3900, 36: 3900,        # tolérance au-dessus de 34
            37: 4900, 50: 4900,
            51: 4900, 52: 4900,        # tolérance au-dessus de 50
            53: 5900, 500: 5900,
        }
        for membres, montant in attendus.items():
            with self.subTest(membres=membres):
                self.assertEqual(calculer_tarif(membres)['montant'], montant)

    def test_informations_sur_le_palier_suivant(self):
        tarif = calculer_tarif(16)
        self.assertTrue(tarif['dans_tolerance'])
        self.assertEqual(tarif['membres_avant_palier_suivant'], 2)
        self.assertEqual(tarif['montant_palier_suivant'], 3900)

        self.assertFalse(calculer_tarif(10)['dans_tolerance'])
        self.assertEqual(calculer_tarif(10)['membres_avant_palier_suivant'], 8)

        dernier = calculer_tarif(80)
        self.assertIsNone(dernier['membres_avant_palier_suivant'])
        self.assertIsNone(dernier['montant_palier_suivant'])


# ─── Données communes ─────────────────────────────────────────────────────────

class AbonnementMixin:

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
        cls.president_beta = cls.creer(cls.autre_gie, '770000011', 'president')
        cls.administrateur = Utilisateur.objects.create_user(
            telephone='770000099', nom='Admin', prenom='Plateforme',
            role='administrateur', statut='actif'
        )

    @staticmethod
    def creer(gie, telephone, role, statut='actif'):
        return Utilisateur.objects.create_user(
            telephone=telephone, nom=f'Nom{telephone[-2:]}', prenom='Prenom',
            role=role, gie=gie, statut=statut
        )

    def client_de(self, utilisateur=None):
        client = APIClient()
        if utilisateur is not None:
            client.force_authenticate(user=utilisateur)
        return client

    def fixer_abonnement(self, statut, date_fin, gie=None):
        abonnement = obtenir_abonnement(gie or self.gie)
        abonnement.statut = statut
        abonnement.date_debut = date_fin - timedelta(days=29)
        abonnement.date_fin = date_fin
        abonnement.save()
        return abonnement


# ─── État et prolongation ─────────────────────────────────────────────────────

class EtatAbonnementTestCase(AbonnementMixin, TestCase):

    def test_essai_de_30_jours_a_la_creation(self):
        abonnement = obtenir_abonnement(self.gie)
        aujourd_hui = timezone.localdate()

        self.assertEqual(abonnement.statut, 'essai')
        self.assertEqual(abonnement.date_debut, aujourd_hui)
        self.assertEqual((abonnement.date_fin - abonnement.date_debut).days + 1, 30)
        self.assertEqual(abonnement.etat(), 'essai')
        # Un seul abonnement par groupement
        self.assertEqual(obtenir_abonnement(self.gie).pk, abonnement.pk)

    def test_pas_de_delai_apres_l_essai(self):
        fin = date(2026, 3, 31)
        abonnement = self.fixer_abonnement('essai', fin)

        self.assertEqual(abonnement.etat(fin), 'essai')
        self.assertEqual(abonnement.etat(fin + timedelta(days=1)), 'lecture_seule')

    def test_trois_jours_de_grace_apres_une_periode_payee(self):
        fin = date(2026, 3, 31)
        abonnement = self.fixer_abonnement('actif', fin)

        self.assertEqual(abonnement.etat(fin), 'actif')
        for jours in (1, 2, 3):
            self.assertEqual(abonnement.etat(fin + timedelta(days=jours)), 'grace')
        self.assertEqual(abonnement.etat(fin + timedelta(days=4)), 'lecture_seule')

    def test_periode_suivante(self):
        fin = date(2026, 3, 31)

        # Payé pendant l'essai : les jours restants ne sont pas perdus
        essai = self.fixer_abonnement('essai', fin)
        self.assertEqual(
            periode_suivante(essai, date(2026, 3, 20)),
            (date(2026, 4, 1), date(2026, 4, 30))
        )
        # Payé après l'essai (lecture seule) : à partir du jour du paiement
        self.assertEqual(
            periode_suivante(essai, date(2026, 4, 10)),
            (date(2026, 4, 10), date(2026, 5, 9))
        )

        # Payé pendant le délai de grâce : le délai n'est pas offert
        paye = self.fixer_abonnement('actif', fin)
        self.assertEqual(
            periode_suivante(paye, date(2026, 4, 3)),
            (date(2026, 4, 1), date(2026, 4, 30))
        )
        # Payé en lecture seule
        self.assertEqual(
            periode_suivante(paye, date(2026, 4, 4)),
            (date(2026, 4, 4), date(2026, 5, 3))
        )

    def test_validation_idempotente(self):
        abonnement = obtenir_abonnement(self.gie)
        fin_essai = abonnement.date_fin
        paiement = creer_paiement(self.gie, 'wave')

        self.assertTrue(valider_paiement(paiement))
        self.assertFalse(valider_paiement(paiement))

        abonnement.refresh_from_db()
        self.assertEqual(abonnement.statut, 'actif')
        self.assertEqual(abonnement.date_debut, fin_essai + timedelta(days=1))
        self.assertEqual(PaiementAbonnement.objects.filter(statut='valide').count(), 1)

    def test_montant_calcule_sur_les_membres_actifs(self):
        # Comptes en attente et suspendus ne comptent pas
        self.creer(self.gie, '770000005', 'membre', statut='en_attente')
        self.creer(self.gie, '770000006', 'membre', statut='inactif')

        paiement = creer_paiement(self.gie, 'wave')

        self.assertEqual(paiement.nombre_membres, 4)
        self.assertEqual(int(paiement.montant), 2900)


# ─── Lecture seule ────────────────────────────────────────────────────────────

class LectureSeuleTestCase(AbonnementMixin, TestCase):

    def mettre_en_lecture_seule(self):
        self.fixer_abonnement('essai', timezone.localdate() - timedelta(days=1))

    def test_essai_en_cours_ne_change_rien(self):
        client = self.client_de(self.president)

        reponse = client.patch(
            f'/api/membres/membres/{self.membre.id}/modifier-fonction/',
            {'fonctionBureau': 'vice_president'}, format='json'
        )

        self.assertEqual(reponse.status_code, 200)

    def test_consultation_toujours_possible(self):
        self.mettre_en_lecture_seule()
        client = self.client_de(self.membre)

        for url in ('/api/membres/membres/', '/api/prets/', '/api/historiques/solde/',
                    '/api/gie/infos/', '/api/abonnements/mon-abonnement/'):
            with self.subTest(url=url):
                self.assertEqual(client.get(url).status_code, 200)

    def test_nouvelles_operations_refusees(self):
        self.mettre_en_lecture_seule()

        cas = [
            (self.president, 'patch', f'/api/membres/membres/{self.membre.id}/modifier-fonction/',
             {'fonctionBureau': 'vice_president'}),
            (self.president, 'patch', '/api/gie/infos/', {'nom': 'Nouveau nom'}),
            (self.tresorier, 'post', '/api/historiques/operations/',
             {'typeOperation': 'entree', 'montant': 1000, 'libelle': 'Test'}),
            (self.membre, 'post', '/api/prets/', {'montant': 5000}),
        ]
        for auteur, methode, url, donnees in cas:
            with self.subTest(url=url):
                reponse = getattr(self.client_de(auteur), methode)(url, donnees, format='json')
                self.assertEqual(reponse.status_code, 403)
                self.assertIn('lecture seule', reponse.json()['detail'])

    def test_profil_et_code_pin_restent_modifiables(self):
        self.mettre_en_lecture_seule()

        reponse = self.client_de(self.membre).patch(
            f'/api/membres/membres/{self.membre.id}/',
            {'email': 'membre@example.com'}, format='json'
        )
        self.assertEqual(reponse.status_code, 200)

        reponse = self.client_de(self.membre).post(
            '/api/membres/membres/changer-pin/',
            {'pinActuel': '0000', 'nouveauPin': '1111', 'confirmationPin': '1111'},
            format='json'
        )
        # Refusé pour un PIN incorrect, pas pour la lecture seule
        self.assertEqual(reponse.status_code, 400)

    def test_le_renouvellement_reste_possible(self):
        self.mettre_en_lecture_seule()

        with patch('abonnements.views.creer_facture', return_value={
            'token': 'jeton-test', 'url_paiement': 'https://paydunya.test/x', 'response_code': '00'
        }):
            reponse = self.client_de(self.tresorier).post(
                '/api/abonnements/payer/', {'modePaiement': 'wave'}, format='json'
            )

        self.assertEqual(reponse.status_code, 201)

    def test_un_autre_groupement_n_est_pas_affecte(self):
        self.mettre_en_lecture_seule()

        reponse = self.client_de(self.president_beta).patch(
            '/api/gie/infos/', {'nom': 'Beta modifié'}, format='json'
        )

        self.assertEqual(reponse.status_code, 200)


# ─── Espace du groupement ─────────────────────────────────────────────────────

class MonAbonnementTestCase(AbonnementMixin, TestCase):

    def test_details_reserves_au_president_et_au_tresorier(self):
        for auteur in (self.president, self.tresorier):
            with self.subTest(role=auteur.role):
                donnees = self.client_de(auteur).get('/api/abonnements/mon-abonnement/').json()
                self.assertEqual(donnees['etat'], 'essai')
                self.assertTrue(donnees['peutPayer'])
                self.assertEqual(donnees['membresActifs'], 4)
                self.assertEqual(donnees['tarif']['montant'], 2900)
                self.assertIn('paiements', donnees)

        for auteur in (self.secretaire, self.membre):
            with self.subTest(role=auteur.role):
                donnees = self.client_de(auteur).get('/api/abonnements/mon-abonnement/').json()
                self.assertEqual(donnees['etat'], 'essai')
                self.assertFalse(donnees['peutPayer'])
                self.assertNotIn('tarif', donnees)
                self.assertNotIn('paiements', donnees)

    def test_seuls_president_et_tresorier_paient(self):
        for auteur in (self.secretaire, self.membre):
            with self.subTest(role=auteur.role):
                reponse = self.client_de(auteur).post(
                    '/api/abonnements/payer/', {'modePaiement': 'wave'}, format='json'
                )
                self.assertEqual(reponse.status_code, 403)

        self.assertEqual(
            self.client_de().get('/api/abonnements/mon-abonnement/').status_code, 401
        )
        self.assertEqual(
            self.client_de(self.administrateur).get('/api/abonnements/mon-abonnement/').status_code, 403
        )

    def test_mode_de_paiement_invalide(self):
        reponse = self.client_de(self.president).post(
            '/api/abonnements/payer/', {'modePaiement': 'especes'}, format='json'
        )
        self.assertEqual(reponse.status_code, 400)


# ─── Paiement PayDunya ────────────────────────────────────────────────────────

FACTURE = {'token': 'jeton-abonnement', 'url_paiement': 'https://paydunya.test/f', 'response_code': '00'}


class PaiementPayDunyaTestCase(AbonnementMixin, TestCase):

    def payer(self):
        with patch('abonnements.views.creer_facture', return_value=FACTURE) as facture:
            reponse = self.client_de(self.president).post(
                '/api/abonnements/payer/', {'modePaiement': 'orange_money'}, format='json'
            )
        return reponse, facture

    def test_creation_de_la_facture(self):
        reponse, facture = self.payer()

        self.assertEqual(reponse.status_code, 201)
        self.assertEqual(reponse.json()['urlPaiement'], FACTURE['url_paiement'])
        self.assertEqual(facture.call_args.kwargs['montant'], 2900)
        self.assertIn('type=abonnement', facture.call_args.kwargs['return_url'])

        paiement = PaiementAbonnement.objects.get()
        self.assertEqual(paiement.statut, 'en_attente')
        self.assertEqual(paiement.token_paydunya, 'jeton-abonnement')
        # Rien n'est prolongé avant la confirmation de PayDunya
        self.assertEqual(obtenir_abonnement(self.gie).statut, 'essai')

    def test_callback_confirme_le_paiement(self):
        self.payer()
        fin_essai = obtenir_abonnement(self.gie).date_fin

        with patch('abonnements.views.verifier_facture',
                   return_value={'statut': 'completed', 'montant_confirme': 2900}):
            reponse = self.client_de().post(
                '/api/paiements/paydunya/callback/',
                {'data[invoice][token]': 'jeton-abonnement'}
            )
            # Notification répétée par PayDunya : sans effet
            self.client_de().post(
                '/api/paiements/paydunya/callback/',
                {'data[invoice][token]': 'jeton-abonnement'}
            )

        self.assertEqual(reponse.status_code, 200)
        abonnement = obtenir_abonnement(self.gie)
        self.assertEqual(abonnement.statut, 'actif')
        self.assertEqual(abonnement.date_debut, fin_essai + timedelta(days=1))
        self.assertEqual(PaiementAbonnement.objects.get().statut, 'valide')
        self.assertEqual(Notification.objects.filter(type='abonnement_renouvele').count(), 1)

    def test_montant_incoherent_refuse(self):
        self.payer()

        with patch('abonnements.views.verifier_facture',
                   return_value={'statut': 'completed', 'montant_confirme': 100}):
            self.client_de().post(
                '/api/paiements/paydunya/callback/',
                {'data[invoice][token]': 'jeton-abonnement'}
            )

        self.assertEqual(PaiementAbonnement.objects.get().statut, 'en_attente')
        self.assertEqual(obtenir_abonnement(self.gie).statut, 'essai')

    def test_paiement_annule(self):
        self.payer()

        with patch('abonnements.views.verifier_facture',
                   return_value={'statut': 'cancelled', 'montant_confirme': 0}):
            self.client_de().post(
                '/api/paiements/paydunya/callback/',
                {'data[invoice][token]': 'jeton-abonnement'}
            )

        self.assertEqual(PaiementAbonnement.objects.get().statut, 'echoue')

    def test_page_de_retour_verifie_aupres_de_paydunya(self):
        reponse, _ = self.payer()
        paiement_id = reponse.json()['paiementId']

        with patch('abonnements.views.verifier_facture',
                   return_value={'statut': 'completed', 'montant_confirme': 2900}):
            reponse = self.client_de(self.tresorier).get(f'/api/abonnements/paiements/{paiement_id}/')

        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.json()['statut'], 'valide')
        # Un autre groupement ne voit pas ce paiement (introuvable pour lui)
        self.assertEqual(
            self.client_de(self.president_beta).get(f'/api/abonnements/paiements/{paiement_id}/').status_code,
            404
        )


# ─── Espace administrateur ────────────────────────────────────────────────────

class AdministrationTestCase(AbonnementMixin, TestCase):

    def test_liste_des_instances(self):
        reponse = self.client_de(self.administrateur).get('/api/abonnements/admin/instances/')

        self.assertEqual(reponse.status_code, 200)
        alpha = next(i for i in reponse.json() if i['code'] == 'ALPHA')
        self.assertEqual(alpha['membresActifs'], 4)
        self.assertEqual(alpha['montantMensuel'], 2900)
        self.assertEqual(alpha['abonnement']['etat'], 'essai')

    def test_reserve_a_l_administrateur(self):
        urls = [
            '/api/abonnements/admin/instances/',
            f'/api/abonnements/admin/instances/{self.gie.id}/',
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client_de().get(url).status_code, 401)
                self.assertEqual(self.client_de(self.president).get(url).status_code, 403)

        reponse = self.client_de(self.president).post(
            f'/api/abonnements/admin/instances/{self.gie.id}/paiement-manuel/', {}, format='json'
        )
        self.assertEqual(reponse.status_code, 403)

    def test_paiement_manuel(self):
        self.fixer_abonnement('essai', timezone.localdate() - timedelta(days=5))

        reponse = self.client_de(self.administrateur).post(
            f'/api/abonnements/admin/instances/{self.gie.id}/paiement-manuel/',
            {'note': 'Paiement en espèces'}, format='json'
        )

        self.assertEqual(reponse.status_code, 201)
        self.assertEqual(reponse.json()['paiement']['modePaiement'], 'manuel')
        abonnement = obtenir_abonnement(self.gie)
        self.assertEqual(abonnement.statut, 'actif')
        self.assertEqual(abonnement.date_debut, timezone.localdate())
        self.assertEqual(abonnement.etat(), 'actif')

        detail = self.client_de(self.administrateur).get(
            f'/api/abonnements/admin/instances/{self.gie.id}/'
        ).json()
        self.assertEqual(len(detail['abonnement']['paiements']), 1)
        self.assertEqual(detail['abonnement']['paiements'][0]['note'], 'Paiement en espèces')


# ─── Rappels ──────────────────────────────────────────────────────────────────

class RappelsTestCase(AbonnementMixin, TestCase):

    def lancer(self):
        sortie = StringIO()
        call_command('traiter_abonnements', stdout=sortie)
        return sortie.getvalue()

    def test_rappels_aux_echeances(self):
        aujourd_hui = timezone.localdate()

        for jours, attendu in ((7, True), (6, False), (1, True), (0, True)):
            with self.subTest(jours=jours):
                Notification.objects.all().delete()
                self.fixer_abonnement('essai', aujourd_hui + timedelta(days=jours))
                self.fixer_abonnement('essai', aujourd_hui + timedelta(days=20), gie=self.autre_gie)

                self.lancer()

                notifications = Notification.objects.filter(type='rappel_abonnement')
                self.assertEqual(notifications.exists(), attendu)
                if attendu:
                    destinataires = set(notifications.get().destinataires.all())
                    self.assertEqual(destinataires, {self.president, self.tresorier})

    def test_debut_du_delai_et_lecture_seule(self):
        aujourd_hui = timezone.localdate()

        self.fixer_abonnement('actif', aujourd_hui - timedelta(days=1))
        self.lancer()
        self.assertIn('Abonnement expiré', list(Notification.objects.values_list('titre', flat=True)))

        Notification.objects.all().delete()
        self.fixer_abonnement('actif', aujourd_hui - timedelta(days=4))
        self.lancer()
        self.assertIn('Groupement en lecture seule', list(Notification.objects.values_list('titre', flat=True)))


# ─── Grille publique ──────────────────────────────────────────────────────────

class GrillePubliqueTestCase(TestCase):

    def test_grille_accessible_sans_connexion(self):
        client = APIClient()
        # Un ancien jeton invalide ne doit pas bloquer une page publique
        client.credentials(HTTP_AUTHORIZATION='Bearer jeton-perime')

        reponse = client.get('/api/abonnements/grille/')

        self.assertEqual(reponse.status_code, 200)
        donnees = reponse.json()
        self.assertEqual(donnees['dureeEssaiJours'], 30)
        self.assertEqual(donnees['tolerance'], 2)
        self.assertEqual(
            [(p['membresMin'], p['membresMax'], p['montant']) for p in donnees['paliers']],
            [(1, 15, 2900), (16, 34, 3900), (35, 50, 4900), (51, None, 5900)]
        )
