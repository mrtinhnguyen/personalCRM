#!/usr/bin/env bash
set -euo pipefail
umask 077
payload=${1:?Pass the LinkedIn export path}
host=${CRM_NAS_HOST:-crm-nas}
destination=${CRM_LINKEDIN_PATH:-/srv/monica-next/data/raw/linkedin/linkedin_enrichment.incoming.json}
temporary="${destination}.tmp.$$"
[[ "$destination" =~ ^/[a-zA-Z0-9_./-]+$ ]] || { echo 'Invalid NAS destination path' >&2; exit 2; }
# Synology may disable the SFTP subsystem used by modern scp. Stream to a
# temporary file over the existing SSH key and publish only after success.
ssh "$host" "umask 077; cat > '$temporary' && mv '$temporary' '$destination'" < "$payload"
