import asyncio
from copy import deepcopy
import json
import tempfile
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.agent.schemas import AssistantResult


class AgentRunError(Exception):
    pass


AGENT_MODEL = "gpt-5.4-mini"
AGENT_REASONING_EFFORT = "medium"


def build_strict_output_schema() -> dict[str, Any]:
    schema = deepcopy(AssistantResult.model_json_schema())
    _normalize_schema_object(schema)
    return schema


def _normalize_schema_object(value: Any) -> None:
    if isinstance(value, dict):
        value.pop("default", None)
        properties = value.get("properties")
        if isinstance(properties, dict):
            value["required"] = list(properties)
        for child in value.values():
            _normalize_schema_object(child)
    elif isinstance(value, list):
        for item in value:
            _normalize_schema_object(item)


class AgentRunner:
    def __init__(self, timeout_seconds: float = 90.0, command: tuple[str, ...] = ("codex", "exec")):
        self.timeout_seconds = timeout_seconds
        self.command = command

    async def run(self, prompt: str) -> AssistantResult:
        with tempfile.TemporaryDirectory() as tmp_dir:
            schema_path = Path(tmp_dir) / "assistant_result.schema.json"
            output_path = Path(tmp_dir) / "assistant_result.json"
            schema_path.write_text(json.dumps(build_strict_output_schema()), encoding="utf-8")

            process = await asyncio.create_subprocess_exec(
                *self._build_command(schema_path, output_path),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr = await asyncio.wait_for(
                    process.communicate(prompt.encode("utf-8")),
                    timeout=self.timeout_seconds,
                )
            except TimeoutError as exc:
                process.kill()
                await process.communicate()
                raise AgentRunError("Agent process timed out") from exc

            if process.returncode != 0:
                message = stderr.decode("utf-8", errors="replace").strip()
                raise AgentRunError(message or f"Agent exited with {process.returncode}")

            if not output_path.exists():
                raise AgentRunError("Agent did not write structured output")

            try:
                return AssistantResult.model_validate_json(output_path.read_text(encoding="utf-8"))
            except (ValidationError, ValueError) as exc:
                raise AgentRunError("Agent returned invalid structured output") from exc

    def _build_command(self, schema_path: Path, output_path: Path) -> tuple[str, ...]:
        return (
            *self.command,
            "-m",
            AGENT_MODEL,
            "-c",
            f'model_reasoning_effort="{AGENT_REASONING_EFFORT}"',
            "--ephemeral",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(output_path),
            "-",
        )

