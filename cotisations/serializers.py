from django.db import transaction
from rest_framework import serializers
from .models import SessionCotisation, Cotisation


class SessionCotisationSerializer(serializers.ModelSerializer):
    class Meta : 
        model= SessionCotisation
        fields = ['id', 'libelle', 'montant', 'date_debut', 'date_fin', 'statut']

    @transaction.atomic
    def create(self, validated_data):
        createur = self.context['request'].user
        session = SessionCotisation.objects.create(
            createur=createur,
            **validated_data
        )
        gie = createur.gie
        membres_actifs = gie.membres.filter(statut='actif')

        cotisations = []

        for membre in membres_actifs:
            cotisations.append(
                Cotisation(
                    session=session,
                    membre=membre
                )
            )

        Cotisation.objects.bulk_create(cotisations)
        return session



class SessionCotisationDetailSerializer(serializers.ModelSerializer):

    class Meta:
        model = SessionCotisation
        fields = ['id','libelle','montant','date_debut','date_fin']

class MembreCotisationSerializer(serializers.Serializer):

    id = serializers.IntegerField()
    nom = serializers.CharField()
    prenom = serializers.CharField()
    telephone = serializers.CharField()

class CotisationSerializer(serializers.ModelSerializer):

    session = SessionCotisationDetailSerializer(read_only=True)
    membre = MembreCotisationSerializer(read_only=True)

    class Meta:
        model = Cotisation
        fields = ['id','session','membre','date_paiement','mode_paiement','statut']


class CotisationPaiementSerializer(serializers.Serializer):

    mode_paiement = serializers.ChoiceField(
        choices=[
            ('especes', 'Espèces'),
        ]
    )