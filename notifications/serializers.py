from rest_framework import serializers

from .models import FCMToken


class FCMTokenSerializer(serializers.ModelSerializer):

    class Meta:
        model = FCMToken
        fields = ['token', 'appareil']
        # L'utilisateur n'est jamais demandé à Angular —
        # il est récupéré depuis le token JWT via self.context['request'].user

    def create(self, validated_data):
        utilisateur = self.context['request'].user

        # Si le token existe déjà (même appareil, même navigateur),
        # on met à jour l'utilisateur et l'appareil associés.
        # Si le token est nouveau, on le crée.
        fcm_token, _ = FCMToken.objects.update_or_create(
            token=validated_data['token'],
            defaults={
                'utilisateur': utilisateur,
                'appareil': validated_data.get('appareil', ''),
            }
        )

        return fcm_token
