"""Strips the GIT_CONFIG_* push-blocking overlay that Orchestrator's agent_env() adds to a
worker's environment (tools/ai_orchestrator/providers.py), for tests that create their own
temporary repos and push to their own temporary origin.

Without this, such a push inherits the real-origin safety net from the parent process and
fails with exit code 128 ("remote helper 'disabled' aborted session"), even though the push
target has nothing to do with the real origin the safety net protects.
"""

from __future__ import annotations

import os

_EXACT_NAMES = ("GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS")
_PREFIXES = ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")


def _is_git_config_override(name: str) -> bool:
    return name in _EXACT_NAMES or name.startswith(_PREFIXES)


def strip_git_config_env() -> dict[str, str]:
    """Remove git-config-override env vars from os.environ; return what was removed."""
    return {name: os.environ.pop(name) for name in list(os.environ) if _is_git_config_override(name)}


def restore_git_config_env(removed: dict[str, str]) -> None:
    """Put back env vars previously removed by strip_git_config_env."""
    os.environ.update(removed)


def isolate_git_env(testcase) -> None:
    """Strip git-config-override env vars for the duration of `testcase`, restoring them after."""
    removed = strip_git_config_env()
    testcase.addCleanup(restore_git_config_env, removed)
