#!/usr/bin/env bash
# Сборка Mini App для локального запуска или перед деплоем.
# Railway делает это автоматически при деплое.

set -e
cd "$(dirname "$0")/.."
echo "Building Mini App..."
cd src/web/miniapp
npm install
npm run build
echo "Done. dist/ is at src/web/miniapp/dist/"
