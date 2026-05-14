# Threat Analysis & Risk Assessment (TARA)

## Document Control

| Field            | Value                                      |
|------------------|--------------------------------------------|
| Version          | 1.0                                        |
| Date             | 2026-05-06                                 |
| Authors          | Alexandru-Cristian Vidu                    |
| Review cycle     | Every 6 months, or after any security incident or material architecture change |
| Classification   | Internal — do not distribute externally    |
| Next review      | 2026-11-06                                 |

---

## 1. Scope & System Description

### 1.1 System purpose

The Medical OCR Platform ingests prescription images from IoT edge devices (clinical scanners) via MQTT over mTLS, extracts structured PHI fields (patient name, medication, expiry date) using an OCR engine, and serves the results through a REST API for clinical review. A Next.js frontend provides the doctor review workflow.

### 1.2 Regulatory context

The system processes Protected Health Information (PHI) as defined by HIPAA (45 CFR §164). Key obligations:
- PHI at rest must be encrypted (AES-256-GCM; see `docs/PHI_FIELDS.md`).
- Access must be role-based and auditable (see `docs/RBAC.md`).
- Minimum-necessary principle applies to all data exposures.
- Unauthorized disclosure of PHI carries civil and criminal liability.

This platform is not itself a Software as a Medical Device (SaMD) but processes data that feeds clinical decisions; therefore a TARA is required under the project's security framework and is informed by IEC 62443-3-3 and OWASP ASVS L2.

### 1.3 In scope

- MQTT broker (`infrastructure/mosquitto/`)
- FastAPI REST API (`services/api/`)
- OCR worker (`services/ocr/`)
- PostgreSQL database (PHI store)
- Next.js frontend (`services/frontend/`)
- Docker host and container runtime
- CI/CD pipeline (GitHub Actions — owned by CI/CD epic)
- Shared OCR queue volume (`/queue`)
- mTLS PKI (`infrastructure/mosquitto/certs/`, `scripts/gen-dev-certs.sh`)

### 1.4 Out of scope

- End-user workstations and browsers
- Network infrastructure (routers, firewalls) operated by the deploying hospital
- DICOM imaging equipment beyond the MQTT publish interface
- Cloud provider IAM and physical data-centre security

---

## 2. Assets

| Asset | Type | Confidentiality req. | Integrity req. | Availability req. |
|-------|------|----------------------|----------------|-------------------|
| Patient name, medication, expiry date (PHI fields) | PHI | Critical — HIPAA breach if disclosed | High — wrong medication is patient-safety critical | High — clinical workflow depends on timely results |
| AES-256-GCM encryption key (`phi_master_key`) | Cryptographic key | Critical — compromise renders all PHI at rest accessible | Critical — corruption breaks decryption for all records | Medium — recoverable from backup |
| JWT signing secret (`jwt_secret`) | Credential | Critical — allows forging auth tokens for any user | Critical | Medium — rotation invalidates all active sessions |
| Per-device mTLS client certificates | PKI credential | High — private key allows impersonating a device | High | Medium — revocation via Mosquitto ACL update |
| Mosquitto CA private key | PKI root | Critical — allows issuing trusted device certs | Critical | Low — only needed for cert issuance |
| PostgreSQL database (`medical_ocr`) | PHI data store | Critical | Critical | High |
| OCR result JSONB data (in-transit and in-DB) | PHI derivative | High | High | Medium |
| Audit log | Compliance record | Medium — internal | Critical — must be tamper-evident | High — required for incident response |
| Docker images (API, OCR, frontend) | Supply chain | Medium | High — malicious code injection | High |
| API source code | Intellectual property / attack surface | Low | Medium | N/A |
| Mosquitto ACL configuration (`acl.conf`) | Access control policy | Medium | Critical — misconfiguration opens MQTT to unauthorised devices | High |
| JWT `initial_admin_password` | Credential | Critical until rotated | High | Low — one-time use |

---

## 3. Threat Actors

