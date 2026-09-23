from rest_framework import serializers

from .models import Activite, Presence


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


        def validate(self, attrs):
            instance = self.instance

            if instance:
                statut = instance.statut

                # L'activité doit être en cours
                # pour pouvoir renseigner l'ordre du jour
                if 'ordre_du_jour' in attrs:
                    if statut == 'planifiee':
                        raise serializers.ValidationError({
                            'ordre_du_jour': (
                                "L'ordre du jour ne peut être renseigné "
                                "que lorsque l'activité est en cours."
                            )
                        })

                # L'activité doit être terminée
                # pour pouvoir renseigner le compte rendu
                if 'compte_rendu' in attrs:
                    if statut != 'terminee':
                        raise serializers.ValidationError({
                            'compte_rendu': (
                                "Le compte rendu ne peut être renseigné "
                                "que lorsque l'activité est terminée."
                            )
                        })

            return attrs


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


class EnregistrerPresenceSerializer(serializers.Serializer):

    presences = PresenceSerializer(
        many=True
    )