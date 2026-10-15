#!/usr/bin/env python3
"""Stdio MCP server that brings the anki-gate rule to the Claude desktop chat.

Holds a minimal JSON-RPC loop, the server instructions that tell Claude to gate
every reply, and the one tool, `anki_gate_check`, which runs the hook's `gate`.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

from anki_gate import gate

SERVER_INFO = {"name": "anki-gate", "version": "0.1.0"}
INSTRUCTIONS = (
    "Before replying to any user message, call anki_gate_check. "
    "If it returns blocked, reply only with a one-line request to answer one Anki "
    "card and say when done, and do nothing else. When the user says they are done, "
    "call anki_gate_check again; once it allows, answer the message that was held "
    "back. If it reports that Anki is unreachable, mention it in one line and reply "
    "normally."
)
TOOL = {
    "name": "anki_gate_check",
    "description": (
        "Check whether the user has a message credit, earned one per Anki answer. "
        "Call it before every reply; reply normally only when it allows."
    ),
    "inputSchema": {"type": "object", "properties": {}},
}
MESSAGES = {
    "off": "allowed: the gate is off.",
    "credit": "allowed: {detail} messages left.",
    "nothing_due": "allowed: no cards are due.",
    "unreachable": "allowed: Anki is unreachable ({detail}).",
    "blocked": "blocked: {detail} cards are due and no credits are left. Anki was brought forward.",
}


def _handle(request):
    """Answer one JSON-RPC request.

    Args:
        request: A decoded JSON-RPC message.

    Returns:
        The `result` object, or None for notifications, which get no reply.

    Raises:
        LookupError: When the method is not one this server implements.
    """
    method = request.get("method")
    if method == "initialize":
        return {
            "protocolVersion": request["params"]["protocolVersion"],
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
            "instructions": INSTRUCTIONS,
        }
    if method == "tools/list":
        return {"tools": [TOOL]}
    if method == "tools/call":
        if request["params"]["name"] != TOOL["name"]:
            raise LookupError(request["params"]["name"])
        status, detail = gate()
        return {"content": [{"type": "text", "text": MESSAGES[status].format(detail=detail)}]}
    if method == "ping":
        return {}
    if "id" not in request:
        return None
    raise LookupError(method)


def main():
    """Read JSON-RPC messages from stdin, one per line, and write replies to stdout."""
    for line in sys.stdin:
        if not line.strip():
            continue
        request = json.loads(line)
        try:
            result = _handle(request)
        except LookupError as error:
            reply = {"error": {"code": -32601, "message": f"Unknown: {error}"}}
        else:
            if result is None or "id" not in request:
                continue
            reply = {"result": result}
        print(json.dumps({"jsonrpc": "2.0", "id": request.get("id"), **reply}), flush=True)


if __name__ == "__main__":
    main()
