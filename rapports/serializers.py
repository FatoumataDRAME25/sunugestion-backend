from django.utils import timezone
from rest_framework import serializers

from rapports.services import ANNEE_MIN, TYPES_PERIODE, obtenir_periode


class RapportPeriodeSerializer(serializers.Serializer):
    """
    Valide les paramètres de période du rapport.
    Aucun identifiant de GIE n'est accepté : le groupement est toujours
    celui de l'utilisateur connecté.
    """

    type_periode = serializers.ChoiceField(
        choices=TYPES_PERIODE,
        error_messages={
            'required': 'Le type de période est obligatoire.',
            'invalid_choice': (
                'Le type de période doit être mensuel, trimestriel ou annuel.'
            ),
        }
    )
    annee = serializers.IntegerField(
        min_value=ANNEE_MIN,
        error_messages={
            'required': "L'année est obligatoire.",
            'invalid': "L'année doit être un nombre entier.",
            'min_value': f"L'année doit être supérieure ou égale à {ANNEE_MIN}.",
        }
    )
    mois = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=12,
        error_messages={
            'invalid': 'Le mois doit être un nombre entier.',
            'min_value': 'Le mois doit être compris entre 1 et 12.',
            'max_value': 'Le mois doit être compris entre 1 et 12.',
        }
    )
    trimestre = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=4,
        error_messages={
            'invalid': 'Le trimestre doit être un nombre entier.',
            'min_value': 'Le trimestre doit être compris entre 1 et 4.',
            'max_value': 'Le trimestre doit être compris entre 1 et 4.',
        }
    )

    def validate(self, attrs):
        type_periode = attrs['type_periode']

        if type_periode == 'mensuel' and attrs.get('mois') is None:
            raise serializers.ValidationError(
                {'mois': 'Le mois est obligatoire pour un rapport mensuel.'}
            )

        if type_periode == 'trimestriel' and attrs.get('trimestre') is None:
            raise serializers.ValidationError(
                {
                    'trimestre': (
                        'Le trimestre est obligatoire pour un rapport '
                        'trimestriel.'
                    )
                }
            )

        # Ignorer les paramètres sans rapport avec le type choisi
        if type_periode != 'mensuel':
            attrs['mois'] = None

        if type_periode != 'trimestriel':
            attrs['trimestre'] = None

        try:
            debut, _ = obtenir_periode(
                type_periode,
                attrs['annee'],
                attrs['mois'],
                attrs['trimestre']
            )
        except ValueError as exc:
            raise serializers.ValidationError({'annee': str(exc)})

        if debut > timezone.localdate():
            raise serializers.ValidationError(
                {
                    'annee': (
                        "La période demandée n'a pas encore commencé. "
                        'Choisissez une période passée ou la période en cours.'
                    )
                }
            )

        return attrs
