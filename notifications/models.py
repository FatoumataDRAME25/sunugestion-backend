from django.db import models
from django.conf import settings


class Notification(models.Model):

    MODULE_CHOICES = [
        ('activites', 'Activités'),
        ('cotisations', 'Cotisations'),
        ('prets', 'Prêts'),
        ('membres', 'Membres'),
        ('general', 'Général'),
    ]

    titre = models.CharField(max_length=255)
    # Texte principal affiché dans la notification push et dans la liste

    message = models.TextField()
    # Corps de la notification

    type = models.CharField(max_length=50)
    # Type d'événement qui a déclenché la notification : "nouvelle_activite", "pret_approuve", "cotisation_payee", etc.
    # Utilisé par Angular pour construire la route de navigation et adapter l'affichage

    module = models.CharField(max_length=50, choices=MODULE_CHOICES)
    # Module auquel appartient la notification → gère le badge par module

    objet_id = models.PositiveIntegerField(null=True, blank=True)
    # ID de l'objet concerné (ex: activité 15, prêt 8)
    # Null pour les notifications générales sans objet précis

    date_creation = models.DateTimeField(auto_now_add=True)

    destinataires = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through='NotificationUtilisateur',
        related_name='notifications'
    )

    def __str__(self):
        return f"{self.titre} — {self.module}"

    class Meta:
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        db_table = "notification"
        ordering = ['-date_creation']


class NotificationUtilisateur(models.Model):
    """
    Table intermédiaire explicite entre Notification et Utilisateur.
    Permet de savoir si un utilisateur précis a lu une notification précise.
    Nécessaire pour le calcul du badge par module.
    """

    notification = models.ForeignKey(
        Notification,
        on_delete=models.CASCADE,
        related_name='notification_utilisateurs'
    )
    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notification_utilisateurs'
    )
    lue = models.BooleanField(default=False)
    # False = badge actif, True = badge effacé pour cet utilisateur

    class Meta:
        verbose_name = "Notification utilisateur"
        verbose_name_plural = "Notifications utilisateurs"
        db_table = "notification_utilisateur"
        unique_together = ['notification', 'utilisateur']


class FCMToken(models.Model):
    """
    Token Firebase Cloud Messaging d'un appareil ou navigateur.
    Un utilisateur peut en avoir plusieurs (PC, téléphone, tablette).
    """

    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='fcm_tokens'
    )
    token = models.TextField(unique=True)
    # Token fourni par Firebase SDK côté Angular

    appareil = models.CharField(max_length=100, blank=True)
    # Libellé libre : "Chrome - PC", "Firefox - Mobile", etc.
    # Optionnel mais utile pour déboguer

    date_creation = models.DateTimeField(auto_now_add=True)
    date_mise_a_jour = models.DateTimeField(auto_now=True)
    # auto_now permet de détecter les tokens potentiellement expirés

    def __str__(self):
        return f"{self.utilisateur} — {self.appareil or 'Appareil inconnu'}"

    class Meta:
        verbose_name = "Token FCM"
        verbose_name_plural = "Tokens FCM"
        db_table = "fcm_token"
