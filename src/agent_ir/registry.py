"""Adapter registry and source-to-target orchestration."""

from typing import cast

from agent_ir.adapters.base import ContextAwareSourceAdapter, ParseResult, SourceAdapter, SourceParseContext
from agent_ir.adapters.claude import ClaudeCodeAdapter
from agent_ir.adapters.codex import CodexAdapter
from agent_ir.adapters.opencode_v2 import OpenCodeV2Adapter, OpenCodeSourceContext
from agent_ir.diagnostics import ConversionDiagnostic
from agent_ir.models import CodexTargetContext

SOURCES: dict[str, SourceAdapter | ContextAwareSourceAdapter] = {
    "claude-code": ClaudeCodeAdapter(),
    "opencode-v2": OpenCodeV2Adapter(),
}
TARGETS = {"codex": CodexAdapter()}


def parse_source(
    harness: str,
    document: str,
    *,
    agent_relative_path: str | None = None,
) -> ParseResult:
    if harness == "opencode-v2":
        if agent_relative_path is None:
            raise ValueError("OpenCode V2 parsing requires an explicit agent-relative path")
        adapter = cast(ContextAwareSourceAdapter, SOURCES[harness])
        return adapter.parse_with_context(document, SourceParseContext(agent_relative_path=agent_relative_path))
    if agent_relative_path is not None:
        raise ValueError("agent-relative path context is only valid for OpenCode V2 sources")
    return cast(SourceAdapter, SOURCES[harness]).parse(document)


def apply_source_context(parsed: ParseResult, context: OpenCodeSourceContext | None) -> ParseResult:
    if parsed.agent.metadata.harness != "opencode-v2":
        if context is not None:
            raise ValueError("OpenCode source context is only valid for OpenCode V2 sources")
        return parsed
    return cast(OpenCodeV2Adapter, SOURCES["opencode-v2"]).apply_source_context(parsed, context)


def validate_source_target_scope(parsed: ParseResult, target: CodexTargetContext) -> list[ConversionDiagnostic]:
    if parsed.agent.metadata.harness != "opencode-v2":
        return []
    return cast(OpenCodeV2Adapter, SOURCES["opencode-v2"]).validate_target_scope(parsed, target)
