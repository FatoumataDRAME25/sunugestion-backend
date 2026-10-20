from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
import secrets
from django.core.cache import cache
from django.utils import timezone
from datetime import timedelta
import uuid


def chemin_logo_gie(gie, nom_fichier):
    """Nom aléatoire : ni collision, ni nom d'origine conservé, et une nouvelle
    adresse à chaque changement (le navigateur ne garde pas l'ancien logo en cache)."""
    return f'gie/logos/{uuid.uuid4().hex}.webp'


class GIE(models.Model):

    STATUT_CHOICES = [
        ('actif', 'Actif'),
        ('inactif', 'Inactf'),
        ('en_attente', 'En attente')
    ]

    type_CHOICES = [
        ('association', 'Association'),
        ('organisation_communautaire', 'Organisation communautaire'),
        ('groupement', 'Groupement'),
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
    type_gie = models.CharField(max_length=50, choices=type_CHOICES)
    telephone = models.CharField(max_length=20, null=True, blank=True) 
    logo = models.ImageField(upload_to=chemin_logo_gie, null=True, blank=True)
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



# Durée de validité d'un lien d'invitation. Passé ce délai, l'activation est
# refusée et le compte en attente est supprimé par la tâche quotidienne
# « supprimer_invitations_expirees ».
DUREE_VALIDITE_INVITATION = timedelta(hours=72)


class UtilisateurManager(BaseUserManager):

    def create_user(self, telephone, nom, prenom, role, gie=None, password=None, **extra_fields):
        if not telephone:
            raise ValueError("Le numéro de téléphone est obligatoire")
        
        utilisateur = self.model(
            telephone=telephone,
            nom=nom,
            prenom=prenom,
            role=role,
            gie=gie,
            **extra_fields
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
        utilisateur.statut = 'actif'
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

    # Titre dans le bureau (adjoints). Purement descriptif : il ne donne
    # aucun droit, les permissions dépendent uniquement du rôle.
    FONCTIONS_BUREAU = [
        ('vice_president', 'Vice-président'),
        ('tresorier_adjoint', 'Trésorier adjoint'),
        ('secretaire_adjoint', 'Secrétaire adjoint'),
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
    fonction_bureau = models.CharField(
        max_length=30,
        choices=FONCTIONS_BUREAU,
        blank=True,
        default=''
    )
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
    date_verrouillage = models.DateTimeField(null=True, blank=True)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    objects = UtilisateurManager()

    USERNAME_FIELD = 'telephone'
    REQUIRED_FIELDS = ['nom', 'prenom']



    # Au-delà de ce nombre d'erreurs, le code OTP est invalidé
    MAX_ESSAIS_OTP = 5

    def _cle_essais_otp(self):
        return f"essais_otp_{self.pk}"

    def generer_otp(self):
        """Génère un code OTP à 6 chiffres avec un générateur cryptographique"""
        self.otp = f"{secrets.randbelow(900000) + 100000}"

        self.otp_expiration = timezone.now() + timedelta(minutes=10)
        self.save()
        cache.delete(self._cle_essais_otp())
        return self.otp

    def verifier_otp(self, code):
        """Vérifie que le code OTP est correct, non expiré et pas trop essayé"""
        if not self.otp:
            return False, "Aucun code en cours. Demandez un nouveau code."

        if self.otp != code:
            essais = cache.get(self._cle_essais_otp(), 0) + 1
            cache.set(self._cle_essais_otp(), essais, timeout=600)

            if essais >= self.MAX_ESSAIS_OTP:
                self.otp = None
                self.otp_expiration = None
                self.save(update_fields=['otp', 'otp_expiration'])
                cache.delete(self._cle_essais_otp())
                return False, "Trop de tentatives. Demandez un nouveau code."

            return False, "Code OTP incorrect."

        if timezone.now() > self.otp_expiration:
            return False, "Code OTP expiré. Demandez un nouveau code."
        self.otp = None
        self.otp_expiration = None
        self.save()
        cache.delete(self._cle_essais_otp())
        return True, "Code OTP valide."



    def generer_token_invitation(self):
        """
        Génère et sauvegarde un token unique pour l'invitation SMS,
        valable DUREE_VALIDITE_INVITATION. Un nouvel appel invalide l'ancien
        lien et repart pour une durée complète.
        """
        self.token_invitation = secrets.token_urlsafe(32)
        self.token_expiration = timezone.now() + DUREE_VALIDITE_INVITATION
        self.save()
        return self.token_invitation

    def invitation_expiree(self):
        """Vrai si le lien d'invitation a dépassé sa date d'expiration."""
        return (
            self.token_expiration is not None
            and timezone.now() >= self.token_expiration
        )

    def verrouiller(self):
        """Verrouille le compte pendant 15 minutes."""
        self.verrouille = True
        self.date_verrouillage = timezone.now()

        self.save(update_fields=[
            'verrouille',
            'date_verrouillage',
            'tentatives_pin'
        ])

    def verifier_pin(self, pin):    
        """Vérifie le PIN et gère le verrouillage temporaire."""

        maintenant = timezone.now()
        duree_verrouillage = timedelta(minutes=15)

        # 1. Vérifier si le compte est verrouillé
        if self.verrouille:

            # Sécuriser les comptes déjà verrouillés
            # qui n'ont pas encore de date de verrouillage.
            if self.date_verrouillage is None:
                self.date_verrouillage = maintenant
                self.save(update_fields=['date_verrouillage'])

                return False, (
                    "Compte verrouillé. "
                    "Réessayez dans 15 minutes."
                )

            # Calculer la fin du verrouillage
            fin_verrouillage = (
                self.date_verrouillage + duree_verrouillage
            )

            # Si les 15 minutes ne sont pas écoulées
            if maintenant < fin_verrouillage:
                secondes_restantes = int(
                    (fin_verrouillage - maintenant).total_seconds()
                )

                return False, (
                    f"Compte verrouillé. "
                    f"Réessayez dans {secondes_restantes} secondes."
                )
            # 2. Les 15 minutes sont écoulées :
            # déverrouiller automatiquement le compte.
            self.verrouille = False
            self.date_verrouillage = None
            self.tentatives_pin = 0

            self.save(update_fields=[
                'verrouille',
                'date_verrouillage',
                'tentatives_pin'
            ])

        # 3. Vérifier le PIN
        if self.check_password(pin):
            self.tentatives_pin = 0
            self.save(update_fields=['tentatives_pin'])

            return True, "PIN correct."

        # 4. Incrémenter le nombre de tentatives incorrectes
        self.tentatives_pin += 1

        # 5. Verrouiller après 5 tentatives
        if self.tentatives_pin >= 5:
            self.verrouiller()

            return False, (
                "Compte verrouillé pendant 15 minutes "
                "après 5 tentatives incorrectes."
            )

        # 6. Informer l'utilisateur des tentatives restantes
        restantes = 5 - self.tentatives_pin

        self.save(update_fields=['tentatives_pin'])

        return False, (
            f"PIN incorrect. "
            f"Il vous reste {restantes} tentative(s)."
        )

    def __str__(self):
        return f"{self.prenom} {self.nom} — {self.role}"

    class Meta:
        verbose_name = "Utilisateur"
        verbose_name_plural = "Utilisateurs"
        db_table = "utilisateur"