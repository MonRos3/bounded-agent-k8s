"""Bedrock-shaped LLM client: speaks the Bedrock converse API via boto3,
pointed at MiniStack (local, LAB_USE_AWS=0) or real AWS (LAB_USE_AWS=1) —
same code, one flag. The model's response is untrusted external input:
parsing never trusts structure and always degrades to a fail-closed
ProposedAction rather than raising. Produces only ProposedAction, never a
safety_core.types.Action — this module has no need to import safety_core
at all.
"""

from __future__ import annotations

import json
import os
from typing import Any

import boto3
from dotenv import load_dotenv

from k8s_agent.prompt import build_prompt
from k8s_agent.proposal_types import ProposedAction

load_dotenv()

_LAB_USE_AWS = os.environ.get("LAB_USE_AWS", "0") == "1"
_MINISTACK_ENDPOINT = os.environ.get("MINISTACK_ENDPOINT", "http://localhost:4566")
_MODEL_ID = os.environ.get("OLLAMA_MODEL", "llama3.1")

_FAIL_CLOSED_TOOL = ""


def _default_bedrock_client() -> Any:
    if _LAB_USE_AWS:
        return boto3.client("bedrock-runtime")
    return boto3.client(
        "bedrock-runtime",
        endpoint_url=_MINISTACK_ENDPOINT,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


def _extract_json_block(text: str) -> Any:
    """Parse `text` as JSON directly; if that fails, scan for the first
    balanced {...} block (brace-depth counting, so it survives prose
    wrapped around the JSON) and parse that instead. Returns None if
    nothing parseable is found.
    """
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass

    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


class ModelClient:
    """Proposes actions via a Bedrock-shaped model. `bedrock_client` is
    injectable for testability (mirrors ClusterClient's api_client
    pattern); the default path builds a real bedrock-runtime client from
    env config.
    """

    def __init__(self, bedrock_client: Any | None = None, model_id: str | None = None) -> None:
        self._client = bedrock_client if bedrock_client is not None else _default_bedrock_client()
        self._model_id = model_id if model_id is not None else _MODEL_ID

    def propose(self, operator_request: str, tool_schema: dict[str, Any]) -> ProposedAction:
        """Assemble the prompt, call the model, and parse its response into
        a ProposedAction.

        Wrapped in one broad try/except: any failure anywhere in this
        pipeline — network/auth failure, a malformed converse response
        shape, unparseable/empty model text — degrades to the fail-closed
        sentinel (tool="") rather than raising. That sentinel can't match
        any Policy rule, so downstream validation rejects it naturally;
        the model is an untrusted external boundary, so nothing here is
        allowed to propagate an unhandled exception to the caller.
        """
        prompt = build_prompt(operator_request, tool_schema)
        try:
            response = self._client.converse(
                modelId=self._model_id,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
            )
            raw_text = response["output"]["message"]["content"][0]["text"]
        except Exception as exc:
            return ProposedAction(
                tool=_FAIL_CLOSED_TOOL,
                args={},
                advisory_note="",
                raw_response=f"<model call failed: {exc!r}>",
            )

        return self._parse(raw_text)

    def _parse(self, raw_text: str) -> ProposedAction:
        data = _extract_json_block(raw_text)
        if not isinstance(data, dict):
            return ProposedAction(tool=_FAIL_CLOSED_TOOL, args={}, advisory_note="", raw_response=raw_text)

        tool = data.get("tool")
        args = data.get("args")
        advisory_note = data.get("advisory_note", "")

        if not isinstance(tool, str) or not tool or not isinstance(args, dict):
            return ProposedAction(tool=_FAIL_CLOSED_TOOL, args={}, advisory_note="", raw_response=raw_text)

        return ProposedAction(
            tool=tool,
            args=args,
            advisory_note=str(advisory_note),
            raw_response=raw_text,
        )
