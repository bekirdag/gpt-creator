import pathlib
import re
import sys


def rewrite_add_column_if_not_exists(sql: str) -> str:
    alter_pattern = re.compile(r'ALTER\s+TABLE\s+(`?)([A-Za-z_][A-Za-z0-9_]*)\1\s+(.*?);', re.IGNORECASE | re.DOTALL)
    add_col_pattern = re.compile(r'ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+(`?)([A-Za-z_][A-Za-z0-9_]*)\1\s+', re.IGNORECASE)
    add_key_pattern = re.compile(r'ADD\s+(UNIQUE\s+)?KEY\s+(`?)([A-Za-z_][A-Za-z0-9_]*)\2', re.IGNORECASE)
    add_constraint_pattern = re.compile(r'ADD\s+CONSTRAINT\s+(`?)([A-Za-z_][A-Za-z0-9_]*)\1\s+FOREIGN\s+KEY', re.IGNORECASE)

    def find_clause_end(body: str, start_idx: int) -> int:
        depth = 0
        i = start_idx
        while i < len(body):
            ch = body[i]
            if ch == '(':
                depth += 1
            elif ch == ')':
                if depth > 0:
                    depth -= 1
            elif ch == ',' and depth == 0:
                return i
            elif ch == ';' and depth == 0:
                return i
            i += 1
        return len(body)

    def split_clauses(body: str):
        clauses = []
        current = []
        depth = 0
        for ch in body:
            if ch == '(':
                depth += 1
            elif ch == ')':
                if depth > 0:
                    depth -= 1
            if ch == ',' and depth == 0:
                clauses.append(''.join(current))
                current = []
                continue
            current.append(ch)
        tail = ''.join(current)
        if tail.strip():
            clauses.append(tail)
        return clauses

    parts = []
    last_idx = 0

    for match in alter_pattern.finditer(sql):
        table_name = match.group(2)
        body = match.group(3)
        clauses = split_clauses(body)

        column_additions = []
        index_additions = []
        constraint_additions = []
        leftover_clauses = []

        for clause in clauses:
            clause_stripped = clause.strip()
            if not clause_stripped:
                continue
            col_match = add_col_pattern.match(clause_stripped)
            if col_match:
                definition = clause_stripped[col_match.end():].strip().rstrip(',')
                col_name = col_match.group(2)
                quote = col_match.group(1) or ''
                column_additions.append((col_name, quote, definition))
                continue
            key_match = add_key_pattern.match(clause_stripped)
            if key_match:
                index_name = key_match.group(3)
                index_additions.append((clause_stripped, index_name))
                continue
            constraint_match = add_constraint_pattern.match(clause_stripped)
            if constraint_match:
                constraint_name = constraint_match.group(2)
                constraint_additions.append((clause_stripped, constraint_name))
                continue
            leftover_clauses.append(clause.rstrip())

        if not (column_additions or index_additions or constraint_additions):
            continue

        parts.append(sql[last_idx:match.start()])

        dynamic_sql = []
        for col_name, quote, definition in column_additions:
            column_token = f"{quote}{col_name}{quote}"
            ddl = f"ALTER TABLE `{table_name}` ADD COLUMN {column_token} {definition}".strip()
            ddl_escaped = ddl.replace("'", "''")
            dynamic_sql.append(
                "SET @ddl := (\n"
                "  SELECT IF(\n"
                "    EXISTS(SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '"
                + table_name + "' AND COLUMN_NAME = '" + col_name + "'),\n"
                "    'DO 0',\n"
                "    '" + ddl_escaped + "'\n"
                "  )\n"
                ");\nPREPARE stmt FROM @ddl;\nEXECUTE stmt;\nDEALLOCATE PREPARE stmt;\n"
            )

        for clause_text, index_name in index_additions:
            ddl = f"ALTER TABLE `{table_name}` {clause_text}".strip()
            ddl_escaped = ddl.replace("'", "''")
            dynamic_sql.append(
                "SET @ddl := (\n"
                "  SELECT IF(\n"
                "    EXISTS(SELECT 1 FROM INFORMATION_SCHEMA.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '"
                + table_name + "' AND INDEX_NAME = '" + index_name + "'),\n"
                "    'DO 0',\n"
                "    '" + ddl_escaped + "'\n"
                "  )\n"
                ");\nPREPARE stmt FROM @ddl;\nEXECUTE stmt;\nDEALLOCATE PREPARE stmt;\n"
            )

        for clause_text, constraint_name in constraint_additions:
            ddl = f"ALTER TABLE `{table_name}` {clause_text}".strip()
            ddl_escaped = ddl.replace("'", "''")
            dynamic_sql.append(
                "SET @ddl := (\n"
                "  SELECT IF(\n"
                "    EXISTS(SELECT 1 FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '"
                + table_name + "' AND CONSTRAINT_NAME = '" + constraint_name + "'),\n"
                "    'DO 0',\n"
                "    '" + ddl_escaped + "'\n"
                "  )\n"
                ");\nPREPARE stmt FROM @ddl;\nEXECUTE stmt;\nDEALLOCATE PREPARE stmt;\n"
            )

        if leftover_clauses:
            remaining_body = ',\n'.join(leftover_clauses)
            dynamic_sql.append(f"ALTER TABLE `{table_name}`\n{remaining_body}\n;")

        parts.append('\n'.join(dynamic_sql))
        last_idx = match.end()

    parts.append(sql[last_idx:])
    return ''.join(parts)


