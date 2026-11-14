#!/usr/bin/env bash
# Copies each production shard into the matching test shard, then anonymizes it.
set -euo pipefail

for shard in 0 1; do
  prod_var="PROD_URL_$shard"
  test_var="TEST_URL_$shard"
  prod_url="${!prod_var}"
  test_url="${!test_var}"

  echo "==> Shard $shard: copying production into test"
  pg_dump "$prod_url" --clean --if-exists --no-owner | psql "$test_url" --quiet

  echo "==> Shard $shard: anonymizing"
  psql "$test_url" -v ON_ERROR_STOP=1 -v shard="$shard" <<'SQL'
UPDATE users u
SET username = (
  SELECT 'user_' || u.id || '_' || n
  FROM generate_series(0, 100) AS n
  WHERE get_byte(sha256(convert_to('user_' || u.id || '_' || n, 'UTF8')), 0) % 2 = :shard
  LIMIT 1
);

UPDATE photos
SET filename = 'photo_' || id || coalesce(substring(filename from '\.[A-Za-z0-9]+$'), '');
SQL
psql "$test_url" -c "SELECT username FROM users;"
done
echo "==> Test databases refreshed"