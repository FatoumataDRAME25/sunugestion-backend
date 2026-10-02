from rest_framework import generics
from rest_framework.response import Response
from rest_framework import status

from authentication.permissions import EstMembreGIE, EstPresident
from .serializers import GieSerializer, GieModifierSerializer


class GieInfosView(generics.GenericAPIView):
    """
    GET  /api/gie/infos/  → tout membre GIE peut lire les infos
    PATCH /api/gie/infos/ → seul le président peut modifier
    """

    def get_permissions(self):
        if self.request.method == 'PATCH':
            return [EstPresident()]
        return [EstMembreGIE()]

    def get(self, request):
        gie = request.user.gie
        if not gie:
            return Response(
                {'detail': "Vous n'êtes rattaché à aucun GIE."},
                status=status.HTTP_404_NOT_FOUND
            )
        serializer = GieSerializer(gie)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request):
        gie = request.user.gie
        if not gie:
            return Response(
                {'detail': "Vous n'êtes rattaché à aucun GIE."},
                status=status.HTTP_404_NOT_FOUND
            )
        serializer = GieModifierSerializer(gie, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(GieSerializer(gie).data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
