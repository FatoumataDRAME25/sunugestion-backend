from django.test import TestCase

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from .models import Utilisateur


class VerrouillagePinTestCase(TestCase):

    def setUp(self):
        """Créer un utilisateur de test."""
        self.utilisateur = Utilisateur.objects.create_user(
            telephone="770000001",
            nom="Test",
            prenom="Utilisateur",
            role="membre",
            password="1234",
            statut="actif",
        )

    def test_quatre_erreurs_ne_verrouillent_pas_le_compte(self):
        """Le compte reste déverrouillé après quatre erreurs."""

        for _ in range(4):
            valide, message = self.utilisateur.verifier_pin("9999")
            self.assertFalse(valide)

        self.utilisateur.refresh_from_db()

        self.assertEqual(self.utilisateur.tentatives_pin, 4)
        self.assertFalse(self.utilisateur.verrouille)

        print("OK : quatre erreurs, compte non verrouillé.")

    def test_cinquieme_erreur_verrouille_le_compte(self):
        """La cinquième erreur déclenche le verrouillage."""

        for _ in range(5):
            valide, message = self.utilisateur.verifier_pin("9999")

        self.utilisateur.refresh_from_db()

        self.assertFalse(valide)
        self.assertTrue(self.utilisateur.verrouille)
        self.assertEqual(self.utilisateur.tentatives_pin, 5)
        self.assertIsNotNone(self.utilisateur.date_verrouillage)

        print("OK : cinquième erreur, compte verrouillé.")

    def test_bon_pin_refuse_pendant_le_verrouillage(self):
        """Le bon PIN ne permet pas de contourner le verrouillage."""

        for _ in range(5):
            self.utilisateur.verifier_pin("9999")

        valide, message = self.utilisateur.verifier_pin("1234")

        self.assertFalse(valide)
        self.assertIn("verrouillé", message.lower())

        print("OK : connexion refusée pendant le verrouillage.")

    def test_deverrouillage_apres_quinze_minutes(self):
        """Le compte se déverrouille après expiration du délai."""

        for _ in range(5):
            self.utilisateur.verifier_pin("9999")

        # Simuler un verrouillage datant de 16 minutes.
        self.utilisateur.date_verrouillage = (
            timezone.now() - timedelta(minutes=16)
        )
        self.utilisateur.save(update_fields=["date_verrouillage"])

        valide, message = self.utilisateur.verifier_pin("1234")

        self.utilisateur.refresh_from_db()

        self.assertTrue(valide)
        self.assertFalse(self.utilisateur.verrouille)
        self.assertEqual(self.utilisateur.tentatives_pin, 0)
        self.assertIsNone(self.utilisateur.date_verrouillage)

        print("OK : déverrouillage automatique après expiration.")

    def test_compteur_reinitialise_apres_connexion_reussie(self):
        """Une connexion réussie remet le compteur à zéro."""

        self.utilisateur.verifier_pin("9999")
        self.utilisateur.verifier_pin("9999")

        valide, message = self.utilisateur.verifier_pin("1234")

        self.utilisateur.refresh_from_db()

        self.assertTrue(valide)
        self.assertEqual(self.utilisateur.tentatives_pin, 0)

        print("OK : compteur réinitialisé après connexion réussie.")
