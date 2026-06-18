# Image de production pour Hugging Face Spaces (SDK Docker, port 7860).
FROM python:3.11-slim

# Hugging Face exécute le conteneur avec un utilisateur non-root (uid 1000).
RUN useradd -m -u 1000 user

WORKDIR /app

# Dépendances d'abord (cache de build).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code applicatif. On donne la propriété de tout /app à l'utilisateur non-root
# (le dossier /app créé par WORKDIR appartient à root, sinon écriture impossible).
COPY . .
RUN chown -R user:user /app

USER user
ENV HOME=/home/user \
    PYTHONUNBUFFERED=1

# Génère la base de démonstration buggée au build.
RUN python scripts/make_demo_db.py

EXPOSE 7860
CMD ["uvicorn", "dbughunter.webapp:app", "--host", "0.0.0.0", "--port", "7860"]
