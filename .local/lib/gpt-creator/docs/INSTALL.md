# INSTALL

## macOS (global install)

```bash
git clone https://example.com/your-org/gpt-creator.git
cd gpt-creator
./install.sh
```

What it does:
- Installs to `/usr/local/lib/gpt-creator`
- Symlinks `gpt-creator` to `/usr/local/bin/gpt-creator`
- Installs shell completions (bash/zsh/fish)
- Performs a preflight: Docker Desktop, Node 20+, pnpm, MySQL client, Codex client, OpenAI creds

Uninstall:
```bash
/usr/local/lib/gpt-creator/uninstall.sh
```