| Actor | Capability | Motivation | Example TTPs |
|-------|------------|------------|--------------|
| External attacker (opportunistic) | Low — commodity tools, automated scanners | Financial (ransomware, PHI resale) | Port scanning, credential stuffing, CVE exploitation of public-facing services |
| External attacker (targeted, nation-state / organised crime) | High — zero-days, custom tooling, long dwell time | State espionage, large-scale PHI theft, insurance fraud | Spear-phishing developers, supply-chain compromise (malicious PyPI packages), TLS interception via forged certificates |
| Malicious insider (e.g. rogue receptionist) | Medium — legitimate credentials, knowledge of system layout | Personal gain, coercion, disgruntlement | Bulk PHI export via API, privilege escalation via RBAC misconfiguration, log deletion |
| Compromised edge device | Medium — firmware RCE, physical access | Pivot point into internal MQTT network, PHI exfiltration, bogus prescription injection | Replay of captured MQTT payloads, certificate reuse after key extraction, image tampering to inject false OCR results |
| Supply chain attacker | Medium to High — targets upstream dependencies | Persistent access, mass-scale compromise | Typosquatting PyPI/npm packages, backdoored base Docker images (eclipse-mosquitto, postgres), malicious GitHub Action |

---

## 4. Attack Surface

| Entry point | Protocol / Auth | Network zone | Notes |
|-------------|----------------|--------------|-------|
| MQTT port 8883 | MQTT over TLS 1.3, per-device mTLS | edge → internal | Only reachable by devices with a CA-signed cert; ACL deny-by-default (`acl.conf`) |
| REST API port 8989 | HTTPS, JWT Bearer | untrusted → frontend | Rate-limited (3/min upload, 100/min default); body-size capped at 10 MB (`middleware.py`) |
| Next.js frontend port 3000 | HTTPS | untrusted | Server-side rendered; calls API on behalf of user |
| Prisma Studio port 5555 | HTTP (no auth) | dev only | **MUST NOT be exposed in production**; absent from `docker-compose.prod.yml` |
| Shared OCR queue volume | Filesystem (Docker volume) | internal | API writes `.job.json`; OCR worker reads jobs, writes `.result.json`; API result-poller consumes results |
| PostgreSQL port 5432 | TCP, password auth | api-internal network only | Not exposed on host in prod compose; internal Docker network only |
| Docker daemon socket | Unix socket / TCP | host | Full root-equivalent access; must not be bind-mounted into any container |
| CI/CD pipeline (GitHub Actions) | GitHub OIDC / secrets | cloud | Builds and pushes Docker images; has access to registry credentials |
| Developer workstations | Various | untrusted | Source of `git push`; can introduce backdoors or secrets in commits |

---

## 5. Threat Scenarios

### 5.1 Edge Devices → Mosquitto (mTLS)

| ID | Threat | STRIDE | Likelihood | Impact | Risk Score | Mitigations | Residual Risk |
|----|--------|--------|------------|--------|------------|-------------|---------------|
| T-01 | Attacker replays a captured MQTT image payload from a previously valid session | Spoofing | 2 | 3 | 6 Medium | TLS session keys are ephemeral (forward secrecy); mTLS verifies device identity per-connection; MQTT QoS and message IDs are monotonic | Low (2) |
| T-02 | Attacker extracts private key from a physical device and impersonates it | Spoofing | 2 | 4 | 8 Medium | Per-device certs with short validity; certificate revocation via Mosquitto ACL `deny` for the device CN; hardware security modules recommended for prod devices | Low–Medium (4) |
| T-03 | Compromised device publishes malformed or oversized images to cause API DoS | Denial of Service | 3 | 3 | 9 Medium | `BodySizeLimitMiddleware` caps uploads at 10 MB; OCR worker validates image with PIL before processing; MQTT ACL restricts topics per device | Low (3) |
| T-04 | Attacker MitMs the TLS connection to inject a modified prescription image | Tampering | 1 | 5 | 5 Medium | TLS 1.3 with server cert pinnable on devices; mTLS mutual authentication; cert-based ACL prevents unauthorised publishers | Low (2) |
| T-05 | Compromised device publishes to a topic it is not authorised for (e.g., `medical/ocr/#`) | Elevation of Privilege | 2 | 3 | 6 Medium | `acl.conf` deny-by-default; explicit per-CN publish grants only to `medical/images/{device_id}/upload` | Low (2) |

### 5.2 Mosquitto → API (internal MQTT)

