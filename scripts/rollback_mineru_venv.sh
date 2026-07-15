#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'EOF'
Usage: rollback_mineru_venv.sh \
  --target /absolute/path/mineru-venv \
  --backup /absolute/path/mineru-venv.bak-TIMESTAMP \
  --check-script /absolute/path/check_mineru.py \
  [--rebuild-script /absolute/path/rebuild_mineru_venv.py] \
  [--mineru-version 3.4.2]
EOF
}

die() {
  echo "ERROR: $1" >&2
  exit 2
}

require_value() {
  local option="$1"
  local value="${2:-}"
  [[ -n "$value" ]] || die "$option requires a value"
}

validate_absolute_path() {
  local label="$1"
  local value="$2"
  [[ "$value" == /* ]] || die "$label must be absolute: $value"
  case "$value" in
    */../*|*/./*|*/..|*/.) die "$label must not contain traversal components: $value" ;;
  esac
}

target=""
backup=""
check_script=""
rebuild_script="${ROOT_DIR}/scripts/rebuild_mineru_venv.py"
mineru_version="3.4.2"
seen_rebuild_script=false
seen_mineru_version=false

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --target)
      require_value "$1" "${2:-}"
      [[ -z "$target" ]] || die "duplicate --target"
      target="$2"
      shift 2
      ;;
    --backup)
      require_value "$1" "${2:-}"
      [[ -z "$backup" ]] || die "duplicate --backup"
      backup="$2"
      shift 2
      ;;
    --check-script)
      require_value "$1" "${2:-}"
      [[ -z "$check_script" ]] || die "duplicate --check-script"
      check_script="$2"
      shift 2
      ;;
    --rebuild-script)
      require_value "$1" "${2:-}"
      [[ "$seen_rebuild_script" == false ]] || die "duplicate --rebuild-script"
      seen_rebuild_script=true
      rebuild_script="$2"
      shift 2
      ;;
    --mineru-version)
      require_value "$1" "${2:-}"
      [[ "$seen_mineru_version" == false ]] || die "duplicate --mineru-version"
      seen_mineru_version=true
      mineru_version="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

[[ -n "$target" ]] || die "--target is required"
[[ -n "$backup" ]] || die "--backup is required"
[[ -n "$check_script" ]] || die "--check-script is required"

validate_absolute_path "target" "$target"
validate_absolute_path "backup" "$backup"
validate_absolute_path "check-script" "$check_script"
validate_absolute_path "rebuild-script" "$rebuild_script"

command=(
  python3
  "$rebuild_script"
  --rollback-backup "$backup"
  --target "$target"
  --mineru-version "$mineru_version"
  --check-script "$check_script"
)
exec "${command[@]}"
