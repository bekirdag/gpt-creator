#!/usr/bin/env python3
"""Backlog guard helpers for the work-on-tasks command."""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

TERMINAL_STATUSES = {
    "complete",
    "completed",
    "completed-no-changes",
    "skipped-already-complete",
}

ACTIVE_STATUSES = {
    "active",
    "in-progress",
    "in progress",
    "blocked",
    "blocked-budget",
    "blocked-migration-transition",
    "blocked-quota",
    "apply-failed-migration-context",
    "blocked-schema-drift",
    "blocked-schema-guard-error",
    "on-hold",
    "review",
    "needs-review",
}

BLOCKED_STATUSES = {
    "blocked",
    "blocked-budget",
    "blocked-migration-transition",
    "blocked-quota",
    "apply-failed-migration-context",
    "blocked-schema-drift",
    "blocked-schema-guard-error",
}

STATUS_NORMALISE_MAP = {
    "in progress": "in-progress",
    "needs review": "needs-review",
}

DEFAULT_EPIC_WATCH = ("adm-01",)
DEFAULT_WINDOW_DAYS = 7.0
DEFAULT_WIP_LIMIT = 12

POINT_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")


def _is_blocked_dependency(status: str) -> bool:
    return (status or "").strip().lower().startswith("blocked-dependency(")


def _slugify(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return value or "item"


def _normalise_whitespace(value: str) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _normalise_title(value: str) -> str:
    return _normalise_whitespace((value or "").lower())


def _parse_points(raw: Any) -> float:
    if raw is None:
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip()
    if not text:
        return 0.0
    match = POINT_PATTERN.search(text)
    if not match:
        return 0.0
    try:
        return float(match.group(0))
    except ValueError:
        return 0.0


def _parse_datetime(value: Any) -> Optional[_dt.datetime]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = _dt.datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_dt.timezone.utc)
        else:
            dt = dt.astimezone(_dt.timezone.utc)
        return dt
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = _dt.datetime.strptime(text, fmt)
            return dt.replace(tzinfo=_dt.timezone.utc)
        except ValueError:
            continue
    return None


def _status_normalise(value: str) -> str:
    text = (value or "").strip().lower()
    return STATUS_NORMALISE_MAP.get(text, text)


def _canonical_task_key(row: Mapping[str, Any]) -> str:
    idempotency = _normalise_whitespace((row.get("idempotency") or "").lower())
    if idempotency:
        return f"idempotency:{idempotency}"
    task_id = _normalise_whitespace((row.get("task_id") or "").lower())
    if task_id:
        return f"task:{task_id}"
    slug = _normalise_whitespace((row.get("story_slug") or "").lower())
    epic = _normalise_whitespace((row.get("epic_key") or row.get("epic_title") or "").lower())
    title_norm = _normalise_title(row.get("title") or "")
    doc_ref = _normalise_whitespace((row.get("document_reference") or "").lower())
    tags = _normalise_whitespace((row.get("tags_text") or "").lower())
    return f"title:{title_norm}|doc:{doc_ref}|epic:{epic}|story:{slug}|tags:{tags}"


@dataclass
class DuplicateGroup:
    key: str
    count: int
    first_points: float
    raw_points_total: float
    raw_points_remaining: float
    has_pending: bool
    title: str
    epic_label: str
    epic_slug: str
    story_slugs: List[str]
    task_ids: List[str]
    tags: List[str]
    statuses: Dict[str, int]
    created_at_values: List[str]
    recent: bool


