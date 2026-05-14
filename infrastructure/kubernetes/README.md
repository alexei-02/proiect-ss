# Kubernetes Deployment

This directory contains all Kubernetes manifests for deploying the medical OCR platform.

## Prerequisites

- `kubectl` >= 1.27 configured against your target cluster
- `helm` (optional, used for nginx-ingress-controller installation)
- NGINX Ingress Controller installed in the `ingress-nginx` namespace
- Metrics Server installed (required for HPA)
- A storage class that supports `ReadWriteMany` for the OCR queue PVC (e.g., NFS, EFS, or CephFS)

## Directory structure

```
kubernetes/
├── namespace.yaml                 # medical-ocr namespace
├── configmaps/
│   └── api-config.yaml            # Non-secret API env vars
├── network-policies/
│   ├── deny-all.yaml              # Default-deny all traffic
│   ├── allow-api-egress.yaml      # API → Postgres + Mosquitto
│   ├── allow-api-ingress.yaml     # frontend + ingress → API
│   ├── allow-frontend-ingress.yaml # ingress → frontend
│   ├── allow-postgres-ingress.yaml # API → Postgres only
│   └── allow-mosquitto-ingress.yaml # API + external → Mosquitto
├── deployments/
│   ├── postgres.yaml              # StatefulSet + PVC (10Gi)
│   ├── mosquitto.yaml             # Deployment
│   ├── api.yaml                   # Deployment (2 replicas) + queue PVC
│   ├── ocr.yaml                   # Deployment (sandboxed, no network)
│   └── frontend.yaml              # Deployment (2 replicas)
├── services/
│   ├── api-svc.yaml               # ClusterIP :8989
│   ├── frontend-svc.yaml          # ClusterIP :3000
│   ├── mosquitto-svc.yaml         # LoadBalancer :8883
│   └── postgres-svc.yaml          # Headless ClusterIP
├── ingress/
│   └── ingress.yaml               # nginx ingress (TLS)
├── hpa/
│   └── api-hpa.yaml               # HPA: min=2, max=10, CPU=70%
└── secrets/
    └── README.md                  # How to create secrets (never commit them)
```

## Deploy

### Step 1 — Create the namespace

```bash
kubectl apply -f infrastructure/kubernetes/namespace.yaml
```

### Step 2 — Create secrets (REQUIRED before any pods start)

Follow the instructions in `secrets/README.md`. At minimum:

```bash
kubectl create secret generic jwt-secret \
  --namespace medical-ocr \
  --from-literal=jwt-secret="$(openssl rand -hex 32)"

kubectl create secret generic phi-master-key \
  --namespace medical-ocr \
  --from-literal=phi-master-key="$(openssl rand -hex 32)"

DB_PASS="$(openssl rand -base64 24)"
kubectl create secret generic db-credentials \
  --namespace medical-ocr \
  --from-literal=db-password="${DB_PASS}" \
  --from-literal=db-url="postgresql://medical:${DB_PASS}@postgres:5432/medical_ocr"

kubectl create secret generic mosquitto-tls \
  --namespace medical-ocr \
  --from-file=ca.crt=infrastructure/mosquitto/certs/ca.crt \
  --from-file=api_server.crt=infrastructure/mosquitto/certs/api_server.crt \
  --from-file=api_server.key=infrastructure/mosquitto/certs/api_server.key

kubectl create secret tls medical-ocr-tls \
  --namespace medical-ocr \
  --cert=path/to/tls.crt \
  --key=path/to/tls.key
```

### Step 3 — Apply all manifests

Apply sequentially to respect dependency ordering:

```bash
# ConfigMaps and NetworkPolicies first
kubectl apply -f infrastructure/kubernetes/configmaps/
kubectl apply -f infrastructure/kubernetes/network-policies/

# Data tier
kubectl apply -f infrastructure/kubernetes/deployments/postgres.yaml
kubectl apply -f infrastructure/kubernetes/deployments/mosquitto.yaml

# Wait for Postgres to be ready
kubectl rollout status statefulset/postgres -n medical-ocr

# Application tier
kubectl apply -f infrastructure/kubernetes/deployments/api.yaml
kubectl apply -f infrastructure/kubernetes/deployments/ocr.yaml
kubectl apply -f infrastructure/kubernetes/deployments/frontend.yaml

# Services, Ingress, HPA
kubectl apply -f infrastructure/kubernetes/services/
kubectl apply -f infrastructure/kubernetes/ingress/
kubectl apply -f infrastructure/kubernetes/hpa/
```

Or apply everything at once with kustomize (if a `kustomization.yaml` is added):

```bash
kubectl apply -k infrastructure/kubernetes/
```

### Step 4 — Verify

```bash
kubectl get pods -n medical-ocr
kubectl get svc -n medical-ocr
kubectl get ingress -n medical-ocr
kubectl get hpa -n medical-ocr
```

## Image tags

By default, manifests use `image: ...:latest`. For production, replace with a specific Git SHA tag:

```bash
# Build images first
IMAGE_TAG=$(git rev-parse --short HEAD) ./scripts/build-images.sh ghcr.io/myorg

# Update manifests (or use kustomize image transforms)
kubectl set image deployment/api api=medical-ocr-api:${IMAGE_TAG} -n medical-ocr
kubectl set image deployment/ocr ocr=medical-ocr-worker:${IMAGE_TAG} -n medical-ocr
kubectl set image deployment/frontend frontend=medical-ocr-frontend:${IMAGE_TAG} -n medical-ocr
```

## Notes

- **Prisma migrations** run automatically on API pod startup via `entrypoint.sh`.
- **OCR models** (~500 MB) are downloaded on first OCR pod start; the PVC at `/models` persists them.
- **Mosquitto** uses a `LoadBalancer` service because edge IoT devices connect from outside the cluster over mTLS. Ensure `externalTrafficPolicy: Local` is preserved to maintain source IPs for ACL enforcement.
- **Prisma Studio** is intentionally absent — it must never be exposed in production.
