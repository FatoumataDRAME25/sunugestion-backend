from rest_framework import serializers
from authentication.models import GIE


class GieSerializer(serializers.ModelSerializer):
    """Serializer en lecture pour les infos du GIE."""

    class Meta:
        model = GIE
        fields = [
            'id',
            'nom',
            'region',
            'secteur',
            'telephone',
            'code',
            'statut',
            'date_creation',
        ]
        read_only_fields = ['id', 'code', 'statut', 'date_creation']


class GieModifierSerializer(serializers.ModelSerializer):
    """Serializer pour la modification partielle du GIE (président uniquement)."""

    class Meta:
        model = GIE
        fields = [
            'nom',
            'region',
            'secteur',
            'telephone',
        ]
