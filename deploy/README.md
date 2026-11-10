# Production deployment (Azure + AWS + GCP)

Two Ubuntu 24.04 hosts, each with Docker, a 4 GB swap file and a shared external
Docker network `dental-net`. TLS terminates in a Caddy `edge` container that obtains
Let's Encrypt certificates automatically for `sslip.io` hostnames derived from the
public IPs. No other container publishes host ports.

| Host | Public origin | This repo deploys | Other repos on the host |
| --- | --- | --- | --- |
| Azure `20.83.242.208` | `https://20-83-242-208.sslip.io` | `edge`, `api-gateway` | ms-erp (`postgres-erp`, `ms1-erp`), microfrontends-web (`shell-web`, `mf-erp-web`) |
| AWS `100.60.248.245` (`us-east-1`) | `https://100-60-248-245.sslip.io` | `edge` | MS3-AGENDA-STOCK (`ms3-agenda`, `ml-service`), microfrontends-web (`mf2-web`) |

GCP configuration is provided below; protected APIs require the GCP Keycloak
realm and notifications remain inactive until n8n credentials are configured.

## Routing

Azure edge: `/api/*` and `/mcp` go to `api-gateway:8080`; `/remotes/erp/*` to
`mf-erp-web`; everything else to `shell-web`. The gateway
([azure/gateway.conf.template](azure/gateway.conf.template)) rewrites
`/api/erp/graphql` to MS1 `/graphql`, streams reports and MCP unbuffered, answers
`/api/expediente/*` to the GCP edge over verified HTTPS, and forwards `/api/agendamiento/*` and
`/api/v1/(citas|horarios|stock)` to the AWS edge over verified HTTPS.

AWS edge: `/api/*` goes to `ms3-agenda:8001`; `/remotes/operations/*` to `mf2-web`
with `Access-Control-Allow-Origin` set to the shell origin.

## GCP deployment

The GCP edge serves `https://35-237-1-132.sslip.io/remotes/clinical/`; clinical
API requests are accepted only from Azure `20.83.242.208`. The public issuer is
`https://auth.35-237-1-132.sslip.io/realms/dental-erp` and MS1's notification
URL is `https://n8n.35-237-1-132.sslip.io/webhook/erp-notificaciones`.
Keycloak and n8n bind loopback; MongoDB and Keycloak PostgreSQL have no host
ports. Restrict the host and cloud firewall to public TCP 80/443, and SSH only
from approved sources. Block public K3s API port 6443; install K3s with
`--disable=traefik`. The MongoDB instance is unauthenticated and must remain
isolated from untrusted workloads, not merely unexposed to the Internet.

Prepare `~/deploy/gcp.env` privately from `deploy/gcp/env.template`, with
independent random passwords and a stable encryption key. Install K3s with
metrics-server and local-path storage, reserve ClusterIPs `10.43.100.11` and
`10.43.100.12`, and import both production images into the K3s containerd image
store (Docker's local image store is separate). Create `ms2-env` on the server
from `k8s/ms2-env.secret.template` after reviewing all MS2 production settings;
never commit the completed Secret. Apply `k8s/00-namespace.yml` before creating
the Secret and applying the rest of `k8s/`. The one-replica MongoDB volume is
node-local: configure independent backups and a recovery plan. HPA requires
metrics and capacity; three MS2 replicas may not fit on an 8 GB node.

From this checkout, start the Compose stack with
`docker compose --env-file ~/deploy/gcp.env -f deploy/gcp/compose.yml up -d`.
The inactive workflow is imported once into persistent n8n storage. Configure
its webhook authentication and provider credentials before activation; do not
reimport over a configured workflow. Populate provider environment variables as
required by the workflow. After Keycloak is healthy run
`sh deploy/gcp/scripts/bootstrap-keycloak-users.sh` once; it refuses an existing
credentials file and stores generated test passwords in
`~/deploy/gcp-credentials.txt` (0600). It can leave a partial result on failure;
reconcile users and the protected file manually before retrying. Bind test users
to application records as required; Keycloak import does not seed them.

GCP CI uses the dedicated `GCP_SSH_KEY` and pulls this repository on pushes to
`main`. It does not build or import the sibling images, configure the Secret,
provision the server, or deploy Azure. Validate the actual images, DNS, firewall,
TLS, issuer, proxy path, probes and HPA on the server before routing production.
`verify-multicloud-defense.sh` and `.ps1` are read-only live checks; set
`AZURE_SSH_ALIAS`, `AWS_SSH_ALIAS`, `GCP_SSH_ALIAS`, and `AZURE_REPO_PATH` if
needed. DynamoDB scans consume read capacity and may take time.

## Server layout

Each repository is checked out (or synced by CI) at `/home/<user>/deploy/<repo>`.
The repository root holds a git-ignored `.env` created from
`deploy/<cloud>/env.template`; its `COMPOSE_FILE` line makes a plain
`docker compose up -d --build` from the repository root use the right compose file.

```sh
cp deploy/azure/env.template .env   # or deploy/aws/env.template on AWS
docker compose up -d --build --remove-orphans
docker compose ps
```

## Continuous deployment

`.github/workflows/deploy-azure.yml` and `deploy-aws.yml` run on every push to
`main`/`master` (and manually). They connect with dedicated CI keys stored as the
`AZURE_SSH_KEY` and `AWS_SSH_KEY` repository secrets; the administrators' `.pem`
keys never leave the operator machine. On the hosts those CI public keys are
restricted with `no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty`.

Public repositories (this one, microfrontends-web) `git pull` on the host. The
AI-Dentist organization disables deploy keys, so private repositories (ms-erp,
MS3-AGENDA-STOCK) are copied by the workflow with `rsync` (excluding `.git` and
`.env`) and the host keeps no GitHub credential.

Rotate a CI key by generating a new pair, replacing its line in the host
`~/.ssh/authorized_keys` and running `gh secret set` again for each repository.

## Checks

`python -m unittest scripts.tests.test_deploy_config` validates routes, limits,
header hygiene and published ports without Docker. Before rolling out gateway
changes, render and test the template with the real image:

```sh
docker run --rm -e MS1_UPSTREAM=ms1-erp:8080 -e AWS_PUBLIC_HOST=100-60-248-245.sslip.io \
  -e 'NGINX_ENVSUBST_FILTER=^(MS1_UPSTREAM|AWS_PUBLIC_HOST)$' \
  -v "$PWD/deploy/azure/gateway.conf.template:/etc/nginx/templates/default.conf.template:ro" \
  nginx:1.28-alpine nginx -t
```
