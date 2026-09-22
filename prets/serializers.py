from rest_framework import serializers
from django.utils import timezone

from .models import Pret, ReglePret

from authentication.models import Utilisateur


class ReglePretSerializer(serializers.ModelSerializer):

    class Meta:
        model = ReglePret
        fields = [
            'id',
            'gie',
            'montant_max',
            'duree_max_mois',
            'nombre_prets_simultanes',
            'cotisation_a_jour_obligatoire',
        ]
        read_only_fields = ['id', 'gie']



class MembrePretSerializer(serializers.ModelSerializer):
    class Meta:
        model = Utilisateur
        fields = ['id', 'prenom', 'nom', 'telephone']

class PretSerializer(serializers.ModelSerializer):
    membre = MembrePretSerializer(read_only=True)

    class Meta:
        model = Pret
        fields = [
            'id',
            'membre',
            'montant',
            'date_demande',
            'duree_mois',
            'date_echeance',
            'date_approbation',
            'date_remboursement',
            'statut',
            'mode_paiement',
        ]

        read_only_fields = [
            'id',
            'membre',
            'date_demande',
            'date_echeance',
            'date_approbation',
            'date_remboursement',
            'statut',
        ]



class PretApprobationSerializer(serializers.Serializer):

    duree_mois = serializers.IntegerField(
        min_value=1
    )

class PretDecaissementSerializer(serializers.Serializer):
    mode_paiement = serializers.ChoiceField(
        choices=Pret.MODE_PAIEMENT_CHOICES
    )


class PretRemboursementSerializer(serializers.Serializer):
    mode_paiement = serializers.ChoiceField(
        choices=Pret.MODE_PAIEMENT_CHOICES
    )