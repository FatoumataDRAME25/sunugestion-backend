from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
import secrets
import random

class GIE(models.Model):

    STATUT_CHOICES = [
        ('actif', 'Actif'),
        ('inactif', 'Inactf'),
        ('en_attente', 'En attente')
    ]

    SECTEUR_CHOICES = [
        ('agriculture', 'Agriculture'),
        ('commerce', 'Commerce'),
        ('peche', 'Pêche'),
        ('artisanat', 'Artisanat'),
        ('services', 'Services'),
        ('autre', 'Autre'),
    ]

    token_inscription = models.CharField(
    max_length=100,
    null=True,
    blank=True,
    unique=True
    )
    nom = models.CharField(max_length=255)
    region = models.CharField(max_length=100)
    secteur = models.CharField(max_length=50, choices=SECTEUR_CHOICES)
    telephone = models.CharField(max_length=20, null=True, blank=True) 
    photo = models.ImageField(upload_to='gie/photos/', null=True, blank=True)
    code = models.CharField(max_length=50, unique=True)
    date_creation = models.DateTimeField(auto_now_add=True)
    statut = models.CharField(
        max_length=20,
        choices=STATUT_CHOICES,
        default='en_attente'
    )

    def __str__(self):
        return self.nom

    class Meta:
        verbose_name = "GIE"
        verbose_name_plural = "GIE"
        db_table = "gie"



class UtilisateurManager(BaseUserManager):

    def create_user(self, telephone, nom, prenom, role, gie=None, password=None):
        if not telephone:
            raise ValueError("Le numéro de téléphone est obligatoire")
        
        utilisateur = self.model(
            telephone=telephone,
            nom=nom,
            prenom=prenom,
            role=role,
            gie=gie
        )
        if password:
            utilisateur.set_password(password)
        utilisateur.save(using=self._db)
        return utilisateur

    def create_superuser(self, telephone, nom, prenom, password):
        utilisateur = self.create_user(
            telephone=telephone,
            nom=nom,
            prenom=prenom,
            role='administrateur',
            password=password
        )
        utilisateur.is_staff = True
        utilisateur.is_superuser = True
        utilisateur.save(using=self._db)
        return utilisateur

class Utilisateur(AbstractBaseUser, PermissionsMixin):

    ROLES = [
        ('administrateur', 'Administrateur'),
        ('president', 'Président'),
        ('tresorier', 'Trésorier'),
        ('secretaire', 'Secrétaire'),
        ('membre', 'Membre simple'),
    ]

    STATUT_CHOICES = [
        ('actif', 'Actif'),
        ('inactif', 'Inactif'),
        ('en_attente', 'En attente'),
    ]

    gie = models.ForeignKey(
        GIE,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='membres'
    )
    nom = models.CharField(max_length=100)
    prenom = models.CharField(max_length=100)
    telephone = models.CharField(max_length=20, unique=True)
    email = models.EmailField(max_length=255, null=True, blank=True, unique=True)
    role = models.CharField(max_length=20, choices=ROLES)
    statut = models.CharField(
        max_length=20,
        choices=STATUT_CHOICES,
        default='en_attente'
    )
    token_invitation = models.CharField(max_length=100, null=True, blank=True)
    token_expiration = models.DateTimeField(null=True, blank=True)
    otp = models.CharField(max_length=6, null=True, blank=True)
    otp_expiration = models.DateTimeField(null=True, blank=True)
    tentatives_pin = models.IntegerField(default=0)
    verrouille = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    objects = UtilisateurManager()

    USERNAME_FIELD = 'telephone'
    REQUIRED_FIELDS = ['nom', 'prenom']



    def generer_otp(self):
        """Génère un code OTP à 6 chiffres"""
        self.otp = str(random.randint(100000, 999999))
        from django.utils import timezone
        from datetime import timedelta
        self.otp_expiration = timezone.now() + timedelta(minutes=10)
        self.save()
        return self.otp

    def verifier_otp(self, code):
        """Vérifie que le code OTP est correct et non expiré"""
        from django.utils import timezone
        if self.otp != code:
            return False, "Code OTP incorrect."
        if timezone.now() > self.otp_expiration:
            return False, "Code OTP expiré. Demandez un nouveau code."
        self.otp = None
        self.otp_expiration = None
        self.save()
        return True, "Code OTP valide."



    def generer_token_invitation(self):
        """Génère et sauvegarde un token unique pour l'invitation SMS"""
        self.token_invitation = secrets.token_urlsafe(32)
        self.save()
        return self.token_invitation

    def verrouiller(self):
        """Verrouille le compte après 5 tentatives échouées"""
        self.verrouille = True
        self.save()

    def verifier_pin(self, pin):
        if self.verrouille:
            return False, "Compte verrouillé."

        if self.check_password(pin):
            self.tentatives_pin = 0
            self.save()
            return True, "PIN correct."

        self.tentatives_pin += 1

        if self.tentatives_pin >= 5:
            self.verrouiller()
            return False, "Compte est verrouillé vous avez fait 5 tentatives."

        self.save()

        restantes = 5 - self.tentatives_pin
        return False, f"PIN incorrect. {restantes} tentative(s) restante(s)."

    def __str__(self):
        return f"{self.prenom} {self.nom} — {self.role}"

    class Meta:
        verbose_name = "Utilisateur"
        verbose_name_plural = "Utilisateurs"
        db_table = "utilisateur"