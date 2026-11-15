#!/usr/bin/env bash
# Run only after reviewing and approving the target project and cloud changes.
set -Eeuo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="${1:?Usage: deploy.sh PROJECT_ID --apply [REGION]}"
[[ "${2:-}" == --apply ]] || { echo 'Explicit --apply required.' >&2; exit 2; }
REGION="${3:-us-central1}"
[[ "$PROJECT" =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]$ ]] || exit 2
[[ "$REGION" =~ ^[a-z0-9-]+$ ]] || exit 2
for bin in terraform gcloud python3 bq; do command -v "$bin" >/dev/null; done
export TF_VAR_project_id="$PROJECT" TF_VAR_region="$REGION"
terraform -chdir="$HERE/infra" init -input=false
terraform -chdir="$HERE/infra" fmt -check
terraform -chdir="$HERE/infra" validate
# Avoid silently switching the project associated with an existing state.
terraform -chdir="$HERE/infra" show -json | python3 -c '
import json,sys
project=sys.argv[1]
def check(module):
 for r in module.get("resources", []):
  p=r.get("values", {}).get("project")
  if p and p != project: raise SystemExit("State belongs to a different project")
 for child in module.get("child_modules", []): check(child)
check(json.load(sys.stdin).get("values", {}).get("root_module", {}))
' "$PROJECT"
gcloud services enable serviceusage.googleapis.com cloudresourcemanager.googleapis.com --project="$PROJECT" --quiet
STATE="$(terraform -chdir="$HERE/infra" state list)"
if ! grep -Fq 'google_cloud_run_v2_service.api[0]' <<< "$STATE"; then
  terraform -chdir="$HERE/infra" apply -var=deploy_service=false
fi
# A Terraform BigQuery job can exist while its SQL has not left the expected row.
# Verify (and if missing, initialize) the singleton before sending traffic to Cloud Run.
# NOTE: Change BQ_DATASET / BQ_LOCATION only if Terraform uses custom values.
DATASET="${BQ_DATASET:-redtelecorp}"
DATA_LOCATION="${BQ_LOCATION:-$REGION}"
python3 "$HERE/scripts/ensure_guard.py" "$PROJECT" \
  --dataset "$DATASET" --location "$DATA_LOCATION" --apply
# Secret values bypass Terraform and stay out of arguments, output and the repository.
EXISTING_API_VERSIONS="$(gcloud secrets versions list rtc-gcp-api-key --project="$PROJECT" --filter=state=ENABLED --format='value(name)')"
if [[ -z "$EXISTING_API_VERSIONS" ]]; then
  KEYDIR="${XDG_CONFIG_HOME:-$HOME/.config}/redtelecorp/$PROJECT"
  mkdir -p "$KEYDIR"
  chmod 700 "$KEYDIR"
  KEYFILE="$KEYDIR/gcp_api_key"
  (umask 077; python3 -c 'import secrets; print(secrets.token_hex(32), end="")' > "$KEYFILE")
  gcloud secrets versions add rtc-gcp-api-key --project="$PROJECT" --data-file="$KEYFILE" >/dev/null
  echo "Integration key stored privately at $KEYFILE"
fi
if [[ -n "${GEMINI_KEY_FILE:-}" ]]; then
  [[ -s "$GEMINI_KEY_FILE" ]] || { echo 'GEMINI_KEY_FILE must name a nonempty private file' >&2; exit 2; }
  gcloud secrets versions add rtc-gcp-gemini-key --project="$PROJECT" --data-file="$GEMINI_KEY_FILE" >/dev/null
fi
API_VERSION="$(gcloud secrets versions list rtc-gcp-api-key --project="$PROJECT" --filter=state=ENABLED --sort-by='~createTime' --limit=1 --format='value(name)')"
GEMINI_VERSION="$(gcloud secrets versions list rtc-gcp-gemini-key --project="$PROJECT" --filter=state=ENABLED --sort-by='~createTime' --limit=1 --format='value(name)')"
API_VERSION="${API_VERSION##*/}"
GEMINI_VERSION="${GEMINI_VERSION##*/}"
TAG="$(date -u +%Y%m%d%H%M%S)"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/rtc-gcp/analisis:${TAG}"
gcloud builds submit "$HERE" --project="$PROJECT" --region="$REGION" \
  --config="$HERE/cloudbuild.yaml" --service-account="projects/$PROJECT/serviceAccounts/rtc-gcp-builder@$PROJECT.iam.gserviceaccount.com" \
  --gcs-source-staging-dir="gs://${PROJECT}-rtc-build-src/source" --substitutions="_IMAGE=$IMAGE"
# Persist only non-secret desired settings, ignored by Git, for repeatable updates/teardown.
python3 - "$HERE/infra/deployment.auto.tfvars.json" "$PROJECT" "$REGION" "$IMAGE" "$API_VERSION" "$GEMINI_VERSION" <<'PY'
import json,sys
from pathlib import Path
path,project,region,image,api,gemini=sys.argv[1:]
p=Path(path)
settings=json.loads(p.read_text()) if p.exists() else {}
settings.update(project_id=project,region=region,image_uri=image,deploy_service=True,
                api_key_version=api,enable_gemini=bool(gemini),gemini_key_version=gemini or '1')
p.write_text(json.dumps(settings,indent=2)+'\n')
PY
terraform -chdir="$HERE/infra" plan -out=deployment.tfplan
terraform -chdir="$HERE/infra" apply deployment.tfplan
terraform -chdir="$HERE/infra" output -raw cloud_run_url
