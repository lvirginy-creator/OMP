#!/usr/bin/env bash
# Déploiement inventaireOMP : à lancer sur le serveur (via SSH), depuis le
# dossier cloné du dépôt, à côté du docker-compose.yml et du .env de prod.
set -euo pipefail

cd "$(dirname "$0")"

BRANCH="main"

echo "==> [$(date '+%Y-%m-%d %H:%M:%S')] Vérification de l'arbre de travail"
if [ -n "$(git status --porcelain)" ]; then
  echo "Erreur : des modifications locales non commitées existent sur le serveur." >&2
  echo "Résous-les (git stash / git checkout) avant de redéployer." >&2
  exit 1
fi

if [ ! -f .env ]; then
  echo "Erreur : fichier .env introuvable (ANTHROPIC_API_KEY, etc.)." >&2
  exit 1
fi

echo "==> Récupération du code depuis GitHub ($BRANCH)"
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git merge --ff-only "origin/$BRANCH"

echo "==> Build de l'image"
docker compose build

echo "==> Redémarrage du conteneur"
docker compose up -d

echo "==> Nettoyage des images Docker obsolètes"
docker image prune -f

echo "==> Statut"
docker compose ps

echo "==> Terminé."
