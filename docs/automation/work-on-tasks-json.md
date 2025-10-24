# Work-on-Tasks JSON Envelope

Codex responses for `gpt-creator work-on-tasks` must comply with the strict JSON envelope expected by downstream automations:

- Emit **only** a single JSON object at the top level containing the keys `plan`, `changes`, `commands`, and `notes`. Omit unused keys instead of emitting `null`.
- Produce plain ASCII output without smart quotes, em dashes, or other Unicode characters.
- Do **not** wrap the JSON in Markdown fences or prepend/append explanatory prose.
- Every entry in `changes` must be a valid unified diff payload (or a full file body); ensure diffs apply cleanly with `git apply`.
- Avoid trailing commentary or diagnostics; tooling treats any non-JSON leading or trailing text as fatal.

Following this contract keeps the automation pipeline reliable and prevents Codex runs from being flagged as failed.
