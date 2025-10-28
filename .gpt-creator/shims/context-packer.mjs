#!/usr/bin/env node
// Prompt compactor: trims noisy lines, enforces range-only snippets,
// and ensures total prompt budget leaves room for responses.

import fs from "fs";

const HARD = Number(process.env.GC_HARD_CONTEXT || 105000);
const SOFT = Number(process.env.GC_SOFT_CONTEXT || 95000);
const MIN_OUT = Number(process.env.GC_MIN_OUTPUT || 5000);
const INPUT_BUDGET = Math.max(1000, Math.min(SOFT, HARD - MIN_OUT));
const MAX_SNIPPET_LINES = Number(process.env.GC_MAX_SNIPPET_LINES || 120);

const text = fs.readFileSync(0, "utf8");

const tokens = (s) => Math.ceil(s.length / 4);

let t = text
  .replace(/^\[?\d{4}-\d{2}-\d{2}T.*tokens used:.*$/gm, "")
  .replace(/^\s*The file is too long.*truncated.*$/gm, "")
  .replace(/^.*\/(node_modules|dist|build|\.gpt-creator\/tmp)\/.*$/gm, "")
  .replace(/^.*seed-[a-z0-9]{8}\.sql.*$/gm, "")
  .replace(/^.*import-XXXX\.sql.*$/gm, "");

t = t.replace(/```[\s\S]*?```/g, (blk) => {
  const lines = blk.split("\n");
  if (lines.length <= MAX_SNIPPET_LINES) return blk;
  const half = Math.floor(MAX_SNIPPET_LINES / 2);
  const head = lines.slice(0, half);
  const tail = lines.slice(-half);
  return (
    head.join("\n") +
    `\n... [${lines.length - MAX_SNIPPET_LINES} lines omitted] ...\n` +
    tail.join("\n")
  );
});

const keepHeadings = [
  /^#\s*You are Codex/i,
  /^##\s*Task\b/i,
  /^##\s*Acceptance Criteria\b/i,
  /^##\s*Instructions\b/i,
  /^##\s*Guardrails\b/i,
  /^##\s*Change Format\b/i,
];

const sliceToBudget = (markdown) => {
  if (tokens(markdown) <= INPUT_BUDGET) return markdown;
  const sections = markdown.split(/\n(?=#+\s)/g);
  const preferred = sections.filter((s) =>
    keepHeadings.some((rx) => rx.test(s))
  );
  const rest = sections.filter((s) => !preferred.includes(s));
  let out = "";
  for (const section of [...preferred, ...rest]) {
    const candidate = out ? `${out}\n${section}` : section;
    if (tokens(candidate) > INPUT_BUDGET) break;
    out = candidate;
  }
  return out;
};

t = sliceToBudget(t);

const hardLimitTokens = HARD - MIN_OUT;
if (tokens(t) > hardLimitTokens) {
  const maxChars = Math.max(40000, hardLimitTokens * 4);
  t =
    t.slice(0, maxChars) +
    `\n\n[context truncated to fit ${hardLimitTokens} tokens]`;
}

process.stdout.write(t);
