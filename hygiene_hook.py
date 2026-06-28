#!/usr/bin/env python3
"""
session-hygiene-hook — a Claude Code Stop hook that nudges you to /clear or
/compact when the current session's context has grown large enough that every
further turn pays a meaningful "context tax".

It reads the hook event JSON on stdin (uses `transcript_path`), measures the
*current* context size from the most recent assistant turn, and — only when that
exceeds a threshold — prints a `{"systemMessage": "..."}` object on stdout
(exit 0). Claude Code shows that message to you in the UI; it is NOT sent to the
model. Below the threshold it prints nothing.

Config via env vars (or flags):
  HYGIENE_WARN_CONTEXT  warn at this many context tokens   (default 300000)
  HYGIENE_WARN_TURNS    also warn at this many turns; 0=off (default 0)

No dependencies. Python 3.8+.
"""
from __future__ import annotations
import json, os, sys

READ_MULT = 0.10  # cache-read is ~0.1x input price; drives the per-turn estimate
INPUT_RATE = {"opus": 5e-6, "sonnet": 3e-6, "haiku": 1e-6}  # per input token, by family


def input_rate(model: str) -> float:
    for fam, rate in INPUT_RATE.items():
        if fam in (model or ""):
            return rate
    return INPUT_RATE["opus"]  # safe default = priciest tier


def measure(transcript_path: str):
    """Return (turns, current_context_tokens, session_cost_estimate)."""
    seen = set()
    turns = last_ctx = 0
    cost = 0.0
    try:
        fh = open(transcript_path, errors="replace")
    except OSError:
        return 0, 0, 0.0
    with fh:
        for line in fh:
            if '"type":"assistant"' not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") != "assistant" or d.get("isSidechain"):
                continue
            m = d.get("message", {}) or {}
            rid = d.get("requestId") or m.get("id")
            u = m.get("usage")
            model = m.get("model", "")
            if not rid or rid in seen or not u or model == "<synthetic>":
                continue
            seen.add(rid)
            turns += 1
            cc = u.get("cache_creation", {}) or {}
            w5 = cc.get("ephemeral_5m_input_tokens", 0) or 0
            w1 = cc.get("ephemeral_1h_input_tokens", 0) or 0
            flat = u.get("cache_creation_input_tokens", 0) or 0
            if not (w5 or w1) and flat:
                w5 = flat
            rd = u.get("cache_read_input_tokens", 0) or 0
            it = u.get("input_tokens", 0) or 0
            ot = u.get("output_tokens", 0) or 0
            last_ctx = it + w5 + w1 + rd       # tokens this turn re-read = current context
            r = input_rate(model)
            cost += it*r + w5*r*1.25 + w1*r*2.0 + rd*r*READ_MULT + ot*(r*5)
    return turns, last_ctx, cost


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    warn_ctx = int(os.environ.get("HYGIENE_WARN_CONTEXT", "300000"))
    warn_turns = int(os.environ.get("HYGIENE_WARN_TURNS", "0"))
    transcript = None
    it = iter(argv)
    for a in it:
        if a == "--warn-context":
            warn_ctx = int(next(it))
        elif a == "--warn-turns":
            warn_turns = int(next(it))
        elif a == "--transcript":
            transcript = next(it)

    if transcript is None and not sys.stdin.isatty():
        try:
            transcript = (json.load(sys.stdin) or {}).get("transcript_path")
        except (ValueError, OSError):
            transcript = None
    if not transcript or not os.path.isfile(transcript):
        return 0

    turns, ctx, cost = measure(transcript)
    over_ctx = ctx >= warn_ctx
    over_turns = bool(warn_turns) and turns >= warn_turns
    if not (over_ctx or over_turns):
        return 0

    bits = []
    if over_ctx:
        bits.append(f"context ~{ctx/1000:.0f}K tokens")
    if over_turns:
        bits.append(f"{turns} turns")
    per_turn = ctx * input_rate("opus") * READ_MULT
    msg = (f"⚠ session hygiene: {', '.join(bits)} — each further turn re-reads this "
           f"context (~${per_turn:.2f}/turn). Consider /clear or /compact to reset the "
           f"context tax. (session ~${cost:.0f} so far)")
    print(json.dumps({"systemMessage": msg}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
