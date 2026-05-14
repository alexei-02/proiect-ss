# Infrastructure & DevOps — Implementation Record

## Status: ✅ Implemented

Tasks t39–t42 are fully implemented. This covers production-grade deployment configuration, secret management, security scanning infrastructure, and the threat model.

---

## What was built

| Task | Status | Notes |
|---|:---:|---|
| t39 Docker Compose / Kubernetes manifests | ✅ | Production Compose + full K8s manifest set |
| t40 Secret management | ✅ | `*_FILE` env var support in `config.py`; Docker secrets wired |
| t41 Centralised security findings dashboard | ✅ | DefectDojo Compose overlay + CI upload scripts |
| t42 TARA document | ✅ | 36 threat scenarios, risk matrix, residual risk register |

---

## New files

| File | Purpose |
|---|---|
| `infrastructure/docker/docker-compose.prod.yml` | Production Compose — Docker secrets, resource limits, no source bind-mounts |
| `infrastructure/docker/docker-compose.security.yml` | DefectDojo + dedicated Postgres; attaches to existing `frontend` network |
| `infrastructure/docker/.env.example` | Template for local `.env`; generation hints for secrets |
| `infrastructure/kubernetes/namespace.yaml` | `medical-ocr` namespace |
| `infrastructure/kubernetes/configmaps/api-config.yaml` | Non-secret API env vars |
| `infrastructure/kubernetes/network-policies/deny-all.yaml` | Default deny-all for the namespace |
| `infrastructure/kubernetes/network-policies/allow-api-egress.yaml` | API → Postgres (5432), Mosquitto (8883), DNS |
| `infrastructure/kubernetes/network-policies/allow-api-ingress.yaml` | Ingress controller → API (8989) |
| `infrastructure/kubernetes/network-policies/allow-frontend-ingress.yaml` | Ingress controller → frontend (3000) |
| `infrastructure/kubernetes/network-policies/allow-postgres-ingress.yaml` | API → Postgres only |
| `infrastructure/kubernetes/network-policies/allow-mosquitto-ingress.yaml` | API + external → Mosquitto (8883) |
| `infrastructure/kubernetes/deployments/postgres.yaml` | StatefulSet, 10 Gi PVC, non-root (uid 999) |
| `infrastructure/kubernetes/deployments/mosquitto.yaml` | Deployment + LoadBalancer service (8883) |
| `infrastructure/kubernetes/deployments/api.yaml` | Deployment ×2, liveness + readiness probes, HPA-ready |
| `infrastructure/kubernetes/deployments/ocr.yaml` | Sandboxed deployment — `cap_drop: ALL`, read-only rootfs, no network |
| `infrastructure/kubernetes/deployments/frontend.yaml` | Deployment ×2 |
| `infrastructure/kubernetes/services/api-svc.yaml` | ClusterIP — port 8989 |
| `infrastructure/kubernetes/services/frontend-svc.yaml` | ClusterIP — port 3000 |
| `infrastructure/kubernetes/services/mosquitto-svc.yaml` | LoadBalancer — port 8883 |
| `infrastructure/kubernetes/services/postgres-svc.yaml` | Headless service for StatefulSet |
| `infrastructure/kubernetes/ingress/ingress.yaml` | nginx ingress; TLS; `/api/` → api; `/` → frontend; `/metrics/prometheus` internal-only |
| `infrastructure/kubernetes/hpa/api-hpa.yaml` | HPA: min 2, max 10, target CPU 70% |
| `infrastructure/kubernetes/secrets/README.md` | How to provision secrets (kubectl / Sealed Secrets / ESO) |
| `infrastructure/kubernetes/README.md` | Deployment walkthrough |
| `scripts/build-images.sh` | Builds all three images tagged with git SHA; optionally pushes to registry |
| `scripts/upload-findings.sh` | Posts SARIF/JSON scan results to DefectDojo API v2 |
| `docs/TARA.md` | Full threat model — see below |

---

## Modified files

| File | Change |
|---|---|
| `services/api/app/core/config.py` | Added `_read_secret()` helper; sensitive fields read from `*_FILE` path first |

---

## Secret management

`config.py` now supports the Docker secrets / Kubernetes secret-mount pattern. For each sensitive field, set the corresponding `*_FILE` env var to the file path and the value is read from there instead of the env var directly:

| Env var | File override |
|---|---|
| `JWT_SECRET` | `JWT_SECRET_FILE` |
| `PHI_MASTER_KEY` | `PHI_MASTER_KEY_FILE` |
| `DATABASE_URL` | `DATABASE_URL_FILE` |
| `INITIAL_ADMIN_PASSWORD` | `INITIAL_ADMIN_PASSWORD_FILE` |

