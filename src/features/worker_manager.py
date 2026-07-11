"""Backward-compatibility re-export shim.

WorkerManager has moved to features.agents.worker_manager.
"""
from features.agents.worker_manager import WorkerManager, WorkerTask, WorkerUsage

__all__ = ["WorkerManager", "WorkerTask", "WorkerUsage"]
