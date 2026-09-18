from django.db import models


class HistoriqueOperation(models.Model):

    TYPE_CHOICES = [
        ('entree', 'Entrée'),
        ('sortie', 'Sortie'),
    ]

    gie = models.ForeignKey(
        'authentication.GIE',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='historique_operations'
    )

    type_operation = models.CharField(
        max_length=10,
        choices=TYPE_CHOICES
    )

    montant = models.DecimalField(
        max_digits=12,
        decimal_places=0
    )

    libelle = models.CharField(
        max_length=255
    )

    cotisation = models.ForeignKey(
        'cotisations.Cotisation',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='operations'
    )

    date_operation = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return f"{self.type_operation} — {self.montant} FCFA — {self.libelle}"

    class Meta:
        verbose_name = "Opération financière"
        verbose_name_plural = "Opérations financières"
        db_table = "historique_operation"
        ordering = ['-date_operation']