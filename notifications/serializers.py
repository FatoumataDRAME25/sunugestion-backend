from rest_framework import serializers

from .models import NotificationUtilisateur


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
