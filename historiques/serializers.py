from rest_framework import serializers
from .models import  HistoriqueOperation


class HistoriqueOperationSerializer(serializers.ModelSerializer):

    class Meta:
        model = HistoriqueOperation
        fields = [
            'id',
            'type_operation',
            'montant',
            'libelle',
            'cotisation',
            'date_operation',
        ]

class SoldeSerializer(serializers.Serializer):

    total_entrees = serializers.DecimalField(
        max_digits=12,
        decimal_places=0
    )

    total_sorties = serializers.DecimalField(
        max_digits=12,
        decimal_places=0
    )

    solde = serializers.DecimalField(
        max_digits=12,
        decimal_places=0
    )


class OperationCreateSerializer(serializers.ModelSerializer):

    class Meta:
        model = HistoriqueOperation
        fields = [
            'type_operation',
            'montant',
            'libelle',
        ]