from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Tuple

from agents_registry import AgentRegistry
from agents_validate import (
    DocBundle,
    parse_tags,
    read_doc,
    summarize_text,
    validate_client_model,
    validate_name,
)
from .llm_store import LLMCatalogStore
from .model import (
    Agent,
    AgentCreate,
    AgentFilter,
    AgentUpdate,
    LLMFilter,
    PromptBundle,
    iso_timestamp,
)
from .repository import AgentRepository
from .summarizer import AgentSummarizer

GUARDRAILS = [
    "- Stay within the job scope and acceptance criteria.",
    "- Use the assigned character style when communicating decisions.",
    "- Apply changes atomically using approved commands (gpt-creator apply-block, python helpers).",
    "- Do not leak raw credentials or sensitive document bodies in logs.",
]


@dataclass
class DocSource:
    path: str
    stdin_payload: Optional[str] = None


class AgentService:
    def __init__(self, db_path: Path, registry: Optional[AgentRegistry] = None):
        self.repo = AgentRepository(db_path)
        self.registry = registry or AgentRegistry.load()
        self._summarizer = AgentSummarizer(self.registry)
        self._catalog_store = LLMCatalogStore(db_path)
        self._warnings: List[str] = []
        self._sync_catalog_registry()
        self._seed_registry_providers()

    def _load_doc(self, source: DocSource) -> DocBundle:
        return read_doc(source.path, stdin_payload=source.stdin_payload)

    def _record_warning(self, message: str) -> None:
        self._warnings.append(message)

    def consume_warnings(self) -> List[str]:
        warnings = list(self._warnings)
        self._warnings.clear()
        return warnings

    def create_agent(
        self,
        *,
        name: str,
        client: str,
        model: str,
        job_doc: DocSource,
        character_doc: DocSource,
        tags: Optional[str] = None,
        summarize: bool = False,
        summarize_model: Optional[str] = None,
        summarize_client: Optional[str] = None,
        guardrails: Optional[str] = None,
        allow_missing_key: bool = False,
    ) -> Agent:
        validated_name = validate_name(name)
        pair = validate_client_model(client, model, self.registry)
        job_bundle = self._load_doc(job_doc)
        char_bundle = self._load_doc(character_doc)
        tags_list = parse_tags(tags or "")
        api_key_env = pair.get("apiKeyEnv") or ""
        api_key_value = os.getenv(api_key_env, "") if api_key_env else ""
        api_base_value = pair.get("apiBase") or ""
        org_env = pair.get("orgEnv") or ""
        api_org_value = os.getenv(org_env, "") if org_env else ""
        missing_key = bool(api_key_env and not api_key_value)
        if missing_key and not allow_missing_key:
            raise ValueError(f"API key for client '{pair['client']}' is not configured (env {api_key_env}). Pass --allow-missing-key to create anyway.")
        if missing_key and allow_missing_key:
            self._record_warning(
                f"API key {api_key_env} is not set; agent '{validated_name}' was created but credentials are still required."
            )
        job_summary = job_bundle.summary
        char_summary = char_bundle.summary
        if summarize:
            job_summary = self._summarize_with_llm(
                job_bundle.text,
                pair["client"],
                pair["model"],
                client_override=summarize_client,
                model_override=summarize_model,
            ) or job_summary
            char_summary = self._summarize_with_llm(
                char_bundle.text,
                pair["client"],
                pair["model"],
                client_override=summarize_client,
                model_override=summarize_model,
            ) or char_summary
        provider_ref = self._ensure_llm_reference(pair["client"], pair["model"])
        payload = {
            "name": validated_name,
            "client": pair["client"],
            "model": pair["model"],
            "llm_provider_id": provider_ref[0],
            "llm_model_id": provider_ref[1],
            "client_api_key": api_key_value,
            "client_api_base": api_base_value,
            "client_api_org": api_org_value,
            "job_doc": job_bundle.text,
            "job_doc_sha256": job_bundle.sha256,
            "job_summary": job_summary,
            "character_doc": char_bundle.text,
            "character_doc_sha256": char_bundle.sha256,
            "character_summary": char_summary,
            "tags_json": json.dumps(tags_list),
            "guardrails": guardrails,
        }
        agent = self.repo.create(self._dict_to_agent_create(payload))
        return agent

    def _dict_to_agent_create(self, payload: dict) -> AgentCreate:
        return AgentCreate(**payload)

    def list_agents(self, filters: Optional[AgentFilter] = None) -> List[Agent]:
        return self.repo.list(filters)

    def list_llms(self, filters: Optional[LLMFilter] = None):
        return self.repo.list_llms(filters)

    def llm_warning(self, provider_id: str, metadata: Optional[Dict[str, Any]] = None) -> Optional[str]:
        record = {"id": provider_id}
        return self._credential_warning(record, metadata or {})

    def sync_llms(
        self,
        *,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        refresh_catalog: bool = False,
        require_adapters: bool = False,
        require_keys: bool = False,
    ) -> Dict[str, Any]:
        seeded = self._catalog_store.seed_from_registry(
            self.registry,
            provider_filter=provider,
            model_filter=model,
        )
        refreshed = 0
        if refresh_catalog:
            from llm_catalog import load_catalog

            data = load_catalog(refresh=True)
            providers = data.get("providers") or []
            if providers:
                self._catalog_store.sync(
                    providers,
                    source=data.get("source") or "catalog",
                    fetched_at=data.get("fetched_at"),
                )
                refreshed = len(providers)
        checks: List[Dict[str, str]] = []
        failure = False
        if require_adapters or require_keys:
            check_results = self.check_llm_adapters(
                provider_id=provider,
                adapter=None,
                dry_run=False,
                install_missing=False,
            )
            for entry in check_results:
                issues = []
                if require_adapters and entry.get("status") != "installed":
                    issues.append(f"adapter status={entry.get('status')}")
                if require_keys and entry.get("credential_warning"):
                    issues.append(entry["credential_warning"])
                if issues:
                    failure = True
                checks.append(
                    {
                        "provider": entry["provider"],
                        "adapter": entry.get("adapter") or "",
                        "status": entry.get("status") or "",
                        "credential_warning": entry.get("credential_warning") or "",
                        "issues": issues,
                    }
                )
        return {
            "seeded": seeded,
            "refreshed": refreshed,
            "checks": checks,
            "failure": failure,
        }

    def check_llm_adapters(
        self,
        *,
        provider_id: Optional[str] = None,
        adapter: Optional[str] = None,
        dry_run: bool = False,
        install_missing: bool = False,
        health_check: bool = False,
    ) -> List[Dict[str, str]]:
        records = self.repo.list_llm_providers(provider_id=provider_id, adapter=adapter)
        results: List[Dict[str, str]] = []
        for record in records:
            metadata = {}
            raw_metadata = record.get("metadata_json")
            if raw_metadata:
                try:
                    metadata = json.loads(raw_metadata)
                except Exception:
                    metadata = {}
            self._attach_install_commands(record, metadata)
            adapter_name = (record.get("adapter") or "").strip().lower()
            binary = self._resolve_adapter_binary(metadata, adapter_name)
            install_command = self._select_install_command(metadata, record, target_os=None)
            status = "not_applicable"
            hint = record.get("install_hint") or metadata.get("install_hint") or ""
            if binary:
                exists = shutil.which(binary) is not None
                status = "installed" if exists else "missing"
                hint = hint or (f"Binary '{binary}' found on PATH." if exists else f"Install '{binary}' and ensure it is on PATH.")
            else:
                status = "not_applicable"
                if not hint:
                    hint = "HTTP adapter; no CLI binary required."
            health_status = "skipped"
            health_message = ""
            if install_missing and status == "missing" and install_command and not dry_run:
                try:
                    subprocess.run(install_command, shell=True, check=True)
                    exists = shutil.which(binary) is not None if binary else False
                    status = "installed" if exists else "missing"
                    hint = f"Attempted auto-install via: {install_command}"
                except subprocess.CalledProcessError as exc:
                    hint = f"Auto-install failed (exit {exc.returncode}); please install manually."
            checked_at = iso_timestamp()
            cred_warning = self._credential_warning(record, metadata)
            if (
                health_check
                and status == "installed"
                and not cred_warning
                and binary
                and not dry_run
            ):
                ok, msg = self._run_health_check(binary)
                health_status = "ok" if ok else "error"
                health_message = msg
            else:
                health_status = (
                    "skipped"
                    if status != "installed" or cred_warning or not health_check
                    else "unavailable"
                )
                health_message = cred_warning if cred_warning and health_status == "skipped" else ""
            if not dry_run:
                self.repo.update_llm_install_status(record["id"], status=status, hint=hint, checked_at=checked_at)
            results.append(
                {
                    "provider": record["id"],
                    "adapter": record.get("adapter") or "",
                    "status": status,
                    "hint": hint,
                    "checked_at": checked_at,
                    "binary": binary or "",
                    "install_command": install_command or "",
                    "credential_warning": cred_warning or "",
                    "health_status": health_status,
                    "health_message": health_message,
                }
            )
        return results

    def install_llm(
        self,
        *,
        provider_id: str,
        adapter: Optional[str] = None,
        target_os: Optional[str] = None,
        dry_run: bool = False,
        auto_run: bool = False,
    ) -> Dict[str, object]:
        records = self.repo.list_llm_providers(provider_id=provider_id, adapter=adapter)
        if not records:
            raise ValueError(f"LLM provider '{provider_id}' not found. Run 'gpt-creator list-llms' first.")
        record = dict(records[0])
        metadata = {}
        raw_metadata = record.get("metadata_json")
        if raw_metadata:
            try:
                metadata = json.loads(raw_metadata)
            except Exception:
                metadata = {}
        self._attach_install_commands(record, metadata)
        command_map = {
            "default": record.get("install_command"),
            "macos": record.get("install_command_macos"),
            "windows": record.get("install_command_windows"),
        }
        selected = self._select_install_command(metadata, record, target_os=target_os)
        target_label = target_os or os.getenv("GC_HOST_OS") or platform.system()
        if not any(command_map.values()):
            hint = record.get("install_hint") or "No installation command recorded."
            raise ValueError(f"No install command stored for provider '{provider_id}'. {hint}")
        warning = self._credential_warning(record, metadata)
        result = {
            "provider": record["id"],
            "provider_name": record.get("name"),
            "adapter": record.get("adapter"),
            "commands": command_map,
            "selectedCommand": selected or "",
            "targetOS": target_label,
            "status": "pending",
            "hint": warning or record.get("install_hint") or metadata.get("install_hint") or "",
            "credential_warning": warning or "",
        }
        if not auto_run or not selected or dry_run:
            return result
        try:
            subprocess.run(selected, shell=True, check=True)
            status = "installed"
            hint = f"Install command succeeded: {selected}"
        except subprocess.CalledProcessError as exc:
            status = "missing"
            hint = f"Install command failed (exit {exc.returncode})."
        checked_at = iso_timestamp()
        self.repo.update_llm_install_status(provider_id, status=status, hint=hint, checked_at=checked_at)
        result["status"] = status
        result["hint"] = warning or hint
        result["credential_warning"] = warning or ""
        result["selectedCommand"] = selected
        result["checked_at"] = checked_at
        return result

    def get_agent(self, name: str) -> Optional[Agent]:
        return self.repo.get_by_name(name)

    def update_agent(
        self,
        name: str,
        *,
        new_name: Optional[str] = None,
        client: Optional[str] = None,
        model: Optional[str] = None,
        job_doc: Optional[DocSource] = None,
        character_doc: Optional[DocSource] = None,
        tags: Optional[str] = None,
        active: Optional[bool] = None,
        resummarize: bool = False,
        summarize: bool = False,
        summarize_model: Optional[str] = None,
        summarize_client: Optional[str] = None,
        guardrails: Optional[str] = None,
        allow_missing_key: bool = False,
    ) -> Agent:
        fields = {}
        existing = self.get_agent(name)
        if not existing:
            raise ValueError(f"Agent '{name}' not found")
        if new_name:
            fields["name"] = validate_name(new_name)
            fields["name_normalized"] = fields["name"].lower()
        if client or model:
            target_client = client or existing.client
            target_model = model or existing.model
            pair = validate_client_model(target_client, target_model, self.registry)
            fields["client"] = pair["client"]
            fields["model"] = pair["model"]
            provider_ref = self._ensure_llm_reference(pair["client"], pair["model"])
            fields["llm_provider_id"] = provider_ref[0]
            fields["llm_model_id"] = provider_ref[1]
            api_key_env = pair.get("apiKeyEnv") or ""
            api_base_value = pair.get("apiBase") or ""
            org_env = pair.get("orgEnv") or ""
            api_key_value = os.getenv(api_key_env, "") if api_key_env else ""
            missing_key = bool(api_key_env and not api_key_value)
            if missing_key and not allow_missing_key:
                raise ValueError(
                    f"API key for client '{pair['client']}' is not configured (env {api_key_env}). "
                    "Pass --allow-missing-key to continue anyway."
                )
            if missing_key and allow_missing_key:
                self._record_warning(
                    f"API key {api_key_env} is not set; agent '{existing.name}' now targets {pair['client']}/{pair['model']} but credentials are still required."
                )
            fields["client_api_key"] = api_key_value
            fields["client_api_base"] = api_base_value
            fields["client_api_org"] = os.getenv(org_env, "") if org_env else ""
        if job_doc:
            job_bundle = self._load_doc(job_doc)
            fields["job_doc"] = job_bundle.text
            fields["job_doc_sha256"] = job_bundle.sha256
            fields["job_summary"] = job_bundle.summary
        if character_doc:
            char_bundle = self._load_doc(character_doc)
            fields["character_doc"] = char_bundle.text
            fields["character_doc_sha256"] = char_bundle.sha256
            fields["character_summary"] = char_bundle.summary
        if tags is not None:
            tags_list = parse_tags(tags)
            fields["tags_json"] = json.dumps(tags_list)
        if active is not None:
            fields["is_active"] = 1 if active else 0
        if guardrails is not None:
            fields["guardrails"] = guardrails.strip()
        if (
            "llm_provider_id" not in fields
            and "llm_model_id" not in fields
            and not existing.llm_provider_id
            and not existing.llm_model_id
        ):
            provider_ref = self._ensure_llm_reference(fields.get("client", existing.client), fields.get("model", existing.model))
            fields["llm_provider_id"] = provider_ref[0]
            fields["llm_model_id"] = provider_ref[1]
        if resummarize:
            job_text = fields.get("job_doc", existing.job_doc)
            char_text = fields.get("character_doc", existing.character_doc)
            summary_client = fields.get("client", existing.client)
            summary_model = fields.get("model", existing.model)
            if summarize:
                fields["job_summary"] = self._summarize_with_llm(
                    job_text,
                    summary_client,
                    summary_model,
                    client_override=summarize_client,
                    model_override=summarize_model,
                )
                fields["character_summary"] = self._summarize_with_llm(
                    char_text,
                    summary_client,
                    summary_model,
                    client_override=summarize_client,
                    model_override=summarize_model,
                )
            else:
                fields["job_summary"] = summarize_text(job_text)
                fields["character_summary"] = summarize_text(char_text)
        return self.repo.update(name, AgentUpdate(fields))

    def delete_agent(self, name: str, *, force: bool = False) -> None:
        if force:
            self.repo.hard_delete(name)
        else:
            self.repo.soft_delete(name)

    def compose_prompt(self, agent: Agent) -> PromptBundle:
        header_lines = [
            f"# Agent: {agent.name}",
            f"Client/Model: {agent.client}/{agent.model}",
            "",
            "## Role / Job",
            agent.job_doc.strip(),
            "",
            "## Character",
            agent.character_doc.strip(),
            "",
            "## Operational Guardrails",
        ]
        if agent.guardrails:
            header_lines.append(agent.guardrails.strip())
        else:
            header_lines.extend(GUARDRAILS)
        header_lines.append("")
        header = "\n".join(line for line in header_lines if line is not None)
        guardrails = [line for line in (agent.guardrails or "").splitlines() if line.strip()] or GUARDRAILS
        return PromptBundle(header=header, client=agent.client, model=agent.model, guardrails=guardrails)

    def record_usage(self, agent_name: str) -> None:
        self.repo.touch_last_used(agent_name)

    def resolve_agent_or_model(self, name_or_model: str) -> Tuple[Optional[Agent], Optional[str]]:
        """
        Resolve input as either a stored agent (preferred) or legacy model override.

        Returns (agent, model_override). When agent is found, model_override is None.
        When agent missing, returns (None, provided string) so callers can keep legacy behaviour.
        """
        agent = self.repo.get_by_name(name_or_model)
        if agent:
            return agent, None
        return None, name_or_model.strip()

    def _summarize_with_llm(
        self,
        text: str,
        client: str,
        model: str,
        *,
        client_override: Optional[str] = None,
        model_override: Optional[str] = None,
    ) -> str:
        target_client = client_override or os.getenv("GC_AGENT_SUMMARIZER_CLIENT", client)
        target_model = model_override or os.getenv("GC_AGENT_SUMMARIZER_MODEL", model)
        summary = self._summarizer.summarize(text, target_client, target_model)
        return summary or summarize_text(text)

    def _sync_catalog_registry(self) -> None:
        try:
            providers = getattr(self.registry, "catalog_providers", lambda: [])()
        except Exception:
            providers = []
        if not providers:
            return
        meta = self.registry.catalog_info()
        source = meta.get("source") or "catalog"
        fetched_at = meta.get("fetched_at")
        try:
            self._catalog_store.sync(providers, source=source, fetched_at=fetched_at)
        except Exception:
            pass

    def _seed_registry_providers(self) -> None:
        try:
            clients = self.registry.list_clients()
        except Exception:
            return
        for entry in clients:
            client_name = entry.get("name")
            default_model = entry.get("defaultModel") or (entry.get("models") or [None])[0]
            if client_name and default_model:
                self._ensure_llm_reference(client_name, default_model)

    def _ensure_llm_reference(self, client: str, model: str) -> Tuple[Optional[str], Optional[str]]:
        cfg = self.registry.get_client_config(client)
        provider_id = cfg.name if cfg else client
        provider_label = cfg.label if cfg else client
        adapter = cfg.adapter if cfg else ""
        provider_meta = {
            "id": provider_id,
            "name": provider_label,
            "adapter": adapter,
            "type": cfg.adapter if cfg else "",
            "source": "registry",
            "adapterConfig": cfg.adapter_config if cfg else {},
            "binary": self._resolve_adapter_binary_from_config(cfg),
            "install_hint": cfg.install_hint if cfg else "",
            "installCommands": cfg.install_commands if cfg else {},
            "install_command": (cfg.install_commands.get("default") if cfg else None),
            "install_command_macos": (cfg.install_commands.get("macos") if cfg else None),
            "install_command_windows": (cfg.install_commands.get("windows") if cfg else None),
            "apiKeyEnv": cfg.api_key_env if cfg else "",
            "envVars": cfg.env_vars if cfg else [],
        }
        model_meta = {"id": model, "name": model, "source": "registry"}
        return self._catalog_store.ensure_provider_model(
            provider_id,
            provider_label,
            adapter=adapter,
            source="registry",
            model_id=model,
            model_name=model,
            provider_metadata=provider_meta,
            model_metadata=model_meta,
        )

    def _resolve_adapter_binary_from_config(self, cfg: Optional["ClientConfig"]) -> Optional[str]:
        if not cfg:
            return None
        adapter = (cfg.adapter or "").lower()
        if adapter in {"codex_cli", "openai_cli", "openai"}:
            return "codex"
        binary = (cfg.adapter_config or {}).get("binary")
        if isinstance(binary, str) and binary.strip():
            return binary.strip()
        if adapter == "command":
            cmd = cfg.adapter_config.get("command")
            if isinstance(cmd, list) and cmd:
                token = cmd[0]
                if isinstance(token, str):
                    return token.strip().strip("{}")
            if isinstance(cmd, str) and cmd.strip():
                first = cmd.strip().split()[0]
                return first.strip("{}")
        return None

    def _resolve_adapter_binary(self, metadata: Dict[str, Any], adapter_name: str) -> Optional[str]:
        if adapter_name in {"codex_cli", "openai_cli", "openai"}:
            return "codex"
        adapter_config = metadata.get("adapterConfig") or {}
        binary = metadata.get("binary")
        if binary:
            return str(binary)
        if adapter_name == "command":
            command = adapter_config.get("command")
            if isinstance(command, list) and command:
                token = command[0]
                if isinstance(token, str):
                    return token.strip().strip("{}")
            if isinstance(command, str) and command.strip():
                return command.strip().split()[0].strip("{}")
        return None

    def _select_install_command(
        self,
        metadata: Dict[str, Any],
        record: Dict[str, Any],
        target_os: Optional[str] = None,
    ) -> Optional[str]:
        commands = metadata.get("installCommands") or {}
        default_cmd = (
            record.get("install_command")
            or metadata.get("install_command")
            or commands.get("default")
        )
        mac_cmd = record.get("install_command_macos") or commands.get("macos")
        win_cmd = record.get("install_command_windows") or commands.get("windows")
        override = target_os or os.getenv("GC_HOST_OS", "")
        system = (override or platform.system()).lower()
        if "darwin" in system or "mac" in system:
            return mac_cmd or default_cmd
        if "windows" in system:
            return win_cmd or default_cmd
        return default_cmd

    def _credential_warning(self, record: Dict[str, Any], metadata: Dict[str, Any]) -> Optional[str]:
        provider = (record.get("provider") or record.get("id") or "").strip()
        env_candidates: List[str] = []
        cfg = self.registry.get_client_config(provider) if provider else None
        if cfg and cfg.api_key_env:
            env_candidates.append(cfg.api_key_env)
        if cfg:
            env_candidates.extend(cfg.env_vars or [])
        record_env = record.get("api_key_env") or record.get("apiKeyEnv")
        if record_env:
            env_candidates.append(record_env)
        meta_env = metadata.get("apiKeyEnv") or metadata.get("api_key_env")
        if meta_env:
            env_candidates.append(meta_env)
        for candidate in metadata.get("envVars") or []:
            env_candidates.append(candidate)
        seen = set()
        for env_name in env_candidates:
            env_name = (env_name or "").strip()
            if not env_name or env_name in seen:
                continue
            seen.add(env_name)
            if not os.getenv(env_name):
                provider_label = provider or (record.get("provider_name") or "")
                target = provider_label or "the provider"
                return f"API key {env_name} not set; run 'gpt-creator keys set {target}'"
        return None

    def _run_health_check(self, binary: str) -> Tuple[bool, str]:
        try:
            subprocess.run([binary, "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=10)
            return True, f"{binary} --version succeeded"
        except subprocess.CalledProcessError as exc:
            return False, f"{binary} --version failed (exit {exc.returncode})"
        except FileNotFoundError:
            return False, f"Binary '{binary}' missing after install"
        except Exception as exc:
            return False, f"Health check failed: {exc}"

    def _attach_install_commands(self, record: Dict[str, Any], metadata: Dict[str, Any]) -> None:
        commands = metadata.get("installCommands") or {}
        record.setdefault("install_command", record.get("install_command") or commands.get("default"))
        record.setdefault("install_command_macos", record.get("install_command_macos") or commands.get("macos"))
        record.setdefault("install_command_windows", record.get("install_command_windows") or commands.get("windows"))

if TYPE_CHECKING:
    from agents_registry import ClientConfig
