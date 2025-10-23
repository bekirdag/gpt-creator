# Work-on-Tasks Logging Schema

This document defines the machine-readable event envelope for the `work-on-tasks` command and related tooling. Events are emitted as **JSON Lines (JSONL)** so downstream processors can stream logs without buffering entire files.

## Event Envelope

Each log line MUST be a single UTF-8 JSON object with the following required fields:

| Field        | Type    | Description |
|--------------|---------|-------------|
| `timestamp`  | string  | UTC instant in ISO-8601 format (e.g. `"2025-10-23T08:50:27.123Z"`). |
| `phase`      | string  | High-level lifecycle bucket for the event. Expected values: `"context"`, `"analysis"`, `"execution"`, `"validation"`, `"summary"`, `"cleanup"`. |
| `category`   | string  | Dot-delimited classifier that narrows the event type (e.g. `context.init`, `tool.exec.request`, `output.diff`). |
| `actor`      | string  | Originator of the event. Allowed values: `"user"`, `"scheduler"`, `"agent"`, `"tool"`, `"system"`. |
| `status`     | string  | Event disposition. Allowed values: `"info"`, `"start"`, `"complete"`, `"error"`, `"warning"`, `"cancelled"`. |
| `summary`    | string  | Human-readable, single-line synopsis of the event (≤ 200 characters). |
| `detailRef`  | object  | Locator for extended details associated with the event (see below). |

### `detailRef` object

`detailRef` provides a durable identifier for the full payload when it is too large for the event itself.

| Field      | Type    | Description |
|------------|---------|-------------|
| `kind`     | string  | Reference type. Values include `"text"`, `"diff"`, `"artifact"`, `"command"`, `"metrics"`, `"plan"`. |
| `path`     | string  | File path or logical URI of the referenced data (relative to repo root when applicable). |
| `offset`   | integer | Byte offset within the referenced file (optional). |
| `length`   | integer | Length, in bytes, of the referenced segment (optional). |
| `checksum` | object  | Optional integrity descriptor with `algo` (e.g. `"sha256"`) and `value`. |

`path` MAY point to a synthetic log attachment (e.g. `/logs/artifacts/<run>/<uuid>.txt`) when the payload is not part of the repository.

## Optional Fields

To keep the envelope concise, everything beyond the required fields is optional and MAY be omitted when empty. These optional fields support traceability, nested context and structured payloads:

| Field          | Type      | Description |
|----------------|-----------|-------------|
| `runId`        | string    | Stable identifier for the overall command execution. UUID v4 recommended. |
| `sessionId`    | string    | Identifier for a sub-session (e.g. reconnect after resume). |
| `eventId`      | string    | Unique identifier for this event. UUID v7 recommended to preserve sortable order. |
| `parentIds`    | string[]  | Zero or more parent event IDs used for hierarchical grouping. First entry SHOULD be the immediate parent. |
| `sequence`     | integer   | Monotonic counter for ordering when timestamps collide. |
| `tags`         | string[]  | Free-form labels (e.g. `["cmd:rg", "workspace:/apps/yoga"]`). |
| `payload`      | object    | Inline structured data; SHOULD include a `type` discriminator. |
| `artifacts`    | object[]  | Array describing produced artifacts (see below). |
| `metrics`      | object    | Lightweight counters or timers (e.g. `{ "tokens": 5893, "latency_ms": 8 }`). |
| `source`       | object    | Additional provenance (e.g. CLI arguments, environment snapshot). |

### Artifact descriptor

Elements inside `artifacts` MUST include:

| Field      | Type   | Description |
|------------|--------|-------------|
| `name`     | string | Human-readable label (`"tmp_final_output.json"`). |
| `type`     | string | MIME category or domain-specific token (`"application/json"`, `"diff"`, `"sql"`). |
| `path`     | string | Relative file path. |
| `checksum` | object | Integrity descriptor as described above. |

