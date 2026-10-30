# Token Usage and Cost Report

Final full-dataset run that produced `output.csv` (518 requests).

## Per model

| Provider | Model | Model calls | Input tokens | Output tokens | Total tokens | Est. cost |
| --- | --- | --- | --- | --- | --- | --- |
| Anthropic | claude-sonnet-5-5 | 0 | 0 | 0 | 0 | $0.0000 |

## Overall

- Model calls: **0** (cache hits not billed: 0)
- Input tokens: **0**  |  Output tokens: **0**  |  Total: **0**
- Average tokens per request: **0.0**
- Estimated total cost: **$0.0000**  |  per request: **$0.000000**

Prices come from `config/config.toml` `[pricing]` (USD per million tokens). No API keys or credentials are stored in this repository.

## How this run was produced

The final `output.csv` is produced by `python code/main.py`, a **deterministic engine**: identity resolution, evidence parsing (SQL, JSON, logs, text), state reconstruction, policy application and plan generation are ordinary code. It made **zero model calls**, so tokens and cost are zero and the usage ledger (`code/evaluation/ledger.jsonl`) is empty.

Model-assisted steps exist but are not part of the final run:

- `code/data/visual_facts.json` (facts read from 11 screenshots + 4 PDFs) was produced during development by Claude Code (`claude-sonnet-5-5`) viewing each file; `code/deletion_audit/visual.py` can regenerate it through the Anthropic API (cached, metered). Token counts for the development session are not available to the code and are therefore not reported here.
- The LLM wrapper (`llm.py`) caches by content hash and logs every call to the ledger; if `visual.py` is run, `python code/evaluation/main.py --report` reports the real per-model calls/tokens/cost (prices from `config/config.toml`).

No API keys or credentials are stored in this repository (`ANTHROPIC_API_KEY` is read from the environment only).