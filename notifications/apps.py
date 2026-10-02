import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class NotificationsConfig(AppConfig):
    name = 'notifications'

    def ready(self):
        """
        Initialise Firebase Admin SDK au démarrage de Django.
        Appelé une seule fois quand toutes les apps sont chargées.
        """
        import os
        import firebase_admin
        from firebase_admin import credentials
        from django.conf import settings

        # Évite la double initialisation en cas de rechargement (ex: runserver)
        if firebase_admin._apps:
            return

        credentials_path = settings.FIREBASE_CREDENTIALS_PATH

        if not credentials_path or not os.path.exists(credentials_path):
            logger.warning(
                "Firebase Admin SDK : fichier de credentials introuvable à '%s'. "
                "Les notifications push ne fonctionneront pas.",
                credentials_path
            )
            return

        try:
            cred = credentials.Certificate(credentials_path)
            firebase_admin.initialize_app(cred)
            logger.info("Firebase Admin SDK initialisé avec succès.")
        except Exception as exc:
            logger.error("Échec de l'initialisation de Firebase Admin SDK : %s", exc)
