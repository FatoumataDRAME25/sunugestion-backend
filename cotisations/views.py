
from rest_framework import generics
from django.db import transaction
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.response import Response
from cotisations.models import Cotisation, SessionCotisation
from historiques.models import HistoriqueOperation
from .serializers import CotisationPaiementSerializer, CotisationSerializer, SessionCotisationSerializer

class SessionCotisationCreateView(generics.ListCreateAPIView):

    serializer_class = SessionCotisationSerializer

    def get_queryset(self):
        return SessionCotisation.objects.filter(
            createur__gie=self.request.user.gie
        )


class CotisationListView(generics.ListAPIView):
    serializer_class = CotisationSerializer

    def get_queryset(self):
        session_id = self.kwargs['session_id']

        return Cotisation.objects.filter(
            session_id=session_id
        )



class CotisationPaiementView(generics.GenericAPIView):

    serializer_class = CotisationPaiementSerializer

    @transaction.atomic
    def post(self, request, pk):

        cotisation = Cotisation.objects.select_for_update().get(
            pk=pk
        )

        if cotisation.statut == 'paye':
            return Response(
                {
                    'detail': 'Cette cotisation a déjà été payée.'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        mode_paiement = serializer.validated_data['mode_paiement']

        cotisation.statut = 'paye'
        cotisation.mode_paiement = mode_paiement
        cotisation.date_paiement = timezone.now()
        cotisation.save()

        HistoriqueOperation.objects.create(
        gie=cotisation.membre.gie,
        type_operation='entree',
        montant=cotisation.session.montant,
        libelle=(
            f'Paiement cotisation - '
            f'{cotisation.membre.prenom} {cotisation.membre.nom} - '
            f'{cotisation.session.libelle}'
        ),
        cotisation=cotisation
    )

        return Response(
            CotisationSerializer(cotisation).data,
            status=status.HTTP_200_OK
        )