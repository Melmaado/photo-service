#!/usr/bin/env bash
# Redeploys the whole online environment (test, prod, monitoring) on the OVH cluster.
# Usage, from the repository root: ./scripts/deploy-online.sh <image-tag>
# Example: ./scripts/deploy-online.sh "$(git rev-parse HEAD)"
set -euo pipefail

CONTEXT="team1@cluster-sc"
TAG="${1:?Usage: $0 <image-tag>}"
IMAGE="ghcr.io/melmaado/photo-service:$TAG"

echo "==> Checking context and secret"
kubectl config get-contexts "$CONTEXT" > /dev/null
kubectl --context "$CONTEXT" -n team1 get secret photo-secrets > /dev/null

# Restore the overlays when the script ends, even after an error.
trap 'git checkout -- manifests/overlays/online-test manifests/overlays/online-prod' EXIT

for env in test prod; do
  echo "==> Deploying $env with $IMAGE"
  (cd "manifests/overlays/online-$env" && kustomize edit set image "photo-service=$IMAGE")
  kubectl --context "$CONTEXT" apply -k "manifests/overlays/online-$env"
done

echo "==> Deploying monitoring"
kubectl --context "$CONTEXT" apply -k manifests/monitoring

echo "==> Waiting for all deployments to be ready"
for deployment in photo-service-test photo-service-prod prometheus grafana; do
  kubectl --context "$CONTEXT" -n team1 rollout status "deployment/$deployment" --timeout=300s
done

echo "==> Everything is deployed"
echo "    Test:    http://team1.laboinfo-ecam.be/test"
echo "    Prod:    http://team1.laboinfo-ecam.be"
echo "    Grafana: http://team1.laboinfo-ecam.be/grafana"