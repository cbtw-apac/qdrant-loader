#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

[[ -f .env ]] || cp .env.example .env
docker compose -f deploy/compose/docker-compose.dev.yml up --build
