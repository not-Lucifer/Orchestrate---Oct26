"""Build evaluation/usage_report.md from the LLM ledger."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path


def build_usage_report(ledger: str | Path, n_requests: int, prices: dict[str, dict[str, float]],
                       provider: str = "Anthropic", configured_models: tuple[str, ...] = (), notes: str = "") -> str:
    """prices: {model: {"input_per_mtok": x, "output_per_mtok": y}} in USD. Must be set by the team."""
    per = defaultdict(lambda: {"calls": 0, "hits": 0, "in": 0, "out": 0})
    p = Path(ledger)
    for line in (p.read_text(encoding="utf-8").splitlines() if p.exists() else []):
        e = json.loads(line)
        m = per[e["model"]]
        if e["cache_hit"]:
            m["hits"] += 1
            continue
        m["calls"] += 1
        m["in"] += e["input_tokens"]
        m["out"] += e["output_tokens"]

    for m in configured_models:                  # models that were available but never called still get a row
        per[m]
    missing = [m for m in per if m not in prices and per[m]["calls"]]
    if missing:
        raise ValueError(f"no price configured for {missing}; fill [pricing] in config/config.toml "
                         f"from the provider's current price list")

    rows, tot_calls, tot_in, tot_out, tot_cost = [], 0, 0, 0, 0.0
    for model, m in sorted(per.items()):
        pr = prices.get(model, {"input_per_mtok": 0.0, "output_per_mtok": 0.0})
        cost = m["in"] / 1e6 * pr["input_per_mtok"] + m["out"] / 1e6 * pr["output_per_mtok"]
        rows.append(f"| {provider} | {model} | {m['calls']} | {m['in']:,} | {m['out']:,} | "
                    f"{m['in'] + m['out']:,} | ${cost:.4f} |")
        tot_calls += m["calls"]; tot_in += m["in"]; tot_out += m["out"]; tot_cost += cost

    n = max(n_requests, 1)
    return "\n".join([
        "# Token Usage and Cost Report", "",
        f"Final full-dataset run that produced `output.csv` ({n_requests} requests).", "",
        "## Per model", "",
        "| Provider | Model | Model calls | Input tokens | Output tokens | Total tokens | Est. cost |",
        "| --- | --- | --- | --- | --- | --- | --- |", *rows, "",
        "## Overall", "",
        f"- Model calls: **{tot_calls:,}** (cache hits not billed: {sum(m['hits'] for m in per.values()):,})",
        f"- Input tokens: **{tot_in:,}**  |  Output tokens: **{tot_out:,}**  |  Total: **{tot_in + tot_out:,}**",
        f"- Average tokens per request: **{(tot_in + tot_out) / n:,.1f}**",
        f"- Estimated total cost: **${tot_cost:.4f}**  |  per request: **${tot_cost / n:.6f}**", "",
        "Prices come from `config/config.toml` `[pricing]` (USD per million tokens). "
        "No API keys or credentials are stored in this repository.", "", notes])
