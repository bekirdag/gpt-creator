# Build Plan (Scaffold)

This file will be populated by Codex based on the staged inputs:
- docs/pdr.md, docs/sds.md, docs/rfp.md, docs/jira.md, docs/ui-pages.md
- openapi/openapi.(yaml|json|src)
- sql/dump.sql
- diagrams/*.mmd
- samples/**

Next steps (automated in future steps):
1. Generate an execution plan with acceptance criteria.
2. Synthesize API scaffolds from OpenAPI (NestJS).
3. Generate schema & migrations (MySQL 8).
4. Generate Vue 3 website & admin shells from UI pages and CSS tokens.
5. Wire Docker Compose for local dev (API, MySQL, Admin, Web, Proxy).
6. Run acceptance checks, then drive Jira via create-tasks/work-on-tasks.

