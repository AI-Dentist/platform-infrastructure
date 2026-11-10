#!/bin/sh
# Read-only live observations; SSH aliases and repository paths may be overridden.
set -u
azure=${AZURE_SSH_ALIAS:-vps-azure}
aws=${AWS_SSH_ALIAS:-vps-aws}
gcp=${GCP_SSH_ALIAS:-vps-gcp}
azure_repo=${AZURE_REPO_PATH:-/home/azureuser/deploy/ms-erp}
status=0
for url in https://20-83-242-208.sslip.io/ https://100-60-248-245.sslip.io/remotes/operations/remote.js https://35-237-1-132.sslip.io/remotes/clinical/ https://auth.35-237-1-132.sslip.io/ https://n8n.35-237-1-132.sslip.io/; do
  printf '%s ' "$url"
  curl -sS -o /dev/null -w '%{http_code}\n' --max-time 20 "$url" || status=1
done
for host in "$azure" "$aws" "$gcp"; do
  printf '\n--- %s docker ps ---\n' "$host"
  ssh "$host" docker ps || status=1
done
printf '\n--- GCP Kubernetes ---\n'
ssh "$gcp" 'sudo k3s kubectl get pods,svc,hpa -n dental-erp-prod' || status=1
printf '\n--- Azure PostgreSQL live counts ---\n'
# Restrict override to a shell-safe absolute path before using it remotely.
case "$azure_repo" in *[!a-zA-Z0-9_./-]*|'') printf '%s\n' 'Invalid AZURE_REPO_PATH' >&2; exit 1;; esac
printf '%s\n' "SELECT format('SELECT %L, count(*) FROM %I.%I;', schemaname || '.' || tablename, schemaname, tablename) FROM pg_tables WHERE schemaname = 'public'" '\gexec' | ssh "$azure" "cd '$azure_repo' && docker compose exec -T postgres-erp sh -c 'psql -v ON_ERROR_STOP=1 -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -At'" || status=1
printf '\n--- AWS DynamoDB live counts ---\n'
ssh "$aws" 'tables=$(aws dynamodb list-tables --region us-east-1 --query "TableNames[]" --output text) || exit 1; for t in $tables; do counts=$(aws dynamodb scan --region us-east-1 --table-name "$t" --select COUNT --query Count --output text) || exit 1; printf "%s " "$t"; printf "%s\n" "$counts" | awk "{for(i=1;i<=NF;i++) s+=\$i} END {print s+0}"; done' || status=1
printf '\n--- GCP MongoDB live counts ---\n'
ssh "$gcp" 'sudo k3s kubectl exec -n dental-erp-prod mongo-0 -c mongo -- mongosh --quiet dental_clinico --eval "for (const c of db.getCollectionNames()) print(c + String.fromCharCode(58) + db.getCollection(c).countDocuments({}))"' || status=1
exit "$status"
