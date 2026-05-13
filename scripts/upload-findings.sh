#!/usr/bin/env bash
# Upload SAST/DAST findings to DefectDojo after each CI run.
# Usage: ./scripts/upload-findings.sh <scan_type> <findings_file>
# Env vars required: DEFECTDOJO_URL, DEFECTDOJO_API_TOKEN, DEFECTDOJO_ENGAGEMENT_ID
set -euo pipefail

SCAN_TYPE="${1:?scan_type required}"
FILE="${2:?findings_file required}"
DOJO_URL="${DEFECTDOJO_URL:-http://localhost:8080}"
ENGAGEMENT="${DEFECTDOJO_ENGAGEMENT_ID:?DEFECTDOJO_ENGAGEMENT_ID required}"

echo "Uploading ${SCAN_TYPE} findings from ${FILE} to DefectDojo..."
response=$(curl -s -w "\n%{http_code}" -X POST \
  "${DOJO_URL}/api/v2/import-scan/" \
  -H "Authorization: Token ${DEFECTDOJO_API_TOKEN}" \
  -F "scan_type=${SCAN_TYPE}" \
  -F "file=@${FILE}" \
  -F "engagement=${ENGAGEMENT}" \
  -F "verified=true" \
  -F "active=true" \
  -F "close_old_findings=true")

http_code=$(echo "$response" | tail -n1)
body=$(echo "$response" | head -n-1)

if [[ "$http_code" -ge 200 && "$http_code" -lt 300 ]]; then
  echo "Upload successful (HTTP ${http_code})"
else
  echo "Upload failed (HTTP ${http_code}): ${body}" >&2
  exit 1
fi
