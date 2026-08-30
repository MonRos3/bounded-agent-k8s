"""ModelClient plumbing tests — request shape and defensive parsing against
stubbed/recorded responses. Never calls the real model (that's M3.3);
every test injects a mock bedrock_client instead.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from safety_core.policy import Policy, Rule
from safety_core.types import Tier

from k8s_agent.model_client import ModelClient
from k8s_agent.prompt import build_tool_schema

_SCHEMA = {"scale_deployment": {"namespace": "string", "deployment": "string", "target_replicas": "integer"}}


def _converse_response(text: str) -> dict:
    return {"output": {"message": {"content": [{"text": text}]}}}


def _client_with(mock_bedrock: MagicMock) -> ModelClient:
    return ModelClient(bedrock_client=mock_bedrock, model_id="llama3.1")


def test_propose_calls_converse_with_correct_model_and_prompt():
    mock_bedrock = MagicMock()
    mock_bedrock.converse.return_value = _converse_response(
        '{"tool": "scale_deployment", "args": {}, "advisory_note": "note"}'
    )
    client = _client_with(mock_bedrock)

    client.propose("scale web-frontend to 5 replicas", _SCHEMA)

    call_kwargs = mock_bedrock.converse.call_args.kwargs
    assert call_kwargs["modelId"] == "llama3.1"
    prompt_text = call_kwargs["messages"][0]["content"][0]["text"]
    assert "scale web-frontend to 5 replicas" in prompt_text
    assert "scale_deployment" in prompt_text


def test_well_formed_json_response_parses_into_proposed_action():
    mock_bedrock = MagicMock()
    mock_bedrock.converse.return_value = _converse_response(
        json.dumps(
            {
                "tool": "scale_deployment",
                "args": {"namespace": "web", "deployment": "web-frontend", "target_replicas": 5},
                "advisory_note": "Traffic is up; scaling out.",
            }
        )
    )
    client = _client_with(mock_bedrock)

    proposal = client.propose("scale web-frontend to 5 replicas", _SCHEMA)

    assert proposal.tool == "scale_deployment"
    assert proposal.args == {"namespace": "web", "deployment": "web-frontend", "target_replicas": 5}
    assert proposal.advisory_note == "Traffic is up; scaling out."
    assert "scale_deployment" in proposal.raw_response


def test_prose_wrapped_json_response_still_parses():
    raw = (
        "Sure, here's my proposal:\n"
        '{"tool": "scale_deployment", "args": {"namespace": "web", "deployment": "web-frontend", '
        '"target_replicas": 5}, "advisory_note": "Scaling out."}\n'
        "Let me know if you need anything else."
    )
    mock_bedrock = MagicMock()
    mock_bedrock.converse.return_value = _converse_response(raw)
    client = _client_with(mock_bedrock)

    proposal = client.propose("scale web-frontend to 5 replicas", _SCHEMA)

    assert proposal.tool == "scale_deployment"
    assert proposal.args == {"namespace": "web", "deployment": "web-frontend", "target_replicas": 5}
    assert proposal.raw_response == raw


def test_malformed_json_response_yields_fail_closed_proposal():
    mock_bedrock = MagicMock()
    mock_bedrock.converse.return_value = _converse_response('{"tool": "scale_deployment", "args": {')
    client = _client_with(mock_bedrock)

    proposal = client.propose("scale web-frontend to 5 replicas", _SCHEMA)

    assert proposal.tool == ""
    assert proposal.args == {}


def test_empty_response_yields_fail_closed_proposal():
    mock_bedrock = MagicMock()
    mock_bedrock.converse.return_value = _converse_response("")
    client = _client_with(mock_bedrock)

    proposal = client.propose("scale web-frontend to 5 replicas", _SCHEMA)

    assert proposal.tool == ""
    assert proposal.args == {}


def test_converse_call_failure_yields_fail_closed_proposal():
    mock_bedrock = MagicMock()
    mock_bedrock.converse.side_effect = RuntimeError("MiniStack unreachable")
    client = _client_with(mock_bedrock)

    proposal = client.propose("scale web-frontend to 5 replicas", _SCHEMA)

    assert proposal.tool == ""
    assert "MiniStack unreachable" in proposal.raw_response


def test_build_tool_schema_reflects_policy_allow_list():
    policy = Policy(
        rules=[
            Rule(tool="scale_deployment", default_tier=Tier.AUTO, reversible=True),
            Rule(tool="delete_pod", default_tier=Tier.APPROVE, reversible=True),
        ],
        protected_zones=set(),
    )

    schema = build_tool_schema(policy)

    assert set(schema.keys()) == {"scale_deployment", "delete_pod"}
