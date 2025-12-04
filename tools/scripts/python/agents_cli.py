#!/usr/bin/env python3
"""CLI glue for agent management commands."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _prepend_sys_path(path: Path) -> None:
    resolved = str(path)
    if resolved and resolved not in sys.path:
        sys.path.insert(0, resolved)


cli_root = os.environ.get("GC_CLI_ROOT")
if cli_root:
    candidate = Path(cli_root).expanduser() / "scripts" / "python"
    if candidate.exists():
        _prepend_sys_path(candidate)
else:
    script_root = Path(__file__).resolve()
    # project/.gpt-creator/shims/python/... => parents[3] is .gpt-creator, parents[4] is project root.
    fallback_root = script_root.parent.parent.parent.parent
    candidate = fallback_root / "scripts" / "python"
    if candidate.exists():
        _prepend_sys_path(candidate)

from agents import AgentFilter, AgentService, DocSource, LLMFilter
from agents.repository import AgentRepository  # type: ignore  # noqa: E402
from agents.model import Agent
from agents_validate import parse_tags, summarize_text
from llm_client_factory import create_llm_client


def _default_tasks_db(project_root: Path) -> Path:
    return project_root / ".gpt-creator" / "staging" / "plan" / "tasks" / "tasks.db"


def _agent_to_dict(agent: Agent, *, include_docs: bool = False, include_keys: bool = False) -> Dict[str, Any]:
    payload = {
        "id": agent.id,
        "name": agent.name,
        "client": agent.client,
        "model": agent.model,
        "llm_provider_id": agent.llm_provider_id,
        "llm_model_id": agent.llm_model_id,
        "client_api_base": agent.client_api_base,
        "client_api_org": agent.client_api_org,
        "has_client_api_key": bool(agent.client_api_key),
        "job_summary": agent.job_summary,
        "character_summary": agent.character_summary,
        "tags": agent.tags,
        "is_active": agent.is_active,
        "last_used_at": agent.last_used_at,
        "created_at": agent.created_at,
        "updated_at": agent.updated_at,
        "guardrails": agent.guardrails,
    }
    if include_docs:
        payload["job_doc"] = agent.job_doc
        payload["character_doc"] = agent.character_doc
    if include_keys:
        payload["client_api_key"] = agent.client_api_key
    return payload


def _render_table(agents: List[Agent]) -> str:
    lines = ["Name\tClient\tModel\tJob summary\tCharacter summary\tActive"]
    for agent in agents:
        lines.append(
            "\t".join(
                [
                    agent.name,
                    agent.client,
                    agent.model,
                    agent.job_summary.replace("\n", " "),
                    agent.character_summary.replace("\n", " "),
                    "yes" if agent.is_active else "no",
                ]
            )
        )
    return "\n".join(lines)


def _render_llm_table(entries: List[Dict[str, Any]], show_warnings: bool = False) -> str:
    header = ["Provider", "Model", "Adapter", "Source", "Status", "Checked at", "Context", "Max output"]
    if show_warnings:
        header.append("Warnings")
    lines = ["\t".join(header)]
    for entry in entries:
        row = [
            entry["provider"],
            entry["model"],
            entry.get("adapter") or "",
            entry.get("source") or "",
            entry.get("install_status") or "",
            entry.get("install_checked_at") or "",
            str(entry.get("context_window") or ""),
            str(entry.get("default_max_tokens") or ""),
        ]
        if show_warnings:
            row.append(entry.get("credential_warning") or "")
        lines.append("\t".join(row))
    return "\n".join(lines)


def _bool_from_string(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "y"}:
        return True
    if lowered in {"0", "false", "no", "n"}:
        return False
    raise ValueError(f"Invalid boolean value '{value}'")


def _resolve_doc_source(path: str, stdin_payload: Optional[str] = None) -> DocSource:
    return DocSource(path=path, stdin_payload=stdin_payload)


def _exit(msg: str, code: int) -> int:
    print(msg, file=sys.stderr)
    return code


def _load_guardrails(args: argparse.Namespace) -> Optional[str]:
    parts: List[str] = []
    if args.guardrails:
        parts.append(args.guardrails.strip())
    for path in args.guardrails_files or []:
        file_path = Path(path)
        if file_path.exists():
            parts.append(file_path.read_text(encoding="utf-8").strip())
    for dir_path in args.guardrails_dirs or []:
        root = Path(dir_path)
        if not root.exists():
            continue
        for child in sorted(root.rglob("*")):
            if child.is_file():
                parts.append(child.read_text(encoding="utf-8").strip())
    joined = "\n\n".join(part for part in parts if part)
    return joined or None


def _apply_env_overrides(env_overrides: Dict[str, str]) -> Dict[str, Optional[str]]:
    previous: Dict[str, Optional[str]] = {}
    for key, value in env_overrides.items():
        if not key:
            continue
        previous[key] = os.environ.get(key)
        os.environ[key] = value
    return previous


def _restore_env(previous: Dict[str, Optional[str]]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _resolve_pair(service: AgentService, client: str, model: str = "") -> Dict[str, Any]:
    if not service.registry:
        raise ValueError("Agent registry unavailable")
    try:
        return service.registry.validate_pair(client, model)
    except ValueError:
        # Retry with default model for the client when a specific model is invalid or missing.
        return service.registry.validate_pair(client, "")


def _build_command_preview(pair: Dict[str, Any], prompt_text: Optional[str] = None) -> Dict[str, Any]:
    adapter = pair.get("adapter") or ""
    cfg = pair.get("adapterConfig") or {}
    model = pair.get("model") or ""
    command: List[str] = []
    if adapter == "command":
        template = cfg.get("command") or []
        if isinstance(template, str):
            template = template.split()
        command = [str(part).format(model=model) for part in template]
        if not command and cfg.get("binary"):
            command = [cfg.get("binary")]
            if model:
                command.append(model)
    elif adapter:
        command = [adapter]
        if model:
            command.append(model)
    else:
        raise ValueError("Adapter not configured for this client/model; cannot preview command.")
    env: Dict[str, str] = {}
    for key in ("apiKeyEnv", "apiBaseEnv", "orgEnv"):
        env_name = pair.get(key)
        if env_name:
            value = os.getenv(env_name, "")
            if value:
                env[env_name] = value
    return {
        "adapter": adapter,
        "command": command,
        "env": env,
        "model": model,
        "client": pair.get("client"),
        "prompt": prompt_text,
    }


def _parse_model_hint(raw: str) -> Tuple[Optional[str], Optional[str]]:
    for sep in (":", "/"):
        if sep in raw:
            parts = raw.split(sep, 1)
            return parts[0].strip(), parts[1].strip()
    return None, None


def _flush_warnings(service: AgentService) -> None:
    warnings = service.consume_warnings()
    for warning in warnings:
        print(f"Warning: {warning}", file=sys.stderr)


def handle_create(service: AgentService, args: argparse.Namespace) -> int:
    job_source = _resolve_doc_source(args.job_doc)
    char_source = _resolve_doc_source(args.character_doc)
    guardrails_text = _load_guardrails(args)
    try:
        agent = service.create_agent(
            name=args.name,
            client=args.client,
            model=args.model,
            job_doc=job_source,
            character_doc=char_source,
            tags=args.tags,
            summarize=args.summarize,
            summarize_model=args.summarize_model,
            summarize_client=args.summarize_client,
            guardrails=guardrails_text,
            allow_missing_key=args.allow_missing_key,
        )
    except ValueError as exc:
        return _exit(str(exc), 2)
    warnings = service.consume_warnings()
    payload = _agent_to_dict(agent, include_docs=args.full)
    if args.json:
        print(json.dumps({"agent": payload, "warnings": warnings}))
    else:
        print(f"Agent '{agent.name}' created (client={agent.client}, model={agent.model}).")
        for warning in warnings:
            print(f"Warning: {warning}", file=sys.stderr)
    return 0


def handle_list(service: AgentService, args: argparse.Namespace) -> int:
    filters = AgentFilter(
        client=args.client,
        model=args.model,
        active=args.active,
        name_like=args.name_like,
        limit=args.limit,
        tags=args.tags,
    )
    agents = service.list_agents(filters)
    if args.json:
        print(json.dumps([_agent_to_dict(agent) for agent in agents], indent=2))
        return 0
    print(_render_table(agents))
    return 0


def handle_show(service: AgentService, args: argparse.Namespace) -> int:
    agent = service.get_agent(args.name)
    if not agent:
        return _exit(f"Agent '{args.name}' not found", 3)
    if args.json:
        print(json.dumps(_agent_to_dict(agent, include_docs=args.full), indent=2))
        return 0
    print(f"Name: {agent.name}")
    print(f"Client: {agent.client}")
    print(f"Model: {agent.model}")
    print(f"Active: {'yes' if agent.is_active else 'no'}")
    print(f"Tags: {', '.join(agent.tags) if agent.tags else '(none)'}")
    print(f"Job summary: {agent.job_summary}")
    print(f"Character summary: {agent.character_summary}")
    if args.full:
        print("\n## Job Doc\n")
        print(agent.job_doc.rstrip())
        print("\n## Character Doc\n")
        print(agent.character_doc.rstrip())
    return 0


def handle_llms(service: AgentService, args: argparse.Namespace) -> int:
    filters = LLMFilter(
        provider=args.provider,
        adapter=args.adapter,
        source=args.source,
        model=args.model,
        name_like=args.name_like,
        limit=args.limit,
        statuses=args.statuses or None,
    )
    entries = service.list_llms(filters)
    records = []
    for entry in entries:
        warning = service.llm_warning(entry.provider_id, entry.metadata)
        if args.needs_key and not warning:
            continue
        records.append(
            {
                "provider": entry.provider_id,
                "provider_name": entry.provider_name,
                "model": entry.model_id,
                "model_name": entry.model_name,
                "adapter": entry.adapter,
                "source": entry.source,
                "install_status": entry.install_status,
                "install_checked_at": entry.install_checked_at,
                "install_hint": entry.install_hint,
                "context_window": entry.context_window,
                "default_max_tokens": entry.default_max_tokens,
                "credential_warning": warning or "",
            }
        )
    show_warnings = args.warn_keys or args.needs_key
    if args.json:
        print(json.dumps(records, indent=2))
        return 0
    if not records:
        print("No LLM catalog entries found.")
        return 0
    print(_render_llm_table(records, show_warnings=show_warnings))
    return 0


def handle_install_llm(service: AgentService, args: argparse.Namespace) -> int:
    target_os = None if not args.os or args.os == "default" else args.os
    try:
        preview = service.install_llm(
            provider_id=args.provider,
            adapter=args.adapter,
            target_os=target_os,
            dry_run=True,
        )
    except ValueError as exc:
        return _exit(str(exc), 2)
    if args.json and not args.run:
        print(json.dumps(preview, indent=2))
    elif not args.json:
        print(f"Provider: {preview['provider']} ({preview.get('provider_name')})")
        print(f"Adapter: {preview.get('adapter') or '(none)'}")
        print("Install commands:")
        commands = preview.get("commands") or {}
        for os_label, command in commands.items():
            if command:
                print(f"  {os_label}: {command}")
        if not any(commands.values()):
            print("  (no commands stored)")
        if preview.get("selectedCommand"):
            print(f"Selected command for OS '{preview.get('targetOS')}': {preview['selectedCommand']}")
        if preview.get("hint"):
            print(f"Hint: {preview['hint']}")
        if preview.get("credential_warning"):
            print(f"Warning: {preview['credential_warning']}")
            print(f"After installing the CLI, run 'gpt-creator keys set {preview['provider']}' to configure credentials.")
        if not args.run:
            print("Run with --run (and optionally --yes) to execute the install command.")
    if not args.run or args.dry_run:
        return 0
    if not args.yes:
        try:
            confirm = input("Execute the install command? [y/N]: ").strip().lower()
        except EOFError:
            confirm = "n"
        if confirm not in {"y", "yes"}:
            print("Install cancelled.")
            return 0
    try:
        result = service.install_llm(
            provider_id=args.provider,
            adapter=args.adapter,
            target_os=target_os,
            auto_run=True,
        )
    except ValueError as exc:
        return _exit(str(exc), 2)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Install status: {result.get('status')}")
        if result.get("hint"):
            print(f"Hint: {result['hint']}")
        if result.get("credential_warning"):
            print(f"Warning: {result['credential_warning']}")
    return 0 if result.get("status") == "installed" else 1


def handle_agent_check(service: AgentService, args: argparse.Namespace) -> int:
    agent = service.get_agent(args.name)
    if not agent:
        return _exit(f"Agent '{args.name}' not found", 3)
    client = args.client or agent.client
    model = args.model or agent.model
    try:
        pair = _resolve_pair(service, client, model)
    except ValueError as exc:
        return _exit(str(exc), 2)
    adapter = pair.get("adapter") or ""
    if not adapter:
        return _exit("Adapter not configured for this client/model; cannot run agent-check.", 2)
    env_overrides: Dict[str, str] = {}
    api_key_env = pair.get("apiKeyEnv")
    if api_key_env:
        key_value = agent.client_api_key or os.getenv(api_key_env, "")
        if key_value:
            env_overrides[api_key_env] = key_value
    previous_env = _apply_env_overrides(env_overrides)
    try:
        llm = create_llm_client(adapter, pair)
        prompt_bundle = service.compose_prompt(agent)
        system_prompt = prompt_bundle.header
        if prompt_bundle.guardrails:
            guardrail_text = "\n".join(prompt_bundle.guardrails)
            system_prompt = f"{system_prompt}\n\n## Guardrails\n{guardrail_text}"
        result = llm.send_chat(
            messages=[args.prompt],
            model=pair["model"],
            system=system_prompt,
        )
    except Exception as exc:
        return _exit(f"Agent check failed: {exc}", 1)
    finally:
        _restore_env(previous_env)
    payload = {
        "agent": agent.name,
        "client": pair["client"],
        "model": pair["model"],
        "prompt": args.prompt,
        "response": (result.content or "").strip(),
        "tokens": {
            "prompt": result.tokens.prompt,
            "completion": result.tokens.completion,
        },
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Agent '{agent.name}' ({pair['client']}/{pair['model']}) response:\n{payload['response']}")
    return 0


def handle_llm_check(service: AgentService, args: argparse.Namespace) -> int:
    results = service.check_llm_adapters(
        provider_id=args.provider,
        adapter=args.adapter,
        dry_run=args.dry_run,
        install_missing=args.install_missing,
        health_check=args.health_check,
    )
    if args.json:
        print(json.dumps(results, indent=2))
        return 0
    if not results:
        print("No LLM providers matched the filters.")
        return 0
    lines = ["Provider\tAdapter\tStatus\tBinary\tChecked at\tHint\tWarnings\tHealth\tHealth message"]
    for entry in results:
        lines.append(
            "\t".join(
                [
                    entry["provider"],
                    entry.get("adapter") or "",
                    entry.get("status") or "",
                    entry.get("binary") or "",
                    entry.get("checked_at") or "",
                    entry.get("hint") or "",
                    entry.get("credential_warning") or "",
                    entry.get("health_status") or "",
                    entry.get("health_message") or "",
                ]
            )
        )
    print("\n".join(lines))
    return 0


def handle_llm_sync(service: AgentService, args: argparse.Namespace) -> int:
    result = service.sync_llms(
        provider=args.provider,
        model=args.model,
        refresh_catalog=args.refresh,
        require_adapters=args.require_adapters or args.ci,
        require_keys=args.require_keys or args.ci,
    )
    exit_code = 1 if result.get("failure") else 0
    if args.json or args.ci:
        print(json.dumps(result, indent=2))
        return exit_code
    print(f"Seeded registry entries: {result['seeded']}")
    if args.refresh:
        print(f"Refreshed catalog providers: {result['refreshed']}")
    if result.get("checks"):
        print("Checks:")
        for entry in result["checks"]:
            issues = entry.get("issues") or []
            status = "OK" if not issues else f"FAIL ({'; '.join(issues)})"
            print(f"  {entry['provider']} ({entry.get('adapter') or 'n/a'}): {status}")
    if result.get("failure"):
        print("sync-llms: failures detected (see above).")
    return exit_code


def handle_edit(service: AgentService, args: argparse.Namespace) -> int:
    job_doc = _resolve_doc_source(args.job_doc) if args.job_doc else None
    character_doc = _resolve_doc_source(args.character_doc) if args.character_doc else None
    guardrails_text = _load_guardrails(args)
    try:
        agent = service.update_agent(
            name=args.name,
            new_name=args.new_name,
            client=args.client,
            model=args.model,
            job_doc=job_doc,
            character_doc=character_doc,
            tags=args.tags,
            active=args.active,
            resummarize=args.resummarize,
            summarize=args.summarize,
            summarize_model=args.summarize_model,
            summarize_client=args.summarize_client,
            guardrails=guardrails_text,
            allow_missing_key=args.allow_missing_key,
        )
    except ValueError as exc:
        return _exit(str(exc), 2 if "not found" not in str(exc).lower() else 3)
    warnings = service.consume_warnings()
    payload = _agent_to_dict(agent)
    if args.json:
        print(json.dumps({"agent": payload, "warnings": warnings}, indent=2))
    else:
        print(f"Agent '{agent.name}' updated.")
        for warning in warnings:
            print(f"Warning: {warning}", file=sys.stderr)
    return 0


def handle_delete(service: AgentService, args: argparse.Namespace) -> int:
    agent = service.get_agent(args.name)
    if not agent:
        return _exit(f"Agent '{args.name}' not found", 3)
    service.delete_agent(args.name, force=args.force)
    if args.json:
        print(json.dumps({"name": args.name, "deleted": True, "force": args.force}))
    else:
        mode = "hard" if args.force else "soft"
        print(f"Agent '{args.name}' deleted ({mode}).")
    return 0


def handle_select(service: AgentService, args: argparse.Namespace) -> int:
    agent, model_override = service.resolve_agent_or_model(args.name)
    resolved_pair: Optional[Dict[str, Any]] = None
    command_preview: Optional[Dict[str, Any]] = None
    if agent:
        try:
            resolved_pair = _resolve_pair(service, agent.client, agent.model)
            command_preview = _build_command_preview(resolved_pair)
        except Exception:
            resolved_pair = None
        payload = _agent_to_dict(agent, include_docs=args.full, include_keys=True)
        prompt_bundle = service.compose_prompt(agent)
        print(
            json.dumps(
                {
                    "kind": "agent",
                    "agent": payload,
                    "prompt": {
                        "header": prompt_bundle.header,
                        "client": prompt_bundle.client,
                        "model": prompt_bundle.model,
                        "guardrails": prompt_bundle.guardrails,
                    },
                    "resolved": resolved_pair,
                    "command": command_preview,
                }
            )
        )
        return 0
    fallback_model = model_override or args.name
    client_hint, model_hint = _parse_model_hint(fallback_model)
    if client_hint:
        try:
            resolved_pair = _resolve_pair(service, client_hint, model_hint or "")
            command_preview = _build_command_preview(resolved_pair)
        except Exception:
            resolved_pair = None
    print(json.dumps({"kind": "model", "model": fallback_model, "resolved": resolved_pair, "command": command_preview}))
    return 0


def handle_export(service: AgentService, args: argparse.Namespace) -> int:
    filters = AgentFilter(
        client=args.client,
        model=args.model,
        active=args.active,
        name_like=args.name_like,
        tags=args.tags,
    )
    agents = service.list_agents(filters)
    records = [
        _agent_to_dict(agent, include_docs=True, include_keys=args.include_keys)
        for agent in agents
    ]
    payload = json.dumps(records, indent=2)
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    else:
        print(payload)
    return 0


def _compute_sha(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _resolve_collision(name: str, repo: AgentRepository, policy: str) -> Optional[str]:
    existing = repo.get_by_name(name)
    if not existing:
        return name
    if policy == "skip":
        return None
    if policy == "overwrite":
        repo.hard_delete(name)
        return name
    suffix = 1
    while repo.get_by_name(f"{name}-{suffix}"):
        suffix += 1
    return f"{name}-{suffix}"


def handle_import(service: AgentService, args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    if not input_path.exists():
        return _exit(f"Import file not found: {input_path}", 2)
    try:
        data = json.loads(input_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return _exit(f"Import file is not valid JSON ({exc})", 2)
    if not isinstance(data, list):
        return _exit("Import file must contain a JSON array of agents.", 2)
    extra_tags = parse_tags(args.tags or "")
    imported = 0
    skipped = 0
    for record in data:
        name = (record.get("name") or "").strip()
        if not name:
            skipped += 1
            continue
        new_name = _resolve_collision(name, service.repo, args.on_collision)
        if not new_name:
            skipped += 1
            continue
        job_doc = record.get("job_doc") or ""
        char_doc = record.get("character_doc") or ""
        if not job_doc or not char_doc:
            skipped += 1
            continue
        tags = list(record.get("tags") or [])
        tags.extend(extra_tags)
        payload = {
            "name": new_name,
            "client": record.get("client") or args.client_override or "openai",
            "model": record.get("model") or args.model_override or "gpt-5.1-codex",
            "client_api_key": record.get("client_api_key") if args.include_keys else None,
            "client_api_base": record.get("client_api_base"),
            "client_api_org": record.get("client_api_org"),
            "job_doc": job_doc,
            "job_doc_sha256": record.get("job_doc_sha256") or _compute_sha(job_doc),
            "job_summary": record.get("job_summary") or summarize_text(job_doc),
            "character_doc": char_doc,
            "character_doc_sha256": record.get("character_doc_sha256") or _compute_sha(char_doc),
            "character_summary": record.get("character_summary") or summarize_text(char_doc),
            "tags_json": json.dumps(tags),
            "guardrails": record.get("guardrails"),
        }
        agent_create = service._dict_to_agent_create(payload)  # type: ignore[attr-defined]
        try:
            service.repo.create(agent_create)
            if args.activate is not None:
                service.update_agent(new_name, active=args.activate)
            imported += 1
        except Exception:
            skipped += 1
    output = {
        "imported": imported,
        "skipped": skipped,
    }
    print(json.dumps(output))
    return 0


def handle_test_agent(service: AgentService, args: argparse.Namespace) -> int:
    agent, model_override = service.resolve_agent_or_model(args.name)
    prompt_text = args.prompt or "ping"
    system_prompt = args.system or ""
    resolved_pair: Optional[Dict[str, Any]] = None
    if agent:
        try:
            resolved_pair = _resolve_pair(service, agent.client, agent.model)
        except Exception as exc:
            return _exit(str(exc), 2)
        if not system_prompt:
            system_prompt = service.compose_prompt(agent).header
    else:
        fallback = model_override or args.name
        client_hint, model_hint = _parse_model_hint(fallback)
        if not client_hint:
            return _exit("Provide an agent name or client:model pair", 2)
        try:
            resolved_pair = _resolve_pair(service, client_hint, model_hint or "")
        except Exception as exc:
            return _exit(str(exc), 2)
    try:
        command_preview = _build_command_preview(resolved_pair, prompt_text)
    except ValueError as exc:
        return _exit(str(exc), 2)
    payload: Dict[str, Any] = {
        "agent": agent.name if agent else None,
        "resolved": resolved_pair,
        "command": command_preview,
        "prompt": prompt_text,
    }
    if args.execute:
        try:
            llm = create_llm_client(resolved_pair.get("adapter"), resolved_pair)
            result = llm.send_chat(
                messages=[prompt_text],
                model=resolved_pair.get("model") or "",
                system=system_prompt,
            )
            payload["result"] = {
                "content": result.content,
                "tokens": {
                    "prompt": result.tokens.prompt,
                    "completion": result.tokens.completion,
                },
            }
        except Exception as exc:
            return _exit(f"test-agent failed: {exc}", 1)
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        resolved = payload.get("resolved") or {}
        print(f"Resolved: {resolved.get('client')}/{resolved.get('model')} (adapter={resolved.get('adapter')})")
        if command_preview:
            print(f"Command: {' '.join(command_preview['command'])}")
        if payload.get("result"):
            print(f"Result: {payload['result']['content']}")
    return 0


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage gpt-creator agents.")
    parser.add_argument("--project", default=os.getcwd(), help="Project root.")
    parser.add_argument("--db-path", help="Override tasks.db location.")
    parser.add_argument("--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    create_parser = sub.add_parser("create", help="Create an agent.")
    create_parser.add_argument("--name", required=True)
    create_parser.add_argument("--client", required=True)
    create_parser.add_argument("--model", required=True)
    create_parser.add_argument("--job-doc", required=True)
    create_parser.add_argument("--character-doc", required=True)
    create_parser.add_argument("--tags", default="")
    create_parser.add_argument("--json", action="store_true")
    create_parser.add_argument("--full", action="store_true", help="Include doc bodies in JSON.")
    create_parser.add_argument("--summarize", action="store_true", help="Use the active LLM to generate summaries (falls back to deterministic truncation if unavailable).")
    create_parser.add_argument("--summarize-model", help="Override the summarizer model (defaults to GC_AGENT_SUMMARIZER_MODEL or the agent model).")
    create_parser.add_argument("--summarize-client", help="Override the summarizer client/provider (defaults to GC_AGENT_SUMMARIZER_CLIENT or the agent client).")
    create_parser.add_argument("--guardrails", help="Custom guardrail text to inject before the shared defaults.")
    create_parser.add_argument("--guardrails-file", dest="guardrails_files", action="append", help="Path to a file containing guardrails (repeatable).")
    create_parser.add_argument("--guardrails-dir", dest="guardrails_dirs", action="append", help="Load every file under this directory as guardrails (repeatable).")
    create_parser.add_argument("--allow-missing-key", action="store_true", help="Create the agent even if the client API key is not set (warns instead of failing).")
    create_parser.set_defaults(guardrails_files=[], guardrails_dirs=[])

    list_parser = sub.add_parser("list", help="List agents.")
    list_parser.add_argument("--client")
    list_parser.add_argument("--model")
    list_parser.add_argument("--active", type=_bool_from_string, default=None)
    list_parser.add_argument("--name-like")
    list_parser.add_argument("--tag", dest="tags", action="append", help="Filter by tag (can be repeated).")
    list_parser.set_defaults(tags=[])
    list_parser.add_argument("--limit", type=int)
    list_parser.add_argument("--json", action="store_true")

    show_parser = sub.add_parser("show", help="Show an agent.")
    show_parser.add_argument("--name", required=True)
    show_parser.add_argument("--full", action="store_true", help="Include doc bodies.")
    show_parser.add_argument("--json", action="store_true")

    edit_parser = sub.add_parser("edit", help="Edit an agent.")
    edit_parser.add_argument("--name", required=True)
    edit_parser.add_argument("--new-name")
    edit_parser.add_argument("--client")
    edit_parser.add_argument("--model")
    edit_parser.add_argument("--job-doc")
    edit_parser.add_argument("--character-doc")
    edit_parser.add_argument("--tags")
    edit_parser.add_argument("--active", type=_bool_from_string, default=None)
    edit_parser.add_argument("--resummarize", action="store_true")
    edit_parser.add_argument("--summarize", action="store_true", help="Use the active LLM when --resummarize is supplied.")
    edit_parser.add_argument("--summarize-model", help="Override the summarizer model when --summarize/--resummarize is used.")
    edit_parser.add_argument("--summarize-client", help="Override the summarizer client when --summarize/--resummarize is used.")
    edit_parser.add_argument("--guardrails", help="Custom guardrail text (set to empty string to clear).")
    edit_parser.add_argument("--guardrails-file", dest="guardrails_files", action="append", help="Path to a guardrail file (repeatable).")
    edit_parser.add_argument("--guardrails-dir", dest="guardrails_dirs", action="append", help="Load guardrail files from a directory (repeatable).")
    edit_parser.set_defaults(guardrails_files=[], guardrails_dirs=[])
    edit_parser.add_argument("--allow-missing-key", action="store_true", help="Update the agent even when the client API key is not set (warns instead of failing).")
    edit_parser.add_argument("--json", action="store_true")

    delete_parser = sub.add_parser("delete", help="Delete an agent.")
    delete_parser.add_argument("--name", required=True)
    delete_parser.add_argument("--force", action="store_true")
    delete_parser.add_argument("--json", action="store_true")

    select_parser = sub.add_parser("select", help="Resolve agent or model by name.")
    select_parser.add_argument("--name", required=True)
    select_parser.add_argument("--full", action="store_true")

    export_parser = sub.add_parser("export", help="Export agents to JSON.")
    export_parser.add_argument("--client")
    export_parser.add_argument("--model")
    export_parser.add_argument("--active", type=_bool_from_string, default=None)
    export_parser.add_argument("--name-like")
    export_parser.add_argument("--tag", dest="tags", action="append", help="Filter by tag (repeatable).")
    export_parser.add_argument("--output", help="Output file (defaults to stdout).")
    export_parser.add_argument("--include-keys", action="store_true", help="Include stored API keys in the export.")
    export_parser.set_defaults(tags=[])

    import_parser = sub.add_parser("import", help="Import agents from JSON.")
    import_parser.add_argument("--input", required=True, help="Path to JSON export file.")
    import_parser.add_argument("--on-collision", choices=["skip", "overwrite", "rename"], default="skip")
    import_parser.add_argument("--tags", help="Comma/space separated tags to append to every imported agent.")
    import_parser.add_argument("--include-keys", action="store_true", help="Import client API keys when present in the file.")
    import_parser.add_argument("--client", dest="client_override", help="Override client id for every imported agent.")
    import_parser.add_argument("--model", dest="model_override", help="Override model id for every imported agent.")
    import_parser.add_argument("--activate", dest="activate", type=_bool_from_string, default=None, help="Force activate/deactivate imported agents.")

    llms_parser = sub.add_parser("llms", help="List LLM catalog entries.")
    llms_parser.add_argument("--provider", help="Filter by provider id.")
    llms_parser.add_argument("--adapter", help="Filter by adapter name.")
    llms_parser.add_argument("--source", help="Filter by source (catalog/registry).")
    llms_parser.add_argument("--model", help="Filter by model id.")
    llms_parser.add_argument("--name-like", help="Filter by provider/model name substring.")
    llms_parser.add_argument("--limit", type=int)
    llms_parser.add_argument(
        "--status",
        dest="statuses",
        action="append",
        choices=["installed", "missing", "not_applicable", "pending", "unknown"],
        help="Filter by adapter install status (repeatable).",
    )
    llms_parser.add_argument(
        "--needs-key",
        action="store_true",
        help="Only show entries missing required API keys.",
    )
    llms_parser.add_argument("--json", action="store_true")
    llms_parser.add_argument("--warn-keys", dest="warn_keys", action="store_true", default=True, help="Show API key warnings in table output (default: on).")
    llms_parser.add_argument("--no-warn-keys", dest="warn_keys", action="store_false", help="Disable API key warnings column.")

    llm_check_parser = sub.add_parser("llms-check", help="Detect adapter installation status.")
    llm_check_parser.add_argument("--provider", help="Check a specific provider id.")
    llm_check_parser.add_argument("--adapter", help="Filter by adapter name.")
    llm_check_parser.add_argument("--json", action="store_true")
    llm_check_parser.add_argument("--dry-run", action="store_true")
    llm_check_parser.add_argument("--install-missing", action="store_true", help="Attempt to run stored install commands for missing adapters.")
    llm_check_parser.add_argument("--health-check", action="store_true", help="Run a lightweight health check (--version) for installed adapters.")

    install_llm_parser = sub.add_parser("install-llm", help="Inspect or run the stored install command for an LLM provider.")
    install_llm_parser.add_argument("--provider", required=True, help="Provider id to install (e.g., openai, gemini).")
    install_llm_parser.add_argument("--adapter", help="Filter by adapter name when multiple entries exist.")
    install_llm_parser.add_argument("--os", choices=["default", "macos", "windows"], default="default", help="Force a specific OS install command (default autodetect).")
    install_llm_parser.add_argument("--run", action="store_true", help="Execute the install command after confirmation.")
    install_llm_parser.add_argument("--yes", action="store_true", help="Skip confirmation when --run is provided.")
    install_llm_parser.add_argument("--dry-run", action="store_true", help="Preview only; do not execute.")
    install_llm_parser.add_argument("--json", action="store_true")

    llm_sync_parser = sub.add_parser("llms-sync", help="Seed the catalog with configured registry providers/models.")
    llm_sync_parser.add_argument("--provider", help="Restrict to a single provider id.")
    llm_sync_parser.add_argument("--model", help="Restrict to a specific model id.")
    llm_sync_parser.add_argument("--refresh", action="store_true", help="Refresh the Catwalk catalog after seeding registry entries.")
    llm_sync_parser.add_argument("--require-adapters", action="store_true", help="Fail if any required adapters are missing after sync.")
    llm_sync_parser.add_argument("--require-keys", action="store_true", help="Fail if any required API keys are missing after sync.")
    llm_sync_parser.add_argument("--ci", action="store_true", help="Imply --require-adapters --require-keys --json for CI usage.")
    llm_sync_parser.add_argument("--json", action="store_true")

    agent_check_parser = sub.add_parser("agent-check", help="Send a quick health-check prompt to an agent.")
    agent_check_parser.add_argument("--name", required=True, help="Agent name.")
    agent_check_parser.add_argument("--prompt", required=True, help="Prompt/question to send.")
    agent_check_parser.add_argument("--client", help="Override the agent client/provider.")
    agent_check_parser.add_argument("--model", help="Override the agent model id.")
    agent_check_parser.add_argument("--json", action="store_true")

    test_agent_parser = sub.add_parser("test-agent", help="Resolve an agent or model and preview the adapter command.")
    test_agent_parser.add_argument("--name", required=True, help="Agent name or client:model pair.")
    test_agent_parser.add_argument("--prompt", help="Prompt to send (default: ping).")
    test_agent_parser.add_argument("--system", help="Optional system prompt override.")
    test_agent_parser.add_argument("--execute", action="store_true", help="Execute the adapter command instead of previewing.")
    test_agent_parser.add_argument("--json", action="store_true")

    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    project_root = Path(args.project).resolve()
    db_path = Path(args.db_path).resolve() if args.db_path else _default_tasks_db(project_root)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    read_only = os.getenv("GC_AGENT_READONLY", "").strip().lower() in {"1", "true", "yes"}
    service = AgentService(db_path, read_only=read_only)
    if args.verbose:
        print(f"[agents] Using tasks database at {db_path}", file=sys.stderr)

    command = args.command
    try:
        if command == "create":
            result = handle_create(service, args)
        elif command == "list":
            result = handle_list(service, args)
        elif command == "show":
            result = handle_show(service, args)
        elif command == "edit":
            result = handle_edit(service, args)
        elif command == "delete":
            result = handle_delete(service, args)
        elif command == "select":
            result = handle_select(service, args)
        elif command == "export":
            result = handle_export(service, args)
        elif command == "import":
            result = handle_import(service, args)
        elif command == "llms":
            result = handle_llms(service, args)
        elif command == "llms-check":
            result = handle_llm_check(service, args)
        elif command == "install-llm":
            result = handle_install_llm(service, args)
        elif command == "llms-sync":
            result = handle_llm_sync(service, args)
        elif command == "agent-check":
            result = handle_agent_check(service, args)
        elif command == "test-agent":
            result = handle_test_agent(service, args)
        else:
            result = 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        _flush_warnings(service)
    return result


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
