
# gpt-creator — Product Definition & Requirements (PDR) v0.2

**Status:** Draft • **Date:** 2025-09-25  
**Owner:** Platform Engineering • **Reviewers:** PM, DevX, Security, QA  
**Scope:** Global CLI & templates that transform heterogeneous project artifacts (PDR/SDS/RFP, OpenAPI, SQL, Mermaid, Jira, HTML/CSS samples) into a runnable stack (API, Web, Admin, DB, Docker) using Codex (GPT‑5‑high).

---

## 1. Summary

`gpt-creator` is a one‑command product builder. It **discovers**, **normalizes**, **plans**, **generates**, **runs** and **verifies** a project locally. It is opinionated around **NestJS + Prisma + MySQL + Vue 3 + Vite + Docker** but pluggable.

---

## 2. Goals & Non‑Goals

### Goals
- G1 — One‑shot: `gpt-creator create-project <path>` brings up API/Web/Admin/DB/Proxy.  
- G2 — Fuzzy discovery for PDR/SDS/RFP, OpenAPI, SQL dumps, Mermaid, Jira, HTML/CSS.  
- G3 — Deterministic **staging layout** for codegen.  
- G4 — Codegen: API (NestJS), DB (Prisma/MySQL), Web+Admin (Vue3), Docker compose+nginx.  
- G5 — **Verify** gates: acceptance, OpenAPI, a11y, Lighthouse, consent, domain checks.  
- G6 — **Iterate** over Jira tasks with Codex until gates pass.  
- G7 — Global CLI install with shell completions and CI lint/validation.

### Non‑Goals
- Cloud infra provisioning (K8s, CD).  
- Multi‑tenant, SSO, production SRE hardening (beyond hooks).

---

## 3. Personas & Use Cases

- **Founder/Tech Lead:** Bootstrap demo from RFP + OpenAPI + sample pages.  
- **Full‑stack Dev:** Align API to spec + DB dump; scaffold FE pages.  
- **QA:** Run verify suite on PRs; ensure NFR thresholds.

Core flow: _Folder → create-project → stack up → verify → iterate (Jira) → pass_.

---

## 4. Assumptions & Constraints

- macOS primary target; Linux supported in CI.  
- Docker Desktop, Node 20+, MySQL client available.  
- OpenAI API key available locally (env vars).  
- No external network access required at runtime beyond Codex calls.

---

## 5. Inputs & Discovery

| Type | Examples / Patterns | Output (normalized) |
|---|---|---|
| PDR/SDS/RFP | `*PDR*.md`, `*SDS*.md`, `*RFP*.md`, `*website UI pages*.md` | `/staging/inputs/pdr.md` `/staging/inputs/sds.md` `/staging/inputs/rfp.md` |
| OpenAPI | `openapi.yaml|yml|json`, `openAPI*.txt` | `/staging/inputs/openapi.yaml` |
| SQL | `sql_dump*.sql`, `schema.sql` | `/staging/inputs/sql/*.sql` |
| Mermaid | `*.mmd` (db, backoffice, website) | `/staging/inputs/mermaid/*.mmd` |
| Jira | `*jira*.md` | `/staging/inputs/jira.md` |
| Page samples | `pagesamples/**` or `page_samples/**` | `/staging/inputs/page_samples/...` |

Discovery emits `/staging/scan.json` with type, path, confidence.

---

## 6. Architecture (High Level)

```
scan → normalize → plan → generate → db → run → verify → iterate
```

Components: `src/cli/*`, `src/lib/*`, `templates/*`, `verify/*`, `examples/*`.

---

## 7. Functional Requirements (FR)

**FR‑1 CLI**  
- `create-project <path>` orchestrates all phases; fails fast with actionable errors.  
- Subcommands: `scan`, `normalize`, `plan`, `generate [api|web|admin|db|docker]`, `db [provision|import|seed]`, `run [compose-up|logs|open]`, `verify`, `iterate`, `help`, `version`.

**FR‑2 Normalize**  
- Copies inputs to `/staging/inputs` with canonical names; keeps provenance in `/staging/plan/provenance.json`.

**FR‑3 Plan**  
- Produces `/staging/plan/*.md|json` covering routes, entities, FE pages, and tasks.  
- Summarizes mismatches between OpenAPI & SQL (entity/field deltas).

**FR‑4 Generate**  
- API: NestJS skeleton aligned to OpenAPI (health, auth placeholders, resources).  
- DB: Prisma schema from SQL (best effort); seed scaffolds.  
- Web/Admin: Vue 3 (router, layout, tokens) from page samples; page code mapping.  
- Docker: compose.yml, Dockerfiles, nginx.conf; env examples.