def _compute_duplicate_groups(
    groups: MutableMapping[str, MutableMapping[str, Any]],
    recent_cutoff: _dt.datetime,
) -> Tuple[List[DuplicateGroup], float, float]:
    duplicates: List[DuplicateGroup] = []
    extra_points_total = 0.0
    extra_points_remaining = 0.0
    for key, payload in groups.items():
        count = payload["count"]
        first_points = payload["first_points"]
        raw_points_total = payload["raw_points_total"]
        raw_points_remaining = payload["raw_points_remaining"]
        has_pending = payload["has_pending"]
        extra_points_total += max(raw_points_total - first_points, 0.0)
        if has_pending:
            extra_points_remaining += max(raw_points_remaining - first_points, 0.0)
        else:
            extra_points_remaining += max(raw_points_remaining, 0.0)
        if count <= 1:
            continue
        created_at_values = sorted(
            value for value in payload["created_at_values"] if value is not None
        )
        recent = False
        if created_at_values:
            recent = any(value >= recent_cutoff for value in created_at_values)
        duplicates.append(
            DuplicateGroup(
                key=key,
                count=count,
                first_points=first_points,
                raw_points_total=raw_points_total,
                raw_points_remaining=raw_points_remaining,
                has_pending=has_pending,
                title=payload["title_raw"] or payload["title_norm"],
                epic_label=payload["epic_label"],
                epic_slug=payload["epic_slug"],
                story_slugs=sorted(payload["story_slugs"]),
                task_ids=sorted(payload["task_ids"]),
                tags=sorted(tag for tag in payload["tags"] if tag),
                statuses=dict(sorted(payload["statuses"].items())),
                created_at_values=[
                    value.strftime("%Y-%m-%dT%H:%M:%SZ")
                    for value in created_at_values
                ],
                recent=recent,
            )
        )
    duplicates.sort(key=lambda item: (item.recent, item.count, item.raw_points_remaining), reverse=True)
    return duplicates, extra_points_total, extra_points_remaining


def _load_tasks(cur: sqlite3.Cursor) -> List[sqlite3.Row]:
    query = """
        SELECT
          story_slug,
          story_id,
          story_title,
          epic_key,
          epic_title,
          task_id,
          title,
          tags_text,
          status,
          story_points,
          created_at,
          updated_at,
          idempotency,
          document_reference
        FROM tasks
    """
    cur.execute(query)
    return list(cur.fetchall())


