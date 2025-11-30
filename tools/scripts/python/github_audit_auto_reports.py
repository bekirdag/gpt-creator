#!/usr/bin/env python3
"""Audit auto-report GitHub issues and optionally close invalid ones."""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import hashlib
from textwrap import indent


def github_request(url, headers, method="GET", payload=None):
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request) as resp:
        if resp.status == 204:
            return None
        body = resp.read().decode("utf-8")
        if not body:
            return None
        return json.loads(body)


def load_allowlist(path, inline_pairs):
    mapping = {}
    inline_entries = [line.strip() for line in inline_pairs.splitlines() if line.strip()]
    for entry in inline_entries:
        if "=" not in entry:
            continue
        version, digest = entry.split("=", 1)
        mapping.setdefault(version.strip(), set()).add(digest.strip().lower())
    if not path:
        return mapping
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return mapping
    except Exception as exc:
        print(f"Failed to read digest allowlist '{path}': {exc}", file=sys.stderr)
        return mapping
    if isinstance(data, dict):
        iterable = data.items()
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                version = str(item.get("version") or "").strip()
                if not version:
                    continue
                sha_values = []
                sha_field = item.get("sha256")
                if isinstance(sha_field, str):
                    sha_values = [sha_field]
                elif isinstance(sha_field, list):
                    sha_values = [val for val in sha_field if isinstance(val, str)]
                elif isinstance(sha_field, dict):
                    for val in sha_field.values():
                        if isinstance(val, str):
                            sha_values.append(val)
                        elif isinstance(val, list):
                            sha_values.extend(x for x in val if isinstance(x, str))
                for digest in sha_values:
                    mapping.setdefault(version, set()).add(digest.lower())
            elif isinstance(item, str) and "=" in item:
                version, digest = item.split("=", 1)
                mapping.setdefault(version.strip(), set()).add(digest.strip().lower())
        return mapping
    else:
        return mapping
    for version, values in iterable:
        if isinstance(values, str):
            mapping.setdefault(str(version), set()).add(values.lower())
        elif isinstance(values, list):
            mapping.setdefault(str(version), set()).update(val.lower() for val in values if isinstance(val, str))
        elif isinstance(values, dict):
            for val in values.values():
                if isinstance(val, str):
                    mapping.setdefault(str(version), set()).add(val.lower())
                elif isinstance(val, list):
                    mapping.setdefault(str(version), set()).update(v.lower() for v in val if isinstance(v, str))
    return mapping


def fetch_issues(repo, state, headers):
    collected = []
    page = 1
    per_page = 100
    while True:
        url = f"https://api.github.com/repos/{repo}/issues?state={urllib.parse.quote(state)}&labels=auto-report&per_page={per_page}&page={page}"
        try:
            items = github_request(url, headers)
        except urllib.error.HTTPError as err:
            text = err.read().decode("utf-8", "ignore")
            print(f"GitHub API error while fetching issues: {err.code} {text}", file=sys.stderr)
            return collected
        except Exception as exc:
            print(f"Failed to fetch GitHub issues: {exc}", file=sys.stderr)
            return collected
        if not items:
            break
        collected.extend(items)
        page += 1
    return collected


def parse_issue(issue, digest_allowlist):
    metadata = issue.get("body") or ""
    version = ""
    binary_hash = ""
    signature = ""
    expected_signature = ""
    signature_valid = False
    watermark_token = ""
    watermark_valid = False
    reasons = []

    for line in metadata.splitlines():
        lower = line.lower()
        if lower.startswith("version:"):
            version = line.split(":", 1)[1].strip()
        elif lower.startswith("binary sha256:"):
            binary_hash = line.split(":", 1)[1].strip().lower()
        elif lower.startswith("signature:"):
            signature = line.split(":", 1)[1].strip()
        elif lower.startswith("expected signature:"):
            expected_signature = line.split(":", 1)[1].strip()
        elif lower.startswith("watermark:"):
            watermark_token = line.split(":", 1)[1].strip()

    if signature and expected_signature:
        signature_valid = signature.lower() == expected_signature.lower()
        if not signature_valid:
            reasons.append("signature mismatch")
    else:
        reasons.append("missing CLI signature")

    if watermark_token:
        watermark_expected = f"{version or 'unknown'}:{expected_signature}" if expected_signature else ""
        if watermark_expected and watermark_token.lower() == watermark_expected.lower():
            watermark_valid = True
        elif version and signature_valid and watermark_token.lower() == f"{version.lower()}:unsigned":
            watermark_valid = False
            reasons.append("watermark unsigned but signature present")
        else:
            reasons.append("watermark mismatch")
    else:
        reasons.append("missing watermark")

    digest_allowed = True
    if digest_allowlist:
        allowed_hashes = digest_allowlist.get(version, set())
        if allowed_hashes:
            if binary_hash not in allowed_hashes:
                digest_allowed = False
                reasons.append("binary hash not in allowlist")
        else:
            digest_allowed = False
            reasons.append("version not present in allowlist")

    valid = signature_valid and watermark_valid and digest_allowed
    return {
        "number": issue.get("number"),
        "title": issue.get("title") or "",
        "url": issue.get("html_url") or "",
        "state": issue.get("state"),
        "version": version,
        "binary_hash": binary_hash,
        "signature": signature,
        "expected_signature": expected_signature,
        "signature_valid": signature_valid,
        "watermark": watermark_token,
        "watermark_valid": watermark_valid,
        "digest_allowed": digest_allowed,
        "valid": valid,
        "reasons": reasons,
        "metadata": metadata,
    }


