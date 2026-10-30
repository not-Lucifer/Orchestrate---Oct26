"""Cached, metered LLM wrapper (Anthropic). Every call is written to a JSONL ledger.

Design goals (token efficiency is explicitly rewarded):
  * content-addressed disk cache -> an evidence file or request text is paid for once
  * ledger of every call (cache hits included, with 0 billed tokens) -> usage_report.md
  * the SDK is imported lazily so the deterministic parts run with zero dependencies

For the FINAL run that produces output.csv use a fresh cache dir and a fresh ledger, otherwise
usage_report.md would under-report what that run actually cost.
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
from pathlib import Path

_MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
          ".gif": "image/gif", ".webp": "image/webp"}


def _attachment_block(path: Path) -> dict:
    data = base64.standard_b64encode(path.read_bytes()).decode()
    ext = path.suffix.lower()
    if ext == ".pdf":
        return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}}
    if ext in _MEDIA:
        return {"type": "image", "source": {"type": "base64", "media_type": _MEDIA[ext], "data": data}}
    raise ValueError(f"unsupported attachment type: {path}")


class LLM:
    def __init__(self, cache_dir: str | Path = ".cache/llm", ledger: str | Path = "evaluation/ledger.jsonl",
                 client=None):
        self.cache_dir = Path(cache_dir)
        self.ledger = Path(ledger)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import anthropic                      # reads ANTHROPIC_API_KEY from the environment
            self._client = anthropic.Anthropic()
        return self._client

    def complete(self, *, model: str, system: str, prompt: str, attachments: list[str | Path] | None = None,
                 max_tokens: int = 1024, tag: str = "") -> str:
        paths = [Path(p) for p in attachments or []]
        key = hashlib.sha256(json.dumps(
            [model, system, prompt, max_tokens, [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]],
        ).encode()).hexdigest()
        cached = self.cache_dir / f"{key}.json"
        if cached.exists():
            hit = json.loads(cached.read_text(encoding="utf-8"))
            self._log(model, tag, 0, 0, True, 0.0)
            return hit["text"]

        content = [_attachment_block(p) for p in paths] + [{"type": "text", "text": prompt}]
        t0 = time.time()
        resp = self.client.messages.create(
            model=model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": content}])
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        cached.write_text(json.dumps({"text": text, "usage": [resp.usage.input_tokens, resp.usage.output_tokens]}),
                          encoding="utf-8")
        self._log(model, tag, resp.usage.input_tokens, resp.usage.output_tokens, False, time.time() - t0)
        return text

    def _log(self, model, tag, tin, tout, hit, secs):
        with open(self.ledger, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": time.time(), "model": model, "tag": tag, "input_tokens": tin,
                                 "output_tokens": tout, "cache_hit": hit, "seconds": round(secs, 3)}) + "\n")
