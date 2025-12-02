"""Agent domain package."""

from typing import TYPE_CHECKING

from .model import (
    Agent,
    AgentCreate,
    AgentFilter,
    AgentUpdate,
    LLMFilter,
    LLMInfo,
    PromptBundle,
)
from .repository import AgentRepository

if TYPE_CHECKING:  # pragma: no cover - avoids import cycles at runtime
    from .service import AgentService, DocSource

__all__ = [
    "Agent",
    "AgentCreate",
    "AgentFilter",
    "AgentUpdate",
    "LLMFilter",
    "LLMInfo",
    "PromptBundle",
    "AgentRepository",
    "AgentService",
    "DocSource",
]


def __getattr__(name):
    if name in {"AgentService", "DocSource"}:
        from .service import AgentService, DocSource

        return AgentService if name == "AgentService" else DocSource
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
