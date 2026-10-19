#!/usr/bin/env bash
# Run the whole acb-delta stack on one GCP VM (docker compose + Caddy for HTTPS and basic auth).
# Uses the active gcloud configuration's project; override with GCP_PROJECT / GCP_ZONE.
#
#   ./scripts/gcp.sh create     reserve a static IP, open 80/443, create the VM (installs Docker on boot)
#   ./scripts/gcp.sh deploy     upload the latest origin/main (GCP_REF), build and start, print URL + login
#   ./scripts/gcp.sh status     service health on the VM
#   ./scripts/gcp.sh login      print the URL, user and password
#   ./scripts/gcp.sh logs [service]
#   ./scripts/gcp.sh ssh
#   ./scripts/gcp.sh stop|start stop the VM to save credit (data and IP kept) / start it again
#   ./scripts/gcp.sh destroy    delete the VM, its disk (ALL data), IP and firewall rule (asks first)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PROJECT="${GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
ZONE="${GCP_ZONE:-asia-southeast1-b}"
REGION="${ZONE%-*}"
VM=acb-delta
IP_NAME=acb-delta-ip
FW_RULE=acb-delta-web
# 16 GB: the bge-m3 embedding container needs ~2.3 GB next to the rest of the stack.
MACHINE="${GCP_MACHINE:-e2-standard-4}"
REF="${GCP_REF:-origin/main}"
# The VM runs as this account; LiteLLM uses it to call Vertex AI, so no model key is stored.
VM_SA=acb-delta-vm
COMPOSE_FILES=docker-compose.yml:deploy/gcp/docker-compose.gcp.yml
# Absolute, not ~: every SSH user (you, CI's service account) must share one checkout and one .env.
REMOTE_DIR=/opt/acb-delta
COMPOSE_GCP="docker compose -f docker-compose.yml -f deploy/gcp/docker-compose.gcp.yml"

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

[ -n "$PROJECT" ] || fail "No GCP project: run 'gcloud config set project <id>' or set GCP_PROJECT."
G=(--project "$PROJECT" --quiet)

# OS Login keys added from CI expire, so ephemeral runners do not pile up keys on the service account.
remote() {
  gcloud compute ssh "$VM" --zone "$ZONE" "${G[@]}" ${CI:+--ssh-key-expire-after=1h} --command "$1"
}

static_ip() {
  gcloud compute addresses describe "$IP_NAME" --region "$REGION" "${G[@]}" --format='value(address)'
}

# sslip.io resolves a.b.c.d.sslip.io to a.b.c.d, which lets Caddy get a real certificate without a domain.
site_address() { local ip; ip="$(static_ip)"; echo "${ip//./-}.sslip.io"; }

cmd_create() {
  info "Project $PROJECT ($(gcloud config get-value account 2>/dev/null)), zone $ZONE, $MACHINE"
  gcloud services enable compute.googleapis.com aiplatform.googleapis.com discoveryengine.googleapis.com "${G[@]}"
  local sa="$VM_SA@$PROJECT.iam.gserviceaccount.com" role
  gcloud iam service-accounts describe "$sa" "${G[@]}" >/dev/null 2>&1 ||
    gcloud iam service-accounts create "$VM_SA" --display-name "acb-delta demo VM" "${G[@]}"
  for role in roles/aiplatform.user roles/discoveryengine.viewer roles/logging.logWriter roles/monitoring.metricWriter; do
    gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$sa" --role "$role" \
      --condition=None "${G[@]}" >/dev/null
  done
  gcloud compute addresses describe "$IP_NAME" --region "$REGION" "${G[@]}" >/dev/null 2>&1 ||
    gcloud compute addresses create "$IP_NAME" --region "$REGION" "${G[@]}"
  gcloud compute firewall-rules describe "$FW_RULE" "${G[@]}" >/dev/null 2>&1 ||
    gcloud compute firewall-rules create "$FW_RULE" --allow tcp:80,tcp:443 \
      --target-tags "$FW_RULE" "${G[@]}"
  if gcloud compute instances describe "$VM" --zone "$ZONE" "${G[@]}" >/dev/null 2>&1; then
    info "VM $VM already exists"
  else
    # Only 80/443 are opened; the stack's own ports (3000, 8000, 8080) stay unreachable from outside.
    gcloud compute instances create "$VM" --zone "$ZONE" --machine-type "$MACHINE" \
      --image-family debian-12 --image-project debian-cloud \
      --boot-disk-size 30GB --boot-disk-type pd-balanced \
      --tags "$FW_RULE" --address "$IP_NAME" \
      --service-account "$sa" --scopes cloud-platform \
      --metadata enable-oslogin=TRUE,startup-script='command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh' \
      "${G[@]}"
  fi
  info "CI deploys over OS Login as the VM's account: grant its deployer roles/iam.serviceAccountUser on $sa"
  info "Next: ./scripts/gcp.sh deploy"
}

