from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from .models import SessionCotisation, Cotisation


class SessionCotisationSerializer(serializers.ModelSerializer):

    # Indicateurs de la session, en lecture seule (attendus par le tableau de bord)
    nombre_membres = serializers.SerializerMethodField()
    nombre_paies = serializers.SerializerMethodField()
    nombre_en_attente = serializers.SerializerMethodField()
    total_attendu = serializers.SerializerMethodField()
    total_collecte = serializers.SerializerMethodField()

    class Meta :
        model= SessionCotisation
        fields = [
            'id', 'libelle', 'montant', 'date_debut', 'date_fin', 'statut',
            'nombre_membres', 'nombre_paies', 'nombre_en_attente',
            'total_attendu', 'total_collecte',
        ]

    def _compteurs(self, session):
        # Valeurs annotées par la vue de liste, sinon calculées (ex. après création)
        nombre = getattr(session, 'nb_cotisations', None)
        paies = getattr(session, 'nb_paies', None)
        if nombre is None or paies is None:
            nombre = session.cotisations.count()
            paies = session.cotisations.filter(statut='paye').count()
        return nombre, paies

    def get_nombre_membres(self, session):
        return self._compteurs(session)[0]

    def get_nombre_paies(self, session):
        return self._compteurs(session)[1]

    def get_nombre_en_attente(self, session):
        nombre, paies = self._compteurs(session)
        return nombre - paies

    def get_total_attendu(self, session):
        return self._compteurs(session)[0] * session.montant

    def get_total_collecte(self, session):
        # Toutes les cotisations d'une session ont le même montant
        return self._compteurs(session)[1] * session.montant

    def validate_montant(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                "Le montant doit être supérieur à 0."
            )
        return value

    def validate_date_debut(self, valeur):
        aujourd_hui = timezone.now().date()
        if valeur < aujourd_hui:
            raise serializers.ValidationError(
                "La date de début ne peut pas être dans le passé."
            )
        return valeur

    def validate_date_fin(self, valeur):
        aujourd_hui = timezone.now().date()
        if valeur < aujourd_hui:
            raise serializers.ValidationError(
                "La date de fin ne peut pas être dans le passé."
            )
        return valeur

    def validate(self, attrs):
        date_debut = attrs.get('date_debut')
        date_fin   = attrs.get('date_fin')
        if date_debut and date_fin and date_fin < date_debut:
            raise serializers.ValidationError(
                {'date_fin': "La date de fin ne peut pas être antérieure à la date de début."}
            )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        # createur est injecté par perform_create via serializer.save(createur=...)
        createur = validated_data.pop('createur')
        gie = createur.gie
        session = SessionCotisation.objects.create(
            gie=gie,
            createur=createur,
            **validated_data
        )
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
        choices=Cotisation.MODE_PAIEMENT_CHOICES
    )

    def validate_mode_paiement(self, value):
        request = self.context.get('request')
        cotisation = self.context.get('cotisation')

        # Si le membre paie pour lui-même → Wave ou Orange Money uniquement
        # Si le trésorier paie pour un autre → Espèces uniquement
        if request and cotisation:
            paye_pour_soi = request.user == cotisation.membre
            if paye_pour_soi and value == 'especes':
                raise serializers.ValidationError(
                    "Un membre qui paie pour lui-même doit utiliser Wave ou Orange Money."
                )
            if not paye_pour_soi and value != 'especes':
                raise serializers.ValidationError(
                    "Le paiement pour un autre membre doit se faire en espèces."
                )
        return value