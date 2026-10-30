"""Optional: regenerate code/data/visual_facts.json with a vision-capable model (prompts/02).

The pipeline itself only reads the JSON, so a normal run needs no network and no tokens.

    ANTHROPIC_API_KEY=... python code/deletion_audit/visual.py --dataset dataset --out code/data/visual_facts.json
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parents[1]
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from deletion_audit.evidence import PREFIX_CATEGORY  # noqa: E402
from deletion_audit.llm import LLM  # noqa: E402

CATEGORIES = {c for _, c in PREFIX_CATEGORY} | {"SUPPORT_ATTACHMENT"}
STATES = {"FOUND", "NOT_FOUND", "IDENTIFIABLE", "REDACTED", "ANONYMIZED", "ACTIVE", "BLOCKED", "DISABLED"}
SYSTEM = (CODE_DIR / "prompts" / "02_evidence_extractor.md").read_text(encoding="utf-8").split("## System")[1].split("```")[1].strip()


def _prompt(file_id: str, captured_at: str, catalog_hints: list[str]) -> str:
    return (f"file_id: {file_id}\ncaptured_at (from the evidence manifest): {captured_at}\n"
            f"catalog_hints: {', '.join(catalog_hints) or 'none'}\n\n"
            'Return {"describes": "<one sentence>", "facts": [{"resource_id": ..., "category": ..., "state": ..., "keys": [...]}]} '
            "following the state guidance in the system prompt. JSON only.")


def parse_response(text: str, captured_at: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    data = json.loads(m.group(0) if m else text)
    facts = []
    for f in data.get("facts", []):
        if f.get("category") not in CATEGORIES or f.get("state") not in STATES or not f.get("resource_id"):
            continue                                   # drop anything outside the vocabulary
        facts.append({"t": captured_at, "resource_id": f["resource_id"], "category": f["category"],
                      "state": f["state"], "keys": [str(k) for k in f.get("keys", [])]})
    return {"describes": data.get("describes", ""), "facts": facts}


def extract(dataset: Path, out: Path, llm: LLM, model: str) -> dict:
    with open(dataset / "evidence_files.csv", newline="", encoding="utf-8-sig") as fh:
        manifest = list(csv.DictReader(fh))
    activity = Path(dataset / "system_activity.csv").read_text(encoding="utf-8")
    hints = sorted(set(re.findall(r"linked (\S+) \(", activity)) | set(re.findall(r"confirmed (\S+) \(", activity)))
    files = {}
    for m in manifest:
        p = dataset / m["file_path"]
        if p.suffix.lower() not in {".png", ".pdf"}:
            continue
        text = llm.complete(model=model, system=SYSTEM, prompt=_prompt(m["file_id"], m["captured_at"], hints),
                            attachments=[p], max_tokens=1200, tag="visual")
        files[m["file_id"]] = parse_response(text, m["captured_at"])
    doc = {"_provenance": {"what": "Facts read from screenshots/PDFs by a vision model.", "model": model,
                           "how": "deletion_audit/visual.py with prompts/02_evidence_extractor.md"}, "files": files}
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    return doc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=str(CODE_DIR.parent / "dataset"))
    ap.add_argument("--out", default=str(CODE_DIR / "data" / "visual_facts.json"))
    ap.add_argument("--model", default="claude-sonnet-5-5")
    ap.add_argument("--cache", default=str(CODE_DIR.parent / ".cache" / "llm"))
    ap.add_argument("--ledger", default=str(CODE_DIR / "evaluation" / "ledger.jsonl"))
    a = ap.parse_args(argv)
    doc = extract(Path(a.dataset), Path(a.out), LLM(a.cache, a.ledger), a.model)
    print(f"wrote {a.out}: {sum(len(v['facts']) for v in doc['files'].values())} facts from {len(doc['files'])} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
