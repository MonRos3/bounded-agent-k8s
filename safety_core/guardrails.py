"""Input/output guardrails: content screening on untrusted operator input,
and secret/PII redaction on anything the system surfaces or audits.

Input and output are distinct trust boundaries and get distinct methods —
screening decides whether to proceed; redaction decides what's safe to show
or persist. Neither method's detection technique (regex, allow-list, model
call, etc.) is part of this contract.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GuardrailResult:
    """The outcome of screening a piece of text.

    `passed` is False if the text must be blocked outright; `flagged` lists
    the reasons a reviewer (human or the gate) should know about, even when
    `passed` is True.
    """

    passed: bool
    flagged: tuple[str, ...]


class Guardrails:
    """Deterministic content screening and redaction, independent of domain."""

    def screen_input(self, text: str) -> GuardrailResult:
        """Screen untrusted input text before it reaches the model or the
        gate. Fails closed: uncertain input must not pass.
        """
        raise NotImplementedError

    def redact_output(self, text: str) -> str:
        """Return `text` with secrets/PII removed, safe to surface or audit."""
        raise NotImplementedError