def build_snapshot(
    db_path: Path,
    *,
    window_days: float = DEFAULT_WINDOW_DAYS,
    epic_watch: Iterable[str] = DEFAULT_EPIC_WATCH,
    wip_limit: int = DEFAULT_WIP_LIMIT,
) -> Dict[str, Any]:
    now = _dt.datetime.utcnow().replace(tzinfo=_dt.timezone.utc)
    recent_cutoff = now - _dt.timedelta(days=max(window_days, 0.0))
    epic_watch_slugs = {_slugify(epic) for epic in epic_watch if epic}

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    rows = _load_tasks(cur)
    conn.close()

    total_tasks = len(rows)
    remaining_tasks = 0
    raw_points_total = 0.0
    raw_points_remaining = 0.0
    wip_active = 0
    wip_blocked = 0
    recent_inflow = 0

    epic_metrics: Dict[str, Dict[str, Any]] = {}
    group_map: Dict[str, Dict[str, Any]] = {}

    for row in rows:
        status_norm = _status_normalise(row["status"] or "")
        is_terminal = status_norm in TERMINAL_STATUSES
        is_active = status_norm in ACTIVE_STATUSES or _is_blocked_dependency(status_norm)
        is_blocked = status_norm in BLOCKED_STATUSES or _is_blocked_dependency(status_norm)

        story_slug = _normalise_whitespace(row["story_slug"] or "")
        epic_label_raw = row["epic_key"] or row["epic_title"] or ""
        epic_label_norm = _normalise_whitespace(epic_label_raw)
        epic_slug = _slugify(epic_label_norm or story_slug or "misc")

        points_value = _parse_points(row["story_points"])
        raw_points_total += points_value
        if not is_terminal:
            remaining_tasks += 1
            raw_points_remaining += points_value
        if is_active:
            wip_active += 1
        if is_blocked:
            wip_blocked += 1

        created_at = _parse_datetime(row["created_at"])
        if created_at and created_at >= recent_cutoff:
            recent_inflow += 1

        epic_entry = epic_metrics.setdefault(
            epic_slug,
            {
                "label": epic_label_norm or epic_slug,
                "total_tasks": 0,
                "completed_tasks": 0,
                "remaining_tasks": 0,
                "raw_points_total": 0.0,
                "raw_points_remaining": 0.0,
                "unique_points_total": 0.0,
                "unique_points_remaining": 0.0,
            },
        )
        epic_entry["total_tasks"] += 1
        if is_terminal:
            epic_entry["completed_tasks"] += 1
        else:
            epic_entry["remaining_tasks"] += 1
            epic_entry["raw_points_remaining"] += points_value
        epic_entry["raw_points_total"] += points_value

        key = _canonical_task_key(row)
        payload = group_map.setdefault(
            key,
            {
                "count": 0,
                "first_points": None,
                "raw_points_total": 0.0,
                "raw_points_remaining": 0.0,
                "has_pending": False,
                "title_norm": _normalise_title(row["title"] or ""),
                "title_raw": _normalise_whitespace(row["title"] or ""),
                "epic_label": epic_entry["label"],
                "epic_slug": epic_slug,
                "story_slugs": set(),
                "task_ids": set(),
                "tags": set(),
                "statuses": {},
                "created_at_values": [],
            },
        )
        payload["count"] += 1
        payload["raw_points_total"] += points_value
        if not is_terminal:
            payload["raw_points_remaining"] += points_value
            payload["has_pending"] = True
        payload["story_slugs"].add(story_slug or epic_slug)
        task_id = _normalise_whitespace(row["task_id"] or "")
        if task_id:
            payload["task_ids"].add(task_id)
        tags_text = _normalise_whitespace(row["tags_text"] or "")
        if tags_text:
            for tag in tags_text.split(","):
                clean = _normalise_whitespace(tag.lower())
                if clean:
                    payload["tags"].add(clean)
        payload["statuses"][status_norm or ""] = payload["statuses"].get(status_norm or "", 0) + 1
        payload["created_at_values"].append(created_at)
        if payload["first_points"] is None:
            payload["first_points"] = points_value

    unique_points_total = 0.0
    unique_points_remaining = 0.0
    duplicate_groups, duplicate_extra_total, duplicate_extra_remaining = _compute_duplicate_groups(
        group_map,
        recent_cutoff,
    )

    for payload in group_map.values():
        first_points = payload["first_points"] or 0.0
        unique_points_total += first_points
        if payload["has_pending"]:
            unique_points_remaining += first_points
        epic_slug = payload["epic_slug"]
        if epic_slug in epic_metrics:
            epic_metrics[epic_slug]["unique_points_total"] += first_points
            if payload["has_pending"]:
                epic_metrics[epic_slug]["unique_points_remaining"] += first_points

    recent_duplicates = [group for group in duplicate_groups if group.recent]

    snapshot = {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_days": window_days,
        "total_tasks": total_tasks,
        "remaining_tasks": remaining_tasks,
        "completed_tasks": total_tasks - remaining_tasks,
        "raw_points_total": raw_points_total,
        "raw_points_remaining": raw_points_remaining,
        "unique_points_total": unique_points_total,
        "unique_points_remaining": unique_points_remaining,
        "duplicate_points_total": duplicate_extra_total,
        "duplicate_points_remaining": duplicate_extra_remaining,
        "duplicate_group_count": sum(1 for entry in group_map.values() if entry["count"] > 1),
        "duplicate_recent_group_count": len(recent_duplicates),
        "duplicates_recent": [
            {
                "key": group.key,
                "count": group.count,
                "title": group.title,
                "epic_label": group.epic_label,
                "epic_slug": group.epic_slug,
                "story_slugs": group.story_slugs,
                "task_ids": group.task_ids,
                "tags": group.tags,
                "status_counts": group.statuses,
                "created_at": group.created_at_values,
                "raw_points_total": group.raw_points_total,
                "raw_points_remaining": group.raw_points_remaining,
                "first_points": group.first_points,
            }
            for group in recent_duplicates
        ],
        "wip_active": wip_active,
        "wip_blocked": wip_blocked,
        "wip_limit": wip_limit,
        "recent_inflow": recent_inflow,
        "epic_metrics": {
            slug: {
                "label": data["label"],
                "total_tasks": data["total_tasks"],
                "completed_tasks": data["completed_tasks"],
                "remaining_tasks": data["remaining_tasks"],
                "raw_points_total": data["raw_points_total"],
                "raw_points_remaining": data["raw_points_remaining"],
                "unique_points_total": data["unique_points_total"],
                "unique_points_remaining": data["unique_points_remaining"],
            }
            for slug, data in sorted(epic_metrics.items())
        },
        "watch_epics": sorted(epic_watch_slugs),
    }
    return snapshot


