#!/bin/sh
# Run on the NAS only after the exact GitHub Actions image artifacts are loaded.
# No build, source import, or bulk backfill is part of a frontend/API release.
set -eu

release_tag=${1:?Usage: deploy-loaded-images.sh FULL_GIT_SHA}
case "$release_tag" in *[!0-9a-f]*|'') echo 'Expected a Git commit SHA' >&2; exit 2;; esac
[ "${#release_tag}" = 40 ] || { echo 'Expected a full 40-character SHA' >&2; exit 2; }
runtime=${DOCKER_BINARY:-/var/packages/ContainerManager/target/usr/bin/docker}
compose=${COMPOSE_BINARY:-/var/packages/ContainerManager/target/usr/bin/docker-compose}
cd "$(dirname "$0")"
[ -f .env ] || { echo 'Private NAS .env is missing' >&2; exit 2; }
"$runtime" image inspect "monica-next-api:$release_tag" "monica-next-web:$release_tag" >/dev/null
"$compose" config --quiet

# Pass the tag as an environment override until migration succeeds. Keep stdin
# closed: compose run otherwise consumes following commands in streamed shells.
IMAGE_TAG=$release_tag "$compose" run --rm --no-deps -T migrate </dev/null
if grep -q '^IMAGE_TAG=' .env; then
  sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=$release_tag/" .env
else
  printf '\nIMAGE_TAG=%s\n' "$release_tag" >> .env
fi
"$compose" up -d --no-build --no-deps api web reverse-proxy </dev/null

service_container() {
  for candidate in $("$compose" ps -q "$1"); do
    oneoff=$("$runtime" inspect "$candidate" --format '{{index .Config.Labels "com.docker.compose.oneoff"}}')
    # Synology Compose may also return a concurrent import's one-off container.
    case "$oneoff" in False|false) printf '%s\n' "$candidate"; return 0;; esac
  done
  return 1
}
api_container=$(service_container api)
attempt=0
until "$runtime" exec "$api_container" python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/api/v1/ready", timeout=5).read()' >/dev/null 2>&1; do
  attempt=$((attempt+1))
  [ "$attempt" -lt 90 ] || { echo 'API readiness failed; keep the previous images for rollback' >&2; exit 1; }
  sleep 2
done
for service in api web; do
  container_id=$(service_container "$service")
  running_image=$("$runtime" inspect "$container_id" --format '{{.Config.Image}}')
  [ "$running_image" = "monica-next-$service:$release_tag" ] || { echo "Unexpected $service image" >&2; exit 1; }
  "$runtime" inspect "$container_id" --format '{{.Name}} {{.Config.Image}} {{.Image}} {{.State.Status}}'
done
echo 'Images are running and the API database check passed. Verify authenticated HTTPS pages separately.'
