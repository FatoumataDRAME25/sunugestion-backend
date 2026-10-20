# Écrite à la main : RenameField renomme la colonne (ALTER TABLE ... RENAME
# COLUMN) et garde son contenu, là où makemigrations peut générer une
# suppression suivie d'un ajout si le renommage n'est pas confirmé.

import authentication.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('authentication', '0008_expiration_invitations_existantes'),
    ]

    operations = [
        migrations.RenameField(
            model_name='gie',
            old_name='photo',
            new_name='logo',
        ),
        migrations.AlterField(
            model_name='gie',
            name='logo',
            field=models.ImageField(blank=True, null=True, upload_to=authentication.models.chemin_logo_gie),
        ),
    ]
