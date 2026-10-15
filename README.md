# anki-gate

A Claude Code plugin that holds back each prompt until you answer an Anki flashcard.

## How it works

Each Anki answer earns one message credit. On every prompt, a `UserPromptSubmit` hook asks AnkiConnect for the answers given since it last counted, banks them as credits, and spends one. Answer three cards and the next three prompts go through without a stop.

| Situation | What happens to the prompt |
| --- | --- |
| A credit is banked | Goes through, and the credits left are shown |
| No credit and cards are due | Blocked, and on macOS Anki comes to the front |
| No credit and nothing is due | Goes through |
| Anki is closed, or AnkiConnect doesn't answer | Goes through with a warning |
| The gate is off or paused | Goes through |

## Turning the gate off

`/anki-gate` switches the gate without restarting Claude Code. The hook runs it and answers on the spot, so it never reaches the model and is never blocked.

| Command | What it does |
| --- | --- |
| `/anki-gate off` | Turns the gate off until `/anki-gate on` |
| `/anki-gate pause 2h` | Turns the gate off for `30m`, `2h`, `1d` or any other length in m, h or d |
| `/anki-gate on` | Turns the gate back on |
| `/anki-gate status` | Shows whether the gate is on and how many credits are banked |

The switch lives in the state file, so it holds for every session at once. Answers given while the gate is off still count once it is back on.

This covers Claude Code in the terminal, in the IDEs, and in the **Code** tab of the Claude desktop app. It doesn't cover the desktop app's chat tab or claude.ai, because neither runs hooks.

## Requirements

- Anki running with the AnkiConnect add-on on `127.0.0.1:8765`
- `python3` on `PATH`

## Install

```sh
claude plugin marketplace add "<path to this folder>"
claude plugin install anki-gate@anki-gate
```

To remove the plugin itself, run `/plugin` and disable `anki-gate`; that takes effect in the next session.

## Settings

Set these environment variables, for example under `env` in `~/.claude/settings.json`:

| Variable | Default | Meaning |
| --- | --- | --- |
| `ANKI_GATE_URL` | `http://127.0.0.1:8765` | Where AnkiConnect listens |
| `ANKI_GATE_DUE_QUERY` | `is:due -is:suspended -is:buried` | Search that decides whether anything is due |

## Claude desktop chat

The chat tab doesn't run hooks, so `mcp/anki_gate_mcp.py` brings the same rule there as an MCP server. Its server instructions tell Claude to call `anki_gate_check` before every reply, and to answer only when the check allows it. This relies on Claude following the instructions, so it isn't enforced the way the hook is.

1. Add the server under `mcpServers` in `~/Library/Application Support/Claude/claude_desktop_config.json`:

   ```json
   "anki-gate": {
     "command": "/opt/homebrew/bin/python3",
     "args": ["<path to this folder>/mcp/anki_gate_mcp.py"],
     "env": { "CLAUDE_PLUGIN_DATA": "<home>/.claude/plugins/data/anki-gate-anki-gate" }
   }
   ```

2. Restart the app.

`CLAUDE_PLUGIN_DATA` points at the installed plugin's data folder, so the hook and the chat share one state: one bank of credits and one switch, wherever a message is sent.
