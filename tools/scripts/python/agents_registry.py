#!/usr/bin/env python3
"""Client/model registry helpers for gpt-creator agents."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from llm_catalog import load_catalog


def _default_registry_path() -> Path:
    base = Path(__file__).resolve().parents[2]
    fallback = base / "config" / "agent_clients.json"
    override = os.environ.get("GC_AGENT_REGISTRY_PATH", "").strip()
    return Path(override) if override else fallback


@dataclass
class ClientConfig:
    name: str
    label: str
    default_model: str
    models: List[str]
    env_vars: List[str] = field(default_factory=list)
    retry: Dict[str, int] = field(default_factory=dict)
    adapter: str = "codex_cli"
    max_context_tokens: Optional[int] = None
    max_output_tokens: Optional[int] = None
    api_key_env: str = ""
    api_base_env: str = ""
    default_api_base: str = ""
    org_env: str = ""
    default_headers: Dict[str, str] = field(default_factory=dict)
    adapter_config: Dict[str, Any] = field(default_factory=dict)
    install_hint: str = ""
    install_commands: Dict[str, str] = field(default_factory=dict)

    def validate_model(self, model: str) -> Tuple[str, str]:
        if not model:
            return self.name, self.default_model
        for candidate in self.models:
            if candidate.lower() == model.lower():
                return self.name, candidate
        raise ValueError(f"Model '{model}' not valid for client '{self.name}'")


class AgentRegistry:
    def __init__(self, clients: Dict[str, ClientConfig], catalog_meta: Optional[Dict[str, Any]] = None):
        self._clients = {key.lower(): value for key, value in clients.items()}
        self._catalog_meta = catalog_meta or {"providers": [], "source": "unavailable"}
        providers = self._catalog_meta.get("providers") or []
        self._catalog = {
            (entry.get("id") or "").strip().lower(): entry for entry in providers if entry.get("id")
        }

    @classmethod
    def load(cls, path: Optional[Path] = None, *, refresh_catalog: bool = False) -> "AgentRegistry":
        target = path or _default_registry_path()
        data = json.loads(target.read_text(encoding="utf-8"))
        clients = {}
        for raw_name, cfg in (data.get("clients") or {}).items():
            name = raw_name.strip()
            if not name:
                continue
            label = (cfg.get("label") or name).strip()
            models = [m.strip() for m in cfg.get("models") or [] if m.strip()]
            default_model = (cfg.get("defaultModel") or (models[0] if models else "")).strip()
            adapter = (cfg.get("adapter") or "codex_cli").strip()
            max_context = cfg.get("maxContextTokens")
            max_output = cfg.get("maxOutputTokens")
            api_key_env = (cfg.get("apiKeyEnv") or "").strip()
            api_base_env = (cfg.get("apiBaseEnv") or "").strip()
            default_api_base = (cfg.get("defaultApiBase") or "").strip()
            org_env = (cfg.get("orgEnv") or "").strip()
            headers = cfg.get("defaultHeaders") or {}
            adapter_config = cfg.get("adapterConfig") or {}
            install_hint = (cfg.get("installHint") or "").strip()
            install_commands = {}
            raw_install = cfg.get("installCommands") or {}
            if isinstance(raw_install, dict):
                for key, value in raw_install.items():
                    if isinstance(value, str) and value.strip():
                        install_commands[key.strip().lower()] = value.strip()
            single_install = (cfg.get("installCommand") or "").strip()
            if single_install and "default" not in install_commands:
                install_commands["default"] = single_install
            try:
                max_context_val = int(max_context)
            except (TypeError, ValueError):
                max_context_val = None
            try:
                max_output_val = int(max_output)
            except (TypeError, ValueError):
                max_output_val = None
            clients[name.lower()] = ClientConfig(
                name=name,
                label=label,
                default_model=default_model,
                models=models,
                env_vars=[entry.strip() for entry in (cfg.get("envVars") or []) if entry.strip()],
                retry=cfg.get("retry") or {},
                adapter=adapter or "codex_cli",
                max_context_tokens=max_context_val,
                max_output_tokens=max_output_val,
                api_key_env=api_key_env,
                api_base_env=api_base_env,
                default_api_base=default_api_base,
                org_env=org_env,
                default_headers=headers,
                adapter_config=adapter_config,
                install_hint=install_hint,
                install_commands=install_commands,
            )
        catalog_disabled = (os.getenv("GC_AGENT_CATALOG_DISABLE", "").strip().lower() in {"1", "true", "yes"})
        catalog_meta: Dict[str, Any] = {"providers": [], "source": "disabled" if catalog_disabled else "unavailable"}
        if not catalog_disabled:
            try:
                catalog_meta = load_catalog(refresh=refresh_catalog)
            except Exception as exc:
                catalog_meta = {
                    "providers": [],
                    "source": f"error:{exc}",
                    "fetched_at": None,
                }
        return cls(clients, catalog_meta)

    def list_clients(self) -> List[Dict[str, object]]:
        entries: List[Dict[str, object]] = []
        for cfg in sorted(self._clients.values(), key=lambda item: item.name):
            provider = self._catalog.get(cfg.name.lower())
            record = {
                "name": cfg.name,
                "label": cfg.label,
                "adapter": cfg.adapter,
                "defaultModel": cfg.default_model,
                "models": cfg.models,
                "envVars": cfg.env_vars,
                "maxContextTokens": cfg.max_context_tokens,
                "maxOutputTokens": cfg.max_output_tokens,
                "retry": cfg.retry,
                "source": "registry",
            }
            if provider:
                record["catalogModels"] = provider.get("models", [])
                record["catalogFetchedAt"] = self._catalog_meta.get("fetched_at")
                record["catalogSource"] = self._catalog_meta.get("source")
            entries.append(record)
        for key, provider in sorted(self._catalog.items()):
            if key in self._clients:
                continue
            models = provider.get("models") or []
            entries.append(
                {
                    "name": provider.get("id"),
                    "label": provider.get("name") or provider.get("id"),
                    "adapter": provider.get("type") or "catalog",
                    "defaultModel": provider.get("defaultSmallModel") or provider.get("defaultLargeModel") or "",
                    "models": [model.get("id") for model in models if model.get("id")],
                    "envVars": [],
                    "maxContextTokens": None,
                    "maxOutputTokens": None,
                    "retry": {},
                    "source": "catalog",
                    "catalogModels": models,
                    "catalogFetchedAt": self._catalog_meta.get("fetched_at"),
                    "catalogSource": self._catalog_meta.get("source"),
                    "catalogOnly": True,
                }
            )
        return entries

    def list_models(self, client: str) -> List[str]:
        cfg = self._clients.get(client.lower())
        if not cfg:
            raise ValueError(f"Unknown client '{client}'")
        return cfg.models

    def validate_pair(self, client: str, model: str = "") -> Dict[str, str]:
        if not client:
            raise ValueError("Client is required")
        cfg = self._clients.get(client.lower())
        if not cfg:
            raise ValueError(f"Unknown client '{client}'")
        _, model_name = cfg.validate_model(model)
        api_base = cfg.default_api_base
        if cfg.api_base_env:
            api_base = os.getenv(cfg.api_base_env, api_base)
        result = {
            "client": cfg.name,
            "model": model_name,
            "adapter": cfg.adapter,
            "maxContextTokens": cfg.max_context_tokens,
            "maxOutputTokens": cfg.max_output_tokens,
            "retry": cfg.retry,
            "apiKeyEnv": cfg.api_key_env,
            "apiBaseEnv": cfg.api_base_env,
            "orgEnv": cfg.org_env,
            "apiBase": api_base,
            "defaultHeaders": cfg.default_headers,
            "adapterConfig": dict(cfg.adapter_config),
            "installHint": cfg.install_hint,
            "installCommands": cfg.install_commands,
        }
        return result

    def catalog_info(self) -> Dict[str, Any]:
        info = dict(self._catalog_meta or {})
        info["providerCount"] = len(self._catalog)
        return info

    def catalog_providers(self) -> List[Dict[str, Any]]:
        return list(self._catalog.values())

    def get_client_config(self, client: str) -> Optional[ClientConfig]:
        if not client:
            return None
        return self._clients.get(client.lower())


def _cmd_validate(registry: AgentRegistry, args: argparse.Namespace) -> int:
    try:
        result = registry.validate_pair(args.client, args.model or "")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, **result}))
    return 0


def _cmd_list_clients(registry: AgentRegistry) -> int:
    print(json.dumps(registry.list_clients(), indent=2))
    return 0


def _cmd_list_models(registry: AgentRegistry, args: argparse.Namespace) -> int:
    try:
        models = registry.list_models(args.client)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(models))
    return 0


def _cmd_catalog(registry: AgentRegistry) -> int:
    print(json.dumps(registry.catalog_info(), indent=2))
    return 0


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="Agent client/model registry helper.")
    parser.add_argument("--refresh-catalog", action="store_true", help="Force refresh of the cached Catwalk catalog.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate client/model pair.")
    validate_parser.add_argument("--client", required=True)
    validate_parser.add_argument("--model", default="")

    list_clients_parser = subparsers.add_parser("list-clients", help="List configured clients.")
    list_clients_parser.set_defaults(command="list-clients")

    list_models_parser = subparsers.add_parser("list-models", help="List models for a client.")
    list_models_parser.add_argument("--client", required=True)

    catalog_parser = subparsers.add_parser("catalog", help="Show synced Catwalk catalog metadata.")
    catalog_parser.set_defaults(command="catalog")

    args = parser.parse_args(argv)
    registry = AgentRegistry.load(refresh_catalog=args.refresh_catalog)

    if args.command == "validate":
        return _cmd_validate(registry, args)
    if args.command == "list-clients":
        return _cmd_list_clients(registry)
    if args.command == "list-models":
        return _cmd_list_models(registry, args)
    if args.command == "catalog":
        return _cmd_catalog(registry)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
