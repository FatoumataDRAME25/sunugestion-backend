from rest_framework import serializers
from django.contrib.auth import get_user_model
from sunugestion.settings import APP_URL
import re

Utilisateur = get_user_model()

ROLES_AUTORISES = [
    'president',
    'tresorier',
    'secretaire',
    'membre'
]

FORMAT_TELEPHONE = r'^(70|71|75|76|77|78)[0-9]{7}$'


def valider_telephone(telephone):
    """Vérifie le format sénégalais et l'unicité."""
    erreurs = []
    telephone = str(telephone).strip()

    if not re.match(FORMAT_TELEPHONE, telephone):
        erreurs.append(
            "Format invalide — doit commencer par 70, 71, 75, 76, 77 ou 78"
        )

    if Utilisateur.objects.filter(telephone=telephone).exists():
        erreurs.append("Ce numéro existe déjà")

    return telephone, erreurs


def valider_role(role):
    """Vérifie que le rôle est autorisé."""
    role = str(role).strip().lower()

    if role not in ROLES_AUTORISES:
        return role, [
            f"Rôle invalide — valeurs autorisées : "
            f"{', '.join(ROLES_AUTORISES)}"
        ]

    return role, []


def valider_nom_prenom(valeur, champ):
    """Vérifie qu'un nom ou prénom contient uniquement des caractères valides."""
    valeur = str(valeur).strip()

    if not valeur:
        raise serializers.ValidationError(
            f"Le {champ} ne peut pas être vide."
        )

    if not re.match(r"^[A-Za-zÀ-ÖØ-öø-ÿ\s'-]+$", valeur):
        raise serializers.ValidationError(
            f"Le {champ} doit contenir uniquement des lettres."
        )

    return valeur


# ==========================================================
# AJOUT MANUEL
# ==========================================================

class AjoutMembreSerializer(serializers.Serializer):

    prenom = serializers.CharField(max_length=100)
    nom = serializers.CharField(max_length=100)
    telephone = serializers.CharField(max_length=20)
    role = serializers.ChoiceField(choices=ROLES_AUTORISES)

    def validate_telephone(self, valeur):
        telephone, erreurs = valider_telephone(valeur)

        if erreurs:
            raise serializers.ValidationError(erreurs)

        return telephone

    def validate_prenom(self, valeur):
        return valider_nom_prenom(valeur, "prénom")

    def validate_nom(self, valeur):
        return valider_nom_prenom(valeur, "nom")

    def create(self, validated_data):

        gie = self.context['gie']

        membre = Utilisateur.objects.create_user(
            telephone=validated_data['telephone'],
            nom=validated_data['nom'],
            prenom=validated_data['prenom'],
            role=validated_data['role'],
            gie=gie,
            statut='en_attente'
        )

        membre.statut = 'en_attente'
        membre.save()

        # Génération du token d'invitation
        membre.generer_token_invitation()

        # 🚀 CORRECTION DU LIEN (Syntaxe Python propre)
        lien = f"http://localhost:4200/activation?token={membre.token_invitation}"
        
        # 📱 AFFICHAGE SÉCURISÉ DANS LE TERMINAL
        print("\n" + "="*60)
        print(f"📱 [SIMULATION SMS] Envoyé au {membre.telephone}")
        print(f"Message : Bienvenue sur SunuGestion ! Activez votre compte ici : {lien}")
        print("="*60 + "\n")

        # TODO : Plus tard, intégrer l'envoi réel avec le SDK Africa's Talking ici


        return membre


# ==========================================================
# IMPORT EXCEL
# ==========================================================

