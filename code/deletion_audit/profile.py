"""Day-0 tooling: understand the dataset, and calibrate planner conventions from sample_output.csv."""
from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from .io_utils import read_csv
from .planner import Convention
from .scoring import load_output


def profile_dataset(dataset: str | Path, max_enum: int = 15) -> str:
    ds = Path(dataset)
    out = [f"# Dataset profile: `{ds}`", ""]
    for csv_path in sorted(ds.glob("*.csv")):
        rows = read_csv(csv_path)
        out += [f"## {csv_path.name} ({len(rows)} rows)", ""]
        if not rows:
            out += ["(empty)", ""]
            continue
        out += ["| column | distinct | values / examples |", "| --- | --- | --- |"]
        for col in rows[0]:
            vals = Counter(r[col] for r in rows)
            if len(vals) <= max_enum:
                shown = ", ".join(f"`{v}`×{c}" for v, c in vals.most_common())
            else:
                shown = ", ".join(f"`{v[:40]}`" for v in list(vals)[:3]) + " …"
            out.append(f"| {col} | {len(vals)} | {shown} |")
        out.append("")

    ev = ds / "evidence"
    if ev.exists():
        files = [p for p in ev.rglob("*") if p.is_file()]
        out += [f"## evidence/ ({len(files)} files)", "",
                "By extension: " + ", ".join(f"`{e or '(none)'}`×{c}" for e, c in
                                            Counter(p.suffix.lower() for p in files).most_common()), ""]
        for sql in sorted(p for p in files if p.suffix.lower() in {".sql", ".db", ".sqlite"})[:5]:
            out += [f"### SQL snapshot `{sql.name}`", "", "```", _describe_sql(sql), "```", ""]
    return "\n".join(out)


def _describe_sql(path: Path) -> str:
    con = sqlite3.connect(":memory:")
    try:
        if path.suffix.lower() == ".sql":
            con.executescript(path.read_text(encoding="utf-8", errors="replace"))
        else:
            con.close()
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        lines = []
        for name, sql in con.execute("select name, sql from sqlite_master where type='table'"):
            n = con.execute(f'select count(*) from "{name}"').fetchone()[0]
            lines.append(f"{name} ({n} rows): {sql}")
        return "\n".join(lines) or "(no tables)"
    except sqlite3.Error as e:
        return f"(not loadable as sqlite: {e})"
    finally:
        con.close()


def _targets(steps, phase):
    return {(s["system_id"], s["resource_id"]) for s in steps if s["phase"] == phase}


def infer_convention(gold: dict) -> tuple[Convention, str]:
    """Derive Convention flags from labelled data and report the evidence behind each flag."""
    ops_by_status: dict[str, Counter] = defaultdict(Counter)
    ev_empty: Counter = Counter()
    clean_checks = present_checks = no_verify = both = 0
    n_incomplete = 0
    for status, steps in gold.values():
        for s in steps:
            ops_by_status[status][(s["phase"], s["operation"])] += 1
            ev_empty[(status, s["phase"], s["evidence_id"] == "")] += 1
        if status != "INCOMPLETE":
            continue
        n_incomplete += 1
        remediated = _targets(steps, "REMEDIATION")
        for s in steps:
            t = (s["system_id"], s["resource_id"])
            if s["phase"] == "VERIFICATION" and s["operation"] == "VERIFY_RECORD_PRESENT":
                present_checks += 1
            elif s["phase"] == "VERIFICATION" and t not in remediated:
                clean_checks += 1
        no_verify += len(remediated - _targets(steps, "VERIFICATION"))
        red = {(s["system_id"], s["resource_id"]) for s in steps if s["operation"] == "VERIFY_RECORD_REDACTED"}
        pres = {(s["system_id"], s["resource_id"]) for s in steps if s["operation"] == "VERIFY_RECORD_PRESENT"}
        both += len(red & pres)
    for status, steps in gold.values():
        if status == "COMPLETE":
            red = {(s["system_id"], s["resource_id"]) for s in steps if s["operation"] == "VERIFY_RECORD_REDACTED"}
            pres = {(s["system_id"], s["resource_id"]) for s in steps if s["operation"] == "VERIFY_RECORD_PRESENT"}
            both += len(red & pres)

    conv = Convention(verify_remediated=no_verify == 0, verify_retained_present=present_checks > 0,
                      verify_already_clean=clean_checks > 0, redact_also_verify_present=both > 0)
    rep = ["# Conventions inferred from labelled data", "",
           f"- INCOMPLETE cases: {n_incomplete}",
           f"- remediated targets WITHOUT a verification: {no_verify}  -> verify_remediated={conv.verify_remediated}",
           f"- VERIFY_RECORD_PRESENT in INCOMPLETE: {present_checks}  -> verify_retained_present={conv.verify_retained_present}",
           f"- verification of never-remediated targets in INCOMPLETE (excl. PRESENT): {clean_checks}"
           f"  -> verify_already_clean={conv.verify_already_clean}",
           f"- targets verified both REDACTED and PRESENT: {both}  -> redact_also_verify_present={conv.redact_also_verify_present}",
           "", "## Operation histogram by status", ""]
    for st, c in sorted(ops_by_status.items()):
        rep.append(f"**{st}**: " + ", ".join(f"{p}/{o}×{n}" for (p, o), n in sorted(c.items())))
    rep += ["", "## evidence_id empty? (status, phase, empty) -> count", ""]
    rep += [f"- {k}: {v}" for k, v in sorted(ev_empty.items())]
    return conv, "\n".join(rep) + "\n"


def conventions_from_file(path: str | Path) -> tuple[Convention, str]:
    return infer_convention(load_output(path))
