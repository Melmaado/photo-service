#!/usr/bin/env bash
# Sends traffic to prod for the monitoring demo.
# Usage: ./scripts/load.sh [number_of_requests]

set -euo pipefail

URL="http://team1.laboinfo-ecam.be/"
REQUESTS="${1:-300}"

echo "==> Sending $REQUESTS requests to $URL"
for i in $(seq 1 "$REQUESTS"); do
  curl -s "$URL" > /dev/null
  sleep 0.2
done
echo "==> Done ✅"