"""Local scorer that mirrors the metrics the statement says the grader considers.

Gold = sample_output.csv (or any hand-labelled file with the same shape).
Metrics: case status accuracy, step-level P/R/F1, field-level accuracy on matched steps,
sequence accuracy (exact array order + LCS ratio).
"""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

FIELDS = ("step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id")
STEP_ID = ("phase", "operation", "system_id", "resource_id")


def load_output(path: str | Path) -> dict[str, tuple[str, list[dict]]]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return {r["case_id"]: (r["deletion_status"], json.loads(r["steps_json"] or "[]"))
                for r in csv.DictReader(fh)}


def _sid(s: dict) -> tuple:
    return tuple(s[k] for k in STEP_ID)


def _lcs(a: list, b: list) -> int:
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b, start=1):
            cur.append(prev[j - 1] + 1 if x == y else max(prev[j], cur[-1]))
        prev = cur
    return prev[-1]


def score(pred: dict, gold: dict) -> dict:
    n = len(gold)
    status_ok = 0
    tp = fp = fn = 0
    field_ok: Counter = Counter()
    field_tot = 0
    seq_exact = 0
    row_exact = 0
    lcs_num = lcs_den = 0
    by_status = defaultdict(lambda: [0, 0])      # gold status -> [correct, total]
    confusion: Counter = Counter()
    failures: list[dict] = []

    for cid, (gstatus, gsteps) in gold.items():
        pstatus, psteps = pred.get(cid, ("<MISSING>", []))
        ok = pstatus == gstatus
        status_ok += ok
        by_status[gstatus][0] += ok
        by_status[gstatus][1] += 1
        confusion[(gstatus, pstatus)] += 1

        gc, pc = Counter(map(_sid, gsteps)), Counter(map(_sid, psteps))
        common = gc & pc
        t = sum(common.values())
        tp += t
        fp += sum(pc.values()) - t
        fn += sum(gc.values()) - t

        gmap = {_sid(s): s for s in gsteps}
        for s in psteps:
            g = gmap.get(_sid(s))
            if g is None:
                continue
            field_tot += 1
            for f in FIELDS:
                field_ok[f] += s.get(f) == g.get(f)

        gseq, pseq = [_sid(s) for s in gsteps], [_sid(s) for s in psteps]
        row_exact += ok and [{k: s.get(k) for k in FIELDS} for s in gsteps] == [{k: s.get(k) for k in FIELDS} for s in psteps]
        seq_exact += gseq == pseq
        lcs_num += _lcs(gseq, pseq)
        lcs_den += max(len(gseq), len(pseq))

        if not ok or gseq != pseq or [s.get("evidence_id") for s in gsteps] != [s.get("evidence_id") for s in psteps]:
            failures.append({"case_id": cid, "gold_status": gstatus, "pred_status": pstatus,
                             "missing": sorted((gc - pc).elements())[:6],
                             "extra": sorted((pc - gc).elements())[:6]})

    prec = tp / (tp + fp) if tp + fp else 1.0
    rec = tp / (tp + fn) if tp + fn else 1.0
    return {
        "cases": n,
        "status_accuracy": status_ok / n if n else 0.0,
        "status_by_gold": {k: {"correct": v[0], "total": v[1]} for k, v in by_status.items()},
        "status_confusion": {f"{g}->{p}": c for (g, p), c in sorted(confusion.items())},
        "step_precision": prec, "step_recall": rec,
        "step_f1": 2 * prec * rec / (prec + rec) if prec + rec else 0.0,
        "field_accuracy": {f: (field_ok[f] / field_tot if field_tot else 0.0) for f in FIELDS},
        "matched_steps": field_tot,
        "row_exact_match": row_exact / n if n else 0.0,
        "sequence_exact_match": seq_exact / n if n else 0.0,
        "sequence_lcs_ratio": lcs_num / lcs_den if lcs_den else 1.0,
        "failures": failures,
    }


def render_markdown(m: dict, title: str = "Results") -> str:
    pct = lambda x: f"{100 * x:.2f}%"
    out = [f"### {title}", "", f"- Cases: **{m['cases']}**",
           f"- Case-level status accuracy: **{pct(m['status_accuracy'])}**"]
    for k, v in sorted(m["status_by_gold"].items()):
        out.append(f"  - gold `{k}`: {v['correct']}/{v['total']}")
    out += [f"- Step-level precision / recall / F1: **{pct(m['step_precision'])} / "
            f"{pct(m['step_recall'])} / {pct(m['step_f1'])}**",
            f"- Row accuracy (status and every step field identical): **{pct(m['row_exact_match'])}**",
           f"- Sequence accuracy: exact-array match **{pct(m['sequence_exact_match'])}**, "
            f"LCS ratio **{pct(m['sequence_lcs_ratio'])}**",
            f"- Field-level accuracy (over {m['matched_steps']} matched steps):", ""]
    out += ["| field | accuracy |", "| --- | --- |"]
    out += [f"| {f} | {pct(a)} |" for f, a in m["field_accuracy"].items()]
    if m["failures"]:
        out += ["", f"Mismatching cases: {len(m['failures'])} (first 10)", ""]
        for f in m["failures"][:10]:
            out.append(f"- `{f['case_id']}` gold={f['gold_status']} pred={f['pred_status']} "
                       f"missing={f['missing']} extra={f['extra']}")
    return "\n".join(out) + "\n"
