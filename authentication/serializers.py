from rest_framework_simplejwt.exceptions import TokenError

from rest_framework import serializers
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from .models import GIE
import secrets

Utilisateur = get_user_model()


class GIECreationSerializer(serializers.ModelSerializer):
    """Étape 1 — Création du GIE"""

    class Meta:
        model = GIE
        fields = ['nom', 'region', 'secteur', 'telephone', 'photo']

    def validate_nom(self, valeur):
        if not valeur.strip():
            raise serializers.ValidationError(
                "Le nom du GIE ne peut pas être vide."
            )
        return valeur.strip()

    def create(self, validated_data):
        # Générer un token d'inscription temporaire
        token_inscription = secrets.token_urlsafe(32)

        gie = GIE.objects.create(
            **validated_data,
            code=f"SG-{secrets.token_hex(3).upper()}",
            token_inscription=token_inscription,
            statut='en_attente'
        )
        return gie


class InscriptionPresidentSerializer(serializers.ModelSerializer):
    """Étape 2 — Informations personnelles + PIN"""

    token_inscription = serializers.CharField(write_only=True)
    pin = serializers.CharField(
        max_length=4,
        min_length=4,
        write_only=True
    )
    confirmation_pin = serializers.CharField(
        max_length=4,
        min_length=4,
        write_only=True
    )

    class Meta:
        model = Utilisateur
        fields = [
            'nom',
            'prenom',
            'telephone',
            'email',
            'pin',
            'confirmation_pin',
            'token_inscription'
        ]

    def validate_telephone(self, valeur):
        if Utilisateur.objects.filter(telephone=valeur).exists():
            raise serializers.ValidationError(
                "Ce numéro de téléphone est déjà utilisé."
            )
        return valeur

    def validate_pin(self, valeur):
        if not valeur.isdigit():
            raise serializers.ValidationError(
                "Le PIN doit contenir uniquement des chiffres."
            )
        return valeur

    def validate(self, data):
        # Vérifier que les deux PIN correspondent
        if data['pin'] != data['confirmation_pin']:
            raise serializers.ValidationError(
                "Les deux PIN ne correspondent pas."
            )

        # Vérifier que le token d'inscription existe
        try:
            gie = GIE.objects.get(
                token_inscription=data['token_inscription'],
                statut='en_attente'
            )
            data['gie'] = gie
        except GIE.DoesNotExist:
            raise serializers.ValidationError(
                "Session d'inscription invalide ou expirée."
            )

        return data

    def create(self, validated_data):
        # Extraire les données non liées au modèle
        pin = validated_data.pop('pin')
        validated_data.pop('confirmation_pin')
        validated_data.pop('token_inscription')
        gie = validated_data.pop('gie')

        # Créer le Président
        president = Utilisateur.objects.create_user(
            telephone=validated_data['telephone'],
            nom=validated_data['nom'],
            prenom=validated_data['prenom'],
            role='president',
            gie=gie,
            password=pin
        )

        # Générer et envoyer l'OTP
        otp = president.generer_otp()

        # TODO : envoyer SMS via Africa's Talking
        print(f"OTP pour {president.telephone} : {otp}")

        return president


class VerifierOTPSerializer(serializers.Serializer):
    """Étape 3 — Vérification du code OTP"""

    token_inscription = serializers.CharField()
    otp = serializers.CharField(max_length=6, min_length=6)

    def validate_otp(self, valeur):
        if not valeur.isdigit():
            raise serializers.ValidationError(
                "Le code OTP doit contenir uniquement des chiffres."
            )
        return valeur

    def validate(self, data):
        # Retrouver le Président via le token du GIE
        try:
            gie = GIE.objects.get(
                token_inscription=data['token_inscription']
            )
            president = Utilisateur.objects.get(
                gie=gie,
                role='president'
            )
            data['president'] = president
        except (GIE.DoesNotExist, Utilisateur.DoesNotExist):
            raise serializers.ValidationError(
                "Session d'inscription invalide."
            )

        # Vérifier l'OTP
        valide, message = president.verifier_otp(data['otp'])
        if not valide:
            raise serializers.ValidationError(message)

        return data

    def activer_compte(self):
        president = self.validated_data['president']
        gie = president.gie

        # Activer le compte et le GIE
        president.statut = 'actif'
        president.save()

        gie.statut = 'actif'
        gie.token_inscription = None
        gie.save()

        return president


class ConnexionSerializer(serializers.Serializer):
    telephone = serializers.CharField()
    pin = serializers.CharField(max_length=4, min_length=4)

    def validate(self, data):
        telephone = data.get('telephone')
        pin = data.get('pin')

        # Vérifier que l'utilisateur existe
        try:
            utilisateur = Utilisateur.objects.get(telephone=telephone)
        except Utilisateur.DoesNotExist:
            raise serializers.ValidationError(
                "Numéro de téléphone introuvable."
            )

        # Vérifier que le compte est actif
        if utilisateur.statut != 'actif':
            raise serializers.ValidationError(
                "Votre compte n'est pas encore activé."
            )

        # Vérifier le PIN
        valide, message = utilisateur.verifier_pin(pin)
        if not valide:
            raise serializers.ValidationError(message)

        data['utilisateur'] = utilisateur
        return data



class DeconnexionSerializer(serializers.Serializer):
    refresh = serializers.CharField()

    def validate(self, data):
        try:
            token = RefreshToken(data['refresh'])
            token.blacklist()
        except TokenError:
            raise serializers.ValidationError(
                "Token invalide ou déjà expiré."
            )
        return data