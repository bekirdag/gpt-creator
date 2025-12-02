import os
import re
import shlex
import sys
from pathlib import Path

IGNORE_DIRS = {
    '.git', '.hg', '.svn', '.tox', '.pytest_cache', '.idea', '.vscode',
    '__pycache__', 'node_modules', 'vendor', 'dist', 'build', 'tmp', 'temp'
}

ORDER_MAP = {'init': 0, 'schema': 1, 'seed': 2}


def normalise_identifier(token: str) -> str:
    token = token.strip().rstrip(';').strip()
    if token.endswith('.*'):
        token = token[:-2]
    if '.' in token:
        token = token.split('.', 1)[0]
    if token and token[0] in "`\"'" and token[-1] == token[0]:
        token = token[1:-1]
    return token.strip()


def collect_sql_entries(root: Path):
    candidate_dirs = []
    seen_dirs = set()
    for rel in [
        os.path.join('.gpt-creator', 'staging', 'sql'),
        os.path.join('.gpt-creator', 'staging'),
        os.path.join('staging', 'sql'),
        os.path.join('staging'),
        os.path.join('db'),
        os.path.join('database'),
        os.path.join('sql'),
        os.path.join('data', 'sql'),
        os.path.join('data'),
        '.',
    ]:
        path = (root / rel).resolve()
        if path.is_dir() and path not in seen_dirs:
            candidate_dirs.append(path)
            seen_dirs.add(path)

    entries = []
    seen_files = set()

    for base in candidate_dirs:
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
            for fname in filenames:
                if not fname.lower().endswith('.sql'):
                    continue
                full = Path(dirpath) / fname
                if full in seen_files:
                    continue
                seen_files.add(full)
                rel_path = os.path.relpath(full, root)
                base_name = os.path.basename(full)
                rel_norm = rel_path.replace('\\', '/')
                if rel_norm.startswith('.gpt-creator/staging/') and (
                    base_name.startswith('import-') or base_name.startswith('seed-')
                ):
                    continue
                lower = fname.lower()
                dir_lower = dirpath.lower()
                label = 'schema'
                if 'init' in lower or 'init' in dir_lower:
                    label = 'init'
                elif any(token in lower or token in dir_lower for token in (
                    'seed', 'fixture', 'sample', 'data-seed', 'seed-data'
                )):
                    label = 'seed'
                elif any(token in lower for token in (
                    'dump', 'schema', 'structure', 'backup', 'snapshot'
                )):
                    label = 'schema'
                try:
                    mtime = os.path.getmtime(full)
                except OSError:
                    mtime = 0
                entries.append((label, mtime, full))

    entries.sort(key=lambda item: (ORDER_MAP.get(item[0], 3), item[1], str(item[2])))
    return entries


def extract_metadata(entries, root: Path):
    db_create_re = re.compile(r"CREATE\s+DATABASE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>`[^`]+`|\"[^\"]+\"|'[^']+'|[A-Za-z0-9_]+)", re.IGNORECASE)
    use_re = re.compile(r"\bUSE\s+(?P<name>`[^`]+`|\"[^\"]+\"|'[^']+'|[A-Za-z0-9_]+)", re.IGNORECASE)
    create_user_re = re.compile(r"CREATE\s+USER\s+(?:IF\s+NOT\s+EXISTS\s+)?'(?P<user>[^']+)'(?:\s*@\s*'(?P<host>[^']*)')?\s+IDENTIFIED(?:\s+WITH\s+[A-Za-z0-9_]+)?\s+BY\s+'(?P<pw>[^']+)'", re.IGNORECASE)
    alter_user_re = re.compile(r"ALTER\s+USER\s+'(?P<user>[^']+)'(?:\s*@\s*'(?P<host>[^']*)')?\s+IDENTIFIED(?:\s+WITH\s+[A-Za-z0-9_]+)?\s+BY\s+'(?P<pw>[^']+)'", re.IGNORECASE)
    grant_re = re.compile(r"GRANT\s+.+?\s+ON\s+(?P<db>`[^`]+`|\"[^\"]+\"|'[^']+'|[A-Za-z0-9_]+(?:\\.[^\s;]+)?)\s+TO\s+'(?P<user>[^']+)'", re.IGNORECASE)

    db_name = ''
    app_user = ''
    app_password = ''
    user_host = ''

    for label, _, path in entries:
        if db_name and app_user and app_password:
            break
        try:
            text = Path(path).read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue
        if not db_name:
            match = db_create_re.search(text)
            if match:
                db_name = normalise_identifier(match.group('name'))
        if not db_name:
            match = use_re.search(text)
            if match:
                db_name = normalise_identifier(match.group('name'))
        if not app_user or not app_password:
            match = create_user_re.search(text) or alter_user_re.search(text)
            if match:
                app_user = match.group('user')
                app_password = match.group('pw')
                host = match.group('host') if match.group('host') is not None else ''
                user_host = host
        if not app_user:
            try:
                for grant_match in grant_re.finditer(text):
                    db_name = db_name or normalise_identifier(grant_match.group('db'))
                    user_token = grant_match.group('user')
                    if user_token:
                        app_user = user_token
                        break
            except Exception:
                pass

    if not app_user:
        app_user = 'app'
    if not app_password:
        app_password = 'app_pass'
    if not db_name:
        db_name = 'app'

    init_list = [str(path) for label, _, path in entries if label == 'init']
    schema_list = [str(path) for label, _, path in entries if label == 'schema']
    seed_list = [str(path) for label, _, path in entries if label == 'seed']
    all_list = [str(path) for _, _, path in entries]

    lines = [
        db_name,
        app_user,
        app_password,
        user_host,
        '\n'.join(init_list),
        '--',
        '\n'.join(schema_list),
        '--',
        '\n'.join(seed_list),
        '--',
        '\n'.join(all_list),
    ]
    print('\n'.join(lines))


def refresh_stack_collect_sql(root: Path):
    entries = collect_sql_entries(root)
    extract_metadata(entries, root)


def main() -> int:
    if len(sys.argv) < 2:
        return 1
    root = Path(sys.argv[1]).resolve()
    refresh_stack_collect_sql(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
