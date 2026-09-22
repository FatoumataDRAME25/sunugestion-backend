from django.utils import timezone
from datetime import date
import calendar
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import ValidationError
from django.db import transaction
from historiques.views import calculer_solde
from historiques.models import HistoriqueOperation

from .models import ReglePret, Pret
from cotisations.models import Cotisation
from .serializers import (
ReglePretSerializer, 
PretSerializer, 
PretApprobationSerializer, 
PretDecaissementSerializer,
PretRemboursementSerializer)


def ajouter_mois(date_depart, nombre_mois):

    mois_total = date_depart.month - 1 + nombre_mois

    annee = date_depart.year + mois_total // 12

    mois = mois_total % 12 + 1

    jour = min(
        date_depart.day,
        calendar.monthrange(annee, mois)[1]
    )

    return date(
        annee,
        mois,
        jour
    )

class ReglePretView(generics.GenericAPIView):
    serializer_class = ReglePretSerializer
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            regle = ReglePret.objects.get(
                gie=request.user.gie
            )
        except ReglePret.DoesNotExist:
            return Response(
                {"message": "Les règles de prêt ne sont pas encore configurées."},
                status=404
            )

        serializer = self.get_serializer(regle)
        return Response(serializer.data)
    

    def post(self, request):
        if ReglePret.objects.filter(gie=request.user.gie).exists():
            raise ValidationError(
                "Les règles de prêt de ce GIE existent déjà."
            )

        serializer = self.get_serializer(data=request.data)

        serializer.is_valid(raise_exception=True)

        serializer.save(
            gie=request.user.gie
        )

        return Response(
            serializer.data,
            status=201
        )

    def patch(self, request):
        try:
            regle = ReglePret.objects.get(
                gie=request.user.gie
            )
        except ReglePret.DoesNotExist:
            return Response(
                {"message": "Les règles de prêt n'existent pas encore."},
                status=404
            )

        serializer = self.get_serializer(
            regle,
            data=request.data,
            partial=True
        )

        serializer.is_valid(raise_exception=True)

        serializer.save(
            gie=request.user.gie
        )

        return Response(serializer.data)



class PretView(generics.GenericAPIView):

    serializer_class = PretSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request):

        gie = request.user.gie

        # Vérifier que les règles de prêt existent
        try:
            regle = ReglePret.objects.get(
                gie=gie
            )
        except ReglePret.DoesNotExist:

            return Response(
                {
                    'message': (
                        'Les règles de prêt de ce GIE '
                        'ne sont pas encore configurées.'
                    )
                },
                status=404
            )

        # Valider les données de la demande
        serializer = self.get_serializer(
            data=request.data
        )

        serializer.is_valid(
            raise_exception=True
        )

        montant = serializer.validated_data['montant']

        # Vérifier le montant maximum autorisé
        if montant > regle.montant_max:

            raise ValidationError(
                {
                    'montant': (
                        f'Le montant maximum autorisé est '
                        f'{regle.montant_max} FCFA.'
                    )
                }
            )

        # Récupérer le solde actuel de la caisse
        _, _, solde = calculer_solde(gie)

        # Vérifier que le prêt ne dépasse pas le solde
        if montant > solde:

            raise ValidationError(
                {
                    'montant': (
                        'Le montant demandé est supérieur '
                        'au solde disponible de la caisse.'
                    )
                }
            )

        # Vérifier le nombre de prêts simultanés
        nombre_prets = Pret.objects.filter(
            membre=request.user,
            statut__in=['en_attente', 'en_cours','approuve']
        ).count()

        if nombre_prets >= regle.nombre_prets_simultanes:

            raise ValidationError(
                {
                    'pret': (
                        'Vous avez deja un prêt non rembourse.'
                    )
                }
            )

        # Vérifier que les cotisations sont à jour
        if regle.cotisation_a_jour_obligatoire:

            cotisation_impayee = Cotisation.objects.filter(
                membre=request.user,
                statut__in=['en_cours', 'en_retard']
            ).exists()

            if cotisation_impayee:

                raise ValidationError(
                    {
                        'cotisation': (
                            'Vous devez être à jour de vos cotisations '
                            'pour demander un prêt.'
                        )
                    }
                )

        # Créer la demande
        serializer.save(
            membre=request.user,
            statut='en_attente'
        )

        return Response(
            serializer.data,
            status=201
        )

    
    def get(self, request, pk=None):

        gie = request.user.gie

        # Si un ID est fourni → détail du prêt
        if pk:

            pret = get_object_or_404(
                Pret,
                id=pk,
                membre__gie=gie
            )

            serializer = self.get_serializer(pret)

            return Response(
                serializer.data,
                status=200
            )

        # Sinon → liste de tous les prêts du GIE
        prets = Pret.objects.filter(
            membre__gie=gie
        )

        serializer = self.get_serializer(
            prets,
            many=True
        )

        return Response(
            serializer.data,
            status=200
        )

