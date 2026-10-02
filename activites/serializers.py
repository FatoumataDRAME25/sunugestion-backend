from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import Activite, Presence

Utilisateur = get_user_model()


class ActiviteSerializer(serializers.ModelSerializer):

    class Meta:
        model = Activite

        fields = [
            'id',
            'gie',
            'organisateur',
            'titre',
            'date_creation',
            'date_activite',
            'lieu',
            'type_activite',
            'ordre_du_jour',
            'compte_rendu',
            'statut',
        ]

        read_only_fields = [
            'id',
            'gie',
            'organisateur',
            'date_creation',
            'statut',
        ]

    def validate_date_activite(self, valeur):
        # Uniquement à la création ou modification — pas lors des actions demarrer/terminer
        # qui n'envoient pas date_activite
        aujourd_hui = timezone.now().date()
        if valeur.date() < aujourd_hui:
            raise serializers.ValidationError(
                "La date de l'activité ne peut pas être dans le passé."
            )
        return valeur

    def validate(self, attrs):
        instance = self.instance

        if instance:
            statut = instance.statut

            if 'ordre_du_jour' in attrs:
                if statut == 'planifiee':
                    raise serializers.ValidationError({
                        'ordre_du_jour': (
                            "L'ordre du jour ne peut être renseigné "
                            "que lorsque l'activité est en cours."
                        )
                    })

            if 'compte_rendu' in attrs:
                if statut != 'terminee':
                    raise serializers.ValidationError({
                        'compte_rendu': (
                            "Le compte rendu ne peut être renseigné "
                            "que lorsque l'activité est terminée."
                        )
                    })

        return attrs


class PresenceItemSerializer(serializers.Serializer):
    """
    Serializer pour un élément de présence dans la liste.
    utilisateur est résolu en objet Utilisateur pour permettre
    les vérifications (gie_id, etc.) dans la vue.
    """
    utilisateur = serializers.PrimaryKeyRelatedField(
        queryset=Utilisateur.objects.all()
    )
    statut = serializers.ChoiceField(choices=['present', 'absent'])


class EnregistrerPresenceSerializer(serializers.Serializer):
    presences = PresenceItemSerializer(many=True)


class PresenceSerializer(serializers.ModelSerializer):

    class Meta:
        model = Presence

        fields = [
            'id',
            'activite',
            'utilisateur',
            'statut',
        ]

        read_only_fields = [
            'id',
            'activite'
        ]
