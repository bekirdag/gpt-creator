import { spawnSync } from 'node:child_process';
import path from 'node:path';

type SchemaKind = 'table' | 'index';

function resolveCliRoot(): string {
  if (process.env.CLI_ROOT) {
    return process.env.CLI_ROOT;
  }
  return path.resolve(__dirname, '..', '..');
}

function schemaScriptPath(): string {
  return path.join(resolveCliRoot(), 'scripts', 'schema_evidence.js');
}

function schemaIndexPath(): string {
  const workspace = process.env.GC_WORKSPACE_DIR || process.cwd();
  return (
    process.env.GC_SCHEMA_EVIDENCE_PATH ||
    path.join(workspace, '.gpt-creator', 'index', 'schema-evidence.json')
  );
}

export function hasEntity(kind: SchemaKind, name: string): boolean {
  if (!kind || !name) {
    return false;
  }
  const script = schemaScriptPath();
  const index = schemaIndexPath();
  const result = spawnSync(
    'node',
    [script, 'query', kind, name, '--out', index],
    { stdio: 'pipe' },
  );
  return result.status === 0;
}
