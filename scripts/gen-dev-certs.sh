#!/usr/bin/env bash
#
# Generate a dev CA and server/client certs for mTLS testing.
# DO NOT use these in production — see infra epic for the real PKI plan.
#
set -euo pipefail

CERT_DIR="$(dirname "$0")/../infrastructure/mosquitto/certs"
mkdir -p "$CERT_DIR"
cd "$CERT_DIR"

DAYS=365
SUBJ_BASE="/C=RO/ST=Bucuresti/L=Bucuresti/O=MedicalOCR-Dev"

echo ">> Generating CA"
openssl genrsa -out ca.key 4096
openssl req -x509 -new -nodes -key ca.key -sha256 -days "$DAYS" \
  -out ca.crt -subj "${SUBJ_BASE}/CN=MedicalOCR-DevCA"

echo ">> Generating server cert (broker)"
openssl genrsa -out server.key 4096
openssl req -new -key server.key -out server.csr \
  -subj "${SUBJ_BASE}/CN=mosquitto"
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out server.crt -days "$DAYS" -sha256 \
  -extfile <(printf "subjectAltName=DNS:mosquitto,DNS:localhost,IP:127.0.0.1")

echo ">> Generating client cert: api_server"
openssl genrsa -out api_server.key 4096
openssl req -new -key api_server.key -out api_server.csr \
  -subj "${SUBJ_BASE}/CN=api_server"
openssl x509 -req -in api_server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out api_server.crt -days "$DAYS" -sha256

echo ">> Generating client cert: ocr_service"
openssl genrsa -out ocr_service.key 4096
openssl req -new -key ocr_service.key -out ocr_service.csr \
  -subj "${SUBJ_BASE}/CN=ocr_service"
openssl x509 -req -in ocr_service.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out ocr_service.crt -days "$DAYS" -sha256

echo ">> Generating client cert: device_dev_001"
openssl genrsa -out device_dev_001.key 4096
openssl req -new -key device_dev_001.key -out device_dev_001.csr \
  -subj "${SUBJ_BASE}/CN=device_dev_001"
openssl x509 -req -in device_dev_001.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out device_dev_001.crt -days "$DAYS" -sha256

# Cleanup
rm -f *.csr *.srl

chmod 600 *.key
chmod 644 *.crt

echo ""
echo "Done. Certs in $CERT_DIR"
ls -la "$CERT_DIR"
