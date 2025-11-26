#!/usr/bin/env python3
"""QA helper: run Playwright smoke checks for ready-for-qa tasks and record findings."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


def _prepend_sys_path(path: Path) -> None:
    resolved = str(path)
    if resolved and resolved not in sys.path:
        sys.path.insert(0, resolved)


SCRIPT_DIR = Path(__file__).resolve().parent
_prepend_sys_path(SCRIPT_DIR)
_prepend_sys_path(SCRIPT_DIR.parent)

from task_comments import ensure_task_comments_schema, insert_task_comment
from update_task_state import update_task_state


def _default_db(project_root: Path) -> Path:
    return project_root / ".gpt-creator" / "staging" / "plan" / "tasks" / "tasks.db"


def _normalize_status(value: str) -> str:
    return (value or "").strip().lower().replace("_", "-")


READY_QA_STATUSES = {"ready-for-qa", "ready_for_qa", "ready-to-qa"}


def _fetch_tasks(cur: sqlite3.Cursor, specific: Optional[str]) -> List[sqlite3.Row]:
    where_clauses = ["LOWER(REPLACE(status,'_','-')) IN ('ready-for-qa','ready_to_qa','ready-to-qa')"]
    params: List[Any] = []
    if specific:
        where_clauses.append("(task_id = ? OR LOWER(story_slug || ':' || (position+1)) = LOWER(?))")
        params.extend([specific, specific])
    sql = f"""
    SELECT id, story_slug, position, task_id, title, status, priority, last_history_summary_path, last_history_meta_path,
           last_notes_json, last_commands_json, last_log_path, last_output_path, last_prompt_path, uid
      FROM tasks
     WHERE {" AND ".join(where_clauses)}
     ORDER BY COALESCE(priority, 1000000) ASC, global_order ASC, position ASC
    """
    cur.execute(sql, params)
    return list(cur.fetchall())


def _parse_list(raw: Any) -> List[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        try:
            loaded = json.loads(raw)
            if isinstance(loaded, list):
                return _parse_list(loaded)
        except Exception:
            pass
        return [line.strip() for line in raw.splitlines() if line.strip()]
    return []


def _safe_tail(path: Path, limit: int = 2000) -> str:
    try:
        data = path.read_text(encoding="utf-8", errors="ignore")
        if limit and len(data) > limit:
            return data[-limit:]
        return data
    except Exception:
        return ""


def _render_task_brief(task: sqlite3.Row, project_root: Path) -> str:
    lines = []
    ref = task["task_id"] or f"{task['story_slug']}:{int(task['position']) + 1}"
    lines.append(f"Task: {ref}")
    if task["title"]:
        lines.append(f"Title: {task['title']}")
    hist_summary = (task["last_history_summary_path"] or "").strip()
    if hist_summary:
        summary_text = _safe_tail((project_root / hist_summary), limit=3000)
        if summary_text:
            lines.append("Latest plan/focus summary:")
            lines.append(summary_text)
    hist_meta = (task["last_history_meta_path"] or "").strip()
    if hist_meta:
        meta_text = _safe_tail((project_root / hist_meta), limit=1200)
        if meta_text:
            lines.append("Plan/focus metadata:")
            lines.append(meta_text)
    last_notes = _parse_list(task["last_notes_json"])
    if last_notes:
        lines.append("Task notes:")
        for note in last_notes[:5]:
            lines.append(f"- {note}")
    last_commands = _parse_list(task["last_commands_json"])
    if last_commands:
        lines.append("Commands used:")
        for cmd in last_commands[:4]:
            lines.append(f"- {cmd}")
    return "\n".join(lines)


def _run_playwright(
    url: str,
    screenshot_path: Path,
    har_path: Path,
    *,
    headless: bool = True,
    timeout_ms: int = 30000,
    viewport: str = "desktop",
) -> Dict[str, Any]:
    js = r"""
