#!/usr/bin/env bash
# shellcheck shell=bash

cmd_qa() {
  local kind="${1:-all}"; shift || true
  local root=""
  local api_base="${GC_API_BASE_URL:-http://localhost:3000/api/v1}"
  local api_health="${GC_API_HEALTH_URL:-}"
  local web_url="${GC_WEB_URL:-http://localhost:8080/}"
  local admin_url="${GC_ADMIN_URL:-http://localhost:8080/admin/}"
  local api_base_override=0 api_health_override=0 web_url_override=0 admin_url_override=0
  local mobile_dir="${GC_MOBILE_APP_DIR:-}"
  local detox_config_ios="${GC_DETOX_CONFIG_IOS:-}"
  local detox_config_android="${GC_DETOX_CONFIG_ANDROID:-}"
  local detox_args="${GC_DETOX_ARGS:-}"
  local maestro_flows_dir="${GC_MAESTRO_FLOWS_DIR:-}"
  local maestro_device="${GC_MAESTRO_DEVICE:-}"
  local maestro_device_ios="${GC_MAESTRO_DEVICE_IOS:-}"
  local maestro_device_android="${GC_MAESTRO_DEVICE_ANDROID:-}"
  local maestro_args="${GC_MAESTRO_ARGS:-}"
  local mobile_optional="${GC_MOBILE_OPTIONAL:-0}"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project) root="$(abs_path "$2")"; shift 2;;
      --api-url) api_base="$2"; api_base_override=1; shift 2;;
      --api-health) api_health="$2"; api_health_override=1; shift 2;;
      --web-url) web_url="$2"; web_url_override=1; shift 2;;
      --admin-url) admin_url="$2"; admin_url_override=1; shift 2;;
      --mobile-dir) mobile_dir="$2"; shift 2;;
      --detox-config-ios) detox_config_ios="$2"; shift 2;;
      --detox-config-android) detox_config_android="$2"; shift 2;;
      --detox-args) detox_args="$2"; shift 2;;
      --maestro-flows) maestro_flows_dir="$2"; shift 2;;
      --maestro-device) maestro_device="$2"; shift 2;;
      --maestro-device-ios) maestro_device_ios="$2"; shift 2;;
      --maestro-device-android) maestro_device_android="$2"; shift 2;;
      --maestro-args) maestro_args="$2"; shift 2;;
      --mobile-optional|--allow-mobile-skip) mobile_optional=1; shift;;
      *) break;;
    esac
  done
  if [[ "$mobile_optional" == "true" || "$mobile_optional" == "yes" ]]; then
    mobile_optional=1
  elif [[ "$mobile_optional" == "false" ]]; then
    mobile_optional=0
  fi
  ensure_ctx "$root"
  if [[ -z "$mobile_dir" ]]; then
    if [[ -d "${PROJECT_ROOT}/apps/mobile" ]]; then
      mobile_dir="${PROJECT_ROOT}/apps/mobile"
    elif [[ -d "${PROJECT_ROOT}/mobile" ]]; then
      mobile_dir="${PROJECT_ROOT}/mobile"
    else
      mobile_dir="${PROJECT_ROOT}"
    fi
  fi
  if [[ -z "$maestro_flows_dir" ]]; then
    if [[ -d "${mobile_dir}/maestro" ]]; then
      maestro_flows_dir="${mobile_dir}/maestro"
    elif [[ -d "${PROJECT_ROOT}/maestro" ]]; then
      maestro_flows_dir="${PROJECT_ROOT}/maestro"
    fi
  fi

  kind="$(printf '%s' "$kind" | tr '[:upper:]' '[:lower:]')"

  local compose_file="${PROJECT_ROOT}/docker/docker-compose.yml"
  local ports_updated=0
  if [[ -f "$compose_file" ]]; then
    local detected
    if detected="$(gc_compose_port "$compose_file" api 3000)"; then
      if [[ -n "$detected" && "$detected" != "$GC_API_HOST_PORT" ]]; then
        GC_API_HOST_PORT="$detected"; API_HOST_PORT="$detected"; ports_updated=1
      fi
    fi
    if detected="$(gc_compose_port "$compose_file" web 5173)"; then
      if [[ -n "$detected" && "$detected" != "$GC_WEB_HOST_PORT" ]]; then
        GC_WEB_HOST_PORT="$detected"; WEB_HOST_PORT="$detected"; ports_updated=1
      fi
    fi
    if detected="$(gc_compose_port "$compose_file" admin 5174)"; then
      if [[ -n "$detected" && "$detected" != "$GC_ADMIN_HOST_PORT" ]]; then
        GC_ADMIN_HOST_PORT="$detected"; ADMIN_HOST_PORT="$detected"; ports_updated=1
      fi
    fi
    if detected="$(gc_compose_port "$compose_file" proxy 80)"; then
      if [[ -n "$detected" && "$detected" != "$GC_PROXY_HOST_PORT" ]]; then
        GC_PROXY_HOST_PORT="$detected"; PROXY_HOST_PORT="$detected"; ports_updated=1
      fi
    fi
  fi
  (( ports_updated )) && gc_env_sync_ports

  if (( api_base_override == 0 )); then
    api_base="${GC_API_BASE_URL:-$api_base}"
  fi
  if (( web_url_override == 0 )); then
    web_url="${GC_WEB_URL:-$web_url}"
  fi
  if (( admin_url_override == 0 )); then
    admin_url="${GC_ADMIN_URL:-$admin_url}"
  fi
  if (( api_health_override == 0 )); then
    api_health="${GC_API_HEALTH_URL:-$api_health}"
  fi

  local trimmed_base="${api_base%/}"
  api_health="${api_health:-${trimmed_base}/health}"

  local verify_root="$CLI_ROOT/verify"
  [[ -d "$verify_root" ]] || die "verify scripts directory missing at ${verify_root}"

  case "$kind" in
    program_filters) kind="program-filters" ;;
    program-filters|acceptance|openapi|a11y|lighthouse|consent|telemetry|mobile|mobile-detox|mobile-maestro|nfr|all) ;;
    *) die "Unknown verify target: ${kind}";;
  esac

  local -a check_names
  case "$kind" in
    acceptance) check_names=(acceptance) ;;
    openapi|a11y|lighthouse|consent|program-filters|telemetry|mobile-detox|mobile-maestro)
      check_names=("$kind")
      ;;
    mobile)
      check_names=(mobile-detox mobile-maestro)
      ;;
    nfr)
      check_names=(openapi a11y lighthouse consent program-filters telemetry)
      ;;
    all)
      check_names=(acceptance openapi a11y lighthouse consent program-filters telemetry mobile-detox mobile-maestro)
      ;;
  esac

  local summary_dir="${PROJECT_ROOT}/.gpt-creator/staging/verify"
  local logs_dir="${summary_dir}/logs"
  mkdir -p "$summary_dir" "$logs_dir"

  local summary_path="${summary_dir}/summary.json"
  local python_available=0
  local python_bin=""
  if command -v python3 >/dev/null 2>&1; then
    python_available=1
    python_bin="$(command -v python3)"
  fi
  local check_order="acceptance,openapi,lighthouse,a11y,consent,program-filters,telemetry,mobile-detox,mobile-maestro"

  local pass=0 fail=0 skip=0

  # verification summary handled inline

  run_check() {
    local require_success=0
    if [[ "${1:-}" == "--require" ]]; then
      require_success=1
      shift
    fi
    local name="$1"; shift
    local label="$1"; shift
    local -a cmd=("$@")
    local timestamp
    timestamp="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    local stamp
    stamp="$(date -u +"%Y%m%d-%H%M%S")"
    local log_file="${logs_dir}/${stamp}-${name}.log"
    SECONDS=0
    set +e
    "${cmd[@]}" 2>&1 | tee "$log_file"
    local exit_status=${PIPESTATUS[0]}
    set -e
    local duration="$SECONDS"
    local status message
    case "$exit_status" in
      0)
        status="pass"
        message="${label} checks passed."
        ((pass++))
        ;;
      3)
        status="skip"
        message="${label} check skipped (missing dependency)."
        if (( require_success )); then
          status="fail"
          message="${label} check required but skipped (missing dependency)."
          ((fail++))
          warn "${label} check required but skipped (missing dependency)"
        else
          ((skip++))
          warn "${label} check skipped (missing dependency)"
        fi
        ;;
      *)
        status="fail"
        message="${label} check failed (exit ${exit_status})."
        ((fail++))
        warn "${label} check failed (exit ${exit_status})"
        ;;
    esac
    cp -f "$log_file" "${logs_dir}/${name}-latest.log" 2>/dev/null || true
    local log_rel="${log_file#$PROJECT_ROOT/}"
    log_rel="${log_rel#./}"
    if [[ "$python_available" -eq 1 ]]; then
      local event=""
      local py_cmd=$'import json, os, sys, datetime