**FR‑5 Run**  
- `docker compose up` orchestrated; health‑wait for MySQL and API; proxy on :8080.

**FR‑6 Verify**  
- Runs acceptance (`/health`, web root, admin `/admin/`), OpenAPI validation, pa11y, Lighthouse, consent check, and program‑filters check.  
- Gating thresholds (see §8 and §9).

**FR‑7 Iterate (Jira)**  
- Parses Jira markdown, converts each item to a Codex task with context (diffs, plan, failing checks), applies patch, re‑runs verify.

---

## 8. Non‑Functional Requirements (NFR)

| ID | Requirement | Target |
|---|---|---|
| NFR‑P1 | Bootstrap time on M1+ | ≤ 5 minutes |
| NFR‑R1 | Re‑runs are idempotent | 100% |
| NFR‑S1 | Secrets handling | No secrets in repo/logs |
| NFR‑A11Y | a11y critical errors | 0 blocking issues via pa11y |
| NFR‑LGT | Lighthouse Performance | ≥ 0.80 home/admin |
| NFR‑SEC | Dependency audit | No high severity (CI) |

---

## 9. Acceptance Criteria (Given/When/Then)

- **AC‑1 Stack Up:**  
  Given a folder with sample artifacts → When `create-project` runs → Then API `/health` returns 200, web `/` and admin `/admin/` return 200.

- **AC‑2 OpenAPI Valid:**  
  Given `openapi.yaml` → When `verify` runs → Then swagger‑cli validates spec (exit 0).

- **AC‑3 a11y:**  
  Given running web/admin → When pa11y runs on `/` and `/admin/` → Then no errors of severity “error”; warnings allowed.

- **AC‑4 Lighthouse:**  
  Given running web/admin → When Lighthouse runs → Then performance ≥ 0.80, a11y ≥ 0.85.

- **AC‑5 Consent:**  
  Given web root → When consent checker runs → Then consent keywords/selectors found and a privacy link exists.

- **AC‑6 Domain Filters:**  
  Given `/programs` endpoint → When filters (type,instructor,level,from,to) are applied → Then results match filters for all items.

---

## 10. Security & Privacy

- Redact secrets in logs; never commit `.env`.  
- Allow offline mode for codex previews; send minimal context windows with doc excerpts.  
- Local cache of prompts and responses in `.gpt-creator/` with opt‑out.

---

## 11. Telemetry & Logging

- Structured logs with phase timings (scan, normalize, plan, generate, db, run, verify).  
- `--verbose` and `--quiet`; exit codes standardized.

---

## 12. Configuration

Environment variables (defaults in `config/defaults.sh`):
- `GC_DEFAULT_API_URL` (e.g., `http://localhost:3000/api/v1`)  
- `OPENAI_API_KEY`, `CODEX_MODEL=gpt-5-high`, `GC_CI=1`  
- DB: `MYSQL_*`, `DATABASE_URL`

User overrides: `~/.config/gpt-creator/config.sh`.

---

## 13. Templates & Outputs

- Docker: `templates/docker/*.tmpl`  
- API (NestJS): `templates/api/nestjs/*`  
- Web/Admin (Vue3): `templates/web/vue3/*`, `templates/admin/vue3/*`  
- DB: `templates/db/mysql/*`  
- OpenAPI generator: `templates/openapi/*`

Generated apps live under `/apps/{api,web,admin}` in the target project.

---

## 14. Risks & Mitigations

- **R1 Discovery misses files** → fuzzy match + manual override + logs.  
- **R2 Spec drift OpenAPI/SQL** → plan deltas + verify gate fails.  
- **R3 Ambiguous HTML → Vue** → require `PAGE-CODE` & docs; human review loop.  
- **R4 Tooling variance** → preflight checks; actionable error messages.

---

## 15. Milestones

- **M0** Scaffold repo + examples + verify.  
- **M1** End‑to‑end success on sample project.  
- **M2** OpenAPI‑first resource generation.  
- **M3** Pages → Vue mapping heuristics.  
- **M4** Jira iterate loop with auto‑patch & re‑verify.

---

## 16. Glossary

- **Staging**: normalized copy of inputs used for deterministic generation.  
- **Verify**: suite of acceptance & NFR checks used as gates.  
- **Iterate**: Codex‑driven task execution from Jira file.

---

## Appendix A — CLI Reference (short)

See `docs/USAGE.md`, `man/gpt-creator.1`.

## Appendix B — Folder Structure

See repo root README and `/templates`, `/src/cli`, `/src/lib`, `/verify`, `/examples`.

## Appendix C — Verify Thresholds

Configurable via env; defaults defined in §8 and §9.

---

*End of PDR v0.2*
