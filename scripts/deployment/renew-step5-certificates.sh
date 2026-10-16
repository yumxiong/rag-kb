#!/usr/bin/env bash
# Host scheduler entry point. No installation, issuance or container startup here.
set -euo pipefail
if [[ $# != 1 || "$1" != /* ]]; then
  echo 'Usage: bash renew-step5-certificates.sh /absolute/deployment/root' >&2
  exit 2
fi
root=$(cd -- "$1" && pwd -P)
bundle=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../docker/step5-candidate" && pwd -P)
export COMPOSE_DISABLE_ENV_FILE=1
export DEPLOY_ROOT="$root"
[[ -f "$root/release.env" && -d "$root/state" ]]
# One scheduler only; another in-progress renewal is an explicit failure.
exec 9>"$root/state/certbot-renew.lock"
flock -n 9
app=(docker compose --env-file "$root/release.env" -p rag-step5 -f "$bundle/compose.app.yml")
cert=(docker compose --env-file "$root/release.env" -p rag-step5-certbot -f "$bundle/compose.certbot.yml")
# Preflight both commands before renewing. Never start an app from the scheduler.
"${app[@]}" config --quiet
"${cert[@]}" config --quiet
"${app[@]}" exec -T nginx nginx -t
"${cert[@]}" run --rm --no-deps certbot renew --webroot -w /var/www/certbot --non-interactive --quiet
"${app[@]}" exec -T nginx nginx -t
"${app[@]}" exec -T nginx nginx -s reload
echo 'Certificate renewal check and Nginx validation/reload completed.'
