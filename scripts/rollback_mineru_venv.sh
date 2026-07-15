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
  case "/$value/" in
    *"/../"*|*"/./"*) die "$label must not contain traversal components: $value" ;;
  esac
}

target=""
backup=""
check_script=""
rebuild_script="${ROOT_DIR}/scripts/rebuild_mineru_venv.py"
mineru_version="3.4.2"

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
      rebuild_script="$2"
      shift 2
      ;;
    --mineru-version)
      require_value "$1" "${2:-}"
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

[[ ! -L "$target" ]] || die "target must not be a symlink: $target"
[[ -d "$target" ]] || die "target must be an existing directory: $target"
[[ ! -L "$backup" ]] || die "backup must not be a symlink: $backup"
[[ -d "$backup" ]] || die "backup must be an existing directory: $backup"
[[ ! -L "$check_script" ]] || die "check-script must not be a symlink: $check_script"
[[ -f "$check_script" ]] || die "check-script must be an existing file: $check_script"
[[ ! -L "$rebuild_script" ]] || die "rebuild-script must not be a symlink: $rebuild_script"
[[ -f "$rebuild_script" ]] || die "rebuild-script must be an existing file: $rebuild_script"

target_parent="$(dirname -- "$target")"
backup_parent="$(dirname -- "$backup")"
target_name="$(basename -- "$target")"
backup_name="$(basename -- "$backup")"
[[ "$backup_parent" == "$target_parent" ]] || die "target and backup must have the same parent"
backup_prefix="${target_name}.bak-"
[[ "$backup_name" == "${backup_prefix}"* ]] || die "backup name must match ${backup_prefix}*"
backup_suffix="${backup_name#"$backup_prefix"}"
[[ -n "$backup_suffix" ]] || die "backup name must include a non-empty suffix"
case "$backup_suffix" in
  *[!A-Za-z0-9._-]*) die "backup suffix contains unsafe characters: $backup_suffix" ;;
esac

operation_id="${MINERU_ROLLBACK_OPERATION_ID:-$(date -u +%Y%m%dT%H%M%SZ)-$$-${RANDOM}}"
case "$operation_id" in
  ""|*[!A-Za-z0-9._-]*) die "rollback operation id contains unsafe characters" ;;
esac
prior="${target}.failed-${operation_id}"
rejected="${target}.rejected-${operation_id}"
if [[ -e "$prior" || -L "$prior" ]]; then
  die "reserved prior path already exists; refusing to overwrite: $prior"
fi
if [[ -e "$rejected" || -L "$rejected" ]]; then
  die "reserved rejected path already exists; refusing to overwrite: $rejected"
fi

restore_prior() {
  if [[ -e "$target" || -L "$target" ]]; then
    echo "ERROR: cannot restore prior active because target is occupied: $target" >&2
    echo "MANUAL RECOVERY: preserve $prior and move it to $target only after clearing the occupied target." >&2
    return 1
  fi
  if mv -- "$prior" "$target"; then
    echo "Prior active restored at: $target" >&2
    return 0
  fi
  echo "ERROR: automatic prior restore failed." >&2
  echo "MANUAL RECOVERY: move $prior to $target; do not start the service until verification succeeds." >&2
  return 1
}

if ! mv -- "$target" "$prior"; then
  echo "ERROR: could not preserve prior active at: $prior" >&2
  exit 1
fi

if ! mv -- "$backup" "$target"; then
  echo "ERROR: candidate activation rename failed: $backup -> $target" >&2
  if restore_prior; then
    echo "Candidate activation failed; prior active was restored." >&2
  fi
  exit 1
fi

if [[ -x "$rebuild_script" ]]; then
  verify_command=("$rebuild_script")
else
  verify_command=(python3 "$rebuild_script")
fi
verify_command+=(
  --verify-only
  --target "$target"
  --mineru-version "$mineru_version"
  --check-script "$check_script"
)

if ! "${verify_command[@]}"; then
  echo "ERROR: rollback candidate failed readiness or exact version verification." >&2
  if ! mv -- "$target" "$rejected"; then
    echo "ERROR: could not preserve rejected candidate." >&2
    echo "MANUAL RECOVERY: candidate remains at $target; prior active remains at $prior." >&2
    exit 1
  fi
  if ! restore_prior; then
    echo "Rejected candidate retained at: $rejected" >&2
    exit 1
  fi
  echo "Rejected candidate retained at: $rejected" >&2
  echo "Service must remain stopped." >&2
  exit 1
fi

echo "Rollback candidate verified: $target"
echo "Prior active retained at: $prior"