const { chromium } = require('playwright');
const [url, screenshotPath, harPath, headlessArg, timeoutArg, viewportLabel] = process.argv.slice(2);
const headless = headlessArg !== '0';
const timeoutMs = parseInt(timeoutArg || '30000', 10);
(async () => {
  let browser;
  const consoleErrors = [];
  const requestFailures = [];
  const a11yIssues = [];
  try {
    browser = await chromium.launch({ headless });
    const mobile = (viewportLabel || '').toLowerCase() === 'mobile';
    const context = await browser.newContext({
      recordHar: { path: harPath, mode: 'minimal' },
      viewport: mobile ? { width: 390, height: 844 } : undefined,
      userAgent: mobile ? 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X)' : undefined,
      isMobile: mobile || undefined,
      hasTouch: mobile || undefined,
    });
    const page = await context.newPage();
    page.on('console', msg => {
      if (msg.type() === 'error') {
        consoleErrors.push(msg.text());
      }
    });
    page.on('requestfailed', req => {
      const failure = req.failure();
      const code = failure && failure.errorText ? failure.errorText : 'request-failed';
      requestFailures.push(`${code} ${req.url()}`);
    });
    const resp = await page.goto(url, { waitUntil: 'load', timeout: timeoutMs });
    const status = resp ? resp.status() : 0;
    await page.waitForTimeout(2000);
    try {
      await page.addScriptTag({ url: 'https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.7.0/axe.min.js' });
      const axeResults = await page.evaluate(async () => {
        if (!('axe' in window)) { return { violations: [] }; }
        // @ts-ignore
        return await window.axe.run();
      });
      if (axeResults && axeResults.violations) {
        for (const v of axeResults.violations) {
          const summary = `${v.id}: ${v.description || v.help || ''}`.trim();
          a11yIssues.push(summary);
        }
      }
    } catch (axeErr) {
      a11yIssues.push(`axe-runner-error: ${String(axeErr)}`);
    }
    if (screenshotPath) {
      await page.screenshot({ path: screenshotPath, fullPage: true });
    }
    await context.close();
    await browser.close();
    const payload = { ok: true, status, consoleErrors, requestFailures, a11yIssues, screenshot: screenshotPath, har: harPath };
    console.log(JSON.stringify(payload));
  } catch (err) {
    if (browser) {
      try { await browser.close(); } catch (e) {}
    }
    console.log(JSON.stringify({ ok: false, error: String(err), consoleErrors, requestFailures, a11yIssues, screenshot: screenshotPath, har: harPath }));
  }
})();
"""
    try:
        result = subprocess.run(
            ["node", "-e", js, url, str(screenshot_path), "1" if headless else "0", str(timeout_ms)],
            capture_output=True,
            text=True,
            check=False,
            env=os.environ.copy(),
        )
    except FileNotFoundError:
        return {"ok": False, "error": "Node not found"}
    stdout = (result.stdout or "").strip()
    try:
        data = json.loads(stdout)
    except Exception:
        data = {"ok": False, "error": stdout or "Unparseable Playwright output"}
    if result.returncode != 0 and data.get("ok") is True:
        data["ok"] = False
        data["error"] = f"Playwright exited {result.returncode}"
    return data


def qa_tasks(
    *,
    db_path: Path,
    project_root: Path,
    base_url: str,
    task_ref: Optional[str],
    headless: bool,
    strict_http: bool,
    allow_console: bool,
    allow_network: bool,
    retry_mobile: bool,
    fallback_cmd: Optional[str],
    dry_run: bool,
) -> int:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    ensure_task_comments_schema(cur)

    tasks = _fetch_tasks(cur, task_ref)
    if not tasks:
        print("No tasks with status ready-for-qa found.", file=sys.stderr)
        return 0

    qa_log_dir = project_root / ".gpt-creator" / "logs" / "qa"
    qa_log_dir.mkdir(parents=True, exist_ok=True)

    for task in tasks:
        task_ref_text = task["task_id"] or f"{task['story_slug']}:{int(task['position']) + 1}"
        if not _has_review_pass(int(task["id"]), task["story_slug"], int(task["position"])):
            print(f"Skipping {task_ref_text} — no review-pass comment found.", file=sys.stderr)
            continue
        print(f"QA {task_ref_text} ...", file=sys.stderr)
        task_brief = _render_task_brief(task, project_root)
        screenshot_path = qa_log_dir / f"{task_ref_text.replace(':', '_')}.png"
        har_path = qa_log_dir / f"{task_ref_text.replace(':', '_')}.har"
        start_ts = time.time()
        result = _run_playwright(base_url, screenshot_path, har_path, headless=headless, viewport="desktop")
        duration_s = time.time() - start_ts

        ok = bool(result.get("ok"))
        status_code = result.get("status", "")
        console_errs = result.get("consoleErrors") or []
        request_fails = result.get("requestFailures") or []
        a11y_issues = result.get("a11yIssues") or []
        error_text = result.get("error") or ""
        status_int: Optional[int] = None
        try:
            status_int = int(status_code) if status_code not in (None, "") else None
        except Exception:
            status_int = None
        http_bad = bool(status_int is not None and status_int >= 400) if strict_http else False
        console_bad = bool(console_errs) and not allow_console
        net_bad = bool(request_fails) and not allow_network
        a11y_bad = bool(a11y_issues)
        desktop_pass = ok and not console_bad and not net_bad and not http_bad and not a11y_bad

        mobile_result: Dict[str, Any] = {}
        mobile_pass = False
        mobile_paths: list[str] = []
        if not desktop_pass and retry_mobile and not dry_run:
            screenshot_path_m = qa_log_dir / f"{task_ref_text.replace(':', '_')}_mobile.png"
            har_path_m = qa_log_dir / f"{task_ref_text.replace(':', '_')}_mobile.har"
            mobile_paths = [str(screenshot_path_m), str(har_path_m)]
            mobile_result = _run_playwright(base_url, screenshot_path_m, har_path_m, headless=headless, viewport="mobile")
            status_code_m = mobile_result.get("status", "")
            console_errs_m = mobile_result.get("consoleErrors") or []
            request_fails_m = mobile_result.get("requestFailures") or []
            a11y_issues_m = mobile_result.get("a11yIssues") or []
            error_text_m = mobile_result.get("error") or ""
            status_int_m = None
            try:
                status_int_m = int(status_code_m) if status_code_m not in (None, "") else None
            except Exception:
                status_int_m = None
            http_bad_m = bool(status_int_m is not None and status_int_m >= 400) if strict_http else False
            console_bad_m = bool(console_errs_m) and not allow_console
            net_bad_m = bool(request_fails_m) and not allow_network
            a11y_bad_m = bool(a11y_issues_m)
            mobile_pass = bool(mobile_result.get("ok")) and not console_bad_m and not net_bad_m and not http_bad_m and not a11y_bad_m
            # Merge findings
            console_errs += console_errs_m
            request_fails += request_fails_m
            a11y_issues += a11y_issues_m
            if error_text_m:
                error_text = error_text or error_text_m

        fallback_pass = False
        fallback_output = ""
        if (not desktop_pass and not mobile_pass) and fallback_cmd and not dry_run:
            try:
                proc = subprocess.run(fallback_cmd, shell=True, capture_output=True, text=True, cwd=project_root)
                fallback_output = (proc.stdout or "") + (proc.stderr or "")
                fallback_pass = proc.returncode == 0
            except Exception as exc:
                fallback_output = f"fallback error: {exc}"

        next_status = "completed" if (desktop_pass or mobile_pass or fallback_pass) else "pending"

        lines = [
          "QA summary:",
          f"- URL: {base_url}",
          f"- Screenshot: {screenshot_path}",
          f"- HAR: {har_path}",
          f"- Page status: {status_code if status_code is not None else 'n/a'}",
          f"- Console errors: {len(console_errs)}",
          f"- Network failures: {len(request_fails)}",
          f"- A11y violations: {len(a11y_issues)}",
          f"- Duration: {duration_s:.1f}s",
        ]
        if console_errs:
            lines.append("Console errors:")
            for entry in console_errs[:8]:
                lines.append(f"  - {entry}")
        if request_fails:
            lines.append("Network failures:")
            for entry in request_fails[:8]:
                lines.append(f"  - {entry}")
        if a11y_issues:
            lines.append("Accessibility issues:")
            for entry in a11y_issues[:8]:
                lines.append(f"  - {entry}")
        if mobile_paths:
            lines.append(f"Mobile artifacts: {', '.join(mobile_paths)}")
        if fallback_cmd:
            lines.append(f"Fallback cmd: {fallback_cmd}")
            if fallback_output:
                lines.append("Fallback output (truncated):")
                lines.append(fallback_output[:800])
        if error_text:
            lines.append(f"Runner error: {error_text}")
        lines.append("")
        lines.append("Task context:")
        lines.append(task_brief or "(no context)")

        severity = "info" if next_status == "completed" else "blocking"
        comment_body = "\n".join(lines)
        first_issue_hint = ""
        for entry in console_errs + request_fails + a11y_issues:
            if entry:
                first_issue_hint = str(entry)[:500]
                break
        if not first_issue_hint and error_text:
            first_issue_hint = error_text[:500]
        if not first_issue_hint and fallback_output:
            first_issue_hint = fallback_output[:500]

        if not dry_run:
            insert_task_comment(
                cur,
                task_row_id=int(task["id"]),
                task_uid=task["uid"],
                story_slug=task["story_slug"],
                task_ref=task_ref_text,
                commenter="qa-agent",
                details=comment_body,
                status_from=task["status"],
                status_to=next_status,
                severity=severity,
                component="frontend-qa",
                suggested_fix=first_issue_hint if next_status != "completed" else "",
                blocking=(next_status != "completed"),
                artifact_path=";".join([str(screenshot_path), str(har_path)] + mobile_paths),
            )
            update_task_state(
                db_path,
                task["story_slug"],
                str(int(task["position"])),
                next_status,
                "qa-run",
            )
            conn.commit()
        print(f"  → status {task['status']} -> {next_status}", file=sys.stderr)

    conn.close()
    return 0


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description="Run QA Playwright smoke on ready-for-qa tasks.")
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="Project root (default cwd)")
    parser.add_argument("--db", type=Path, help="Path to tasks.db (default: <project>/.gpt-creator/staging/plan/tasks/tasks.db)")
    parser.add_argument("--url", required=True, help="Base URL to open for QA")
    parser.add_argument("--task", help="Specific task id or story:position to QA")
    parser.add_argument("--headless", action="store_true", help="Run browser headless (default true)")
    parser.add_argument("--headed", action="store_true", help="Force headed browser")
    parser.add_argument("--strict-http", action="store_true", help="(Deprecated) 4xx/5xx always fail QA")
    parser.add_argument("--allow-console", action="store_true", help="Allow console errors without failing QA")
    parser.add_argument("--allow-network", action="store_true", help="Allow network failures without failing QA")
    parser.add_argument("--retry-mobile", action="store_true", help="Retry once with mobile viewport if desktop attempt fails")
    parser.add_argument("--no-retry-mobile", action="store_true", help="Disable mobile retry")
    parser.add_argument("--fallback-cmd", help="Fallback shell command (lint/test) when Playwright fails")
    parser.add_argument("--dry-run", action="store_true", help="Preview without updating statuses/comments")
    args = parser.parse_args(argv)

    project_root = args.project.resolve()
    db_path = args.db or _default_db(project_root)
    headless = True
    retry_mobile = True
    if args.headed:
        headless = False
    strict_http = True  # always fail on 4xx/5xx
    if args.no_retry_mobile:
        retry_mobile = False
    if args.retry_mobile:
        retry_mobile = True
    return qa_tasks(
        db_path=db_path,
        project_root=project_root,
        base_url=args.url,
        task_ref=args.task,
        headless=headless,
        strict_http=strict_http,
        allow_console=args.allow_console,
        allow_network=args.allow_network,
        retry_mobile=retry_mobile,
        fallback_cmd=args.fallback_cmd,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
    def _has_review_pass(task_row_id: int, story_slug: str, position: int) -> bool:
        row = cur.execute(
            """
            SELECT 1
              FROM task_comments
             WHERE (task_row_id = ? OR (story_slug = ? AND task_ref = ?))
               AND LOWER(status_to) = 'ready-for-qa'
               AND blocking = 0
             ORDER BY created_at DESC
             LIMIT 1
            """,
            (task_row_id, story_slug, f"{story_slug}:{position+1}"),
        ).fetchone()
        return bool(row)