def drop_check_constraint(src_text: str, name: str) -> str:
    pattern = re.compile(rf"CONSTRAINT\s+{re.escape(name)}\s+CHECK\s*\(", re.IGNORECASE)
    while True:
        match = pattern.search(src_text)
        if not match:
            return src_text
        start = match.start()
        comma_idx = src_text.rfind(',', 0, start)
        if comma_idx == -1:
            comma_idx = start
        depth = 1
        i = match.end()
        while i < len(src_text):
            ch = src_text[i]
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
                if depth == 0:
                    i += 1
                    break
            i += 1
        else:
            return src_text
        src_text = src_text[:comma_idx] + src_text[i:]


def render_sql(src: pathlib.Path, dest: pathlib.Path, db_name: str, app_user: str, app_pass: str) -> None:
    text = src.read_text()

    text = text.replace('{{DB_NAME}}', db_name)
    text = text.replace('{{DB_USER}}', app_user)
    text = text.replace('{{DB_PASSWORD}}', app_pass)

    text = rewrite_add_column_if_not_exists(text)

    old_slug_update = """UPDATE instructors
SET slug = LOWER(
  REPLACE(
    REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
      TRIM(COALESCE(NULLIF(display_name,''), CONCAT(TRIM(first_name),' ',TRIM(last_name)))),
      'ç','c'),'ğ','g'),'ı','i'),'ö','o'),'ş','s'),'ü','u'
    )
  , ' ', '-')
)
WHERE slug IS NULL;"""

    new_slug_update = """UPDATE instructors
SET slug = LOWER(
  REPLACE(
    REPLACE(
      REPLACE(
        REPLACE(
          REPLACE(
            REPLACE(
              REPLACE(
                TRIM(COALESCE(NULLIF(display_name,''), CONCAT(TRIM(first_name),' ',TRIM(last_name)))),
                'ç','c'),
              'ğ','g'),
            'ı','i'),
          'ö','o'),
        'ş','s'),
      'ü','u'),
    ' ', '-')
)
WHERE slug IS NULL;"""

    text = text.replace(old_slug_update, new_slug_update)

    old_unique_block = """ALTER TABLE instructors
  MODIFY slug VARCHAR(120) NOT NULL,
  ADD UNIQUE KEY uq_instructors_slug (slug);"""

    new_unique_block = """ALTER TABLE instructors
  MODIFY slug VARCHAR(120) NOT NULL;

SET @ddl := (
  SELECT IF(
    EXISTS(SELECT 1 FROM INFORMATION_SCHEMA.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'instructors' AND INDEX_NAME = 'uq_instructors_slug'),
    'DO 0',
    'ALTER TABLE `instructors` ADD UNIQUE KEY `uq_instructors_slug` (`slug`)' 
  )
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;"""

    text = text.replace(old_unique_block, new_unique_block)

    text = re.sub(r'^\s*USE\s+`?[^`]+`?;', lambda _m: f"USE `{db_name}`;", text, flags=re.IGNORECASE | re.MULTILINE)
    text = re.sub(r'CREATE\s+DATABASE\s+IF\s+NOT\s+EXISTS\s+`[^`]+`', lambda _m: f"CREATE DATABASE IF NOT EXISTS `{db_name}`", text, flags=re.IGNORECASE)
    text = re.sub(r'ON\s+`[^`]+`\.\*\s+TO', lambda _m: f"ON `{db_name}`.* TO", text, flags=re.IGNORECASE)
    text = re.sub(r"(CREATE\s+USER[^']*')([^']+)(')", lambda m: f"{m.group(1)}{app_user}{m.group(3)}", text, flags=re.IGNORECASE)
    text = re.sub(r"(IDENTIFIED\s+BY\s+')([^']+)(')", lambda m: f"{m.group(1)}{app_pass}{m.group(3)}", text, flags=re.IGNORECASE)
    text = re.sub(r"(TO\s+')([^']+)('@)", lambda m: f"{m.group(1)}{app_user}{m.group(3)}", text, flags=re.IGNORECASE)

    def wrap_add_column(match):
        prefix, name = match.group(1), match.group(2)
        if name.startswith('`') and name.endswith('`'):
            return match.group(0)
        return f"{prefix}`{name}`"

    text = re.sub(r"(?i)(ADD\s+COLUMN\s+)([A-Za-z_][A-Za-z0-9_]*)", wrap_add_column, text)

    for ident in ("row_number", "field_name", "error_code"):
        pattern = re.compile(rf"(?<![`'])\b{re.escape(ident)}\b(?![`'])", re.IGNORECASE)
        text = pattern.sub(lambda m: f"`{m.group(0)}`", text)

    for constraint in ("ck_seo_target", "ck_legal_rev_publish"):
        text = drop_check_constraint(text, constraint)

    dest.write_text(text)


def main() -> int:
    if len(sys.argv) < 6:
        return 1
    src = pathlib.Path(sys.argv[1])
    dest = pathlib.Path(sys.argv[2])
    db_name, app_user, app_pass = sys.argv[3:6]
    render_sql(src, dest, db_name, app_user, app_pass)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