| ID | Threat | STRIDE | Likelihood | Impact | Risk Score | Mitigations | Residual Risk |
|----|--------|--------|------------|--------|------------|-------------|---------------|
| T-06 | Attacker compromises Mosquitto container and forges MQTT messages to the API consumer | Spoofing | 1 | 4 | 4 Low | Internal Docker network `mqtt-internal` is not reachable from host or other networks; API validates message schema (`schemas/ocr.py`) | Low (2) |
| T-07 | API consumer processes malicious MQTT payload leading to code injection | Tampering | 2 | 4 | 8 Medium | Strict Pydantic schema validation on every inbound message; no `eval`/`exec` in consumer code; SAST (Bandit) scans for injection patterns | Low (3) |
| T-08 | Flood of internal MQTT messages exhausts API consumer threads | Denial of Service | 2 | 3 | 6 Medium | MQTT topic ACLs limit inbound rate to number of enrolled devices; API result poller is independent of MQTT consumer; services can be restarted independently | Low (2) |

### 5.3 REST API layer

| ID | Threat | STRIDE | Likelihood | Impact | Risk Score | Mitigations | Residual Risk |
|----|--------|--------|------------|--------|------------|-------------|---------------|
| T-09 | Unauthenticated user accesses PHI via `/api/v1/documents` | Information Disclosure | 3 | 5 | 15 Critical | JWT Bearer token required on all document/review routes (`security.py`); `DEV_AUTH_BYPASS` must be `false` in prod; RBAC enforced per route | Medium (5) — residual if JWT secret is weak |
| T-10 | Authenticated user with `receptionist` role accesses doctor-only review endpoints | Elevation of Privilege | 2 | 4 | 8 Medium | RBAC decorator on every route checks role; four roles: admin, doctor, receptionist, auditor; roles are claim-bound in JWT | Low (2) |
| T-11 | Attacker uploads 100 MB images to exhaust disk/memory | Denial of Service | 3 | 3 | 9 Medium | `BodySizeLimitMiddleware` returns 413 for requests >10 MB; rate limiter (slowapi) 3/min on `/documents/upload` | Low (2) |
| T-12 | JWT secret brute-force or weak secret allows token forgery | Spoofing | 2 | 5 | 10 High | `jwt_secret` loaded from Docker secret file in prod; validation requires both `aud` and `iss` claims; HS256 with ≥256-bit secret; `_read_secret` in `config.py` reads from `/run/secrets/jwt_secret` | Low–Medium (4) |
| T-13 | Verbose error messages leak internal stack traces or DB connection strings | Information Disclosure | 3 | 3 | 9 Medium | FastAPI `debug=False` in production; `ENV=production` suppresses stack traces; error handlers return generic messages | Low (2) |
| T-14 | SSRF via user-supplied URLs in API requests | Information Disclosure | 1 | 4 | 4 Low | API does not make outbound HTTP calls based on user input; internal network not reachable from API egress in prod | Low (1) |

### 5.4 OCR Worker (sandboxed)

| ID | Threat | STRIDE | Likelihood | Impact | Risk Score | Mitigations | Residual Risk |
|----|--------|--------|------------|--------|------------|-------------|---------------|
| T-15 | Malicious image exploits a vulnerability in EasyOCR/PIL to achieve RCE | Elevation of Privilege | 2 | 4 | 8 Medium | OCR container: `read_only: true`, `cap_drop: ALL`, `no-new-privileges:true`, no network egress, `tmpfs` with `noexec,nosuid`; distroless base image minimises attack surface; SAST on OCR code | Low–Medium (4) |
| T-16 | Attacker writes a malicious `.result.json` to the queue volume to inject false OCR output | Tampering | 2 | 4 | 8 Medium | Result poller validates JSON schema with Pydantic before writing to DB; OCR worker runs as non-root; volume permissions restrict write access to OCR container only | Low (3) |
| T-17 | OCR worker crashes in a loop (adversarial images), exhausting CPU | Denial of Service | 3 | 2 | 6 Medium | Container restart policy; resource limits (`cpus: 2.0, memory: 2G`) prevent host exhaustion; jobs not ACKed until processing completes | Low (2) |

### 5.5 PostgreSQL (PHI at rest)

