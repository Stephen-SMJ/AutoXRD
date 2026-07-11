"""features.agents — built-in agent definitions and WorkerManager."""

from .definitions import AgentDefinition, BUILTIN_AGENT_DEFINITIONS, EXPLORE_SYSTEM_PROMPT
from .worker_manager import WorkerManager, WorkerTask, WorkerUsage

__all__ = [
    "AgentDefinition",
    "BUILTIN_AGENT_DEFINITIONS",
    "EXPLORE_SYSTEM_PROMPT",
    "WorkerManager",
    "WorkerTask",
    "WorkerUsage",
]
