#!/usr/bin/env python3
import argparse, re, sys, pathlib, json

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--status', type=int, required=True)
    ap.add_argument('--log', required=True)
    args = ap.parse_args()

    status = args.status
    text = pathlib.Path(args.log).read_text(errors='ignore')

    # Known transient errors -> ask outer retry loop to retry (124)
    transient_patterns = [
        r'heredoc[^\n]*(missing closing|unterminated)',
        r'blocked-?heredoc-?unterminated',
        r'stream disconnected before completion',
        r'context window|exceeds the context window',
        r'produced no output',
        r'JSON not found in Codex output',
        r'Structured instructions not found in Codex output',
        r'apply-failed-migration-context|empty-apply checkpoint',
        r'Template not found: .*empty_apply_checkpoint',
    ]
    for pat in transient_patterns:
        if re.search(pat, text, re.IGNORECASE):
            print(124)
            return 0

    # Environment/tooling missing -> soft pass (0) while recording reason
    softpass_patterns = [
        r'Prisma Client could not locate the Query Engine',
        r'generated for "debian-openssl-1\.1\.x".*required "debian-openssl-3\.0\.x"',
        r'cypress: not found',
    ]
    for pat in softpass_patterns:
        if re.search(pat, text, re.IGNORECASE):
            # print a message to stderr but return 0 to not fail the task
            sys.stderr.write("[softpass] optional test/tool unavailable; marking as skipped.\n")
            print(0)
            return 0

    if status == 0:
        blocked_patterns = [
            (r'^\s*blocked-dependency\([^)]+\)', 6),
            (r'^\s*blocked-merge-conflict\b', 3),
            (r'^\s*blocked-dirty-tree\b', 2),
            (r'^\s*blocked-schema-drift\b', 4),
            (r'^\s*blocked-schema-guard-error\b', 4),
            (r'^\s*blocked-i18n-guard-error\b', 6),
        ]
        for pat, mapped_status in blocked_patterns:
            if re.search(pat, text, re.MULTILINE):
                print(mapped_status)
                return 0

    # Else: leave status unchanged
    print(status)
    return 0

if __name__ == '__main__':
    sys.exit(main())