| ID | Threat | STRIDE | Likelihood | Impact | Risk Score | Mitigations | Residual Risk |
|----|--------|--------|------------|--------|------------|-------------|---------------|
| T-18 | Attacker with network access to internal Docker network reads raw PHI from DB | Information Disclosure | 1 | 5 | 5 Medium | Postgres only on `api-internal` network; password auth required; PHI fields encrypted with AES-256-GCM before storage | Low (2) |
| T-19 | SQL injection via OCR result data written to JSONB column | Tampering | 1 | 4 | 4 Low | All DB writes use Prisma parameterised queries; no raw SQL string concatenation; SAST catches string formatting in query context | Low (1) |
| T-20 | DB volume mounted from host; attacker with host access reads postgres_data directly | Information Disclosure | 2 | 5 | 10 High | PHI fields AES-256-GCM encrypted at application layer; even raw access to PGDATA reveals only ciphertext; DB volume encrypted at rest by cloud provider in prod | Medium (5) — relies on app-layer encryption being correctly implemented |
| T-21 | DB password exposed in dev Compose file committed to repo | Information Disclosure | 3 | 3 | 9 Medium | Dev password (`dev_only_replace_me`) is not a real credential; prod uses `POSTGRES_PASSWORD_FILE` from Docker secret; `.gitignore` excludes `.env` | Low (2) |

### 5.6 Shared OCR Queue Volume

| ID | Threat | STRIDE | Likelihood | Impact | Risk Score | Mitigations | Residual Risk |
|----|--------|--------|------------|--------|------------|-------------|---------------|
| T-22 | API service is compromised; attacker writes arbitrary `.job.json` files to queue | Tampering | 2 | 3 | 6 Medium | OCR worker validates job schema with Pydantic; worker runs with minimal privileges; images validated by PIL before OCR | Low (2) |
| T-23 | PHI in `.job.json` files on shared volume is read by another container | Information Disclosure | 1 | 4 | 4 Low | Only API and OCR containers mount the queue volume; OCR container has no network egress; volume not accessible from host in prod | Low (1) |
| T-24 | Queue volume fills up (disk exhaustion DoS) | Denial of Service | 2 | 3 | 6 Medium | Result poller deletes `.result.json` files after DB write; job files cleaned up after processing; production volume quota set in K8s PVC (`5Gi`) | Low (2) |

### 5.7 JWT / Auth subsystem

| ID | Threat | STRIDE | Likelihood | Impact | Risk Score | Mitigations | Residual Risk |
|----|--------|--------|------------|--------|------------|-------------|---------------|
| T-25 | Token is stolen from browser (XSS) and replayed | Spoofing | 2 | 4 | 8 Medium | Short `access_ttl` (15 min); refresh tokens are separate; HTTPS enforced; `HttpOnly` cookie recommended for refresh token | Medium (4) |
| T-26 | Attacker cracks weak `initial_admin_password` and escalates to admin | Elevation of Privilege | 2 | 5 | 10 High | `initial_admin_password` loaded from Docker secret; enforced password rotation on first login; argon2 password hashing (`argon2-cffi`) | Low–Medium (4) |
| T-27 | `DEV_AUTH_BYPASS=true` accidentally deployed to production | Elevation of Privilege | 2 | 5 | 10 High | `_guard_bypass_in_prod` validator raises `ValueError` if `ENV=production` and bypass is enabled, preventing startup | Low (1) — startup guard is effective |

### 5.8 CI/CD Pipeline (GitHub Actions)

| ID | Threat | STRIDE | Likelihood | Impact | Risk Score | Mitigations | Residual Risk |
|----|--------|--------|------------|--------|------------|-------------|---------------|
| T-28 | Malicious pull request injects code into build that exfiltrates secrets | Information Disclosure | 2 | 5 | 10 High | Branch protection on `main`; PR review required; GitHub Actions secrets not exposed to PRs from forks; OIDC for registry auth avoids long-lived credentials | Medium (5) |
| T-29 | Compromised dependency (`pip install` / `npm install`) introduces backdoor at build time | Tampering | 2 | 5 | 10 High | `pip-audit` in CI checks for known CVEs; `bandit` and `semgrep` SAST; pinned base image digests recommended; CycloneDX SBOM generation (`cyclonedx-bom`) | Medium (5) — supply chain risk is hard to eliminate |
| T-30 | GitHub Actions runner is compromised; attacker pushes backdoored image to registry | Elevation of Privilege | 1 | 5 | 5 Medium | Separate signing step (cosign/Sigstore) recommended; image digest pinning in K8s deployments | Low–Medium (3) |

### 5.9 Frontend (Next.js)

