#!/usr/bin/env bash
# Smoke check for a deployed storage service, through the shared API and against
# its real provider. It writes one small file, reads it back, deletes it, and
# fails on the first step that does not behave as documented.
#
#   deploy/smoke-check.sh https://ds.packapunch.xyz
set -euo pipefail

base=${1:?usage: deploy/smoke-check.sh BASE_URL}
base=${base%/}
key="smoke-check/$(date -u +%Y%m%dT%H%M%SZ)-$RANDOM.txt"
work=$(mktemp -d)
expected="smoke check for $base at $(date -u +%FT%TZ)"
printf '%s' "$expected" > "$work/upload.txt"

# Remove the test file even when a step fails halfway, so the bucket stays clean.
cleanup() {
  curl -sS -o /dev/null -X DELETE "$base/files?path=$key" || true
  rm -rf "$work"
}
trap cleanup EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }
status() { curl -sS -o "$work/body" -w '%{http_code}' "$@" || echo 000; }

echo "Waiting for $base/health"
for attempt in $(seq 1 24); do
  [ "$(status --max-time 5 "$base/health")" = 200 ] && break
  [ "$attempt" = 24 ] && fail "/health did not return 200 within 2 minutes"
  sleep 5
done
echo "ok   GET /health"

code=$(status "$base/health/provider")
[ "$code" = 200 ] || fail "GET /health/provider returned $code: $(cat "$work/body")"
echo "ok   GET /health/provider"

code=$(status -X POST --form-string "path=$key" -F "file=@$work/upload.txt;type=text/plain" "$base/files")
[ "$code" = 201 ] || fail "POST /files returned $code: $(cat "$work/body")"
echo "ok   POST /files ($key)"

code=$(status "$base/files/download?path=$key")
[ "$code" = 200 ] || fail "GET /files/download returned $code: $(cat "$work/body")"
[ "$(cat "$work/body")" = "$expected" ] || fail "downloaded bytes differ from the upload"
echo "ok   GET /files/download (same bytes)"

code=$(status -X DELETE "$base/files?path=$key")
[ "$code" = 204 ] || fail "DELETE /files returned $code: $(cat "$work/body")"
echo "ok   DELETE /files"

code=$(status "$base/files/download?path=$key")
[ "$code" = 404 ] || fail "the file is still readable after delete (status $code)"
echo "ok   GET /files/download after delete returns 404"

echo "Smoke check passed for $base"
