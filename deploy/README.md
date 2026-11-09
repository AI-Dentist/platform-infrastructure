# Production deployment (Azure + AWS)

Two Ubuntu 24.04 hosts, each with Docker, a 4 GB swap file and a shared external
Docker network `dental-net`. TLS terminates in a Caddy `edge` container that obtains
Let's Encrypt certificates automatically for `sslip.io` hostnames derived from the
public IPs. No other container publishes host ports.

| Host | Public origin | This repo deploys | Other repos on the host |
| --- | --- | --- | --- |
| Azure `20.83.242.208` | `https://20-83-242-208.sslip.io` | `edge`, `api-gateway` | ms-erp (`postgres-erp`, `ms1-erp`), microfrontends-web (`shell-web`, `mf-erp-web`) |
| AWS `100.60.248.245` (`us-east-1`) | `https://100-60-248-245.sslip.io` | `edge` | MS3-AGENDA-STOCK (`ms3-agenda`, `ml-service`), microfrontends-web (`mf2-web`) |

Keycloak and n8n are not deployed here; they belong to the later GCP environment.
Until then protected APIs answer 401 and multichannel notifications use the
`SIMULADO_SIN_N8N` fallback.

## Routing

Azure edge: `/api/*` and `/mcp` go to `api-gateway:8080`; `/remotes/erp/*` to
`mf-erp-web`; everything else to `shell-web`. The gateway
([azure/gateway.conf.template](azure/gateway.conf.template)) rewrites
`/api/erp/graphql` to MS1 `/graphql`, streams reports and MCP unbuffered, answers
`/api/expediente/*` with 503 until MS2 exists, and forwards `/api/agendamiento/*` and
`/api/v1/(citas|horarios|stock)` to the AWS edge over verified HTTPS.

AWS edge: `/api/*` goes to `ms3-agenda:8001`; `/remotes/operations/*` to `mf2-web`
with `Access-Control-Allow-Origin` set to the shell origin.

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
