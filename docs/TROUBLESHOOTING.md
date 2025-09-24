# TROUBLESHOOTING

**Docker not running**
- Start Docker Desktop. Re-run: `gpt-creator run up --root /path`.

**MySQL import fails**
- Check credentials in `.env`. Ensure dump matches MySQL 8. Re-run: `gpt-creator db import --root /path`.

**OpenAI/Codex auth error**
- Export a valid `OPENAI_API_KEY`. If using a custom endpoint, set `CODEX_BASE_URL`.

**Ports already in use**
- Edit `docker/compose.yml` in the project to change host ports; re-run `run up`.

**Vue site isn’t styling correctly**
- Ensure `page_samples/style.css` was discovered; re-run `scan` then `normalize` then `generate web`.

**Verify step fails Lighthouse**
- Optimize images, check bundle sizes, ensure gzip/brotli at proxy. Re-run `verify`.
