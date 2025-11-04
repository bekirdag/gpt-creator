## work-on-tasks Prompt
- Load the task details and acceptance criteria from the context section.
- Consult the documentation catalog or search hits before modifying files.
- Outline a concise plan (<=3 bullets focused on actions), execute the required edits, and capture final status notes with clear pass/fail decisions.
- Apply changes by editing files directly via shell commands (no diff/patch output).
- Every time you run a command that edits files, writes content, stages changes, or runs tests/tools, list that exact command under the `Commands` heading; if you truly ran nothing, state `- (none)` explicitly.
- Record follow-up actions when blockers remain.
