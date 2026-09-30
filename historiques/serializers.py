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


class CotisationResumSerializer(serializers.Serializer):
    """Résumé d'une cotisation liée à une opération."""
    id = serializers.IntegerField()
    libelle_session = serializers.SerializerMethodField()
    membre_nom = serializers.SerializerMethodField()

    def get_libelle_session(self, obj):
        return obj.session.libelle if obj.session else None

    def get_membre_nom(self, obj):
        if obj.membre:
            return f"{obj.membre.prenom} {obj.membre.nom}"
        return None


class PretResumSerializer(serializers.Serializer):
    """Résumé d'un prêt lié à une opération."""
    id = serializers.IntegerField()
    montant = serializers.DecimalField(max_digits=12, decimal_places=0)
    membre_nom = serializers.SerializerMethodField()
    statut = serializers.CharField()

    def get_membre_nom(self, obj):
        if obj.membre:
            return f"{obj.membre.prenom} {obj.membre.nom}"
        return None


class HistoriqueOperationDetailSerializer(serializers.ModelSerializer):

    cotisation_detail = serializers.SerializerMethodField()
    pret_detail = serializers.SerializerMethodField()

    class Meta:
        model = HistoriqueOperation
        fields = [
            'id',
            'type_operation',
            'montant',
            'libelle',
            'date_operation',
            'cotisation',
            'pret',
            'cotisation_detail',
            'pret_detail',
        ]

    def get_cotisation_detail(self, obj):
        if obj.cotisation:
            return CotisationResumSerializer(obj.cotisation).data
        return None

    def get_pret_detail(self, obj):
        if obj.pret:
            return PretResumSerializer(obj.pret).data
        return None


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