The dev Compose still uses plain env vars. The prod Compose uses `docker secret create` externals mounted at `/run/secrets/`.

To rotate a secret without downtime: create the new Docker secret under a different name, update the service to reference it, then rolling-update the service.

---

## Production Compose

```bash
# One-time secret provisioning
printf 'your-jwt-secret'    | docker secret create jwt_secret -
printf 'your-phi-hex-key'   | docker secret create phi_master_key -
printf 'postgresql://...'   | docker secret create db_url -
printf 'your-db-password'   | docker secret create db_password -

# Deploy
IMAGE_TAG=$(git rev-parse --short HEAD) \
  docker compose -f infrastructure/docker/docker-compose.prod.yml up -d
```

No source code is bind-mounted. Images are built separately via `scripts/build-images.sh` and referenced by `IMAGE_TAG`.

---

## Kubernetes deployment

Prerequisites: `kubectl` configured against the target cluster; secrets created before applying manifests.

```bash
# 1. Create required secrets (example — use Sealed Secrets or ESO in practice)
kubectl create namespace medical-ocr
kubectl create secret generic jwt-secret \
  --from-literal=JWT_SECRET_FILE=<value> -n medical-ocr
kubectl create secret generic phi-master-key \
  --from-literal=PHI_MASTER_KEY_FILE=<value> -n medical-ocr
kubectl create secret generic db-credentials \
  --from-literal=DATABASE_URL_FILE=<dsn> \
  --from-literal=POSTGRES_PASSWORD=<value> -n medical-ocr
kubectl create secret tls medical-ocr-tls \
  --cert=path/to/tls.crt --key=path/to/tls.key -n medical-ocr
kubectl create secret generic mosquitto-tls -n medical-ocr \
  --from-file=ca.crt=infrastructure/mosquitto/certs/ca.crt \
  --from-file=api_server.crt=infrastructure/mosquitto/certs/api_server.crt \
  --from-file=api_server.key=infrastructure/mosquitto/certs/api_server.key

# 2. Apply all manifests
kubectl apply -f infrastructure/kubernetes/namespace.yaml
kubectl apply -f infrastructure/kubernetes/configmaps/
kubectl apply -f infrastructure/kubernetes/network-policies/
kubectl apply -f infrastructure/kubernetes/deployments/
kubectl apply -f infrastructure/kubernetes/services/
kubectl apply -f infrastructure/kubernetes/ingress/
kubectl apply -f infrastructure/kubernetes/hpa/
```

Full walkthrough: `infrastructure/kubernetes/README.md`.

---

## Security findings dashboard (DefectDojo)

Run alongside the dev stack:

```bash
docker compose \
  -f infrastructure/docker/docker-compose.dev.yml \
  -f infrastructure/docker/docker-compose.security.yml \
  up -d
```

DefectDojo is available at `http://localhost:8080`. After setup, configure an engagement and export the API token, then set:

```bash
export DEFECTDOJO_URL=http://localhost:8080
export DEFECTDOJO_API_TOKEN=<token>
export DEFECTDOJO_ENGAGEMENT_ID=<id>
```

Upload findings manually:

```bash
bandit -r services/api/app -f json -o bandit.json
./scripts/upload-findings.sh "Bandit Scan" bandit.json
```

The SAST/DAST pipeline that drives this dashboard is owned by the **CI/CD epic** (t29, t30) and is out of scope here. Once that pipeline exists, it can invoke `scripts/upload-findings.sh` to push results — the script expects `DEFECTDOJO_URL`, `DEFECTDOJO_API_TOKEN`, and `DEFECTDOJO_ENGAGEMENT_ID` in the environment.

---

## Building images

```bash
# Build all three images tagged with the current git SHA
./scripts/build-images.sh

# Build and push to a registry
./scripts/build-images.sh ghcr.io/your-org
```

Images produced: `medical-ocr-api`, `medical-ocr-worker`, `medical-ocr-frontend`.

---

## TARA summary

`docs/TARA.md` covers:

- **12 assets** with CIA requirements (PHI, encryption keys, JWT secret, device certs, DB, audit log, images, source code)
- **5 threat actors** with capability and motivation profiles
- **9 attack surface entry points**
- **36 threat scenarios** across 10 components, rated by Likelihood × Impact (STRIDE categories)
- **5×5 risk matrix** with Low / Medium / High / Critical thresholds
- **23-row residual risk register** for all Medium+ post-mitigation findings
- **26-row security controls traceability table** linking each control to threat IDs and implementation files
