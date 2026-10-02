from django.db import models
from django.conf import settings


class Activite(models.Model):

    STATUT_CHOICES = [
        ('planifiee', 'Planifiée'),
        ('en_cours', 'En cours'),
        ('terminee', 'Terminée'),
        ('annulee', 'Annulée'),
    ]

    TYPE_ACTIVITE_CHOICES = [
        ('reunion', 'Réunion'),
        ('formation', 'Formation'),
        ('production', 'Production'),
        ('commerciale', 'Commerciale'),
        ('autre', 'Autre'),
    ]

    gie = models.ForeignKey(
        'authentication.GIE',
        on_delete=models.CASCADE,
        related_name='activites'
    )

    organisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='activites_organisees'
    )

    titre = models.CharField(
        max_length=255
    )

    date_creation = models.DateTimeField(
        auto_now_add=True
    )

    date_activite = models.DateTimeField()

    lieu = models.CharField(
        max_length=255
    )

    type_activite = models.CharField(
        max_length=30,
        choices=TYPE_ACTIVITE_CHOICES
    )

    ordre_du_jour = models.TextField(
        blank=True,
        null=True
    )

    compte_rendu = models.TextField(
        blank=True,
        null=True
    )

    statut = models.CharField(
        max_length=20,
        choices=STATUT_CHOICES,
        default='planifiee'
    )

    def __str__(self):
        return self.titre

    class Meta:
        verbose_name = "Activité"
        verbose_name_plural = "Activités"
        db_table = "activite"
        ordering = ['-date_activite']



class Presence(models.Model):

    STATUT_CHOICES = [
        ('present', 'Présent'),
        ('absent', 'Absent'),
    ]

    activite = models.ForeignKey(
        Activite,
        on_delete=models.CASCADE,
        related_name='presences'
    )

    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='presences'
    )

    statut = models.CharField(
        max_length=20,
        choices=STATUT_CHOICES
    )

    def __str__(self):
        return f"{self.utilisateur} - {self.activite}"

    class Meta:
        verbose_name = "Présence"
        verbose_name_plural = "Présences"
        db_table = "presence"

        constraints = [
            models.UniqueConstraint(
                fields=['activite', 'utilisateur'],
                name='presence_unique_par_activite'
            )
        ]
