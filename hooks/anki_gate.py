#!/usr/bin/env python3
"""UserPromptSubmit hook for Claude Code that gates each prompt behind Anki answers.

Holds the AnkiConnect client, the state file (message credits, the time answers
were last counted, and the off switch), the `/anki-gate:<action>` command handler, and the
entry point Claude Code runs on every prompt.
"""

import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ANKI_URL = os.environ.get("ANKI_GATE_URL", "http://127.0.0.1:8765")
DUE_QUERY = os.environ.get("ANKI_GATE_DUE_QUERY", "is:due -is:suspended -is:buried")
STATE_DIR = Path(
    os.environ.get("CLAUDE_PLUGIN_DATA") or Path.home() / ".claude" / "anki-gate"
)
STATE_FILE = STATE_DIR / "state.json"
# Each action is its own plugin command, `/anki-gate:<action>`.
COMMAND = "/anki-gate:"
DAY_MS = 86_400_000
UNITS_MS = {"m": 60_000, "h": 3_600_000, "d": DAY_MS}


class AnkiError(Exception):
    """Signal that AnkiConnect was unreachable or answered with an error."""


def _anki(action, **params):
    """Call one AnkiConnect action.

    Args:
        action: AnkiConnect action name, such as `findCards`.
        **params: The action's parameters, sent as JSON.

    Returns:
        The action's `result` value.

    Raises:
        AnkiError: When Anki does not answer within 3 seconds, or reports an error.
    """
    body = json.dumps({"action": action, "version": 6, "params": params}).encode()
    try:
        with urllib.request.urlopen(ANKI_URL, body, timeout=3) as response:
            reply = json.load(response)
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise AnkiError(str(error)) from error
    if reply.get("error"):
        raise AnkiError(reply["error"])
    return reply["result"]


def _load_state():
    """Read the state file.

    Reads a file from before credits existed as zero credits counted from its
    `last_pass_ms`.

    Returns:
        A dict with `counted_ms`, `credits` and `off_until`. `off_until` is None
        when the gate is on, and -1 when it is off with no end.
    """
    try:
        saved = json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        saved = {}
    return {
        "counted_ms": saved.get("counted_ms", saved.get("last_pass_ms", 0)),
        "credits": saved.get("credits", 0),
        "off_until": saved.get("off_until"),
    }


def _save_state(state):
    """Write `state` to the state file.

    Args:
        state: A dict shaped like the one `_load_state` returns.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state))


def _is_off(state, now_ms):
    """Check whether the off switch holds at `now_ms`.

    Args:
        state: A dict shaped like the one `_load_state` returns.
        now_ms: Epoch milliseconds.

    Returns:
        True when the gate is off for good, or paused past `now_ms`.
    """
    off_until = state["off_until"]
    return off_until == -1 or (off_until is not None and off_until > now_ms)


def _new_answers(since_ms, now_ms):
    """Find the answers given after `since_ms`.

    Searches only the cards rated in the days that span `since_ms` to `now_ms`
    (today alone when `since_ms` is 0), and skips manual reschedules (ease 0).

    Args:
        since_ms: Epoch milliseconds; 0 when answers were never counted.
        now_ms: Epoch milliseconds.

    Returns:
        A tuple `(count, newest_ms)`: how many answers there are, and the time of
        the newest one, or `since_ms` when there are none.
    """
    days = 1 if since_ms == 0 else min(365, math.ceil((now_ms - since_ms) / DAY_MS) + 1)
    cards = _anki("findCards", query=f"rated:{days}")
    if not cards:
        return 0, since_ms
    reviews = _anki("getReviewsOfCards", cards=cards)
    times = [
        review["id"]
        for card_reviews in reviews.values()
        for review in card_reviews
        if review["id"] > since_ms and review["ease"] > 0
    ]
    return len(times), max(times, default=since_ms)


def gate():
    """Decide whether the next message may go through, spending a credit if so.

    Turns every answer given since the last count into one credit, then spends
    one. With no credit left, lets the message through only when nothing is due;
    otherwise brings Anki to the front on macOS and blocks it.

    Returns:
        A tuple `(status, detail)`. `status` is "off", "credit", "nothing_due",
        "unreachable" or "blocked". `detail` is the credits left for "credit",
        the error text for "unreachable", the due count for "blocked", and None
        otherwise.
    """
    now_ms = int(time.time() * 1000)
    state = _load_state()
    if _is_off(state, now_ms):
        return "off", None
    try:
        count, state["counted_ms"] = _new_answers(state["counted_ms"], now_ms)
        state["credits"] += count
        if state["credits"] == 0:
            due = _anki("findCards", query=DUE_QUERY)
    except AnkiError as error:
        return "unreachable", str(error)
    if state["credits"] > 0:
        state["credits"] -= 1
        _save_state(state)
        return "credit", state["credits"]
    _save_state(state)
    if not due:
        return "nothing_due", None
    if sys.platform == "darwin":
        subprocess.run(["open", "-a", "Anki"], check=False, capture_output=True)
    return "blocked", len(due)


def run_command(args):
    """Carry out an `/anki-gate:<action>` command.

    Accepts `on`, `off`, `pause <n><m|h|d>` and `status`; anything else returns
    the usage line.

    Args:
        args: The action, then the words typed after the command.

    Returns:
        The line to show the user.
    """
    now_ms = int(time.time() * 1000)
    state = _load_state()
    action = args[0] if args else "status"
    if action == "on":
        state["off_until"] = None
    elif action == "off":
        state["off_until"] = -1
    elif action == "pause" and len(args) == 2 and (match := re.fullmatch(r"(\d+)([mhd])", args[1])):
        state["off_until"] = now_ms + int(match[1]) * UNITS_MS[match[2]]
    elif action != "status":
        return "anki-gate: use /anki-gate:on, /anki-gate:off, /anki-gate:pause <30m|2h|1d> or /anki-gate:status"
    if action != "status":
        _save_state(state)

    if state["off_until"] == -1:
        switch = "off"
    elif _is_off(state, now_ms):
        switch = "paused until " + time.strftime("%H:%M", time.localtime(state["off_until"] / 1000))
    else:
        switch = "on"
    return f"anki-gate: {switch}. Credits banked: {state['credits']}."


def _emit(payload):
    """Print `payload` as the hook's JSON output and exit 0.

    Args:
        payload: Hook output fields, such as `decision` or `systemMessage`.
    """
    print(json.dumps(payload))
    sys.exit(0)


def main():
    """Handle `/anki-gate:<action>`, or let the prompt through or block it per `gate`.

    Runs `/anki-gate:<action>` here and blocks it, so the command never reaches the model.
    Lets other prompts through with the credits left shown, or with a warning
    when Anki can't be reached.
    """
    try:
        prompt = json.load(sys.stdin).get("prompt", "")
    except ValueError:
        prompt = ""
    words = prompt.split()
    if words and words[0].startswith(COMMAND):
        _emit({"decision": "block", "reason": run_command([words[0].removeprefix(COMMAND), *words[1:]])})

    status, detail = gate()
    if status == "credit":
        _emit({"systemMessage": f"anki-gate: {detail} messages left."})
    if status == "unreachable":
        _emit({"systemMessage": f"anki-gate: could not reach Anki ({detail}). Prompt let through."})
    if status != "blocked":
        return
    _emit({
        "decision": "block",
        "reason": "anki-gate: answer Anki cards, then send the prompt again. Each answer lets one message through.",
    })


if __name__ == "__main__":
    main()