class PretApprobationView(generics.GenericAPIView):

    serializer_class = PretApprobationSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):

        try:
            pret = Pret.objects.get(
                id=pk
            )
        except Pret.DoesNotExist:
            return Response(
                {
                    'message': 'Ce prêt n existe pas.'
                },
                status=404
            )

        # Vérifier que le prêt est encore en attente
        if pret.statut != 'en_attente':

            raise ValidationError(
                {
                    'pret': (
                        'Ce prêt ne peut plus être approuvé.'
                    )
                }
            )

        # Récupérer les règles du GIE
        gie = pret.membre.gie

        try:
            regle = ReglePret.objects.get(
                gie=gie
            )
        except ReglePret.DoesNotExist:

            return Response(
                {
                    'message': (
                        'Les règles de prêt de ce GIE '
                        'ne sont pas configurées.'
                    )
                },
                status=404
            )

        # Valider la durée envoyée par le président
        serializer = self.get_serializer(
            data=request.data
        )

        serializer.is_valid(
            raise_exception=True
        )

        duree_mois = serializer.validated_data['duree_mois']

        # Vérifier la durée maximale
        if duree_mois > regle.duree_max_mois:

            raise ValidationError(
                {
                    'duree_mois': (
                        f'La durée maximale autorisée est de '
                        f'{regle.duree_max_mois} mois.'
                    )
                }
            )

        # Vérifier à nouveau le solde de la caisse
        _, _, solde = calculer_solde(gie)

        if pret.montant > solde:

            raise ValidationError(
                {
                    'pret': (
                        'Le solde disponible de la caisse '
                        'ne permet plus d approuver ce prêt.'
                    )
                }
            )

        # Pour l'instant : approbation uniquement
        pret.duree_mois = duree_mois
        pret.date_approbation = timezone.now()
        pret.statut = 'approuve'

        pret.save()

        return Response(PretSerializer(pret).data, status=200)


class PretDecaissementView(generics.GenericAPIView):

    serializer_class = PretDecaissementSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):

        try:
            pret = Pret.objects.get(id=pk)
        except Pret.DoesNotExist:
            return Response(
                {
                    'message': 'Ce prêt n existe pas.'
                },
                status=404
            )

        # Le prêt doit avoir été approuvé
        if pret.statut != 'approuve':
            raise ValidationError(
                {
                    'pret': (
                        'Seul un prêt approuvé peut être décaissé.'
                    )
                }
            )

        gie = pret.membre.gie

        # Vérification du solde actuel
        _, _, solde = calculer_solde(gie)

        if pret.montant > solde:
            raise ValidationError(
                {
                    'pret': (
                        'Le solde disponible de la caisse '
                        'ne permet pas de décaisser ce prêt.'
                    )
                }
            )

        # Validation du mode de paiement
        serializer = self.get_serializer(
            data=request.data
        )
        serializer.is_valid(
            raise_exception=True
        )

        mode_paiement = serializer.validated_data[
            'mode_paiement'
        ]

        # Décaissement
        with transaction.atomic():

            HistoriqueOperation.objects.create(
                gie=gie,
                type_operation='sortie',
                montant=pret.montant,
                libelle=f'Décaissement du prêt de {pret.membre}',
            )

            # Date de décaissement = aujourd'hui
            date_decaissement = timezone.now().date()

            # Calcul de la date d'échéance
            date_echeance = ajouter_mois(
                date_decaissement,
                pret.duree_mois
            )

            pret.mode_paiement = mode_paiement
            pret.date_echeance = date_echeance
            pret.statut = 'en_cours'

            pret.save()

        return Response(PretSerializer(pret).data, status=200)


class PretRemboursementView(generics.GenericAPIView):

    serializer_class = PretRemboursementSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):

        try:
            pret = Pret.objects.get(id=pk)
        except Pret.DoesNotExist:
            return Response(
                {
                    'message': 'Ce prêt n existe pas.'
                },
                status=404
            )

        if pret.statut != 'en_cours':
            raise ValidationError(
                {
                    'pret': (
                        'Seul un prêt en cours peut être remboursé.'
                    )
                }
            )

        serializer = self.get_serializer(
            data=request.data
        )
        serializer.is_valid(
            raise_exception=True
        )

        mode_paiement = serializer.validated_data[
            'mode_paiement'
        ]

        with transaction.atomic():

            HistoriqueOperation.objects.create(
                gie=pret.membre.gie,
                type_operation='entree',
                montant=pret.montant,
                libelle=f'Remboursement du prêt de {pret.membre}',
            )

            pret.date_remboursement = timezone.now().date()
            pret.statut = 'rembourse'
            pret.mode_paiement = mode_paiement

            pret.save()

        return Response(PretSerializer(pret).data, status=200)
