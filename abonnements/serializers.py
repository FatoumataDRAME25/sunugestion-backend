from rest_framework import serializers

from .models import PaiementAbonnement


class PaiementAbonnementSerializer(serializers.ModelSerializer):

    initie_par = serializers.SerializerMethodField()

    class Meta:
        model = PaiementAbonnement
        fields = [
            'id',
            'montant',
            'nombre_membres',
            'mode_paiement',
            'statut',
            'periode_debut',
            'periode_fin',
            'initie_par',
            'note',
            'date_creation',
            'date_validation',
        ]
        read_only_fields = fields

    def get_initie_par(self, paiement):
        u = paiement.initie_par
        return f"{u.prenom} {u.nom}" if u else None


class PayerAbonnementSerializer(serializers.Serializer):
    mode_paiement = serializers.ChoiceField(
        choices=['wave', 'orange_money'],
        error_messages={
            'required': 'Le mode de paiement est obligatoire.',
            'invalid_choice': 'Le mode de paiement doit être Wave ou Orange Money.',
        }
    )


class PaiementManuelSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=255, required=False, allow_blank=True)
