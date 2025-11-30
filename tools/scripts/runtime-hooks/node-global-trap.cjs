#!/usr/bin/env node
// Global Node trap: route unhandled errors to parent Bash finalizer.
const { kill, pid } = process;
const parentPid = Number(process.env.GC_PARENT_PID || 0);

const signalParent = () => {
  if (parentPid > 0) {
    try {
      kill(parentPid, 'SIGUSR1');
    } catch {
      // ignore signaling issues
    }
  }
};

const logError = (tag, err) => {
  try {
    const msg = err && err.stack ? err.stack : String(err || '');
    console.error(`[gc-child-unhandled:${tag}] pid=${pid}\n${msg}`);
  } catch {
    // ignore logging issues
  }
};

process.on('unhandledRejection', (err) => {
  logError('unhandledRejection', err);
  signalParent();
  setImmediate(() => process.exit(1));
});

process.on('uncaughtException', (err) => {
  logError('uncaughtException', err);
  signalParent();
  setImmediate(() => process.exit(1));
});

process.on('beforeExit', () => {
  // Allow parent to flush before exit; no-op placeholder
});