class ImportExcelSerializer(serializers.Serializer):

    fichier = serializers.FileField()

    def validate_fichier(self, fichier):

        if not fichier.name.endswith('.xlsx'):
            raise serializers.ValidationError(
                "Le fichier doit être au format .xlsx"
            )

        return fichier

    def analyser(self):

        import openpyxl

        fichier = self.validated_data['fichier']

        wb = openpyxl.load_workbook(fichier)
        ws = wb.active

        colonnes_requises = [
            'prenom',
            'nom',
            'telephone',
            'role'
        ]

        membres_valides = []
        membres_invalides = []

        # Récupération des colonnes
        headers = [
            str(cell.value).strip().lower()
            for cell in ws[1]
        ]

        # Vérification des colonnes obligatoires
        for col in colonnes_requises:

            if col not in headers:
                raise serializers.ValidationError(
                    f"Colonne manquante dans le fichier : '{col}'"
                )

        # Lecture des lignes
        for numero_ligne, ligne in enumerate(
            ws.iter_rows(min_row=2, values_only=True),
            start=2
        ):

            # Ignorer les lignes complètement vides
            if not any(ligne):
                continue

            donnees = dict(zip(headers, ligne))

            erreurs_ligne = []

            prenom = str(
                donnees.get('prenom', '') or ''
            ).strip()

            nom = str(
                donnees.get('nom', '') or ''
            ).strip()

            telephone = str(
                donnees.get('telephone', '') or ''
            ).strip()

            role = str(
                donnees.get('role', '') or ''
            ).strip().lower()

            # -----------------------------
            # Prénom
            # -----------------------------

            if not prenom:
                erreurs_ligne.append("Prénom manquant")
            else:
                try:
                    prenom = valider_nom_prenom(
                        prenom,
                        "prénom"
                    )
                except serializers.ValidationError as erreur:
                    erreurs_ligne.extend(erreur.detail)

            # -----------------------------
            # Nom
            # -----------------------------

            if not nom:
                erreurs_ligne.append("Nom manquant")
            else:
                try:
                    nom = valider_nom_prenom(
                        nom,
                        "nom"
                    )
                except serializers.ValidationError as erreur:
                    erreurs_ligne.extend(erreur.detail)

            # -----------------------------
            # Téléphone
            # -----------------------------

            if not telephone:
                erreurs_ligne.append("Téléphone manquant")
            else:

                telephone, erreurs_tel = valider_telephone(
                    telephone
                )

                erreurs_ligne.extend(erreurs_tel)

            # -----------------------------
            # Rôle
            # -----------------------------

            if not role:
                erreurs_ligne.append("Rôle manquant")
            else:

                role, erreurs_role = valider_role(role)

                erreurs_ligne.extend(erreurs_role)

            membre = {
                'ligne': numero_ligne,
                'prenom': prenom,
                'nom': nom,
                'telephone': telephone,
                'role': role,
            }

            if erreurs_ligne:

                membre['erreurs'] = erreurs_ligne

                membres_invalides.append(membre)

            else:

                membres_valides.append(membre)

        return membres_valides, membres_invalides


# ==========================================================
# AFFICHAGE / MODIFICATION D'UN MEMBRE
# ==========================================================

class MembreSerializer(serializers.ModelSerializer):

    class Meta:

        model = Utilisateur

        fields = [
            'id',
            'prenom',
            'nom',
            'telephone',
            'role',
            'statut',
        ]

        # Ces champs sont visibles mais ne peuvent pas
        # être modifiés avec PATCH.
        read_only_fields = [
            'id',
        ]

    def validate_prenom(self, valeur):
        return valider_nom_prenom(
            valeur,
            "prénom"
        )

    def validate_nom(self, valeur):
        return valider_nom_prenom(
            valeur,
            "nom"
        )

    def validate_telephone(self, valeur):

        telephone = str(valeur).strip()

        # Pendant une modification, le numéro actuel
        # appartient déjà à l'utilisateur.
        utilisateur = self.instance

        requete = Utilisateur.objects.filter(
            telephone=telephone
        ).exclude(
            id=utilisateur.id
        )

        if not re.match(
            FORMAT_TELEPHONE,
            telephone
        ):
            raise serializers.ValidationError(
                "Format de téléphone invalide."
            )

        if requete.exists():
            raise serializers.ValidationError(
                "Ce numéro de téléphone est déjà utilisé."
            )

        return telephone