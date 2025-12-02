from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional


def iso_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass
class Agent:
    id: str
    name: str
    client: str
    model: str
    job_doc: str
    job_doc_sha256: str
    job_summary: str
    character_doc: str
    character_doc_sha256: str
    character_summary: str
    llm_provider_id: Optional[str] = None
    llm_model_id: Optional[str] = None
    client_api_key: Optional[str] = None
    client_api_base: Optional[str] = None
    client_api_org: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    guardrails: Optional[str] = None
    is_active: bool = True
    last_used_at: Optional[str] = None
    created_at: str = field(default_factory=iso_timestamp)
    updated_at: str = field(default_factory=iso_timestamp)

    @classmethod
    def from_row(cls, row) -> "Agent":
        tags_raw = row["tags_json"] if "tags_json" in row.keys() else row["tags"]
        tags = []
        if tags_raw:
            try:
                parsed = json.loads(tags_raw)
                if isinstance(parsed, list):
                    tags = [str(item) for item in parsed if str(item).strip()]
            except Exception:
                tags = []
        client_api_key = row["client_api_key"] if "client_api_key" in row.keys() else None
        client_api_base = row["client_api_base"] if "client_api_base" in row.keys() else None
        client_api_org = row["client_api_org"] if "client_api_org" in row.keys() else None
        llm_provider_id = row["llm_provider_id"] if "llm_provider_id" in row.keys() else None
        llm_model_id = row["llm_model_id"] if "llm_model_id" in row.keys() else None
        guardrails_value = None
        if "guardrails" in row.keys():
            guardrails_value = row["guardrails"]
        elif "custom_guardrails" in row.keys():
            guardrails_value = row["custom_guardrails"]
        return cls(
            id=row["id"],
            name=row["name"],
            client=row["client"],
            model=row["model"],
            llm_provider_id=llm_provider_id,
            llm_model_id=llm_model_id,
            client_api_key=client_api_key,
            client_api_base=client_api_base,
            client_api_org=client_api_org,
            job_doc=row["job_doc"],
            job_doc_sha256=row["job_doc_sha256"],
            job_summary=row["job_summary"],
            character_doc=row["character_doc"],
            character_doc_sha256=row["character_doc_sha256"],
            character_summary=row["character_summary"],
            tags=tags,
            is_active=bool(row["is_active"]),
            last_used_at=row["last_used_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            guardrails=guardrails_value,
        )


@dataclass
class AgentFilter:
    client: Optional[str] = None
    model: Optional[str] = None
    active: Optional[bool] = None
    name_like: Optional[str] = None
    limit: Optional[int] = None
    tags: Optional[List[str]] = None


@dataclass
class AgentCreate:
    name: str
    client: str
    model: str
    job_doc: str
    job_doc_sha256: str
    job_summary: str
    character_doc: str
    character_doc_sha256: str
    character_summary: str
    llm_provider_id: Optional[str] = None
    llm_model_id: Optional[str] = None
    client_api_key: Optional[str] = None
    client_api_base: Optional[str] = None
    client_api_org: Optional[str] = None
    tags_json: str = "[]"
    guardrails: Optional[str] = None


@dataclass
class AgentUpdate:
    fields: dict

    def is_empty(self) -> bool:
        return not self.fields


@dataclass
class PromptBundle:
    header: str
    client: str
    model: str
    guardrails: List[str] = field(default_factory=list)


@dataclass
class LLMInfo:
    provider_id: str
    provider_name: str
    model_id: str
    model_name: str
    adapter: Optional[str] = None
    source: Optional[str] = None
    install_status: Optional[str] = None
    install_checked_at: Optional[str] = None
    install_hint: Optional[str] = None
    context_window: Optional[int] = None
    default_max_tokens: Optional[int] = None
    metadata: Dict[str, object] = field(default_factory=dict)


@dataclass
class LLMFilter:
    provider: Optional[str] = None
    adapter: Optional[str] = None
    source: Optional[str] = None
    model: Optional[str] = None
    name_like: Optional[str] = None
    limit: Optional[int] = None
    statuses: Optional[List[str]] = None