path = sys.argv[1]
root = os.environ.get("PROJECT_ROOT", "")
name = os.environ.get("CHECK_NAME", "")
if not name:
    sys.exit(0)
label = os.environ.get("CHECK_LABEL", name.title())
status = os.environ.get("CHECK_STATUS", "unknown")
message = os.environ.get("CHECK_MESSAGE", "")
log_path = os.environ.get("CHECK_LOG", "")
report_path = os.environ.get("CHECK_REPORT", "")
score_raw = os.environ.get("CHECK_SCORE", "")
duration_raw = os.environ.get("CHECK_DURATION", "")
run_kind = os.environ.get("CHECK_RUN_KIND", "")
timestamp = os.environ.get("CHECK_TIMESTAMP", datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z")
order_raw = os.environ.get("CHECK_ORDER", "")

def relify(path_value):
    if not path_value:
        return ""
    if not os.path.isabs(path_value) and root:
        abs_path = os.path.normpath(os.path.join(root, path_value))
    else:
        abs_path = os.path.normpath(path_value)
    if root:
        try:
            rel = os.path.relpath(abs_path, root)
        except Exception:
            rel = abs_path
    else:
        rel = abs_path
    return rel.replace(os.sep, "/")

score = None
if score_raw:
    try:
        score = float(score_raw)
    except Exception:
        score = None

duration_value = None
if duration_raw:
    try:
        duration_value = float(duration_raw)
    except Exception:
        duration_value = None

log_path = relify(log_path)
report_path = relify(report_path)

summary = {
    "name": name,
    "label": label,
    "status": status,
    "message": message,
    "log": log_path,
    "report": report_path,
    "score": score,
    "duration": duration_value,
    "run_kind": run_kind,
    "timestamp": timestamp,
}

order = [item.strip() for item in order_raw.split(",") if item.strip()]

try:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    data = {}

if order:
    data["order"] = order
data.setdefault("runs", [])
data["runs"].append(summary)

with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, ensure_ascii=False, indent=2)

