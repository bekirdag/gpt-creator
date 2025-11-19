import pytest

from src.lib.work_on_tasks_runtime import _autoformat_note_entry, _has_action_token


def test_autoformat_keeps_existing_action_note():
    note = "Action: build | Result: done"
    formatted, changed = _autoformat_note_entry(note)
    assert formatted == note
    assert changed is False


def test_autoformat_generates_action_result_for_narration():
    note = "Need to rerun prisma generate after touching schema"
    formatted, changed = _autoformat_note_entry(note)
    assert changed is True
    assert formatted.startswith("Action: auto-note:")
    assert formatted.endswith(f"Result: {note}")


def test_has_action_token_detects_lists_and_prefixes():
    assert _has_action_token("- update deps") is True
    assert _has_action_token("Commands: none") is True
    assert _has_action_token("Focus: src/lib") is True
    assert _has_action_token("1) stage changes") is True
    assert _has_action_token("just narration") is False