| ID | Threat | STRIDE | Likelihood | Impact | Risk Score | Mitigations | Residual Risk |
|----|--------|--------|------------|--------|------------|-------------|---------------|
| T-31 | XSS via unsanitised OCR result text rendered in the review UI | Information Disclosure | 2 | 4 | 8 Medium | React auto-escapes all rendered values by default; no `dangerouslySetInnerHTML` usage; CSP headers recommended | Low (2) |
| T-32 | CSRF attack causes doctor to inadvertently approve a forged prescription | Tampering | 2 | 4 | 8 Medium | JWT-based auth (not cookie-based) eliminates classic CSRF; `SameSite=Strict` on any cookies; `Origin` header validation | Low (2) |
| T-33 | Exposed Next.js API routes leak internal service addresses | Information Disclosure | 2 | 2 | 4 Low | `API_BASE_URL` is a server-side env var; not exposed to client bundle; all API calls proxied server-side | Low (1) |

### 5.10 Docker host / container runtime

| ID | Threat | STRIDE | Likelihood | Impact | Risk Score | Mitigations | Residual Risk |
|----|--------|--------|------------|--------|------------|-------------|---------------|
| T-34 | Container escape via privileged container or mounted Docker socket | Elevation of Privilege | 1 | 5 | 5 Medium | No containers run with `--privileged`; Docker socket never bind-mounted; `cap_drop: ALL` on OCR; `no-new-privileges:true` on OCR and API | Low (2) |
| T-35 | Host kernel vulnerability exploited from inside OCR container | Elevation of Privilege | 1 | 5 | 5 Medium | OCR runs in distroless image; no shell; `seccomp` default profile applied; regular base-image updates via CI | Low (2) |
| T-36 | Attacker gains access to Docker host and reads postgres_data volume | Information Disclosure | 1 | 5 | 5 Medium | PHI fields AES-256-GCM encrypted at application layer; encryption key stored in Docker secret, not on host filesystem; volume encryption at rest (cloud) | Low–Medium (3) |

---

## 6. Risk Rating Matrix

| | **Impact 1 (Negligible)** | **Impact 2 (Minor)** | **Impact 3 (Moderate)** | **Impact 4 (Major)** | **Impact 5 (Catastrophic)** |
|---|---|---|---|---|---|
| **Likelihood 5 (Almost Certain)** | 5 Low | 10 Medium | 15 High | 20 Critical | 25 Critical |
| **Likelihood 4 (Likely)** | 4 Low | 8 Medium | 12 High | 16 Critical | 20 Critical |
| **Likelihood 3 (Possible)** | 3 Low | 6 Medium | 9 Medium | 12 High | 15 High |
| **Likelihood 2 (Unlikely)** | 2 Low | 4 Low | 6 Medium | 8 Medium | 10 High |
| **Likelihood 1 (Rare)** | 1 Low | 2 Low | 3 Low | 4 Low | 5 Medium |

**Colour key:**
- **Low (1–4):** Accept; monitor annually
- **Medium (5–9):** Mitigate; owner assigned; review every 6 months
- **High (10–14):** Urgent mitigation required; review quarterly
- **Critical (15–25):** Immediate action; escalate to CISO/DPO

---

## 7. Residual Risk Register

Threats rated **Medium or above** after mitigations are tracked here.

