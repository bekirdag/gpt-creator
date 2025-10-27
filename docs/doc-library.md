# Documentation Library (shim)

This shim exists so prompts that reference `doc-library.md` resolve even if the canonical file lives in `.gpt-creator/staging/doc-library.md`.

- Canonical (when present): `.gpt-creator/staging/doc-library.md`
- Headings index: `.gpt-creator/staging/doc-index.md`
- Catalog: `.gpt-creator/staging/plan/work/doc-catalog.json`

## Conventions
- Each entry: **title** — owner — path — tags  
  Examples:
  - **SDS** — Architecture — `docs/sds.md` — tags: [security, rbac, admin]
  - **RFP** — Product — `docs/rfp.md` — tags: [requirements]

> If the staging copy is absent, add entries here; when staging exists, treat this as a readme that points to it.