print(json.dumps(summary, ensure_ascii=False))'
      event="$(
        CHECK_NAME="$name" \
        CHECK_STATUS="$status" \
        CHECK_LABEL="$label" \
        CHECK_MESSAGE="$message" \
        CHECK_LOG="$log_rel" \
        CHECK_REPORT="" \
        CHECK_SCORE="" \
        CHECK_DURATION="$duration" \
        CHECK_RUN_KIND="$kind" \
        CHECK_TIMESTAMP="$timestamp" \
        CHECK_ORDER="$check_order" \
        PROJECT_ROOT="$PROJECT_ROOT" \
        "$python_bin" -c "$py_cmd" "$summary_path" 2>/dev/null
      )"
      if [[ -n "$event" ]]; then
        printf '::verify::%s\n' "$event"
      fi
    fi
    return 0
  }

  find_openapi_candidate() {
    local spec=""
    for cand in "$INPUT_DIR/openapi.yaml" "$INPUT_DIR/openapi.yml" "$INPUT_DIR/openapi.json"; do
      if [[ -f "$cand" ]]; then
        spec="$cand"
        break
      fi
    done
    printf '%s' "$spec"
  }

  for name in "${check_names[@]}"; do
    case "$name" in
      acceptance)
        run_check "acceptance" "Acceptance" \
          env PROJECT_ROOT="$PROJECT_ROOT" GC_COMPOSE_FILE="$compose_file" \
          bash "$verify_root/acceptance.sh" "${api_base}" "${web_url}" "${admin_url}" "${api_health}"
        ;;
      openapi)
        run_check "openapi" "OpenAPI" \
          bash "$verify_root/check-openapi.sh" "$(find_openapi_candidate)"
        ;;
      a11y)
        run_check "a11y" "Accessibility" \
          bash "$verify_root/check-a11y.sh" "${web_url}" "${admin_url}"
        ;;
      lighthouse)
        run_check "lighthouse" "Lighthouse" \
          bash "$verify_root/check-lighthouse.sh" "${web_url}" "${admin_url}"
        ;;
      consent)
        run_check "consent" "Consent" \
          bash "$verify_root/check-consent.sh" "${web_url}"
        ;;
      program-filters)
        run_check "program-filters" "Program Filters" \
          bash "$verify_root/check-program-filters.sh" "${api_base}"
        ;;
      telemetry)
        run_check "telemetry" "Telemetry" \
          bash "$verify_root/check-telemetry.sh"
        ;;
      mobile-detox)
        if (( mobile_optional )); then
          run_check "mobile-detox" "Mobile (Detox)" \
            env PROJECT_ROOT="$PROJECT_ROOT" \
              GC_MOBILE_APP_DIR="$mobile_dir" \
              GC_DETOX_CONFIG_IOS="$detox_config_ios" \
              GC_DETOX_CONFIG_ANDROID="$detox_config_android" \
              GC_DETOX_ARGS="$detox_args" \
              GC_MOBILE_OPTIONAL="$mobile_optional" \
            bash "$verify_root/mobile-detox.sh"
        else
          run_check --require "mobile-detox" "Mobile (Detox)" \
            env PROJECT_ROOT="$PROJECT_ROOT" \
              GC_MOBILE_APP_DIR="$mobile_dir" \
              GC_DETOX_CONFIG_IOS="$detox_config_ios" \
              GC_DETOX_CONFIG_ANDROID="$detox_config_android" \
              GC_DETOX_ARGS="$detox_args" \
              GC_MOBILE_OPTIONAL="$mobile_optional" \
            bash "$verify_root/mobile-detox.sh"
        fi
        ;;
      mobile-maestro)
        if (( mobile_optional )); then
          run_check "mobile-maestro" "Mobile (Maestro)" \
            env PROJECT_ROOT="$PROJECT_ROOT" \
              GC_MOBILE_APP_DIR="$mobile_dir" \
              GC_MAESTRO_FLOWS_DIR="$maestro_flows_dir" \
              GC_MAESTRO_DEVICE="$maestro_device" \
              GC_MAESTRO_DEVICE_IOS="$maestro_device_ios" \
              GC_MAESTRO_DEVICE_ANDROID="$maestro_device_android" \
              GC_MAESTRO_ARGS="$maestro_args" \
              GC_MOBILE_OPTIONAL="$mobile_optional" \
            bash "$verify_root/mobile-maestro.sh"
        else
          run_check --require "mobile-maestro" "Mobile (Maestro)" \
            env PROJECT_ROOT="$PROJECT_ROOT" \
              GC_MOBILE_APP_DIR="$mobile_dir" \
              GC_MAESTRO_FLOWS_DIR="$maestro_flows_dir" \
              GC_MAESTRO_DEVICE="$maestro_device" \
              GC_MAESTRO_DEVICE_IOS="$maestro_device_ios" \
              GC_MAESTRO_DEVICE_ANDROID="$maestro_device_android" \
              GC_MAESTRO_ARGS="$maestro_args" \
              GC_MOBILE_OPTIONAL="$mobile_optional" \
            bash "$verify_root/mobile-maestro.sh"
        fi
        ;;
    esac
  done

  if (( fail > 0 )); then
    die "QA failed — pass=${pass} fail=${fail} skip=${skip}"
  fi
  ok "QA complete — pass=${pass} skip=${skip}"
}
