# MindMargin — Deployment Report

**Date:** 2026-07-03
**Status:** ✅ Deployment infrastructure configured

---

## Docker Architecture

### Images

| Image | Base | Purpose | Exposed Ports |
|-------|------|---------|---------------|
| `mindmargin-api` | python:3.12-slim | FastAPI REST server | 8000 |
| `mindmargin-worker` | python:3.12-slim | Background pipeline runner | none |
| `mindmargin-cli` | python:3.12-slim | CLI tool (interactive) | none |

### Services (docker-compose.yml)

| Service | Image | Ports | Volumes |
|---------|-------|-------|---------|
| `redis` | redis:7-alpine | 6379 | redis_data |
| `ollama` | ollama/ollama:latest | 11434 | ollama_data |
| `api` | mindmargin-api | 8000 | output, data, config |
| `worker` | mindmargin-worker | — | output, data, config |

### Production Additions (docker-compose.prod.yml)

| Service | Image | Ports | Notes |
|---------|-------|-------|-------|
| `nginx` | nginx:alpine | 80, 443 | Reverse proxy, 500M upload limit |

---

## Environment Configuration

### Required Environment Variables

| Variable | Dev Default | Production |
|----------|-------------|------------|
| `ENVIRONMENT` | `development` | `production` |
| `OLLAMA_BASE_URL` | `http://ollama:11434` | `http://ollama:11434` |
| `LLM_MODEL` | `qwen2.5:0.5b` | `qwen2.5:0.5b` |
| `REDIS_URL` | `redis://redis:6379/0` | `redis://redis:6379/0` |
| `LOG_LEVEL` | `DEBUG` | `INFO` |
| `DEBUG` | `true` | `false` |

### Secrets (not in compose — must be injected)

| Secret | Purpose |
|--------|---------|
| `YOUTUBE_TOKEN_B64` | YouTube OAuth token |
| `CLIENT_SECRETS` | Google OAuth client secrets |
| `TELEGRAM_BOT_TOKEN` | Failure notifications |
| `TELEGRAM_CHAT_ID` | Notification target |

---

## Deployment Commands

```bash
# Development
./deploy/deploy.sh dev

# Staging
./deploy/deploy.sh staging

# Production
./deploy/deploy.sh prod

# Stop all
./deploy/deploy.sh stop

# View logs
./deploy/deploy.sh logs [service]

# Status
./deploy/deploy.sh status

# Run tests
./deploy/deploy.sh test

# Build Docker images
./deploy/deploy.sh docker-build

# Push to registry
DOCKER_REGISTRY=ghcr.io/mindmargin ./deploy/deploy.sh docker-push
```

---

## Health Endpoints

| Endpoint | Purpose | Response |
|----------|---------|----------|
| `GET /health` | Liveness check | `{"status": "ok", "checks": {...}}` |
| `GET /readiness` | Readiness check | `{"status": "ready"}` |
| `GET /` | API info | `{"name": "MindMargin API", "version": "1.0.0"}` |
| `GET /docs` | Swagger UI | Interactive API docs |

---

## Resource Limits (Production)

| Service | Memory | CPU | Restart |
|---------|--------|-----|---------|
| API | 4GB | 2.0 | always |
| Worker | 4GB | 2.0 | always |
| Redis | — | — | always |
| Ollama | — | — | always |
| Nginx | — | — | always |

---

## Issues Found

1. ❌ **No SSL certs** — Production nginx references `./certs` but no cert volume exists
2. ❌ **Worker healthcheck** — Uses Python Redis check but CMD is exec form (env var won't expand)
3. ⚠️ **API binds 8000:8000 directly** — Should only be internal in production (nginx should proxy)
4. ⚠️ **No `.env` in Docker** — Secrets must be injected via GitHub Secrets or Docker secrets
5. ⚠️ **SQLite in Docker** — Shared volume mount, not suitable for concurrent access

---

## Recommendation

For GitHub Actions deployment:
1. Use `workflow_dispatch` trigger on `deploy.yml`
2. Set `environment: production`
3. Ensure SSL certs are in `deploy/docker/certs/`
4. Inject YouTube secrets via GitHub Environment secrets
5. Monitor first deployment closely