# Upload the latest committed $REF (never local edits, .env, node_modules or plans/),
# plus deploy/gcp from this checkout so the overlay works before it is merged.
upload() {
  local tmp
  info "Fetching latest $REF"
  git fetch --quiet origin "${REF#origin/}"
  tmp="$(mktemp -d)"
  git archive "$REF" | tar -x -C "$tmp"
  mkdir -p "$tmp/deploy" && cp -R deploy/gcp "$tmp/deploy/"
  info "Uploading $REF @ $(git log -1 --format='%h %s' "$REF")"
  # macOS bsdtar would add AppleDouble/xattr entries; GNU tar (CI) has no such flag.
  local tar_flags=()
  tar --version | grep -q bsdtar && tar_flags=(--no-mac-metadata)
  # The VM's .env (generated passwords) survives each upload; everything else is replaced.
  COPYFILE_DISABLE=1 tar ${tar_flags[@]+"${tar_flags[@]}"} -czf - -C "$tmp" . |
    remote "set -e; sudo rm -rf $REMOTE_DIR.new; sudo mkdir -p $REMOTE_DIR.new
      sudo tar --warning=no-unknown-keyword --no-same-owner -xzf - -C $REMOTE_DIR.new
      sudo chmod 755 $REMOTE_DIR.new  # the archive root carries mktemp's 700; .env stays 600 root
      if sudo test -f $REMOTE_DIR/.env; then sudo cp -p $REMOTE_DIR/.env $REMOTE_DIR.new/.env; fi
      sudo rm -rf $REMOTE_DIR; sudo mv $REMOTE_DIR.new $REMOTE_DIR"
  rm -rf "$tmp"
}

