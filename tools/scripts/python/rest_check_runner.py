#!/usr/bin/env python3
"""
Reusable REST check runner for GPT Creator agents.

Given a YAML or TOML manifest that defines a list of HTTP checks, this script
sends each request, evaluates expectations, and prints a compact report that can
be consumed by humans or other tooling.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

try:
    import httpx
except ImportError as exc:  # pragma: no cover
    raise SystemExit("httpx is required. Install with `pip install httpx`.") from exc

ENV_PATTERN = re.compile(r"\{\{\s*env:([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


@dataclass
class CheckResult:
    name: str
    success: bool
    status_code: Optional[int]
    elapsed_ms: Optional[float]
    details: List[str] = field(default_factory=list)
    error: Optional[str] = None
    attempt: int = 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run HTTP checks defined in a YAML/TOML manifest.",
    )
    parser.add_argument("manifest", help="Path to the manifest file.")
    parser.add_argument(
        "--only",
        help="Comma separated glob(s) of check names to run (e.g. 'health,users-*').",
    )
    parser.add_argument(
        "--skip",
        help="Comma separated glob(s) of check names to skip.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop after the first failure.",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Summary output format. Text is always printed; JSON is appended.",
    )
    parser.add_argument(
        "--env-file",
        action="append",
        default=[],
        help="Optional .env file(s) to load before resolving placeholders.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and list checks without executing any HTTP requests.",
    )
    return parser.parse_args()


def load_env_files(paths: Iterable[str]) -> None:
    for path in paths:
        env_path = Path(path).expanduser()
        if not env_path.exists():
            raise SystemExit(f".env file not found: {env_path}")
        for raw_line in env_path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def load_manifest(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Manifest not found: {path}")
    ext = path.suffix.lower()
    text = path.read_text()
    if ext in {".yaml", ".yml"}:
        if yaml is None:  # pragma: no cover
            raise SystemExit("PyYAML is required for YAML manifests. `pip install pyyaml`.")
        data = yaml.safe_load(text)
    elif ext == ".toml":
        data = load_toml(text)
    else:
        raise SystemExit("Unsupported manifest format. Use .yaml, .yml, or .toml.")

    if not isinstance(data, dict):
        raise SystemExit("Manifest root must be a mapping/object.")

    return data


def load_toml(text: str) -> Dict[str, Any]:
    try:
        import tomllib as toml_lib  # type: ignore
    except ModuleNotFoundError:  # pragma: no cover
        try:
            import tomli as toml_lib  # type: ignore
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise SystemExit("tomllib/tomli not found; install tomli for Python < 3.11") from exc
    loaded = toml_lib.loads(text)
    if not isinstance(loaded, dict):
        raise SystemExit("TOML manifest root must be a table/object.")
    return loaded


def resolve_placeholders(obj: Any) -> Any:
    if isinstance(obj, str):
        def _replace(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in os.environ:
                raise SystemExit(f"Environment variable '{key}' required but not set.")
            return os.environ[key]

        return ENV_PATTERN.sub(_replace, obj)
    if isinstance(obj, list):
        return [resolve_placeholders(item) for item in obj]
    if isinstance(obj, dict):
        return {key: resolve_placeholders(value) for key, value in obj.items()}
    return obj


def merge_values(base: Any, override: Any) -> Any:
    if base is None:
        return override
    if override is None:
        return base
    if isinstance(base, dict) and isinstance(override, dict):
        merged: Dict[Any, Any] = {}
        for key in base.keys() | override.keys():
            if key in base and key in override:
                merged[key] = merge_values(base[key], override[key])
            elif key in base:
                merged[key] = base[key]
            else:
                merged[key] = override[key]
        return merged
    if isinstance(base, list) and isinstance(override, list):
        return base + override
    return override


def build_dotted_path(data: Any, path: str) -> Tuple[bool, Any]:
    current = data
    for part in path.split("."):
        if isinstance(current, dict):
            if part not in current:
                return False, None
            current = current[part]
            continue
        if isinstance(current, list):
            if not part.isdigit():
                return False, None
            index = int(part)
            if index >= len(current):
                return False, None
            current = current[index]
            continue
        return False, None
    return True, current


def evaluate_expectations(expect: Dict[str, Any], response: httpx.Response) -> Tuple[bool, List[str]]:
    if not expect:
        return True, []
    reasons: List[str] = []
    status = expect.get("status") or expect.get("status_in")
    if status is not None:
        expected_codes = status if isinstance(status, list) else [status]
        if response.status_code not in expected_codes:
            reasons.append(f"status {response.status_code} not in expected {expected_codes}")
    max_latency = expect.get("max_latency_ms")
    elapsed_ms = response.elapsed.total_seconds() * 1000 if response.elapsed else None
    if max_latency is not None and elapsed_ms is not None and elapsed_ms > max_latency:
        reasons.append(f"latency {elapsed_ms:.1f}ms exceeds {max_latency}ms")

    body_contains = expect.get("body_contains")
    if body_contains is not None:
        text = response.text
        checks = body_contains if isinstance(body_contains, list) else [body_contains]
        for needle in checks:
            if needle not in text:
                reasons.append(f"body missing substring '{needle}'")

    body_not_contains = expect.get("body_not_contains")
    if body_not_contains is not None:
        text = response.text
        checks = body_not_contains if isinstance(body_not_contains, list) else [body_not_contains]
        for needle in checks:
            if needle in text:
                reasons.append(f"body contains forbidden substring '{needle}'")

    header_expect = expect.get("headers")
    if header_expect:
        response_headers = {k.lower(): v for k, v in response.headers.items()}
        for key, expected in header_expect.items():
            actual = response_headers.get(key.lower())
            if actual is None:
                reasons.append(f"header '{key}' missing")
            elif str(actual).lower() != str(expected).lower():
                reasons.append(f"header '{key}' mismatch (got '{actual}')")

    json_equals = expect.get("json_equals")
    json_exists = expect.get("json_exists")
    json_not_null = expect.get("json_not_null")
    json_body: Any = None
    json_error: Optional[str] = None
    if any([json_equals, json_exists, json_not_null]):
        try:
            json_body = response.json()
        except ValueError as exc:  # pragma: no cover
            json_error = str(exc)
            reasons.append(f"response body is not valid JSON: {exc}")

    if json_equals and json_body is not None:
        for path, expected in json_equals.items():
            found, value = build_dotted_path(json_body, path)
            if not found:
                reasons.append(f"json path '{path}' missing")
            elif value != expected:
                reasons.append(f"json path '{path}' expected '{expected}' got '{value}'")

    if json_exists and json_body is not None:
        checks = json_exists if isinstance(json_exists, list) else [json_exists]
        for path in checks:
            found, _ = build_dotted_path(json_body, path)
            if not found:
                reasons.append(f"json path '{path}' missing")

    if json_not_null and json_body is not None:
        checks = json_not_null if isinstance(json_not_null, list) else [json_not_null]
        for path in checks:
            found, value = build_dotted_path(json_body, path)
            if not found or value in (None, "", []):
                reasons.append(f"json path '{path}' null/empty")

    return not reasons, reasons


def matches_filters(name: str, only: Optional[List[str]], skip: Optional[List[str]]) -> bool:
    if only and not any(fnmatch(name, pattern) for pattern in only):
        return False
    if skip and any(fnmatch(name, pattern) for pattern in skip):
        return False
    return True


def as_list(arg: Optional[str]) -> Optional[List[str]]:
    if not arg:
        return None
    patterns = [item.strip() for item in arg.split(",") if item.strip()]
    return patterns or None


def merge_simple(*dicts: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for data in dicts:
        if not data:
            continue
        merged.update(data)
    return merged


def resolve_check_name(check: Dict[str, Any]) -> str:
    request_cfg = check.get("request") or {}
    return check.get("name") or request_cfg.get("name") or request_cfg.get("url") or check.get("url") or "unnamed-check"


def run_check(
    client: httpx.Client,
    check: Dict[str, Any],
    defaults: Dict[str, Any],
    base_headers: Dict[str, Any],
    base_params: Dict[str, Any],
    base_cookies: Dict[str, Any],
    default_expect: Dict[str, Any],
    default_timeout: float,
    default_method: str,
    default_retries: int,
    default_backoff: float,
) -> CheckResult:
    name = resolve_check_name(check)
    request_cfg = merge_simple(defaults.get("request"), check.get("request"))
    method = (request_cfg or {}).get("method") or check.get("method") or default_method
    url = (request_cfg or {}).get("url") or check.get("url")
    if not url:
        raise SystemExit(f"Check '{name}' missing request.url")
    headers = merge_simple(base_headers, request_cfg.get("headers"), check.get("headers"))
    params = merge_simple(base_params, request_cfg.get("params"), check.get("params"))
    cookies = merge_simple(base_cookies, request_cfg.get("cookies"), check.get("cookies"))
    timeout = (
        check.get("timeout")
        or (request_cfg or {}).get("timeout")
        or defaults.get("timeout")
        or default_timeout
    )
    retries = check.get("retries", defaults.get("retries", default_retries))
    backoff = check.get("retry_backoff_seconds", defaults.get("retry_backoff_seconds", default_backoff))

    payload: Dict[str, Any] = {}
    for key in ("json", "data", "content"):
        if key in request_cfg:
            payload[key] = request_cfg[key]
    for key in ("json", "data", "content"):
        if key in check:
            payload[key] = check[key]

    expect = merge_values(default_expect, check.get("expect"))

    attempts = retries + 1
    last_error: Optional[str] = None
    last_details: List[str] = []

    for attempt in range(1, attempts + 1):
        started = time.time()
        try:
            response = client.request(
                method=method,
                url=url,
                headers=headers or None,
                params=merge_simple(params, payload.get("params")),
                cookies=cookies or None,
                timeout=timeout,
                json=payload.get("json"),
                data=payload.get("data"),
                content=payload.get("content"),
            )
        except httpx.HTTPError as exc:
            last_error = str(exc)
            if attempt == attempts:
                elapsed_ms = (time.time() - started) * 1000
                return CheckResult(
                    name=name,
                    success=False,
                    status_code=None,
                    elapsed_ms=elapsed_ms,
                    error=last_error,
                    details=[],
                    attempt=attempt,
                )
            time.sleep(backoff * attempt)
            continue

        ok, details = evaluate_expectations(expect or {}, response)
        elapsed_ms = response.elapsed.total_seconds() * 1000 if response.elapsed else None
        if ok:
            return CheckResult(
                name=name,
                success=True,
                status_code=response.status_code,
                elapsed_ms=elapsed_ms,
                details=[],
                attempt=attempt,
            )
        last_details = details
        if attempt == attempts:
            snippet = response.text[:400].replace("\n", " ") if response.text else ""
            if snippet:
                last_details.append(f"body snippet: {snippet}...")
            return CheckResult(
                name=name,
                success=False,
                status_code=response.status_code,
                elapsed_ms=elapsed_ms,
                details=last_details,
                attempt=attempt,
            )
        time.sleep(backoff * attempt)

    return CheckResult(
        name=name,
        success=False,
        status_code=None,
        elapsed_ms=None,
        error=last_error,
        details=last_details,
    )


def main() -> None:
    args = parse_args()
    load_env_files(args.env_file)

    manifest_path = Path(args.manifest)
    manifest = load_manifest(manifest_path)
    manifest = resolve_placeholders(manifest)

    checks = manifest.get("checks")
    if not isinstance(checks, list) or not checks:
        raise SystemExit("Manifest must define a non-empty 'checks' list.")

    defaults = manifest.get("defaults", {})
    base_headers = merge_simple(
        manifest.get("default_headers"),
        defaults.get("headers"),
        (manifest.get("auth") or {}).get("headers"),
    )
    base_params = merge_simple(
        defaults.get("params"),
        (manifest.get("auth") or {}).get("query"),
    )
    base_cookies = merge_simple(
        defaults.get("cookies"),
        (manifest.get("auth") or {}).get("cookies"),
    )

    default_expect = defaults.get("expect") or {}
    default_timeout = defaults.get("timeout", 15)
    default_method = defaults.get("method", "GET")
    default_retries = defaults.get("retries", 0)
    default_backoff = defaults.get("retry_backoff_seconds", 1.0)

    only_filters = as_list(args.only)
    skip_filters = as_list(args.skip)

    selected_checks = [
        check for check in checks if matches_filters(resolve_check_name(check), only_filters, skip_filters)
    ]
    if not selected_checks:
        raise SystemExit("Filter removed all checks; nothing to do.")

    if args.dry_run:
        print(f"[dry-run] {len(selected_checks)} checks loaded from {manifest_path}")
        for check in selected_checks:
            print(f" - {resolve_check_name(check)}")
        return

    base_url = manifest.get("base_url")
    follow_redirects = defaults.get("follow_redirects", True)
    verify = manifest.get("verify_ssl", defaults.get("verify_ssl", True))
    transport_kwargs = {}
    if isinstance(verify, bool):
        transport_kwargs["verify"] = verify

    client = httpx.Client(
        base_url=base_url or None,
        timeout=default_timeout,
        follow_redirects=follow_redirects,
        **transport_kwargs,
    )

    results: List[CheckResult] = []
    try:
        for check in selected_checks:
            name = resolve_check_name(check)
            result = run_check(
                client=client,
                check=check,
                defaults=defaults,
                base_headers=base_headers,
                base_params=base_params,
                base_cookies=base_cookies,
                default_expect=default_expect,
                default_timeout=default_timeout,
                default_method=default_method,
                default_retries=default_retries,
                default_backoff=default_backoff,
            )
            results.append(result)
            status_text = f"{result.status_code}" if result.status_code is not None else "N/A"
            elapsed_text = f"{result.elapsed_ms:.1f}ms" if result.elapsed_ms is not None else "N/A"
            prefix = "[PASS]" if result.success else "[FAIL]"
            attempt_note = f" (attempt {result.attempt})" if result.attempt > 1 else ""
            print(f"{prefix} {name} -> {status_text}, {elapsed_text}{attempt_note}")
            if not result.success:
                if result.error:
                    print(f"       error: {result.error}")
                for detail in result.details:
                    print(f"       - {detail}")
                if args.fail_fast:
                    break
    finally:
        client.close()

    passed = sum(1 for r in results if r.success)
    failed = sum(1 for r in results if not r.success)

    print(f"\nSummary: {passed} passed, {failed} failed, {len(results)} executed.")

    if args.format == "json":
        payload = {
            "manifest": str(manifest_path),
            "passed": passed,
            "failed": failed,
            "results": [
                {
                    "name": r.name,
                    "success": r.success,
                    "status_code": r.status_code,
                    "elapsed_ms": r.elapsed_ms,
                    "details": r.details,
                    "error": r.error,
                    "attempt": r.attempt,
                }
                for r in results
            ],
        }
        print(json.dumps(payload, indent=2))

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()
