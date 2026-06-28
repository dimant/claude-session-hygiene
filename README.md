# session-hygiene-hook

A tiny [Claude Code](https://claude.com/claude-code) **Stop hook** that nudges you to
`/clear` or `/compact` when your session has grown large enough that every additional turn
is quietly burning money.

No dependencies. One Python file. Shows a message to *you* — never to the model.

---

## The problem it solves

In a long Claude Code session, the model re-reads the **entire conversation history on every
turn**. That history is cached (cheap per token), but it grows roughly linearly with turn
count — so the cost of each *new* turn climbs as the session ages, even though the work isn't
getting more valuable.

Measured over six weeks of real usage on one heavy project:

| Turn position in session | Avg context re-read | Avg cost / turn |
|---|---|---|
| turns 1–25 | 67K tokens | **$0.12** |
| turns 101–200 | 306K | $0.21 |
| turns 201–400 | 490K | $0.33 |
| turns 401–800 | 739K | **$0.45** |

A turn at position ~500 cost **~3.6× a turn at position ~10** — same model, same kind of
work, just dragging a bigger prefix. In that dataset, **turns past #200 were ~half the
project's entire bill**, and a handful of marathon sessions (≥200 turns, context approaching
the 1M window) dominated spend.

The fix is cheap and boring: **start a fresh session or compact before the context bloats.**
The hard part is *remembering* to. This hook remembers for you.

---

## What it does

On every `Stop` event (i.e. after each Claude response), the hook:

1. reads the current session transcript (Claude Code passes its path on stdin),
2. measures the **current context size** from the most recent turn,
3. if context ≥ a threshold (default **300K tokens**), prints a one-line nudge to you:

   > ⚠ session hygiene: context ~530K tokens — each further turn re-reads this context
   > (~$0.27/turn). Consider /clear or /compact to reset the context tax. (session ~$52 so far)

Below the threshold it prints nothing. After you `/compact` (or `/clear`), context drops and
**the nudge goes quiet on its own** — no snooze logic, no state to manage.

It uses *current* context, not raw turn count, because context is what actually drives
per-turn cost — and it naturally resets after a compaction, where a turn counter wouldn't.

---

## Install

Requires `python3` (3.8+). Clone anywhere, e.g.:

```sh
git clone <this-repo> ~/src/session-hygiene-hook
```

Add a `Stop` hook to your Claude Code settings — `~/.claude/settings.json` for all projects,
or `.claude/settings.json` for one project. Merge this into the existing JSON (don't replace
the whole file):

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          { "type": "command",
            "command": "python3 ~/src/session-hygiene-hook/hygiene_hook.py" }
        ]
      }
    ]
  }
}
```

Open `/hooks` in a Claude Code session once (it reloads hook config) or restart, then verify
it's registered there. The nudge appears in the UI after a turn once your context crosses the
threshold.

---

## Configuration

Tune via environment variables (or flags appended to the command):

| Env var | Flag | Default | Meaning |
|---|---|---|---|
| `HYGIENE_WARN_CONTEXT` | `--warn-context N` | `300000` | warn at this many context tokens |
| `HYGIENE_WARN_TURNS` | `--warn-turns N` | `0` (off) | also warn at this many turns |

Example — warn earlier, at 250K:

```json
{ "type": "command",
  "command": "python3 ~/src/session-hygiene-hook/hygiene_hook.py --warn-context 250000" }
```

---

## Try it without wiring a hook

Point it at any existing transcript `.jsonl`:

```sh
python3 hygiene_hook.py --transcript ~/.claude/projects/<encoded-path>/<session>.jsonl
# prints a {"systemMessage": ...} line if that session ended large; silent otherwise
```

Or simulate the hook event:

```sh
echo '{"transcript_path":"/path/to/session.jsonl"}' | python3 hygiene_hook.py
```

---

## How it works (internals)

- **Stop hook** fires after each assistant response, so it tracks context in real time.
- Claude Code sends the hook a JSON event on stdin including `transcript_path` and
  `session_id`; the script reads `transcript_path`.
- It scans the transcript's `assistant` records (deduped by `requestId`, skipping
  sub-agent/sidechain turns and synthetic messages) and takes the **last** turn's
  `input_tokens + cache_creation + cache_read` as the current context size.
- To surface a message to the user without feeding it to the model, the hook emits
  `{"systemMessage": "..."}` on stdout and exits 0 — Claude Code's documented user-facing
  output channel for hooks.

## Caveats

- The `Stop` event, the `transcript_path` stdin field, and the `systemMessage` output field
  are standard Claude Code hook behavior, but exact hook handling has shifted across
  versions. If the nudge never appears, check `/hooks` to confirm it's registered and firing,
  or run `claude --debug` to see hook execution logs.
- The per-turn `$` figure is an estimate (Opus cache-read rate); treat it as an order of
  magnitude, not a bill.

## Origin

Extracted from a `claude-cost` usage analysis whose headline finding was that a few marathon
sessions, each paying a linearly growing context tax, drove the majority of spend. This hook
is the preventive half of that analysis.

## License

MIT — see [LICENSE](LICENSE).