def _load_snapshot(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def compare_snapshots(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    epic_watch: Iterable[str],
    wip_limit: int,
) -> List[Tuple[str, str]]:
    messages: List[Tuple[str, str]] = []

    def fmt_delta(value: float, as_points: bool = False) -> str:
        if as_points:
            return f"{value:+.1f}"
        if isinstance(value, float) and not value.is_integer():
            return f"{value:+.1f}"
        return f"{int(value):+d}"

    remaining_before = float(before.get("remaining_tasks", 0))
    remaining_after = float(after.get("remaining_tasks", 0))
    delta_remaining = remaining_after - remaining_before

    unique_points_before = float(before.get("unique_points_remaining", 0.0))
    unique_points_after = float(after.get("unique_points_remaining", 0.0))
    delta_unique_points = unique_points_after - unique_points_before

    raw_points_before = float(before.get("raw_points_remaining", 0.0))
    raw_points_after = float(after.get("raw_points_remaining", 0.0))
    delta_raw_points = raw_points_after - raw_points_before

    messages.append(
        (
            "INFO",
            f"Remaining tasks {int(remaining_before)} → {int(remaining_after)} ({fmt_delta(delta_remaining)})",
        )
    )
    messages.append(
        (
            "INFO",
            f"Unique remaining story points {unique_points_before:.1f} → {unique_points_after:.1f} ({fmt_delta(delta_unique_points, as_points=True)})",
        )
    )

    watch_epics = {_slugify(epic) for epic in epic_watch if epic}
    if not watch_epics:
        watch_epics = set(before.get("watch_epics") or after.get("watch_epics") or DEFAULT_EPIC_WATCH)
    epic_metrics_before = before.get("epic_metrics") or {}
    epic_metrics_after = after.get("epic_metrics") or {}

    stagnant_epics: List[str] = []
    for epic_slug in watch_epics:
        before_epic = epic_metrics_before.get(epic_slug, {})
        after_epic = epic_metrics_after.get(epic_slug, {})
        before_completed = int(before_epic.get("completed_tasks", 0))
        after_completed = int(after_epic.get("completed_tasks", 0))
        if after_completed <= before_completed:
            stagnant_epics.append(after_epic.get("label") or before_epic.get("label") or epic_slug)

    if delta_remaining > 0 and delta_unique_points >= 0 and stagnant_epics:
        epic_list = ", ".join(stagnant_epics)
        messages.append(
            (
                "WARN",
                f"Backlog grew by {fmt_delta(delta_remaining)} task(s) and {fmt_delta(delta_unique_points, as_points=True)} SP while {epic_list} completion stagnated – investigate duplicate or regenerated intake.",
            )
        )

    duplicate_recent_groups = after.get("duplicates_recent") or []
    if duplicate_recent_groups:
        duplicate_overhang = float(after.get("duplicate_points_remaining", 0.0))
        duplicate_instances = sum(max(int(group.get("count", 0)) - 1, 0) for group in duplicate_recent_groups)
        top_group = max(
            duplicate_recent_groups,
            key=lambda item: (item.get("count", 0), item.get("raw_points_remaining", 0.0)),
        )
        example_title = top_group.get("title") or "(untitled)"
        example_epic = top_group.get("epic_label") or top_group.get("epic_slug") or "unknown epic"
        example_count = int(top_group.get("count", 0))
        messages.append(
            (
                "FREEZE",
                f"{duplicate_instances} duplicate task(s) detected across {len(duplicate_recent_groups)} recent group(s); example '{example_title}' in {example_epic} appears {example_count}×. Freeze intake automations immediately.",
            )
        )
        messages.append(
            (
                "WARN",
                "Route new intake to a Triage queue and block story point assignment until triaged to contain duplicate ingress.",
            )
        )
        messages.append(
            (
                "WARN",
                "Bulk-close newer duplicates, keep the oldest canonical issue, add duplicate=true label, and link via DuplicateOf.",
            )
        )
        if duplicate_overhang > 0.0:
            messages.append(
                (
                    "WARN",
                    f"Story-point roll-up inflation detected: duplicates account for {duplicate_overhang:.1f} SP (raw {raw_points_after:.1f} vs unique {unique_points_after:.1f}). Move estimation to parent tickets or exclude subtasks from roll-ups.",
                )
            )

    wip_after = int(after.get("wip_active", 0))
    wip_limit_effective = int(after.get("wip_limit", wip_limit))
    if wip_after >= wip_limit_effective > 0:
        messages.append(
            (
                "WARN",
                f"WIP pressure: {wip_after} active/blocked tasks ≥ limit {wip_limit_effective}. Enforce column caps and surface blockers.",
            )
        )

    recent_inflow = int(after.get("recent_inflow", 0))
    if recent_inflow > 0 and delta_remaining >= 0 and duplicate_recent_groups:
        messages.append(
            (
                "INFO",
                f"{recent_inflow} item(s) entered backlog during the monitoring window; keep migration jobs idempotent (hash title|description|originId) and reject when origin already mapped.",
            )
        )

    if duplicate_recent_groups:
        messages.append(
            (
                "INFO",
                "Persist originId→issueKey mapping and add server-side checks to block creation when (normalized_title, component, epic) already exists in the last 7 days.",
            )
        )

    return messages


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Backlog guard utilities")
    subparsers = parser.add_subparsers(dest="command", required=True)

    snap = subparsers.add_parser("snapshot", help="Emit a backlog snapshot JSON payload")
    snap.add_argument("--db", required=True, type=Path, help="Path to tasks SQLite database")
    snap.add_argument("--window-days", type=float, default=DEFAULT_WINDOW_DAYS, help="Recent window size in days")
    snap.add_argument("--epic", action="append", default=list(DEFAULT_EPIC_WATCH), help="Epic key/slug to watch (repeatable)")
    snap.add_argument("--wip-limit", type=int, default=DEFAULT_WIP_LIMIT, help="Advisory WIP limit for active tasks")
    snap.add_argument("--output", type=Path, help="Optional path to persist the snapshot JSON")

    comp = subparsers.add_parser("compare", help="Compare two backlog snapshots")
    comp.add_argument("--before", required=True, type=Path, help="Path to baseline snapshot JSON")
    comp.add_argument("--after", required=True, type=Path, help="Path to post-run snapshot JSON")
    comp.add_argument("--epic", action="append", default=list(DEFAULT_EPIC_WATCH), help="Epic key/slug to emphasise (repeatable)")
    comp.add_argument("--wip-limit", type=int, default=DEFAULT_WIP_LIMIT, help="Advisory WIP limit for warnings")

    args = parser.parse_args(argv)

    if args.command == "snapshot":
        snapshot = build_snapshot(
            args.db,
            window_days=args.window_days,
            epic_watch=args.epic,
            wip_limit=args.wip_limit,
        )
        payload = json.dumps(snapshot, indent=2, sort_keys=True)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(payload + "\n", encoding="utf-8")
        sys.stdout.write(payload)
        if not payload.endswith("\n"):
            sys.stdout.write("\n")
        return 0

    if args.command == "compare":
        before = _load_snapshot(args.before)
        after = _load_snapshot(args.after)
        messages = compare_snapshots(before, after, epic_watch=args.epic, wip_limit=args.wip_limit)
        for level, message in messages:
            sys.stdout.write(f"{level}\t{message}\n")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