Optional fields: `sizeBytes`, `expiresAt`, `uri`.

## Hierarchical Grouping

Emit explicit boundary events to identify nested scopes and tie child events back to parents:

1. **Run start/end**  
   - `category: "run.start"` (status `"start"`) and `category: "run.end"` (status `"complete"`).  
   - Provide `runId`, overall target summary, and initial `tags`.

2. **Phase boundaries**  
   - `category: "phase.start"` / `"phase.end"` with `phase` set to the logical phase.  
   - Include `eventId` and push to `parentIds` of child events until the corresponding `phase.end`.

3. **Task steps**  
   - For each backlog task, emit `category: "task.start"` / `"task.end"` events with a unique `taskId`.  
   - Subsequent `thinking`, `exec`, or `tool` events reference the active task via `parentIds`.

Consumers reconstruct the narrative by building a tree keyed by `eventId`. An event MAY have multiple parents when it logically belongs to several contexts (e.g. a command that spans phase and task scopes).

## Example JSONL

```jsonl
{"runId":"8c5e2c56-ff7c-4a91-8eb0-14c75f20dcb5","eventId":"018b5b68-7aa2-7135-bf9f-1d9df5f9f5a1","timestamp":"2025-10-23T08:50:19.000Z","phase":"context","category":"run.start","actor":"system","status":"start","summary":"Work-on-tasks session began","detailRef":{"kind":"text","path":"logs/wot-logs.txt"},"tags":["project:/apps/yoga","story:ADM-01-US-08"]}
{"runId":"8c5e2c56-ff7c-4a91-8eb0-14c75f20dcb5","eventId":"018b5b68-7aa3-75b1-9fb7-6cf0fa60c942","parentIds":["018b5b68-7aa2-7135-bf9f-1d9df5f9f5a1"],"timestamp":"2025-10-23T08:50:23.112Z","phase":"analysis","category":"tool.exec.request","actor":"agent","status":"start","summary":"Running repository listing","detailRef":{"kind":"command","path":"commands/018b5b68-7aa3-75b1-9fb7-6cf0fa60c942.sh"},"payload":{"type":"shell","command":"bash -lc ls","cwd":"/home/wodo/apps/yoga"}}
{"runId":"8c5e2c56-ff7c-4a91-8eb0-14c75f20dcb5","eventId":"018b5b68-7aa3-75b1-9fb7-6cf0fa60c943","parentIds":["018b5b68-7aa3-75b1-9fb7-6cf0fa60c942"],"timestamp":"2025-10-23T08:50:23.121Z","phase":"analysis","category":"tool.exec.result","actor":"tool","status":"complete","summary":"Command succeeded","detailRef":{"kind":"text","path":"logs/artifacts/018b5b68-7aa3-75b1-9fb7-6cf0fa60c942.out"},"metrics":{"latency_ms":8},"payload":{"type":"shellResult","exitCode":0,"stdout":["ansible","apps","auth_service.patch", "..."]}}
{"runId":"8c5e2c56-ff7c-4a91-8eb0-14c75f20dcb5","eventId":"018b5b68-7aa4-73cc-8454-93b4a4b6c1f2","parentIds":["018b5b68-7aa2-7135-bf9f-1d9df5f9f5a1","task:ADM-01-US-08-T04"],"timestamp":"2025-10-23T09:05:27.404Z","phase":"execution","category":"output.diff","actor":"agent","status":"info","summary":"Generated diff for apps/api/src/auth/auth.service.ts","detailRef":{"kind":"diff","path":"logs/diffs/2025-10-23/018b5b68-7aa4.diff","checksum":{"algo":"sha256","value":"8103dfc60104602ef..."}}, "artifacts":[{"name":"apps/api/src/auth/auth.service.ts","type":"diff","path":"logs/diffs/2025-10-23/018b5b68-7aa4.diff"}]}
{"runId":"8c5e2c56-ff7c-4a91-8eb0-14c75f20dcb5","eventId":"018b5b68-7aa6-744f-8cf7-7ed648161a8f","timestamp":"2025-10-23T10:12:12.901Z","phase":"summary","category":"run.end","actor":"system","status":"complete","summary":"Work-on-tasks session completed successfully","detailRef":{"kind":"text","path":"logs/wot-logs.txt"},"metrics":{"tokens_total":120456,"duration_s":5013}}
```