| ID | Component | Threat summary | Pre-mitigation risk | Mitigations applied | Post-mitigation risk | Owner | Review date | Acceptance justification |
|----|-----------|----------------|--------------------|--------------------|---------------------|-------|-------------|--------------------------|
| T-01 | Edge → Mosquitto | MQTT payload replay | 6 Medium | Ephemeral TLS keys; per-session mTLS | 2 Low | Platform Team | 2026-11-06 | TLS forward secrecy effectively eliminates replay |
| T-02 | Edge → Mosquitto | Device private key extraction | 8 Medium | Per-device certs; ACL revocation | 4 Low | Platform Team | 2026-11-06 | Acceptable pending HSM adoption on devices |
| T-03 | Edge → Mosquitto | Oversized image DoS | 9 Medium | 10 MB body limit; PIL validation | 3 Low | Platform Team | 2026-11-06 | Rate limiter and size cap are effective |
| T-04 | Edge → Mosquitto | TLS MitM image injection | 5 Medium | TLS 1.3; mTLS; cert pinning | 2 Low | Platform Team | 2026-11-06 | mTLS makes active MitM infeasible without CA compromise |
| T-07 | MQTT → API | Malicious MQTT payload injection | 8 Medium | Pydantic schema validation; SAST | 3 Low | API Team | 2026-11-06 | Schema validation blocks all known injection vectors |
| T-08 | MQTT → API | MQTT flood DoS | 6 Medium | ACL rate bounds; service isolation | 2 Low | Platform Team | 2026-11-06 | Device count is bounded |
| T-09 | REST API | Unauthenticated PHI access | 15 Critical | JWT auth; RBAC; bypass guard | 5 Medium | Auth Lead | 2026-08-06 | **Residual risk: weak JWT secret.** Mitigated by Docker secrets and 64-char entropy requirement. Rotate every 90 days. |
| T-10 | REST API | RBAC privilege escalation | 8 Medium | Per-route role decorator | 2 Low | Auth Lead | 2026-11-06 | Role claims are tamper-proof inside signed JWT |
| T-11 | REST API | Large-upload DoS | 9 Medium | Body size limit; rate limiter | 2 Low | API Team | 2026-11-06 | 10 MB cap and 3/min rate limit are effective |
| T-12 | REST API / Auth | JWT secret brute-force | 10 High | Docker secret; aud+iss validation; 256-bit secret | 4 Low | Auth Lead | 2026-08-06 | 256-bit random secret; 90-day rotation; Docker secret prevents exposure |
| T-13 | REST API | Verbose error message leakage | 9 Medium | Production mode; generic error handlers | 2 Low | API Team | 2026-11-06 | Production config disables debug mode |
| T-15 | OCR Worker | RCE via malicious image | 8 Medium | Sandbox: read-only FS, cap_drop ALL, no network | 4 Low | DevOps | 2026-11-06 | Defence-in-depth; RCE confined to isolated container |
| T-16 | OCR Worker | False result injection via queue | 8 Medium | Pydantic schema validation on result; worker ACLs | 3 Low | API Team | 2026-11-06 | Schema validation + result file ownership |
| T-18 | PostgreSQL | Network access to DB | 5 Medium | api-internal network; PHI AES-GCM | 2 Low | Platform Team | 2026-11-06 | Network isolation + encryption-at-rest |
| T-20 | PostgreSQL | Direct PGDATA volume access | 10 High | AES-256-GCM app-layer encryption; cloud volume encryption | 5 Medium | Security | 2026-08-06 | **Residual risk: app-layer encryption must be validated.** Key stored in Docker secret. HIPAA requires encryption at rest — this control is non-negotiable. |
| T-21 | PostgreSQL | Dev DB password in Compose | 9 Medium | Non-real credential; prod uses secrets; .gitignore | 2 Low | DevOps | 2026-11-06 | Dev credential has no access to production |
| T-25 | JWT / Auth | Token theft via XSS | 8 Medium | Short TTL; HTTPS; HttpOnly cookie | 4 Low | Frontend Team | 2026-11-06 | 15-min access TTL limits blast radius |
| T-26 | JWT / Auth | Weak admin password cracking | 10 High | Docker secret; argon2; forced rotation | 4 Low | Auth Lead | 2026-08-06 | Argon2 makes brute-force infeasible; secret-based initial password |
| T-27 | JWT / Auth | DEV_AUTH_BYPASS in prod | 10 High | Startup validator raises ValueError | 1 Low | Auth Lead | 2026-11-06 | Validator prevents startup; monitoring catches config drift |
| T-28 | CI/CD | Secrets exfiltration via PR | 10 High | Branch protection; fork isolation | 5 Medium | DevOps | 2026-08-06 | **Residual risk.** GitHub Actions fork isolation mitigates, but supply chain risk remains. Adopt OIDC, remove long-lived tokens. |
| T-29 | CI/CD | Malicious dependency | 10 High | pip-audit; bandit; semgrep; SBOM | 5 Medium | DevOps | 2026-08-06 | **Residual risk.** No perfect mitigation for zero-day supply chain. Mitigated by tooling; residual risk accepted with 6-month review. |
| T-31 | Frontend | XSS via OCR text | 8 Medium | React auto-escape; CSP headers | 2 Low | Frontend Team | 2026-11-06 | React default escaping is robust |
| T-32 | Frontend | CSRF | 8 Medium | JWT auth; SameSite cookie | 2 Low | Frontend Team | 2026-11-06 | JWT Bearer auth eliminates classic CSRF |

