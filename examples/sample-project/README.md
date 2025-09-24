# Sample Project for `gpt-creator`

This is a minimal reference project you can point `gpt-creator` at to see the full workflow:
- OpenAPI spec for the API
- MySQL schema
- Basic environment variables

## Try it

```bash
# from repo root
gpt-creator create-project ./examples/sample-project
```

`gpt-creator` will scan the folder, normalize inputs into a staging area, generate the backend (NestJS), clients, and Vue apps, provision DB in Docker, and run the stack.

### What’s included
- `openapi.yaml` — endpoints for `/health` and `/programs` (with filters).  
- `sql/schema.sql` — MySQL 8 schema for `users`, `instructors`, `programs`, and a join table.  
- `.env.example` — environment variables used by Docker and apps.

### Notes
- The `/programs` endpoint supports filters used by verify scripts: `type`, `instructor`, `level`, `from`, `to`.
- DB names and credentials match the docker-compose template defaults (`yoga_app`, user `yoga`).
