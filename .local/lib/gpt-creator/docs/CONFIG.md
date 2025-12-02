# CONFIG

Default location: `~/.config/gpt-creator/config.yaml`

```yaml
version: 1
codex:
  provider: openai
  model: gpt-5-high
  base_url: ${CODEX_BASE_URL:-}
  api_key_env: OPENAI_API_KEY

project:
  default_timezone: Europe/Istanbul
  docker_compose_file: docker/compose.yml
  mysql:
    image: mysql:8.4
    root_password_env: MYSQL_ROOT_PASSWORD
    database: appdb
    user: app
    password_env: MYSQL_PASSWORD

discovery:
  include:
    - "**/*.md"
    - "**/*.mmd"
    - "**/*.yaml"
    - "**/*.yml"
    - "**/*.sql"
    - "page_samples/**/*.html"
    - "page_samples/**/*.css"
  fuzzy_labels:
    pdr: ["pdr", "product design requirements"]
    sds: ["sds", "system design specification"]
    rfp: ["rfp", "request for proposal"]
    jira: ["jira", "tasks", "todo"]
    openapi: ["openapi", "swagger"]
    sql: ["sql_dump", "schema", "database"]
    diagrams: ["mermaid", "mmd"]
    pages: ["page_samples", "website_ui_pages", "backoffice_pages"]

generate:
  api:
    framework: nestjs
    orm: prisma
  web:
    framework: vue3
  admin:
    framework: vue3
  db:
    seeds: true

verify:
  lighthouse_mobile_threshold: 90
  wcag_level: "AA"
```

Override with `GPT_CREATOR_CONFIG=/path/to/config.yaml`.
