#!/usr/bin/env bash
# Create one RDP connection for one employee from a template and grant READ to exactly that user.
# Needs: bash, curl, jq. Admin credentials are read from the environment, never argv:
#   GUAC_URL=https://desktop.lab.test GUAC_ADMIN_USER=... GUAC_ADMIN_PASSWORD=...
# SAML-only deployments have no admin password: create a short-lived API token another way
# (e.g. a dedicated local automation user created and removed by IT) and export GUAC_TOKEN instead.
#
# usage: provision-connection.sh <template.json> <employee-email> <workspace-host> <xrdp-cert-fingerprint>
# fingerprint is what the workspace_vm role prints, in Guacamole format: SHA256:AB:CD:...:EF (32 bytes)
# Not executed in CI: needs a running Guacamole.
set -euo pipefail

template=${1:?template json}
employee=${2:?employee email (SAML NameID)}
host=${3:?workspace hostname or ip}
fingerprint=${4:?xrdp certificate fingerprint, SHA256:AB:CD:...}
# a mis-formatted pin would make every connection fail (ignore-cert=false), so reject it here
fingerprint=${fingerprint^^}
fingerprint=SHA256:${fingerprint#SHA256:}
[[ $fingerprint =~ ^SHA256:([0-9A-F]{2}:){31}[0-9A-F]{2}$ ]]   || { echo "fingerprint must look like SHA256:AB:CD:... (32 colon-separated bytes)" >&2; exit 1; }
: "${GUAC_URL:?}"
ds=postgresql

command -v jq >/dev/null || { echo "jq required" >&2; exit 1; }

if [ -z "${GUAC_TOKEN:-}" ]; then
  : "${GUAC_ADMIN_USER:?}" "${GUAC_ADMIN_PASSWORD:?}"
  # password via stdin (not argv); printf avoids a trailing newline
  GUAC_TOKEN=$(printf %s "${GUAC_ADMIN_PASSWORD}" | curl -fsS --data-urlencode "username=${GUAC_ADMIN_USER}" \
    --data-urlencode "password@-" "${GUAC_URL}/api/tokens" | jq -r .authToken)
fi
api() { curl -fsS -H "Guacamole-Token: ${GUAC_TOKEN}" -H 'Content-Type: application/json' "$@"; }

name="workspace-${employee%@*}"
body=$(jq --arg name "$name" --arg host "$host" --arg fp "$fingerprint" \
  '.name=$name | .parameters.hostname=$host | .parameters["cert-fingerprints"]=$fp' "$template")

# refuse to create anything that weakens the policy
echo "$body" | jq -e '
  .parameters["ignore-cert"]=="false" and .parameters.security=="tls" and
  .parameters["enable-drive"]=="false" and .parameters["disable-download"]=="true" and
  .parameters["disable-upload"]=="true" and .parameters["enable-printing"]=="false" and
  .parameters["enable-sftp"]=="false" and .parameters["disable-copy"]=="true"' >/dev/null \
  || { echo "template violates transfer policy" >&2; exit 1; }

uenc=$(jq -rn --arg u "$employee" '$u|@uri')
base="${GUAC_URL}/api/session/data/${ds}"

# The user row normally appears at the first SAML login. Create it now (unusable random password,
# SAML is the only way in) so the grant below cannot fail and strand a connection.
if ! api -o /dev/null "${base}/users/${uenc}" 2>/dev/null; then
  jq -n --arg u "$employee" --arg p "$(head -c 32 /dev/urandom | base64)" \
    '{username:$u,password:$p,attributes:{}}' | api -X POST --data @- "${base}/users" >/dev/null
fi

# Re-running updates the existing connection instead of creating a duplicate.
id=$(api "${base}/connections" | jq -r --arg n "$name" 'to_entries[] | select(.value.name==$n) | .key' | head -n1)
created=0
if [ -n "$id" ]; then
  echo "$body" | api -X PUT --data @- "${base}/connections/${id}" >/dev/null
else
  id=$(echo "$body" | api -X POST --data @- "${base}/connections" | jq -r .identifier)
  created=1
  # ponytail: no rollback of the user row; it is harmless (no permissions) and SAML would create it anyway
  trap 'api -X DELETE "${base}/connections/${id}" >/dev/null 2>&1 || true' ERR
fi

# one user, read only: the connection is invisible to everyone else
api -X PATCH "${base}/users/${uenc}/permissions" \
  --data "[{\"op\":\"add\",\"path\":\"/connectionPermissions/${id}\",\"value\":\"READ\"}]" >/dev/null
trap - ERR
echo "connection ${id} (${name}) ready for ${employee} (created=${created})"