def ensure_label(repo, headers, invalid_label, issue_number):
    if not invalid_label:
        return
    try:
        issue = github_request(f"https://api.github.com/repos/{repo}/issues/{issue_number}", headers)
    except Exception:
        return
    if not issue:
        return
    labels = issue.get("labels") or []
    label_names = {lbl["name"] if isinstance(lbl, dict) else str(lbl) for lbl in labels}
    if invalid_label in label_names:
        return
    label_names.add(invalid_label)
    payload = {"labels": sorted(label_names)}
    try:
        github_request(f"https://api.github.com/repos/{repo}/issues/{issue_number}", headers, method="PATCH", payload=payload)
    except Exception:
        pass


def close_issue(repo, headers, close_comment, item, close_invalid):
    number = item["number"]
    if not close_invalid or str(item.get("state")) == "closed":
        return
    try:
        github_request(
            f"https://api.github.com/repos/{repo}/issues/{number}/comments",
            headers,
            method="POST",
            payload={"body": close_comment},
        )
    except Exception as exc:
        print(f"Failed to comment on issue #{number}: {exc}", file=sys.stderr)
    try:
        github_request(
            f"https://api.github.com/repos/{repo}/issues/{number}",
            headers,
            method="PATCH",
            payload={"state": "closed"},
        )
    except Exception as exc:
        print(f"Failed to close issue #{number}: {exc}", file=sys.stderr)
    else:
        ensure_label(repo, headers, invalid_label, number)
        print(f"Closed issue #{number} ({item['title']}) as authenticity failed.")


def summarize(item, digest_allowlist):
    header = f"#{item['number']} [{item['state']}] {item['title']}"
    verdict = "VALID" if item["valid"] else "INVALID"
    print(f"\n{header}\nResult: {verdict}")
    print(f"URL: {item['url']}")
    print(f"Version: {item['version'] or '(missing)'}")
    print(f"Binary SHA256: {item['binary_hash'] or '(missing)'}")
    print(f"Signature: {item['signature'] or '(missing)'}")
    print(f"Watermark: {item['watermark'] or '(missing)'}")
    print(f"Signature OK: {'yes' if item['signature_valid'] else 'no'}")
    print(f"Watermark OK: {'yes' if item['watermark_valid'] else 'no'}")
    if digest_allowlist:
        print(f"Allowlist OK: {'yes' if item['digest_allowed'] else 'no'}")
    if item["reasons"]:
        detail = "\n".join(f"- {reason}" for reason in item["reasons"])
        print("Notes:\n" + indent(detail, "  "))


def main(argv: list[str]) -> int:
    if len(argv) != 10:
        raise SystemExit(
            "Usage: github_audit_auto_reports.py REPO TOKEN STATE CLOSE_FLAG COMMENT LIMIT DIGEST_PATH INVALID_LABEL ALLOW_PAYLOAD"
        )

    repo, token, state, close_flag, close_comment, limit_value, digests_path, invalid_label, allow_payload = argv[1:10]
    close_invalid = close_flag == "1"
    limit = None
    if limit_value:
        try:
            parsed_limit = int(limit_value)
            if parsed_limit > 0:
                limit = parsed_limit
        except ValueError:
            limit = None

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "gpt-creator-reports-audit",
    }

    digest_allowlist = load_allowlist(digests_path, allow_payload or "")
    issues = fetch_issues(repo, state, headers)
    if not issues:
        print("No GitHub issues labelled 'auto-report' found.")
        return 0

    parsed = [parse_issue(issue, digest_allowlist) for issue in issues]
    if limit is not None:
        parsed = parsed[:limit]
    valid_count = sum(1 for item in parsed if item["valid"])

    print(f"Audited {len(parsed)} auto-report issue(s) [{state}].")
    print(f" - Valid:   {valid_count}")
    print(f" - Invalid: {len(parsed) - valid_count}")
    if digest_allowlist:
        print(f" - Allowlist source: {digests_path or 'inline overrides only'}")

    for item in parsed:
        summarize(item, digest_allowlist)
        if not item["valid"]:
            close_issue(repo, headers, close_comment, item, close_invalid)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
