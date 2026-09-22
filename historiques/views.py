from django.db.models import Sum

from rest_framework import generics, serializers
from rest_framework.response import Response

from historiques.models import HistoriqueOperation
from historiques.serializers import (
    HistoriqueOperationSerializer,
    OperationCreateSerializer,
    SoldeSerializer
)


def calculer_solde(gie):

    total_entrees = HistoriqueOperation.objects.filter(
        gie=gie,
        type_operation='entree'
    ).aggregate(
        total=Sum('montant')
    )['total'] or 0

    total_sorties = HistoriqueOperation.objects.filter(
        gie=gie,
        type_operation='sortie'
    ).aggregate(
        total=Sum('montant')
    )['total'] or 0

    solde = total_entrees - total_sorties

    return total_entrees, total_sorties, solde


class HistoriqueOperationListView(generics.ListAPIView):

    serializer_class = HistoriqueOperationSerializer

    def get_queryset(self):

        return HistoriqueOperation.objects.filter(
            gie=self.request.user.gie
        )


class SoldeView(generics.GenericAPIView):

    serializer_class = SoldeSerializer

    def get(self, request):

        gie = request.user.gie

        total_entrees, total_sorties, solde = calculer_solde(gie)

        donnees = {
            'total_entrees': total_entrees,
            'total_sorties': total_sorties,
            'solde': solde
        }

        serializer = self.get_serializer(donnees)

        return Response(serializer.data)


class OperationCreateView(generics.CreateAPIView):

    serializer_class = OperationCreateSerializer

    def perform_create(self, serializer):

        gie = self.request.user.gie

        if serializer.validated_data['type_operation'] == 'sortie':

            solde = calculer_solde(gie)

            montant_sortie = serializer.validated_data['montant']

            if montant_sortie > solde:

                raise serializers.ValidationError(
                    {
                        'montant': (
                            'Le montant de la sortie est supérieur '
                            'au solde disponible.'
                        )
                    }
                )

        serializer.save(gie=gie)