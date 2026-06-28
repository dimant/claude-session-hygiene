#!/usr/bin/env python3
"""
statusline.py — a Claude Code statusLine command that shows live context usage.

Renders a compact, always-visible readout in the status bar, e.g.

    vibeos · opus-4-8 · ctx 530K (53%) · $52

reusing the same transcript measurement as hygiene_hook.py. The status bar turns
yellow past 50% of the context window and red past 75%, so context bloat is
visible before the Stop-hook nudge fires.

Claude Code passes a JSON object on stdin (includes `transcript_path`, `cwd`,
`model`, and often a `cost` object). This script prints one line of text.

No dependencies. Python 3.8+.
"""
from __future__ import annotations
import json, os, sys

INPUT_RATE = {"opus": 5e-6, "sonnet": 3e-6, "haiku": 1e-6}     # per input token
WINDOW = {"opus": 1_000_000, "sonnet": 1_000_000, "haiku": 200_000}


def family(model: str) -> str:
    for fam in INPUT_RATE:
        if fam in (model or ""):
            return fam
    return "opus"


def measure(transcript_path: str):
    """Return (turns, current_context_tokens, cost_estimate, last_model)."""
    seen = set()
    turns = ctx = 0
    cost = 0.0
    last_model = ""
    try:
        fh = open(transcript_path, errors="replace")
    except OSError:
        return 0, 0, 0.0, ""
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
            last_model = model or last_model
            cc = u.get("cache_creation", {}) or {}
            w5 = cc.get("ephemeral_5m_input_tokens", 0) or 0
            w1 = cc.get("ephemeral_1h_input_tokens", 0) or 0
            flat = u.get("cache_creation_input_tokens", 0) or 0
            if not (w5 or w1) and flat:
                w5 = flat
            rd = u.get("cache_read_input_tokens", 0) or 0
            it = u.get("input_tokens", 0) or 0
            ot = u.get("output_tokens", 0) or 0
            ctx = it + w5 + w1 + rd
            r = INPUT_RATE[family(model)]
            cost += it*r + w5*r*1.25 + w1*r*2.0 + rd*r*0.10 + ot*(r*5)
    return turns, ctx, cost, last_model


def human(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1000:.0f}K"
    return str(n)


def color_for(pct: float) -> str:
    if os.environ.get("NO_COLOR"):
        return ""
    if pct >= 90:
        return "\x1b[1;31m"   # bold red
    if pct >= 75:
        return "\x1b[31m"     # red
    if pct >= 50:
        return "\x1b[33m"     # yellow
    return "\x1b[32m"         # green


def main():
    data = {}
    if not sys.stdin.isatty():
        try:
            data = json.load(sys.stdin) or {}
        except (ValueError, OSError):
            data = {}

    transcript = data.get("transcript_path")
    # model id can arrive as a string or {"id": ..., "display_name": ...}
    model_field = data.get("model")
    model_id = model_field.get("id") if isinstance(model_field, dict) else (model_field or "")
    cwd = data.get("cwd") or (data.get("workspace") or {}).get("current_dir") or os.getcwd()

    turns = ctx = 0
    cost_est = 0.0
    last_model = ""
    if transcript and os.path.isfile(transcript):
        turns, ctx, cost_est, last_model = measure(transcript)

    model_id = model_id or last_model
    fam = family(model_id)
    window = WINDOW[fam]
    pct = (ctx / window * 100) if window else 0.0

    # prefer the host-provided authoritative cost if present
    cost = ((data.get("cost") or {}).get("total_cost_usd"))
    if cost is None:
        cost = cost_est

    project = os.path.basename(cwd.rstrip("/")) or cwd
    model_short = model_id.replace("claude-", "") if model_id else "?"
    c, reset = color_for(pct), ("" if os.environ.get("NO_COLOR") else "\x1b[0m")

    parts = [project, model_short, f"{c}ctx {human(ctx)} ({pct:.0f}%){reset}"]
    if cost:
        parts.append(f"${cost:.0f}")
    print(" · ".join(parts))


if __name__ == "__main__":
    main()
