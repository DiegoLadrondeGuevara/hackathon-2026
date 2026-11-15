#!/usr/bin/env bash
# Explicit teardown. Without --destroy this only inspects local state.
set -Eeuo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="${1:?Usage: cleanup.sh PROJECT_ID [--destroy]}"
[[ -f "$HERE/infra/deployment.auto.tfvars.json" ]] || { echo 'Use the original deployment directory/state.' >&2; exit 2; }
python3 - "$HERE/infra/deployment.auto.tfvars.json" "$PROJECT" <<'PY'
import json,sys
if json.load(open(sys.argv[1]))['project_id'] != sys.argv[2]: raise SystemExit('Project mismatch')
PY
terraform -chdir="$HERE/infra" state list
[[ "${2:-}" == --destroy ]] || exit 0
read -r -p "Delete service, history, secrets and build artifacts? Type BORRAR $PROJECT: " answer
[[ "$answer" == "BORRAR $PROJECT" ]] || exit 2
# Table deletion protection must first be updated in state. Both plans remain reviewable.
terraform -chdir="$HERE/infra" apply -var=protect_data=false
terraform -chdir="$HERE/infra" destroy -var=protect_data=false
