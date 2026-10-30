#!/usr/bin/env bash
# Redeploys the whole online environment (test, prod, monitoring) on the OVH cluster.
# Run from the repository root: ./scripts/deploy-online.sh

# Strict mode: stop on the first error, forbid unset variables,
# and catch errors inside pipes (|).
set -euo pipefail

# kubectl context of the OVH cluster. Defined once, used everywhere.
CONTEXT="team1@cluster-sc"

echo "==> Checking context $CONTEXT"
# Fails (and stops the script thanks to set -e) if the context does not exist.
# > /dev/null hides the output: we only care whether it succeeds.
kubectl config get-contexts "$CONTEXT" > /dev/null

echo "==> Deploying test environment"
kubectl --context "$CONTEXT" apply -k manifests/overlays/online-test

echo "==> Deploying prod environment"
kubectl --context "$CONTEXT" apply -k manifests/overlays/online-prod

echo "==> Deploying monitoring"
kubectl --context "$CONTEXT" apply -k manifests/monitoring

echo "==> Waiting for all deployments to be ready"
# Loop: run the same command for each Deployment in the list.
for deployment in photo-service-test photo-service-prod prometheus; do
  kubectl --context "$CONTEXT" rollout status "deployment/$deployment" --timeout=180s
done

echo "==> Everything is deployed ✅"
echo "    Prod: http://team1.laboinfo-ecam.be"