---

## 8. Security Controls Traceability

| Control | Mitigates threats | Implementation file(s) |
|---------|-------------------|------------------------|
| mTLS on MQTT (TLS 1.3, per-device client cert) | T-01, T-02, T-04, T-05 | `infrastructure/mosquitto/mosquitto.conf`, `scripts/gen-dev-certs.sh` |
| Mosquitto ACL deny-by-default | T-05, T-06, T-08 | `infrastructure/mosquitto/acl.conf` |
| JWT Bearer auth on all API routes | T-09, T-10, T-25 | `services/api/app/core/security.py`, `services/api/app/api/routes/` |
| RBAC (admin/doctor/receptionist/auditor) | T-10 | `services/api/app/core/security.py`, `docs/RBAC.md` |
| PHI AES-256-GCM encryption at rest | T-18, T-20, T-36 | `services/api/app/core/security.py`, `docs/PHI_FIELDS.md` |
| Rate limiting (slowapi) | T-11 | `services/api/app/core/limiter.py` |
| Body size limit middleware (10 MB) | T-03, T-11 | `services/api/app/core/middleware.py` |
| OCR worker sandbox (read-only FS, cap_drop ALL, no network, tmpfs noexec) | T-15, T-17, T-34, T-35 | `infrastructure/docker/docker-compose.dev.yml` (ocr service), `infrastructure/docker/docker-compose.prod.yml` |
| Pydantic schema validation on MQTT payloads and OCR results | T-07, T-16, T-19 | `services/api/app/schemas/ocr.py`, `services/api/app/mqtt/consumer.py`, `services/api/app/services/result_poller.py` |
| Docker network isolation (api-internal, ocr-isolated) | T-06, T-18, T-23 | `infrastructure/docker/docker-compose.dev.yml`, `infrastructure/docker/docker-compose.prod.yml`, `infrastructure/kubernetes/network-policies/` |
| Docker secrets / `*_FILE` env var pattern | T-09, T-12, T-20, T-26, T-28 | `services/api/app/core/config.py` (`_read_secret`), `infrastructure/docker/docker-compose.prod.yml` |
| `DEV_AUTH_BYPASS` production guard | T-27 | `services/api/app/core/config.py` (`_guard_bypass_in_prod` validator) |
| HTTPS (TLS termination at ingress) | T-04, T-09, T-25, T-32 | `infrastructure/kubernetes/ingress/ingress.yaml` |
| Kubernetes NetworkPolicy deny-all + selective allow | T-06, T-18, T-23, T-34 | `infrastructure/kubernetes/network-policies/` |
| SAST — Bandit + Semgrep | T-07, T-13, T-19, T-29 | _(owned by CI/CD epic, t29)_ |
| Dependency audit (pip-audit) | T-29 | _(owned by CI/CD epic, t29)_ |
| DefectDojo findings dashboard | T-07, T-29, T-31 | `infrastructure/docker/docker-compose.security.yml`, `scripts/upload-findings.sh` |
| SBOM generation (CycloneDX) | T-29 | `services/api/pyproject.toml` (`cyclonedx-bom` dev dep) |
| Branch protection + PR review | T-28, T-30 | GitHub repository settings |
| Prisma Studio absent from prod Compose | T-09 | `infrastructure/docker/docker-compose.prod.yml` |
| Audit logging | T-09, T-10, T-25 | `services/api/app/` (structured logging via uvicorn/FastAPI) |
| argon2 password hashing | T-26 | `services/api/app/core/security.py` (`argon2-cffi`) |
| JWT audience + issuer claim validation | T-09, T-12 | `services/api/app/core/security.py` |
| Short JWT access TTL (15 min) | T-25 | `services/api/app/core/config.py` (`jwt_access_ttl_seconds = 900`) |
| HPA (Kubernetes autoscaler) | T-11, T-17 | `infrastructure/kubernetes/hpa/api-hpa.yaml` |
| Read-only root filesystem on OCR | T-15, T-34 | `infrastructure/docker/docker-compose.dev.yml`, `infrastructure/docker/docker-compose.prod.yml`, `infrastructure/kubernetes/deployments/ocr.yaml` |