cmd_deploy() {
  local site
  site="$(site_address)"
  upload
  info "Building and starting on the VM (first run takes several minutes)"
  remote "set -euo pipefail; cd $REMOTE_DIR
    # The binary appears before the daemon is up, so wait for the daemon itself.
    until sudo docker info >/dev/null 2>&1; do echo 'waiting for Docker to finish installing...'; sleep 5; done
    sudo ./scripts/run.sh up >/dev/null
    if ! sudo grep -q '^BASIC_AUTH_HASH=' .env; then
      pw=\$(openssl rand -hex 12)
      hash=\$(sudo docker run --rm caddy:2.10-alpine caddy hash-password --plaintext \"\$pw\")
      # Single quotes: the bcrypt hash contains \$ that compose would otherwise interpolate.
      printf '\n# Public access, written by scripts/gcp.sh\nSITE_ADDRESS=%s\nBASIC_AUTH_USER=acb\nBASIC_AUTH_PASSWORD=%s\nBASIC_AUTH_HASH=%s\n' \
        '$site' \"\$pw\" \"'\$hash'\" | sudo tee -a .env >/dev/null
    fi
    # Bearer key for the public /v1 model endpoint (see deploy/gcp/Caddyfile).
    if ! sudo grep -q '^MODEL_API_KEY=' .env; then
      printf 'MODEL_API_KEY=%s\n' \"\$(openssl rand -hex 24)\" | sudo tee -a .env >/dev/null
    fi
    # From now on every plain 'docker compose' (and run.sh) on the VM includes the GCP overlay.
    sudo grep -q '^COMPOSE_FILE=' .env || echo 'COMPOSE_FILE=$COMPOSE_FILES' | sudo tee -a .env >/dev/null
    sudo $COMPOSE_GCP up -d --wait
    # Compose does not restart a container when only a bind-mounted config file changed, and the
    # upload replaces those files, so recreate the services that read deploy/gcp/* configs.
    sudo $COMPOSE_GCP up -d --wait --force-recreate litellm caddy
    # Restore the evaluation dashboard from the committed baseline so it is never empty on a fresh
    # database. Idempotent: skips when eval_runs already has a run or no baseline is committed.
    sudo $COMPOSE_GCP exec -T api python -m app.evaluation.seed || true
    sudo ./scripts/run.sh status"
  check_models
  # CI logs are public for this repo: print only the URL there, never the password.
  if [ -n "${CI:-}" ]; then
    info "Deployed: https://$site"
  else
    cmd_login
  fi
}

# Fail the deploy when a model does not answer, instead of a "healthy" stack that silently falls
# back to rules (api) or 503s (agent). One short call each; prints no config or credentials.
check_models() {
  info "Checking the models: chat + rerank (Vertex AI via LiteLLM), embedding (bge-m3), agent"
  remote "set -euo pipefail; cd $REMOTE_DIR
    sudo $COMPOSE_GCP exec -T api python -c '
from app.ria import embeddings, llm, rerank
assert llm.llm_model(), \"LLM_MODEL is empty\"
llm.chat_json(\"Return the JSON object {\\\"ok\\\": true}.\", \"ping\")
print(\"chat ok:\", llm.llm_model())
assert rerank.rerank_model(), \"RERANK_MODEL is empty\"
rerank.rerank(\"ping\", [\"ping\"])
print(\"rerank ok:\", rerank.rerank_model())
dim = len(embeddings.embed([\"ping\"])[0])
print(\"embedding ok:\", embeddings.embedding_version(), dim, \"dims\")'
    sudo $COMPOSE_GCP exec -T agent python -c '
import json, urllib.request
req = urllib.request.Request(\"http://localhost:8080/invoke\", json.dumps({\"vbpl_text\": \"Thông tư thử nghiệm.\"}).encode(), {\"Content-Type\": \"application/json\"})
urllib.request.urlopen(req, timeout=300)
print(\"agent ok\")'"
}

cmd_login() {
  remote "cd $REMOTE_DIR && sudo grep -E '^(SITE_ADDRESS|BASIC_AUTH_USER|BASIC_AUTH_PASSWORD|MODEL_API_KEY)=' .env" |
    sed -e 's|^SITE_ADDRESS=|  URL       https://|' -e 's|^BASIC_AUTH_USER=|  User      |' \
      -e 's|^BASIC_AUTH_PASSWORD=|  Password  |' -e 's|^MODEL_API_KEY=|  Model key |'
}

cmd_destroy() {
  printf 'This deletes VM %s with ALL its data, plus the static IP and firewall rule in %s. Type "destroy": ' "$VM" "$PROJECT"
  local answer
  read -r answer
  [ "$answer" = "destroy" ] || fail "Cancelled."
  gcloud compute instances delete "$VM" --zone "$ZONE" "${G[@]}" || true
  gcloud compute addresses delete "$IP_NAME" --region "$REGION" "${G[@]}" || true
  gcloud compute firewall-rules delete "$FW_RULE" "${G[@]}" || true
}

usage() { sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; }

case "${1:-}" in
  create) cmd_create ;;
  deploy) cmd_deploy ;;
  status) remote "cd $REMOTE_DIR && sudo $COMPOSE_GCP ps -a --format 'table {{.Service}}\t{{.Status}}' && curl -s localhost:8000/api/health/ready; echo" ;;
  login) cmd_login ;;
  logs) shift; remote "cd $REMOTE_DIR && sudo $COMPOSE_GCP logs --tail 100 $*" ;;
  ssh) gcloud compute ssh "$VM" --zone "$ZONE" --project "$PROJECT" ;;
  stop) gcloud compute instances stop "$VM" --zone "$ZONE" "${G[@]}" ;;
  start) gcloud compute instances start "$VM" --zone "$ZONE" "${G[@]}" ;;
  destroy) cmd_destroy ;;
  -h | --help | help | "") usage ;;
  *) usage; fail "Unknown command: $1" ;;
esac
