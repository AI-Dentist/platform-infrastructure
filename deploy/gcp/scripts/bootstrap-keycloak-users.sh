#!/bin/sh
# Run on GCP, after Keycloak is ready. Refuses to overwrite credentials or users.
set -eu
umask 077
root=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
file="$HOME/deploy/gcp-credentials.txt"
envfile=${GCP_ENV_FILE:-$HOME/deploy/gcp.env}
[ ! -e "$file" ] || { printf '%s\n' 'Credentials file already exists; refusing to overwrite.' >&2; exit 1; }
mkdir -p "$HOME/deploy"
# Exclusively create the file before provisioning so a partial run cannot silently overwrite it.
(set -C; : > "$file")
chmod 600 "$file"
compose() { docker compose --env-file "$envfile" -f "$root/deploy/gcp/compose.yml" "$@"; }
# Authenticate inside the container using its existing bootstrap environment.
compose exec -T keycloak sh -c '/opt/keycloak/bin/kcadm.sh config credentials --server http://localhost:8080 --realm master --user "$KC_BOOTSTRAP_ADMIN_USERNAME" --password "$KC_BOOTSTRAP_ADMIN_PASSWORD" >/dev/null' >/dev/null
for role in ADMIN ODONTOLOGO RECEPCIONISTA CAJERO PACIENTE; do
  user="test_$(printf '%s' "$role" | tr '[:upper:]' '[:lower:]')"
  password=$(openssl rand -hex 24)
  # Persist before each operation so a failure cannot lose an already-set password.
  printf '%s %s %s\n' "$user" "$role" "$password" >> "$file"
  compose exec -T keycloak /opt/keycloak/bin/kcadm.sh create users -r dental-erp -s "username=$user" -s enabled=true -s firstName=Test -s "lastName=$role" -s "email=$user@dental.test" -s emailVerified=true >/dev/null
  compose exec -T keycloak /opt/keycloak/bin/kcadm.sh set-password -r dental-erp --username "$user" --new-password "$password" >/dev/null
  compose exec -T keycloak /opt/keycloak/bin/kcadm.sh add-roles -r dental-erp --uusername "$user" --rolename "$role" >/dev/null
done
printf '%s\n' 'Test users created; credentials stored in the protected file.'