## Producer Guidelines

1. **One event per logical action:** a `tool.exec.request` should precede the corresponding `tool.exec.result`. Long-running operations can emit intermediate `"progress"` statuses via `status:"info"` events.
2. **Short summaries:** keep `summary` succinct; place longer narratives inside `payload.notes` or the referenced artifact.
3. **Stable identifiers:** use deterministic IDs when possible (e.g. `task:<slug>`), especially for `parentIds`.
4. **Integrity metadata:** include `checksum` data for artifacts written to disk to simplify tamper detection.
5. **Backpressure friendliness:** because the format is JSONL, producers SHOULD flush events immediately to support real-time streaming into the TUI.

## Implementation Roadmap

The schema above is the contract; the following work items track the migration of tooling and runtime surfaces to emit and consume it consistently.

### CLI Log Producers
- **Writer abstraction**: introduce a JSONL emitter in `bin/gpt-creator` that replaces plain-text `append_log` calls. Each event should funnel through a helper that accepts the canonical fields (`timestamp`, `phase`, `category`, …) and persists artifacts to `.gpt-creator/artifacts/` when `detailRef.kind != "text"`.
- **Context lifecycle markers**: ensure command orchestration (job queue, tool invocations, task loop) emits paired `run`, `phase`, and `task` start/end envelopes. The orchestration code in `bin/gpt-creator` already knows when tasks advance; wire those hooks to the new emitter.
- **Telemetry aggregation**: replace per-line “tokens used” updates with structured `metrics` objects so downstream summaries (`tui/cmd/logsummaries`) derive from the JSONL stream rather than scraping human-oriented text.

### TUI Rendering (`tui/model.go`, `tui/logs_column.go`, `tui/columns.go`)
- **Parser**: add a reader that ingests JSONL events, flattens key fields for display, and exposes artifact summary rows (e.g. `[artifact]` with checksum and path). Preserve legacy mode for pre-migration logs to avoid breaking existing sessions.
- **Component updates**:
  - `model.go`: swap `appendLog` and related helpers to consume structured events, update selection/copy logic to include metadata, and expose filters (by `phase`, `category`, `actor`).
  - `logs_column.go` / `columns.go`: adjust layout so each event renders as a compact block (timestamp, phase badge, summary) with expandable details for `payload`, `artifacts`, or `metrics`.
  - Add keyboard shortcuts (e.g. `f` to filter by phase, `a` to open artifact) once structured data is available.

### Testing
- **Writer tests**: add unit coverage around the CLI emitter ensuring required fields are present, large payloads spill to artifact files, and hierarchical parent IDs link correctly.
- **Reader tests**: under `tui/internal` create fixtures with mixed event types (context, command, diff, telemetry) and assert the parser handles missing optional fields, nested parents, and artifact linking. Snapshot tests can validate rendered rows without the TUI runtime.
- **Integration smoke**: wire a lightweight e2e test that runs `formatlogs` + `logsummaries` against a synthetic JSONL log to guarantee downstream tooling continues to function on the new format.

### Documentation & Adoption
- Update `README.md` / `docs/USAGE.md` with a short “Structured Logs” section describing how to stream events, where artifacts live, and how to run the summarizer utilities.
- Publish an “Analytics Integration” note enumerating the fields downstream jobs (issue tracking, telemetry dashboards) can rely on, including sample JQ / SQL snippets.
- Track the rollout with a migration checklist (CLI flag for opt-in, telemetry to confirm adoption, final cutover date once legacy mode is unused).
