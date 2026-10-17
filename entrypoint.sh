#!/bin/sh
# Démarrage du conteneur backend : attend PostgreSQL, applique les migrations,
# prépare les fichiers statiques, puis lance gunicorn (ou la commande fournie).
set -e

echo "Attente de PostgreSQL (${DB_HOST}:${DB_PORT})..."
python - <<'PY'
import os
import sys
import time

import psycopg2

for tentative in range(30):
    try:
        psycopg2.connect(
            dbname=os.environ['DB_NAME'],
            user=os.environ['DB_USER'],
            password=os.environ['DB_PASSWORD'],
            host=os.environ['DB_HOST'],
            port=os.environ['DB_PORT'],
        ).close()
        sys.exit(0)
    except psycopg2.OperationalError:
        time.sleep(2)

print("PostgreSQL injoignable après 60 secondes.", file=sys.stderr)
sys.exit(1)
PY

python manage.py migrate --noinput

# Commande fournie (mode développement : runserver) : lancée à la place de
# gunicorn, sans collectstatic, inutile avec DEBUG=True
if [ "$#" -gt 0 ]; then
    exec "$@"
fi

python manage.py collectstatic --noinput

# Délai de 120 s : l'analyse IA et l'OCR peuvent prendre plusieurs dizaines
# de secondes ; les threads évitent qu'une analyse bloque toute l'API.
exec gunicorn sunugestion.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-2}" \
    --threads "${GUNICORN_THREADS:-4}" \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
