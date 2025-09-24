# GETTING_STARTED

Quick path:

```bash
# 1) Install (see INSTALL.md for details)
curl -fsSL https://example.com/gpt-creator/install.sh | bash

# 2) Prepare your inputs (any names, any layout):
#    - PDR / SDS / RFP (md/doc/txt)
#    - OpenAPI (openapi.yaml|json)
#    - SQL dump (sql_dump*.sql)
#    - Mermaid diagrams (*.mmd)
#    - Jira tasks (markdown)
#    - page_samples/ (HTML + CSS for web & backoffice)

# 3) Run the orchestrator
gpt-creator create-project /path/to/project

# 4) Bring containers up and open the app
gpt-creator run up --root /path/to/project
gpt-creator run open --root /path/to/project
```

What you get:
- Dockerized NestJS API + Vue 3 Website + Admin + MySQL 8
- DB provision/import/seed done for you
- Acceptance/NFR sanity checks
