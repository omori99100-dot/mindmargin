#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEPLOY_DIR="$REPO_ROOT/deploy/docker"

usage() {
    echo "Usage: $0 <command> [environment]"
    echo ""
    echo "Commands:"
    echo "  dev          Start development environment"
    echo "  staging      Start staging environment"
    echo "  prod         Start production environment"
    echo "  stop         Stop all services"
    echo "  logs         Show service logs"
    echo "  status       Show service status"
    echo "  test         Run full test suite"
    echo "  docker-build Build Docker images"
    echo "  docker-push  Push images to registry"
    echo ""
    echo "Examples:"
    echo "  $0 dev                # Start dev environment"
    echo "  $0 prod               # Start production"
    echo "  $0 logs api           # Show API logs"
    echo "  $0 stop               # Stop everything"
}

cmd_dev() {
    echo "Starting development environment..."
    cd "$DEPLOY_DIR"
    docker compose up -d --build
    echo ""
    echo "Waiting for API to be ready..."
    for i in $(seq 1 30); do
        if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
            echo "✅ API ready at http://localhost:8000"
            echo "📖 Docs at http://localhost:8000/docs"
            return 0
        fi
        sleep 2
    done
    echo "❌ API failed to start. Check logs: $0 logs api"
    return 1
}

cmd_staging() {
    echo "Starting staging environment..."
    cd "$DEPLOY_DIR"
    docker compose -f docker-compose.staging.yml up -d --build
    echo "✅ Staging environment started"
}

cmd_prod() {
    echo "Starting production environment..."
    cd "$DEPLOY_DIR"
    docker compose -f docker-compose.prod.yml up -d --build
    echo "✅ Production environment started"
    echo ""
    echo "Waiting for services..."
    for i in $(seq 1 30); do
        if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
            echo "✅ API ready"
            return 0
        fi
        sleep 2
    done
    echo "⚠️  API not yet ready. Check logs."
}

cmd_stop() {
    echo "Stopping all services..."
    cd "$DEPLOY_DIR"
    docker compose down 2>/dev/null || true
    docker compose -f docker-compose.staging.yml down 2>/dev/null || true
    docker compose -f docker-compose.prod.yml down 2>/dev/null || true
    echo "✅ All services stopped"
}

cmd_logs() {
    local service="${1:-}"
    cd "$DEPLOY_DIR"
    if [ -n "$service" ]; then
        docker compose logs -f "$service"
    else
        docker compose logs -f
    fi
}

cmd_status() {
    cd "$DEPLOY_DIR"
    echo "=== Service Status ==="
    docker compose ps 2>/dev/null || echo "No dev services running"
    echo ""
    docker compose -f docker-compose.staging.yml ps 2>/dev/null || true
    echo ""
    docker compose -f docker-compose.prod.yml ps 2>/dev/null || true
}

cmd_test() {
    echo "Running full test suite..."
    cd "$REPO_ROOT"
    python -m pytest tests/ -q --tb=short --timeout=60
}

cmd_docker_build() {
    echo "Building Docker images..."
    cd "$REPO_ROOT"
    docker build -f deploy/docker/Dockerfile.api -t mindmargin-api:latest .
    docker build -f deploy/docker/Dockerfile.worker -t mindmargin-worker:latest .
    docker build -f deploy/docker/Dockerfile.cli -t mindmargin-cli:latest .
    echo "✅ All images built"
}

cmd_docker_push() {
    local registry="${DOCKER_REGISTRY:-ghcr.io/mindmargin}"
    local tag="${DOCKER_TAG:-latest}"
    echo "Pushing images to $registry..."
    docker tag mindmargin-api:latest "$registry/api:$tag"
    docker tag mindmargin-worker:latest "$registry/worker:$tag"
    docker push "$registry/api:$tag"
    docker push "$registry/worker:$tag"
    echo "✅ Images pushed"
}

case "${1:-}" in
    dev)         cmd_dev ;;
    staging)     cmd_staging ;;
    prod)        cmd_prod ;;
    stop)        cmd_stop ;;
    logs)        cmd_logs "${2:-}" ;;
    status)      cmd_status ;;
    test)        cmd_test ;;
    docker-build) cmd_docker_build ;;
    docker-push) cmd_docker_push ;;
    *)           usage ;;
esac
