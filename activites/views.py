from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework.decorators import action

from django.contrib.auth import get_user_model

from .models import Activite, Presence
from .serializers import ActiviteSerializer, EnregistrerPresenceSerializer
from notifications.service import envoyer_notification
from authentication.permissions import EstMembreGIE, EstPresidentOuSecretaire

Utilisateur = get_user_model()


def _membres_actifs_sauf(gie, exclu_id):
    """Retourne les membres actifs du GIE en excluant l'utilisateur donné."""
    return Utilisateur.objects.filter(
        gie=gie,
        statut='actif'
    ).exclude(id=exclu_id)


class ActiviteViewSet(viewsets.ModelViewSet):

    serializer_class = ActiviteSerializer

    def get_permissions(self):
        # Lecture seule : tout membre GIE (admin exclu)
        if self.action in ('list', 'retrieve', 'membres'):
            return [EstMembreGIE()]
        # Écriture et actions : président ou secrétaire uniquement
        return [EstPresidentOuSecretaire()]

    def get_queryset(self):
        return Activite.objects.filter(
            gie=self.request.user.gie
        ).order_by('-date_activite')

    def perform_create(self, serializer):
        activite = serializer.save(
            gie=self.request.user.gie,
            organisateur=self.request.user
        )
        envoyer_notification(
            destinataires=_membres_actifs_sauf(self.request.user.gie, self.request.user.id),
            titre="Nouvelle activité",
            message=f"Une activité a été planifiée : {activite.titre}",
            type_evenement="nouvelle_activite",
            module="activites",
            objet_id=activite.id,
        )

    @action(detail=True, methods=['post'])
    def annuler(self, request, pk=None):
        activite = self.get_object()

        activite.statut = 'annulee'
        activite.save(update_fields=['statut'])

        envoyer_notification(
            destinataires=_membres_actifs_sauf(activite.gie, request.user.id),
            titre="Activité annulée",
            message=f"L'activité « {activite.titre} » a été annulée.",
            type_evenement="activite_annulee",
            module="activites",
            objet_id=activite.id,
        )

        return Response({'message': 'Activité annulée avec succès.'})

    @action(detail=True, methods=['post'])
    def demarrer(self, request, pk=None):
        activite = self.get_object()

        if activite.statut != 'planifiee':
            return Response(
                {'message': 'Seule une activité planifiée peut être démarrée.'},
                status=400
            )

        activite.statut = 'en_cours'
        activite.save(update_fields=['statut'])

        envoyer_notification(
            destinataires=_membres_actifs_sauf(activite.gie, request.user.id),
            titre="Activité démarrée",
            message=f"L'activité « {activite.titre} » vient de démarrer.",
            type_evenement="activite_demarree",
            module="activites",
            objet_id=activite.id,
        )

        return Response({
            'message': 'Activité démarrée avec succès.',
            'statut': activite.statut
        })

    @action(detail=True, methods=['post'])
    def terminer(self, request, pk=None):
        activite = self.get_object()

        if activite.statut != 'en_cours':
            return Response(
                {'message': 'Seule une activité en cours peut être terminée.'},
                status=400
            )

        compte_rendu = request.data.get('compte_rendu')

        if not compte_rendu:
            return Response(
                {
                    'compte_rendu': (
                        "Le compte rendu est obligatoire pour terminer "
                        "l'activité."
                    )
                },
                status=400
            )

        activite.compte_rendu = compte_rendu
        activite.statut = 'terminee'
        activite.save(update_fields=['compte_rendu', 'statut'])

        envoyer_notification(
            destinataires=_membres_actifs_sauf(activite.gie, request.user.id),
            titre="Activité terminée",
            message=f"L'activité « {activite.titre} » est terminée.",
            type_evenement="activite_terminee",
            module="activites",
            objet_id=activite.id,
        )

        return Response({
            'message': 'Activité terminée avec succès.',
            'statut': activite.statut,
            'compte_rendu': activite.compte_rendu
        })

    @action(detail=True, methods=['get'])
    def membres(self, request, pk=None):
        activite = self.get_object()

        membres = Utilisateur.objects.filter(
            gie=activite.gie
        ).exclude(role='administrateur')

        resultats = []

        for membre in membres:
            presence = Presence.objects.filter(
                activite=activite,
                utilisateur=membre
            ).first()

            resultats.append({
                'id': membre.id,
                'nom': membre.nom,
                'prenom': membre.prenom,
                'telephone': membre.telephone,
                'statut': presence.statut if presence else None
            })

        return Response(resultats)

    @action(detail=True, methods=['post'], url_path='enregistrer-presences')
    def enregistrer_presences(self, request, pk=None):
        activite = self.get_object()

        if activite.statut not in ['en_cours', 'terminee']:
            return Response(
                {
                    'message': (
                        'Les présences peuvent être enregistrées '
                        'uniquement pour une activité en cours ou terminée.'
                    )
                },
                status=400
            )

        serializer = EnregistrerPresenceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        presences = serializer.validated_data['presences']

        for presence in presences:
            utilisateur = presence['utilisateur']

            if utilisateur.gie_id != activite.gie_id:
                return Response(
                    {
                        'message': (
                            f'Le membre {utilisateur.id} '
                            'n\u2019appartient pas à ce GIE.'
                        )
                    },
                    status=400
                )

            if Presence.objects.filter(
                activite=activite,
                utilisateur=utilisateur
            ).exists():
                return Response(
                    {
                        'message': (
                            f'La présence du membre {utilisateur.id} '
                            'est déjà enregistrée.'
                        )
                    },
                    status=400
                )

        Presence.objects.bulk_create([
            Presence(
                activite=activite,
                utilisateur=presence['utilisateur'],
                statut=presence['statut']
            )
            for presence in presences
        ])

        return Response(
            {'message': 'Les présences ont été enregistrées avec succès.'},
            status=201
        )
