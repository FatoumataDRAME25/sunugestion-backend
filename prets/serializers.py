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
    # Décaissement : tous les modes autorisés, pas de restriction


class PretRemboursementSerializer(serializers.Serializer):
    mode_paiement = serializers.ChoiceField(
        choices=Pret.MODE_PAIEMENT_CHOICES
    )

    def validate_mode_paiement(self, value):
        request = self.context.get('request')
        pret = self.context.get('pret')

        # Si le membre rembourse pour lui-même → Wave ou Orange Money uniquement
        # Si le trésorier rembourse pour un autre → Espèces uniquement
        if request and pret:
            paye_pour_soi = request.user == pret.membre
            if paye_pour_soi and value == 'especes':
                raise serializers.ValidationError(
                    "Un membre qui rembourse pour lui-même doit utiliser Wave ou Orange Money."
                )
            if not paye_pour_soi and value != 'especes':
                raise serializers.ValidationError(
                    "Le remboursement pour un autre membre doit se faire en espèces."
                )
        return value