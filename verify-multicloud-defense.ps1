# Read-only live observations; override SSH aliases and Azure repository path via environment.
$azure = if ($env:AZURE_SSH_ALIAS) { $env:AZURE_SSH_ALIAS } else { 'vps-azure' }
$aws = if ($env:AWS_SSH_ALIAS) { $env:AWS_SSH_ALIAS } else { 'vps-aws' }
$gcp = if ($env:GCP_SSH_ALIAS) { $env:GCP_SSH_ALIAS } else { 'vps-gcp' }
$repo = if ($env:AZURE_REPO_PATH) { $env:AZURE_REPO_PATH } else { '/home/azureuser/deploy/ms-erp' }
if ($repo -notmatch '^/[a-zA-Z0-9_./-]+$') { throw 'Invalid AZURE_REPO_PATH' }
$failed = $false
foreach ($url in @('https://20-83-242-208.sslip.io/', 'https://100-60-248-245.sslip.io/remotes/operations/remote.js', 'https://35-237-1-132.sslip.io/remotes/clinical/', 'https://auth.35-237-1-132.sslip.io/', 'https://n8n.35-237-1-132.sslip.io/')) {
  & curl.exe -sS -o NUL -w "$url %{http_code}`n" --max-time 20 $url
  if ($LASTEXITCODE -ne 0) { $failed = $true }
}
foreach ($hostAlias in @($azure, $aws, $gcp)) {
  Write-Host "--- $hostAlias docker ps ---"
  & ssh $hostAlias docker ps
  if ($LASTEXITCODE -ne 0) { $failed = $true }
}
& ssh $gcp 'sudo k3s kubectl get pods,svc,hpa -n dental-erp-prod'
if ($LASTEXITCODE -ne 0) { $failed = $true }
Write-Host '--- Azure PostgreSQL live counts ---'
$sql = "SELECT format('SELECT %L, count(*) FROM %I.%I;', schemaname || '.' || tablename, schemaname, tablename) FROM pg_tables WHERE schemaname = 'public'`n\gexec"
$remote = "cd '$repo' && docker compose exec -T postgres-erp sh -c 'psql -v ON_ERROR_STOP=1 -U `"`$POSTGRES_USER`" -d `"`$POSTGRES_DB`" -At'"
$sql | & ssh $azure $remote
if ($LASTEXITCODE -ne 0) { $failed = $true }
Write-Host '--- AWS DynamoDB live counts ---'
& ssh $aws 'tables=$(aws dynamodb list-tables --region us-east-1 --query "TableNames[]" --output text) || exit 1; for t in $tables; do counts=$(aws dynamodb scan --region us-east-1 --table-name "$t" --select COUNT --query Count --output text) || exit 1; printf "%s " "$t"; printf "%s\n" "$counts" | awk "{for(i=1;i<=NF;i++) s+=\$i} END {print s+0}"; done'
if ($LASTEXITCODE -ne 0) { $failed = $true }
Write-Host '--- GCP MongoDB live counts ---'
& ssh $gcp 'sudo k3s kubectl exec -n dental-erp-prod mongo-0 -c mongo -- mongosh --quiet dental_clinico --eval "for (const c of db.getCollectionNames()) print(c + String.fromCharCode(58) + db.getCollection(c).countDocuments({}))"'
if ($LASTEXITCODE -ne 0) { $failed = $true }
if ($failed) { exit 1 }
