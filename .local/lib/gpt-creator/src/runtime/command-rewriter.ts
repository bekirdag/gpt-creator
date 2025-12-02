const TSC_PATTERN = /\btsc(\.js)?\b/;
const SKIP_LIB_PATTERN = /--skipLibCheck(?:\b|=)/;
const NO_EMIT_PATTERN = /--noEmitOnError(?:\s+\S+|=\S+)?/;

function appendFlag(payload: string, flag: string, value?: string): string {
  if (value === undefined) {
    return `${payload} ${flag}`;
  }
  return `${payload} ${flag} ${value}`;
}

export function rewriteForTsc(cmd: string): string {
  if (!TSC_PATTERN.test(cmd)) {
    return cmd;
  }
  let next = cmd.trim();
  if (!SKIP_LIB_PATTERN.test(next)) {
    next = appendFlag(next, '--skipLibCheck');
  }
  next = appendFlag(next, '--pretty', 'false');
  if (NO_EMIT_PATTERN.test(next)) {
    next = next.replace(NO_EMIT_PATTERN, '--noEmitOnError false');
  } else {
    next = appendFlag(next, '--noEmitOnError', 'false');
  }
  return next;
}
