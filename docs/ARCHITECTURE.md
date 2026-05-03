# Architecture Overview

This document describes the runtime architecture of the medical OCR platform.

## High-level diagram

```
                            ┌──────────────────┐
                            │   Edge devices   │
                            │ (ESP32, mobile)  │
                            └────────┬─────────┘
                                     │ mTLS over MQTT (TLSv1.3)
                                     │ topic: medical/images/{id}/upload
                                     ▼
                            ┌──────────────────┐
                            │     Mosquitto    │
                            │   (TLS-only,     │
                            │    ACL, limits)  │
                            └────────┬─────────┘
                                     │ subscribe (api_server cert)
                                     ▼
                ┌────────────────────────────────────┐
                │           API service              │
                │  ┌──────────────────────────────┐  │
                │  │  body-size middleware (413)  │  │
                │  ├──────────────────────────────┤  │
                │  │  rate limiter (slowapi)      │  │
                │  ├──────────────────────────────┤  │
                │  │  RBAC (Auth epic)            │  │
                │  ├──────────────────────────────┤  │
                │  │  routes / MQTT consumer      │  │
                │  └──────────────┬───────────────┘  │
                └─────────────────┼──────────────────┘
                       ┌──────────┼──────────┐
                       │          │          │
              shared volume       │     internal TLS
              (OCR queue)         │          │
                       │          │          ▼
                       ▼          │   ┌────────────┐
              ┌────────────────┐  │   │ PostgreSQL │
              │  OCR worker    │  │   │ (PHI       │
              │  ───────────   │  │   │ encrypted  │
              │  distroless    │  │   │ at rest)   │
              │  no network    │  │   └────────────┘
              │  no privileges │  │
              │  read-only fs  │  │
              └────────┬───────┘  │
                       │          │
                       └──────────┘
                       MQTT publish:
                  medical/ocr/{id}/results
```

## Trust zones

The system has four trust zones, in order of decreasing trust:

1. **Internal trusted** — API service, database. Holds plaintext PHI in memory during processing. Behind the firewall.
2. **Sandbox** — OCR worker. Processes attacker-controlled bytes. Isolated by container, network, filesystem, and user.
3. **Edge devices** — Mobile apps, ESP32 cameras. Authenticated via certificates but assume any individual device may be compromised.
4. **Untrusted** — anything else (the open internet, the operator's laptop on a hotel WiFi).

Communication crossing a trust boundary is mTLS-authenticated and authorized via the broker ACL or the API RBAC.

## Why a queue between API and OCR?

The OCR engine is a synchronous, CPU-bound, attacker-exposed component. Putting a queue between it and the API:

- **Decouples timing.** A slow OCR doesn't stall the HTTP server.
- **Limits blast radius.** If OCR crashes (which is more likely than other components — bad image bytes), the API stays up and queues retries.
- **Enables horizontal scaling.** Multiple OCR workers can drain the queue in parallel.
- **Makes audit easier.** Every job is a file (or a Redis stream entry) with a stable ID, traceable end-to-end.

## Data flow for a single image

1. Device captures image, signs MQTT publish with its client cert.
2. Mosquitto verifies cert against CA, looks up CN in ACL, accepts publish to `medical/images/{cn}/upload`.
3. API service (subscribed) receives message, validates topic regex, creates `Document` row in PostgreSQL with `status=queued`.
4. API writes job manifest + image bytes to OCR queue (shared volume).
5. OCR worker picks up job, validates image (PIL `verify()` + size check), runs OCR.
6. Worker extracts fields, applies confidence gate (≥ 0.95), builds `OCRResult` JSON.
7. Worker writes `<doc_id>.result.json` to the shared queue volume.
8. API result poller (background task, 2s interval) reads the result file, calls `store.attach_ocr_result()`, deletes the file. Document status becomes `pending_review` (confidence < 0.95 on any field) or `completed`.
9. Doctor (via dashboard) queries `GET /api/v1/review-queue`, reviews flagged items, submits correction via `POST /api/v1/review-queue/{id}/resolve` → status set to `completed`.

## Failure modes & mitigations

| Failure | Mitigation |
|---------|-----------|
| Malicious image triggers libpng RCE | OCR sandbox: no network, read-only fs, dropped caps, distroless |
| Device certificate stolen | Per-device ACL restricts to that device's topics; revoke + reissue cert |
| DoS via huge image upload | Broker `message_size_limit` + API `Content-Length` middleware + streaming size check |
| DoS via request flood | Per-IP and per-user slowapi rate limits |
| OCR engine returns garbage | Confidence threshold (≥95%) routes to manual review |
| DB compromise leaks PHI | Column-level encryption at rest (DB epic owns key rotation) |
| AI agent goes rogue (CI epic) | MCP capability gateway, outbound quarantine, human approval gate |

## What's intentionally out of scope

- **End-to-end encryption** of images on the device. The threat model here trusts the broker because it's controlled by the operator.
- **Patient consent management.** Out of scope for v1; assumes operator is compliant via process.
- **HIPAA/GDPR audit log retention policy.** Compliance team needs to set the retention window.
