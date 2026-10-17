# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgomp1 \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Cache pip conservé entre les constructions (hors de l'image) : après une
# coupure réseau, inutile de retélécharger PaddlePaddle (plusieurs centaines de Mo).
# paddleocr réclame opencv-python et opencv-contrib-python, d'autres paquets
# opencv-python-headless : les trois s'installent dans le même dossier cv2 et
# s'écrasent. On ne garde que la version headless, prévue pour un serveur, dans
# la même étape pour que les versions retirées ne restent pas dans l'image.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --default-timeout=120 --retries 10 -r requirements.txt \
    && pip uninstall -y opencv-python opencv-contrib-python opencv-python-headless \
    && pip install --no-deps opencv-python-headless==4.11.0.86

COPY . .

RUN chmod +x entrypoint.sh

EXPOSE 8000

# Migrations, fichiers statiques puis gunicorn (voir entrypoint.sh)
CMD ["./entrypoint.sh"]
