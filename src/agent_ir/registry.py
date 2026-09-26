"""Adapter registry and source-to-target orchestration."""

from agent_ir.adapters.claude import ClaudeCodeAdapter
from agent_ir.adapters.codex import CodexAdapter

SOURCES = {"claude-code": ClaudeCodeAdapter()}
TARGETS = {"codex": CodexAdapter()}
