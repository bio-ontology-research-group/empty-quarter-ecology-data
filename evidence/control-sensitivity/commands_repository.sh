# Repository-layout replay; set PROJECT_ROOT to the source checkout.
: "${PROJECT_ROOT:?set PROJECT_ROOT to the source checkout}"
#!/usr/bin/env bash
set -euo pipefail

project_root=${PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}
exec bash "$project_root/scripts/controls/run_control_ecology_sensitivity.sh" \
  "$project_root" "$project_root/analysis/v3/control_sensitivity"
