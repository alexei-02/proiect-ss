#!/usr/bin/env bash
# Build and tag all service Docker images with the current git SHA.
# Usage: ./scripts/build-images.sh [registry_prefix]
# Example: ./scripts/build-images.sh ghcr.io/myorg
set -euo pipefail

REGISTRY="${1:-}"
TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD)}"

build_image() {
  local name="$1"
  local context="$2"
  local dockerfile="$3"
  local full_name="${REGISTRY:+${REGISTRY}/}${name}:${TAG}"
  echo "Building ${full_name}..."
  docker build -t "${full_name}" -f "${context}/${dockerfile}" "${context}"
  if [[ -n "$REGISTRY" ]]; then
    docker push "${full_name}"
    echo "Pushed ${full_name}"
  fi
}

build_image "medical-ocr-api"      "services/api"      "Dockerfile"
build_image "medical-ocr-worker"   "services/ocr"      "Dockerfile.ocr"
build_image "medical-ocr-frontend" "services/frontend" "Dockerfile"

echo "All images built with tag: ${TAG}"
