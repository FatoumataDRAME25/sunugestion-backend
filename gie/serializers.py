import io

from django.core.files.base import ContentFile
from django.db import transaction
from PIL import Image, ImageOps, UnidentifiedImageError
from rest_framework import serializers

from authentication.models import GIE
from authentication.validators import valider_nom_gie, valider_telephone_gie

TAILLE_MAX_LOGO = 2 * 1024 * 1024
FORMATS_LOGO = {'JPEG', 'PNG', 'WEBP'}
# Refusé avant décodage : une petite image compressée peut occuper
# des centaines de Mo en mémoire une fois décodée
PIXELS_MAX_LOGO = 25_000_000
COTE_LOGO = 512


def preparer_logo(fichier):
    """Vérifie l'image envoyée puis la réencode en WebP de 512 px au plus : les
    métadonnées (position GPS…) et tout contenu caché dans le fichier disparaissent."""
    if fichier.size > TAILLE_MAX_LOGO:
        raise serializers.ValidationError("Le logo ne doit pas dépasser 2 Mo.")
    try:
        image = Image.open(fichier)
        if image.format not in FORMATS_LOGO:
            raise serializers.ValidationError("Le logo doit être une image JPEG, PNG ou WebP.")
        if image.width * image.height > PIXELS_MAX_LOGO:
            raise serializers.ValidationError("L'image est trop grande (25 millions de pixels au plus).")
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise serializers.ValidationError("Le fichier n'est pas une image valide (JPEG, PNG ou WebP).")

    image = ImageOps.exif_transpose(image)
    transparente = image.mode in ('RGBA', 'LA', 'PA') or 'transparency' in image.info
    image = image.convert('RGBA' if transparente else 'RGB')
    image.thumbnail((COTE_LOGO, COTE_LOGO))

    tampon = io.BytesIO()
    image.save(tampon, format='WEBP', quality=85)
    return ContentFile(tampon.getvalue(), name='logo.webp')


class GieSerializer(serializers.ModelSerializer):
    """Serializer en lecture pour les infos du GIE."""

    class Meta:
        model = GIE
        fields = [
            'id',
            'nom',
            'region',
            'type_gie',
            'telephone',
            'code',
            'statut',
            'date_creation',
            'logo',
        ]
        read_only_fields = ['id', 'code', 'statut', 'date_creation', 'logo']


class GieModifierSerializer(serializers.ModelSerializer):
    """Serializer pour la modification partielle du GIE (président uniquement)."""

    # Fichier (multipart) pour changer le logo, null (JSON) pour le retirer
    logo = serializers.FileField(required=False, allow_null=True)

    class Meta:
        model = GIE
        fields = [
            'nom',
            'region',
            'type_gie',
            'telephone',
            'logo',
        ]

    def validate_nom(self, valeur):
        return valider_nom_gie(valeur)

    def validate_telephone(self, valeur):
        return valider_telephone_gie(valeur)

    def validate_logo(self, fichier):
        return preparer_logo(fichier) if fichier else None

    def update(self, gie, validated_data):
        ancien_logo = gie.logo.name if 'logo' in validated_data else None
        gie = super().update(gie, validated_data)
        # Ancien fichier supprimé une fois la modification enregistrée en base
        if ancien_logo and ancien_logo != gie.logo.name:
            stockage = gie.logo.storage
            transaction.on_commit(lambda: stockage.delete(ancien_logo))
        return gie
