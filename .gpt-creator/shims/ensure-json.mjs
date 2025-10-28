// Reads agent output from STDIN, guarantees a valid task JSON object.
// Usage: cat raw.txt | node .gpt-creator/shims/ensure-json.mjs
import fs from 'fs';

const readStdin = () => fs.readFileSync(0, 'utf8');
const RAW = readStdin();

// Helper: attempt parse, with a few gentle repairs
const tryParse = (s) => {
  try { return JSON.parse(s); } catch (_) {}
  // strip leading/trailing noise; grab outermost {...}
  const first = s.indexOf('{'); const last = s.lastIndexOf('}');
  if (first >= 0 && last > first) {
    const core = s.slice(first, last + 1);
    // remove trailing commas
    const noTrailingCommas = core.replace(/,\s*([}\]])/g, '$1');
    try { return JSON.parse(noTrailingCommas); } catch (_) {}
  }
  return null;
};

const ensureShape = (obj) => {
  const out = {
    plan: Array.isArray(obj?.plan) ? obj.plan : [],
    focus: Array.isArray(obj?.focus) ? obj.focus : [],
    changes: Array.isArray(obj?.changes) ? obj.changes : [],
    commands: Array.isArray(obj?.commands) ? obj.commands : [],
    notes: Array.isArray(obj?.notes) ? obj.notes : []
  };
  // If we salvaged nothing, at least preserve the raw text for traceability.
  if (
    out.plan.length + out.focus.length + out.changes.length +
    out.commands.length + out.notes.length === 0
  ) {
    out.notes = [
      "AUTO-FIX: agent output was not valid JSON; raw preserved below.",
      RAW.slice(0, 4000) // cap to avoid huge blobs
    ];
  }
  return out;
};

const parsed = tryParse(RAW);
const finalObj = ensureShape(parsed || {});
process.stdout.write(JSON.stringify(finalObj));
