from django.db import models

from django.conf import settings

class Pret(models.Model):
    
    STATUT_CHOICES = [
        ('en_cours', 'En cours'),
        ('en_attente', 'En attente'),
        ('rembourse', 'Remboursé'),
        ('refuse', 'Refusé'),
        ('en_retard', 'En retard'),
    ]

    MODE_PAIEMENT_CHOICES = [
        ('especes', 'Espèces'),
        ('wave', 'Wave'),
        ('orange_money', 'Orange Money'),
    ]

    membre = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='prets'
    )
    montant = models.DecimalField(
        max_digits=12,
        decimal_places=0
    )
    date_demande = models.DateField(auto_now_add=True)
    date_echeance = models.DateField()
    date_remboursement = models.DateField( null=True, blank=True)
    date_approbation = models.DateTimeField( null=True, blank=True)

    statut = models.CharField(
        max_length=20,
        choices=STATUT_CHOICES,
        default='en_attente'
    )
    mode_paiement = models.CharField(
        max_length=20,
        choices=MODE_PAIEMENT_CHOICES,
        null=True,
        blank=True
    )

    def __str__(self):
        return f"Prêt de {self.membre} — {self.montant} — {self.statut}"

    class Meta:
        verbose_name = "Prêt"
        verbose_name_plural = "Prêts"
        db_table = "pret"
        ordering = ['-date_approbation']