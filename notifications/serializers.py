from rest_framework import serializers

from .models import FCMToken, NotificationUtilisateur


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


class NotificationListeSerializer(serializers.ModelSerializer):
    """
    Notification telle que la voit un utilisateur : contenu de la
    notification et état « lue » propre à cet utilisateur.
    """

    id = serializers.IntegerField(source='notification.id')
    titre = serializers.CharField(source='notification.titre')
    message = serializers.CharField(source='notification.message')
    type = serializers.CharField(source='notification.type')
    module = serializers.CharField(source='notification.module')
    objet_id = serializers.IntegerField(source='notification.objet_id')
    date_creation = serializers.DateTimeField(source='notification.date_creation')

    class Meta:
        model = NotificationUtilisateur
        fields = [
            'id',
            'titre',
            'message',
            'type',
            'module',
            'objet_id',
            'date_creation',
            'lue',
        ]
        read_only_fields = fields
