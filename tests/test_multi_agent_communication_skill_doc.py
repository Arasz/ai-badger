"""Doc-coverage tests for the multi-agent-communication skill's pi-native path.

The protocol (what to announce, message shape, ack-without-reply) is harness-neutral;
the transport is not: under pi the message-bus extension tool replaces the
send_message.py subprocess. These tests pin that SKILL.md states the pi path where
the agent reads, next to the python path — not recoverable from the scripts alone.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_DOC = ROOT / "features/common/skills/multi-agent-communication/SKILL.md"


def test_the_skill_doc_documents_pi_native_send():
    """The How-to-send section must name the pi-native transport: the message-bus
    tool (project broadcast) and the /messages command, with the python script
    kept as the non-pi path."""
    text = SKILL_DOC.read_text(encoding="utf-8")
    assert "message-bus" in text
    assert "/messages" in text


def test_the_skill_doc_keeps_ack_discipline_on_the_pi_path():
    """The ack-without-reply rule must visibly cover the pi path: acking through
    the extension tool, never replying to an ack, whatever the transport."""
    text = SKILL_DOC.read_text(encoding="utf-8")
    assert "ack:" in text
    assert "Never reply to an ack" in text
