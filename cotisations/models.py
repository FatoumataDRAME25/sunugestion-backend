from django.db import models

from django.db import models
from django.conf import settings


class SessionCotisation(models.Model):

    STATUT_CHOICES = [
        ('ouverte', 'Ouverte'),
        ('cloturee', 'Clôturée'),
    ]

    createur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='sessions_creees'
    )
    libelle = models.CharField(max_length=255)
    montant = models.DecimalField(
        max_digits=12,
        decimal_places=0
    )
    date_debut = models.DateField()
    date_fin = models.DateField()
    statut = models.CharField(
        max_length=20,
        choices=STATUT_CHOICES,
        default='ouverte'
    )
    date_creation = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.libelle} — {self.createur.gie}"

    class Meta:
        verbose_name = "Session de cotisation"
        verbose_name_plural = "Sessions de cotisation"
        db_table = "session_cotisation"
        ordering = ['-date_creation']


class Cotisation(models.Model):

    STATUT_CHOICES = [
        ('en_cours', 'En cours'),
        ('paye', 'Payé'),
        ('en_retard', 'En retard'),
    ]

    MODE_PAIEMENT_CHOICES = [
        ('especes', 'Espèces'),
        ('wave', 'Wave'),
        ('orange_money', 'Orange Money'),
    ]

    session = models.ForeignKey(
        SessionCotisation,
        on_delete=models.CASCADE,
        related_name='cotisations'
    )
    membre = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='cotisations'
    )
    date_paiement = models.DateTimeField(null=True, blank=True)

    mode_paiement = models.CharField(
        max_length=20,
        choices=MODE_PAIEMENT_CHOICES,
        null=True,
        blank=True
    )
    statut = models.CharField(
        max_length=20,
        choices=STATUT_CHOICES,
        default='en_cours'
    )

    def __str__(self):
        return f"{self.membre} — {self.session.libelle} — {self.statut}"

    class Meta:
        verbose_name = "Cotisation"
        verbose_name_plural = "Cotisations"
        db_table = "cotisation"
        unique_together = ['session', 'membre']
