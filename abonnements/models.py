from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


# Après l'échéance d'un abonnement payé (pas après l'essai), le groupement
# garde un accès complet pendant ce délai avant de passer en lecture seule.
DELAI_GRACE_JOURS = 3


class Abonnement(models.Model):
    """
    Abonnement d'un groupement (une instance SunuGestion).

    `statut` indique la nature de la période en cours (essai gratuit ou
    période payée) ; l'état d'accès (actif, délai de grâce, lecture seule)
    est calculé à partir des dates par `etat()`, sans dépendre d'une tâche
    planifiée.
    """

    STATUT_CHOICES = [
        ('essai', 'Essai gratuit'),
        ('actif', 'Abonnement payé'),
    ]

    gie = models.OneToOneField(
        'authentication.GIE',
        on_delete=models.CASCADE,
        related_name='abonnement'
    )
    statut = models.CharField(
        max_length=10,
        choices=STATUT_CHOICES,
        default='essai'
    )
    # Période en cours, dates incluses
    date_debut = models.DateField()
    date_fin = models.DateField()

    date_creation = models.DateTimeField(auto_now_add=True)
    date_mise_a_jour = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.gie} — {self.get_statut_display()} jusqu'au {self.date_fin}"

    def delai_grace(self):
        """Pas de délai après l'essai gratuit, 3 jours après une période payée."""
        return DELAI_GRACE_JOURS if self.statut == 'actif' else 0

    def date_lecture_seule(self):
        """Premier jour où le groupement passe en lecture seule sans paiement."""
        return self.date_fin + timedelta(days=self.delai_grace() + 1)

    def etat(self, aujourd_hui=None):
        """
        'essai' ou 'actif'  : période en cours, accès complet
        'grace'             : échéance dépassée, accès complet pendant le délai
        'lecture_seule'     : consultation uniquement jusqu'au paiement
        """
        aujourd_hui = aujourd_hui or timezone.localdate()

        if aujourd_hui <= self.date_fin:
            return self.statut

        if aujourd_hui < self.date_lecture_seule():
            return 'grace'

        return 'lecture_seule'

    def acces_ecriture(self, aujourd_hui=None):
        return self.etat(aujourd_hui) != 'lecture_seule'

    def jours_restants(self, aujourd_hui=None):
        """Jours restants de la période en cours (0 le dernier jour, négatif ensuite)."""
        aujourd_hui = aujourd_hui or timezone.localdate()
        return (self.date_fin - aujourd_hui).days

    class Meta:
        verbose_name = "Abonnement"
        verbose_name_plural = "Abonnements"
        db_table = "abonnement"


class PaiementAbonnement(models.Model):
    """Paiement d'une période d'abonnement (PayDunya ou enregistrement manuel)."""

    STATUT_CHOICES = [
        ('en_attente', 'En attente'),
        ('valide', 'Validé'),
        ('echoue', 'Échoué'),
    ]

    MODE_CHOICES = [
        ('wave', 'Wave'),
        ('orange_money', 'Orange Money'),
        ('manuel', "Enregistré par l'administrateur"),
    ]

    abonnement = models.ForeignKey(
        Abonnement,
        on_delete=models.CASCADE,
        related_name='paiements'
    )
    montant = models.DecimalField(max_digits=12, decimal_places=0)
    # Membres actifs comptés au moment du paiement (base du tarif)
    nombre_membres = models.PositiveIntegerField()
    mode_paiement = models.CharField(max_length=20, choices=MODE_CHOICES)
    statut = models.CharField(
        max_length=20,
        choices=STATUT_CHOICES,
        default='en_attente'
    )
    token_paydunya = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        unique=True
    )
    # Période couverte, renseignée à la validation
    periode_debut = models.DateField(null=True, blank=True)
    periode_fin = models.DateField(null=True, blank=True)

    initie_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='paiements_abonnement'
    )
    note = models.CharField(max_length=255, blank=True, default='')

    date_creation = models.DateTimeField(auto_now_add=True)
    date_validation = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.abonnement.gie} — {self.montant} FCFA — {self.get_statut_display()}"

    class Meta:
        verbose_name = "Paiement d'abonnement"
        verbose_name_plural = "Paiements d'abonnement"
        db_table = "paiement_abonnement"
        ordering = ['-date_creation']
