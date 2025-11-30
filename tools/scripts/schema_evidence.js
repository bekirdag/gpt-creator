#!/usr/bin/env node
/**
 * Schema evidence indexer/query helper.
 * Scans SQL/ORM sources across multiple stacks (SQL, Prisma, Knex, Rails, TypeORM, Django).
 */

const fs = require('fs');
const path = require('path');

const SUPPORTED_EXTS = new Set(['.sql', '.prisma', '.js', '.ts', '.rb', '.py']);
const IGNORE_DIRS = new Set([
  '.git',
  '.gpt-creator',
  'node_modules',
  '.next',
  '.turbo',
  'dist',
  'build',
  '.venv',
  'venv',
]);

const RX = {
  // SQL
  createTable: /\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?["'`\[]?([\w.:-]+)["'`\]]?/gi,
  createIndex: /\bCREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?["'`\[]?([\w.:-]+)["'`\]]?\s+ON\s+["'`\[]?([\w.:-]+)["'`\]]?/gi,
  // Prisma
  prismaModel: /^\s*model\s+(\w+)\s*\{/gim,
  prismaMap: /@@map\("([^"]+)"\)/gi,
  prismaIdx: /@@index\([^)]*map:\s*"([^"]+)"[^)]*\)/gi,
  // Knex
  knexTable: /knex\.schema\.createTable\(\s*['"]([^'"]+)['"]/gi,
  knexIdx: /\.index\(\s*['"]([^'"]+)['"]/gi,
  // Rails
  railsTable: /create_table\s+:([\w_]+)/gi,
  railsIdx: /add_index\s+:?([\w_]+)\s*,\s*(?::[\w_]+|\[[^\]]+\])\s*(?:,|\s)\s*name:\s*['"]([^'"]+)['"]/gi,
  // TypeORM
  typeormEntity: /@Entity\s*\(\s*['"]?([\w_]+)['"]?\s*\)/gi,
  typeormIdx: /@Index\s*\(\s*['"]([^'"]+)['"]/gi,
  // Django
  djangoModel: /migrations\.CreateModel\(\s*name=['"]([\w_]+)['"]/gi,
  djangoTable: /db_table=['"]([\w_]+)['"]/gi,
  djangoIdx: /migrations\.Index\([^)]*name=['"]([^'"]+)['"][^)]*\)/gi,
};

function wantFile(filePath) {
  return SUPPORTED_EXTS.has(path.extname(filePath).toLowerCase());
}

function* walk(dir) {
  let entries = [];
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    if (IGNORE_DIRS.has(entry.name)) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      yield* walk(full);
    } else if (entry.isFile() && wantFile(full)) {
      yield full;
    }
  }
}

function pushOnce(arr, item) {
  const key = `${item.name}:${item.file}`;
  if (!arr.some((existing) => `${existing.name}:${existing.file}` === key)) {
    arr.push(item);
  }
}

function norm(name) {
  if (!name) return name;
  return name.replace(/^["'`\[]|["'`\]]$/g, '');
}

function indexDir(root) {
  const output = { tables: [], indexes: [], models: [], sources: [] };
  for (const file of walk(root)) {
    let source = '';
    try {
      source = fs.readFileSync(file, 'utf8');
    } catch {
      continue;
    }
    const rel = path.relative(root, file);
    let match;
    // SQL
    while ((match = RX.createTable.exec(source))) {
      pushOnce(output.tables, { name: norm(match[1]), file: rel, kind: 'sql' });
    }
    while ((match = RX.createIndex.exec(source))) {
      pushOnce(output.indexes, { name: norm(match[1]), on: norm(match[2]), file: rel, kind: 'sql' });
    }
    // Prisma
    while ((match = RX.prismaModel.exec(source))) {
      pushOnce(output.models, { name: match[1], file: rel, kind: 'prisma' });
    }
    while ((match = RX.prismaMap.exec(source))) {
      pushOnce(output.tables, { name: norm(match[1]), file: rel, kind: 'prisma' });
    }
    while ((match = RX.prismaIdx.exec(source))) {
      pushOnce(output.indexes, { name: norm(match[1]), file: rel, kind: 'prisma' });
    }
    // Knex
    while ((match = RX.knexTable.exec(source))) {
      pushOnce(output.tables, { name: norm(match[1]), file: rel, kind: 'knex' });
    }
    while ((match = RX.knexIdx.exec(source))) {
      pushOnce(output.indexes, { name: norm(match[1]), file: rel, kind: 'knex' });
    }
    // Rails
    while ((match = RX.railsTable.exec(source))) {
      pushOnce(output.tables, { name: norm(match[1]), file: rel, kind: 'rails' });
    }
    while ((match = RX.railsIdx.exec(source))) {
      pushOnce(output.indexes, {
        name: norm(match[2]),
        on: norm(match[1]),
        file: rel,
        kind: 'rails',
      });
    }
    // TypeORM
    while ((match = RX.typeormEntity.exec(source))) {
      pushOnce(output.tables, { name: norm(match[1]), file: rel, kind: 'typeorm' });
    }
    while ((match = RX.typeormIdx.exec(source))) {
      pushOnce(output.indexes, { name: norm(match[1]), file: rel, kind: 'typeorm' });
    }
    // Django
    while ((match = RX.djangoTable.exec(source))) {
      pushOnce(output.tables, { name: norm(match[1]), file: rel, kind: 'django' });
    }
    while ((match = RX.djangoIdx.exec(source))) {
      pushOnce(output.indexes, { name: norm(match[1]), file: rel, kind: 'django' });
    }
  }
  output.sources = Array.from(new Set(output.tables.concat(output.indexes).map((item) => item.file)));
  return output;
}

function normalizeNames(name) {
  const lower = name.toLowerCase();
  return new Set([name, lower, name.replace(/\./g, '_'), lower.replace(/\./g, '_')]);
}

function queryIndex(index, kind, name) {
  const targets = normalizeNames(name);
  const haystack = kind === 'table' ? index.tables : index.indexes;
  return haystack.filter(
    (entry) => targets.has(entry.name) || targets.has(entry.name.toLowerCase()),
  );
}

function usage() {
  console.error('usage: schema_evidence.js build|query <table|index> <name> [--out <file>]');
}

const [, , command, argKind, argName, ...rest] = process.argv;
const workspace = process.env.GC_WORKSPACE_DIR || process.cwd();
const outIndex =
  rest.includes('--out') && rest[rest.indexOf('--out') + 1]
    ? path.resolve(rest[rest.indexOf('--out') + 1])
    : path.join(workspace, '.gpt-creator', 'index', 'schema-evidence.json');

fs.mkdirSync(path.dirname(outIndex), { recursive: true });

if (command === 'build') {
  const idx = indexDir(workspace);
  fs.writeFileSync(outIndex, JSON.stringify(idx, null, 2));
  console.log(
    `wrote index ${outIndex} (${idx.tables.length} tables, ${idx.indexes.length} indexes)`,
  );
  process.exit(0);
}

if (command === 'query') {
  if (!argKind || !argName) {
    usage();
    process.exit(2);
  }
  let index = { tables: [], indexes: [] };
  if (fs.existsSync(outIndex)) {
    try {
      index = JSON.parse(fs.readFileSync(outIndex, 'utf8'));
    } catch {
      // ignore corrupted cache
    }
  }
  const hits = queryIndex(index, argKind, argName);
  if (hits.length > 0) {
    console.log(JSON.stringify(hits, null, 2));
    process.exit(0);
  }
  console.log('NO_MATCH');
  process.exit(1);
}

usage();
process.exit(2);
