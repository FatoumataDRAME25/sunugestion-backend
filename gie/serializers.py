from rest_framework import serializers
from authentication.models import GIE
from authentication.validators import valider_nom_gie, valider_telephone_gie


class GieSerializer(serializers.ModelSerializer):
    """Serializer en lecture pour les infos du GIE."""

    class Meta:
        model = GIE
        fields = [
            'id',
            'nom',
            'region',
            'type_gie',
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
            'type_gie',
            'telephone',
        ]

    def validate_nom(self, valeur):
        return valider_nom_gie(valeur)

    def validate_telephone(self, valeur):
        return valider_telephone_gie(valeur)
