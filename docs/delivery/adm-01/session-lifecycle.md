# Session Lifecycle Blueprint

## Overview
- Idle budget: 30 minutes with a five minute warning window (`SESSION_IDLE_MINUTES=30`, `SESSION_WARNING_LEAD_SECONDS=300`).
- Absolute cap: 12 hours (`SESSION_ABSOLUTE_MINUTES=720`); heartbeats never extend this limit.
- Security and architecture sign-off recorded through the relevant policy addendum and change-control entry.
- Default configuration lives in shared infrastructure; overrides require change-control approval and evidence updates.

## Flow Scenarios
### Login (Sunny Day)
1. Admin/Editor authenticates with `POST /auth/login`.
2. API issues session row (`id`, `user_id`, `session_token`, `last_seen_at`, `expires_at=created_at+12h`, `revoked_at=NULL`).
3. SPA stores token, assigns a tab-local `tabId` (UUID v4), emits `session-started` broadcast, and schedules heartbeats no less than every 120 seconds while active.

### Heartbeat Maintenance
- Endpoint: `POST /api/v1/admin/session/heartbeat` (RBAC: Admin|Editor).
- Payload: `{ "tabId": uuid, "clientTimestamp": iso8601, "lastInteractionAt"?: iso8601, "visibilityState"?: "visible" | "hidden" }`.
- Success: `204 No Content`; service updates `last_seen_at = now` (debounced at ≥5 seconds) and recalculates `warn_at = last_seen_at + idle_budget - warning_lead`.
- Rate limits: ≤12 heartbeats per minute per session, ≤60 per minute per IP; violations return 429 with Problem+JSON, scope (`session`|`ip`) echoed in headers.
- Missing heartbeat fallback: client retries with 10s → 30s → 60s backoff, tagging retries with the same `tabId`. After two missed intervals, UI surfaces offline banner and caches the latest warning deadline locally.

### Idle Warning
1. When `now >= warn_at` and `idle_warning_sent` is false, heartbeat responds `204` with headers `X-Session-Warn-In` (seconds) and `X-Session-Tab` (optional).
2. Client displays countdown modal, records analytics event `admin.session.warning` with `{ remainingSeconds, tabId, visibilityState }`.
3. Countdown broadcast via client-side messaging (for example a `BroadcastChannel` or storage events) to keep background tabs synchronized.

### Idle Timeout
- Condition: `now >= last_seen_at + idle_budget`.
- Response: `401` Problem+JSON `{ code: "IDLE_TIMEOUT", message, reauthUrl, retryable: false, remainingSeconds: 0, tabId }`.
- Client clears auth state, emits `admin.session.ended` (reason `idleTimeout`), and redirects to `reauthUrl`.

### Absolute Expiry
- Condition: `now >= created_at + absolute_cap`.
- Guarded endpoints (`GET /api/v1/me`, heartbeat, protected admin APIs) return `401 { code: "SESSION_EXPIRED", ... }`.
- SPA shows absolute timeout message and prompts full re-authentication.

### Manual Logout or Revoke
- `POST /auth/logout` sets `revoked_at = now`, tears down tokens, and returns 204.
- Ops/Security tooling can revoke sessions directly; subsequent heartbeats return `401 { code: "SESSION_REVOKED" }`.
- Analytics event `admin.session.ended` recorded with reason `manualLogout` or `revoked`.

### Network Loss / Offline Tabs
- Tabs pause heartbeats when `visibilityState="hidden"` but send a keep-alive every 120 seconds.
- Offline detection triggers sticky banner; cached warning deadline ensures forced logout if reconnection misses the grace period.
- Once connectivity returns, first heartbeat reconciles timers; stale timestamps older than five minutes are ignored but return 204 to avoid double logout.

## Multi-Tab Behaviour
- Heartbeats always include `tabId`; server optionally mirrors it in warning/timeout responses.
- Broadcast semantics: `session-heartbeat`, `session-warning`, `session-ended` events keep tabs in sync and prevent duplicate dialogs.
- Forced logouts propagate via broadcast even if the originating tab closes mid-flow.

## API Contract
```json
{
  "code": "IDLE_TIMEOUT" | "SESSION_EXPIRED" | "SESSION_REVOKED",
  "message": "string",
  "reauthUrl": "https://admin.example.com/login?redirect=...",
  "retryable": false,
  "remainingSeconds": 0,
  "tabId": "uuid4?" 
}
```
- Login/logout endpoints retain legacy behaviour.
- Rate-limit breaches respond with `{ code: "RATE_LIMITED", scope, retryAfterSeconds }`.
- All Problem payloads include `traceId` header to align with logging.

## Persistence & Jobs
- `sessions` table columns: `id`, `user_id`, `session_token` (unique), `ip_address`, `user_agent`, `last_seen_at`, `expires_at`, `revoked_at`, `created_at`.
- Heartbeat writes are idempotent; stale client timestamps (< current `last_seen_at`) are ignored.
- Background pruning task runs hourly: deletes sessions where `expires_at < now - 1 day` or `revoked_at < now - 7 days`, and rotates audit trail references.
- Cache: in-memory store keyed by `session_token` with TTL `min(idle_budget, 5 minutes)`; warmed on login and pruned when revoked.

## Observability & Alerts
- Logs: `SESSION_LOGIN`, `SESSION_HEARTBEAT`, `SESSION_WARNING`, `SESSION_TERMINATED` (fields: `sessionId`, `userId`, `tabId`, `reason`, `traceId`).
- Metrics:
  - Counter `admin_session_requests_total{action=login|heartbeat|logout, outcome=success|failed|rate_limited}`.
  - Gauge `admin_active_sessions`.
  - Histogram `admin_session_idle_seconds_bucket`.
- Alerts:
  - Heartbeat lag P95 > 120s (5 minute window).
  - Idle warning to termination delta > 300s.
  - Termination spikes > 3x baseline.

## Analytics & UX
- Analytics events: `admin.session.warning`, `admin.session.ended`, `admin.session.rate_limited`.
- Each event carries privacy flag, locale, `tabId`, and `remainingSeconds` when relevant.
- UX messaging stored alongside product design assets; coordinate with content team for localisation updates.

## QA Coverage
- Unit: lifecycle logic (idle math, warning windows, revoke path).
- Integration: session service (multi-tab sync, rate limit enforcement, offline resume).
- End-to-end: automated acceptance coverage for warning modal, forced logout, manual revoke, and idle override toggles.
- Evidence stored under `qa/evidence/session-lifecycle/` with screenshots and logs.

## Change Control
- Change request CR-SESSION-LIFECYCLE-2025-11-05 captured the 30 minute idle budget and five minute warning window.
- Change-control board approvals recorded in the centralized ticketing system; roll-out completed 2025-11-05 18:00 UTC.
- Future overrides require change-control approval plus security and architecture sign-off, and must update this blueprint and the supporting policy documentation.
