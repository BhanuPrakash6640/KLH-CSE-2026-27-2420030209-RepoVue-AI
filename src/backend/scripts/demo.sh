#!/usr/bin/env bash
# End-to-end demo: register a repo, run an analysis, print the findings.
set -euo pipefail

API="${REPOVUE_URL:-http://localhost:8000}/api/v1"
KEY="${REPOVUE_API_KEY:-dev-local-key}"
TARGET="${1:-https://github.com/pallets/flask}"

echo "==> Health"
curl -sS "$API/health" -H "X-API-Key: $KEY" | jq .

echo "==> Queueing analysis for $TARGET"
ID=$(curl -sS -X POST "$API/analyses" \
  -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d "{\"url\":\"$TARGET\",\"diff_only\":false,\"open_pr\":false}" | jq -r .id)
echo "analysis_id=$ID"

echo "==> Waiting"
while true; do
  A=$(curl -sS "$API/analyses/$ID" -H "X-API-Key: $KEY")
  printf "\r%-12s %3s%%" "$(echo "$A" | jq -r .stage)" "$(echo "$A" | jq -r .progress)"
  S=$(echo "$A" | jq -r .status)
  [ "$S" = "succeeded" ] || [ "$S" = "failed" ] && break
  sleep 5
done
echo

echo "==> Summary"
curl -sS "$API/analyses/$ID/summary" -H "X-API-Key: $KEY" | jq '{stats:.analysis.stats, by_severity:.findings_by_severity, by_category:.findings_by_category, top_files:.top_files}'

echo "==> Quality gate (what CI polls)"
curl -sS "$API/analyses/$ID/gate?fail_on=high" -H "X-API-Key: $KEY" \
  | jq '{complete, passed, blocking_findings, counts}'

echo "==> Top findings"
curl -sS "$API/findings?analysis_id=$ID&limit=10" -H "X-API-Key: $KEY" \
  | jq -r '.items[] | "[\(.severity)] \(.title)\n    \(.path):\(.start_line)  \(.cwe // "")\n"'

echo "==> Open it"
echo "    ${REPOVUE_WEB:-http://localhost:3000}/analyses/$ID"
