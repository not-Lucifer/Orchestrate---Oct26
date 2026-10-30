"""RealAssessor: request row -> CaseAssessment (the seam consumed by planner.py).

Reasoning model (all derived from participant-visible files; no labels):

  intent     request_text authorises deletion?                                   intent.py
  identity   request email -> person -> every historical email/phone/hash          identity.py
  anchor     the latest evidence file captured <= audit_at that mentions the        (this file)
             person. It is the case's source of truth: the resource states are
             read from it and findings/verifications cite it.
  linking    which resources belong to the person?
               1. records whose identifiers (email/phone/hash/user_id) match      fact
               2. data-catalog link events                                        catalog
               3. identifier-free records (404 accounts, anonymised analytics)    activity
                  are attributed through the deletion-worker activity batch:
                  same reported_at window, result == reported_status, and
                  elimination of records already owned by someone else.
  state      latest observation of each resource inside the anchor (+ absence by
             omission when the anchor enumerates the whole category)
  policy     category -> treatment from deletion_rules.csv
"""
from __future__ import annotations

import csv
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .evidence import EvidenceStore, Fact, category_of, system_of
from .identity import IdentityIndex, Person
from .intent import classify
from .models import (
    CaseAssessment, FlowAssessment, RecordState, ResourceAssessment, RestoreAssessment, Treatment,
)

DELETE_LIKE = {"USER_PROFILE", "SEARCH_INDEX_ENTRY", "SUPPORT_ATTACHMENT", "USER_EXPORT", "MARKETING_PROFILE",
               "SECONDARY_IDENTIFIER"}
SEVERITY = {  # several copies observed in one snapshot: the worst copy decides
    "FOUND": 3, "NOT_FOUND": 0, "IDENTIFIABLE": 3, "REDACTED": 1, "ANONYMIZED": 1, "ACTIVE": 3,
    "BLOCKED": 1, "DISABLED": 1,
}
STATE_MAP = {"FOUND": RecordState.INTACT, "NOT_FOUND": RecordState.ABSENT, "IDENTIFIABLE": RecordState.INTACT,
             "REDACTED": RecordState.REDACTED, "ANONYMIZED": RecordState.ANONYMIZED}
RESULT_TO_STATUS = {"SUCCESS": "COMPLETE", "PARTIAL": "PARTIALLY_COMPLETE", "FAILED": "NOT_STARTED"}
P = lambda s: datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")


def case_key(case_id: str) -> tuple[int, str]:
    """Natural order for ids such as case_9 < case_10; non-numeric ids sort after numeric ones."""
    m = re.search(r"(\d+)$", case_id)
    return (int(m.group(1)) if m else 10**9, case_id)


LINK_RE = re.compile(r"linked (\S+) \(.*?\) to (\S+@\S+) and (user_\w+)|confirmed (\S+) \(.*?\) belongs only to (\S+@\S+) and (user_\w+)")


@dataclass
class Plan:
    case_id: str
    request: dict
    deletion: bool
    person: Person | None = None
    anchor: str | None = None
    resources: dict[str, str] = field(default_factory=dict)      # resource_id -> provenance
    notes: list[str] = field(default_factory=list)


@dataclass
class Observed:
    resource_id: str
    category: str
    state: str
    file_id: str
    how: str          # 'fact' | 'omission' | 'assumed'


class RealAssessor:
    def __init__(self, dataset: str | Path = "dataset", visual_facts: str | Path | None = None, llm=None):
        self.llm = llm                     # optional second opinion for low-confidence intent only
        self.ds = Path(dataset)
        self.store = EvidenceStore(self.ds, visual_facts)
        self.ix = IdentityIndex(self.ds)
        self.rules = self._load_rules()
        self.activity = self._load_activity()
        self.facts_by_res: dict[str, list[Fact]] = defaultdict(list)
        self.facts_by_key: dict[str, list[Fact]] = defaultdict(list)
        self.facts_by_file_res: dict[tuple[str, str], list[Fact]] = defaultdict(list)
        for f in self.store.all_facts():
            self.facts_by_res[f.resource_id].append(f)
            self.facts_by_file_res[(f.file_id, f.resource_id)].append(f)
            for k in f.keys:
                self.facts_by_key[k].append(f)
        # A resource keeps its most specific type: an attachment is also rendered as a support-ticket row
        # in some snapshots, and a secondary identifier as an analytics/support row.
        self.res_category: dict[str, str] = {}
        for rid, fs in self.facts_by_res.items():
            specific = {f.category for f in fs} & {"SUPPORT_ATTACHMENT", "SECONDARY_IDENTIFIER"}
            if specific:
                self.res_category[rid] = sorted(specific)[0]
        self.coverage_by_file: dict[str, set[str]] = defaultdict(set)
        self.coverage_t: dict[tuple[str, str], str] = {}
        for c in self.store.all_coverage():
            self.coverage_by_file[c.file_id].add(c.category)
            self.coverage_t[(c.file_id, c.category)] = c.t
        self.plans: dict[str, Plan] = {}
        self.warnings: list[str] = []
        self.catalog_links = self._catalog_links()
        self.evidence_owned = {f.resource_id for f in self.store.all_facts() if self.ix.owners_of(f.keys)}
        self.owner_of: dict[str, set[str]] = defaultdict(set)         # resource -> persons (any time)
        for f in self.store.all_facts():
            o = self.ix.owners_of(f.keys)
            if len(o) == 1:
                self.owner_of[f.resource_id] |= o

    # ------------------------------------------------------------------ loading
    def _load_rules(self) -> dict[str, str]:
        with open(self.ds / "deletion_rules.csv", newline="", encoding="utf-8-sig") as fh:
            return {r["data_category"]: r["required_action"] for r in csv.DictReader(fh)}

    def _load_activity(self) -> list[dict]:
        with open(self.ds / "system_activity.csv", newline="", encoding="utf-8-sig") as fh:
            return list(csv.DictReader(fh))

    def _catalog_links(self) -> list[tuple[str, str, str, str]]:
        out = []
        for a in self.activity:
            if a["event_type"] != "LINK_RESOURCE_IDENTITY":
                continue
            m = LINK_RE.search(a["details"])
            if m:
                g = [x for x in m.groups() if x]
                out.append((g[0], g[1].lower().rstrip("."), g[2], a["event_time"]))
        return out

    # ------------------------------------------------------------------ linking
    def fact_linked(self, person: Person, audit_at: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for k in person.keys:
            for f in self.facts_by_key.get(k, ()):
                if f.t <= audit_at and self.ix.owners_of(f.keys) == {person.user_id}:
                    out.setdefault(f.resource_id, "fact")
                    for linked in f.links:
                        out.setdefault(linked, "fact-link")
        for rid, email, user, t in self.catalog_links:
            if t <= audit_at and (user == person.user_id or email in person.emails):
                out.setdefault(rid, "catalog")
        return out

    STALE_DAYS = 30

    def case_resources(self, person: Person, anchor: str | None, audit_at: str) -> dict[str, str]:
        """One resource per data category (every labelled case has exactly that shape).

        Candidates are the person's records: ownership may be established by any evidence (a resource id
        never changes hands) or by an explicit data-catalog link. Ranking: a row of the anchor file beats
        an older observation, newer beats older. An observation more than STALE_DAYS older than the
        anchor is history of some earlier scenario, not the current state, and is ignored."""
        base = self.fact_linked(person, audit_at)
        best: dict[str, tuple[tuple, str, str]] = {}

        def offer(category: str, rank: tuple, rid: str, prov: str) -> None:
            if category not in best or rank > best[category][0]:      # first (smallest) id wins exact ties
                best[category] = (rank, rid, prov)

        cut = ""
        if anchor:
            cut = (P(self.store.captured_at(anchor)) - timedelta(days=self.STALE_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        mine = {rid for rid, o in self.owner_of.items() if o == {person.user_id}}
        mine |= {rid for rid, prov in base.items() if prov in ("catalog", "fact-link")}
        for rid in sorted(mine):                     # sorted: ties must not depend on the interpreter's hash seed
            fs = self.facts_by_res.get(rid, ())
            in_anchor = [f for f in fs if f.file_id == anchor] if anchor else []
            usable = [f for f in fs if f.t <= audit_at]
            prov = base.get(rid, "fact")
            if in_anchor:
                f = self._latest(in_anchor)
                offer(self._typed(f)[0], (1, f.t), rid, prov)
            elif usable:
                f = self._latest(usable)
                if not anchor or f.t >= cut:
                    offer(self._typed(f)[0], (0, f.t), rid, prov if prov != "fact" else "fact-older")
        return {rid: prov for _, rid, prov in best.values()}

    def find_anchor(self, person: Person, audit_at: str, catalog: set[str] = frozenset()) -> str | None:
        """Latest evidence file captured <= audit_at that mentions the person (by identifier, or through a
        resource the data catalog explicitly links to them)."""
        best: tuple[str, str] | None = None

        def consider(f: Fact) -> None:
            nonlocal best
            if f.t > audit_at or self.store.captured_at(f.file_id) > audit_at:
                return
            cand = (self.store.captured_at(f.file_id), f.file_id)
            if best is None or cand > best:
                best = cand

        for k in person.keys:
            for f in self.facts_by_key.get(k, ()):
                if self.ix.owners_of(f.keys) == {person.user_id}:
                    consider(f)
        for rid in catalog:
            for f in self.facts_by_res.get(rid, ()):
                consider(f)
        return best[1] if best else None

    # ------------------------------------------------------------------ batch pre-pass
    def prepare(self, requests: list[dict]) -> None:
        for req in requests:
            intent = classify(req["request_text"], self.llm)
            plan = Plan(req["case_id"], req, intent.deletion)
            if intent.deletion:
                plan.person = self.ix.resolve_email(req["email"])
                if plan.person is None:
                    self.warnings.append(f"{req['case_id']}: email does not resolve to a unique person")
                else:
                    base = self.fact_linked(plan.person, req["audit_at"])
                    catalog = {r for r, prov in base.items() if prov == "catalog"}
                    plan.anchor = self.find_anchor(plan.person, req["audit_at"], catalog)
                    plan.resources = self.case_resources(plan.person, plan.anchor, req["audit_at"])
            self.plans[req["case_id"]] = plan
        self._assign_accounts()
        self._assign_analytics()

    def _events(self, event_type: str, target_system: str, details_contains: str = "") -> list[dict]:
        return [a for a in self.activity if a["event_type"] == event_type and a["source_system"] == "deletion_worker"
                and a["target_system"] == target_system and details_contains in a["details"]]

    def _claimed(self) -> set[str]:
        owned = set(self.evidence_owned)
        for p in self.plans.values():
            owned.update(p.resources)
        return owned

    def _assign(self, todo: list[Plan], cands: dict[str, set[str]], tag: str, when: dict[str, str]) -> None:
        """Unique-candidate propagation, then a deterministic guess for what elimination cannot settle:
        the lowest case number takes the earliest event (matches every resolvable pair in the samples)."""
        taken: set[str] = set()
        got: set[str] = set()
        changed = True
        while changed:
            changed = False
            for p in todo:
                if p.case_id in got:
                    continue
                left = cands[p.case_id] - taken
                if len(left) == 1:
                    rid = next(iter(left))
                    p.resources[rid] = "activity"
                    taken.add(rid)
                    got.add(p.case_id)
                    changed = True
        for p in sorted(todo, key=lambda x: case_key(x.case_id)):
            if p.case_id in got:
                continue
            left = sorted(cands[p.case_id] - taken, key=lambda r: (when[r], r))
            if left:
                rid = left[0]
                p.resources[rid] = "activity-guess"
                taken.add(rid)
                got.add(p.case_id)
                p.notes.append(f"{tag} {rid}: one of {len(left)} equally plausible activity records")

    def _assign_accounts(self) -> None:
        events = self._events("DELETE_RECORD", "account_service")
        owned = self._claimed()
        todo = [p for p in self.plans.values() if p.deletion and p.person and
                not any(category_of(r) == "USER_PROFILE" for r in p.resources)]
        cands: dict[str, set[str]] = {}
        for p in todo:
            rep = P(p.request["reported_at"])
            manual = (rep.minute, rep.second) != (0, 0)                        # not an on-the-hour batch run
            free = [(a, (P(a["event_time"]) - rep).total_seconds() / 60.0) for a in events
                    if a["resource_id"] not in owned]
            if manual:                      # one-off runs: the deletion event sits within minutes of the report
                cands[p.case_id] = {a["resource_id"] for a, dt in free if abs(dt) <= 15}
            else:                           # batch runs: ~45-75 min before the report, result mirrors the status
                cands[p.case_id] = {a["resource_id"] for a, dt in free if -85 <= dt <= -35
                                    and RESULT_TO_STATUS[a["reported_result"]] == p.request["reported_status"]}
        self._assign(todo, cands, "account", {a["resource_id"]: a["event_time"] for a in events})

    def _has_violation(self, p: Plan) -> bool:
        for rid in p.resources:
            ob = self.observe(rid, p)
            if ob is None:
                continue
            if ob.category == "DATA_FLOW":
                if ob.state == "ACTIVE":
                    return True
            elif ob.category == "BACKUP_ARCHIVE":
                if ob.state != "BLOCKED":
                    return True
            else:
                action = self.rules.get(ob.category)
                if action == "DELETE" and ob.state != "NOT_FOUND":
                    return True
                if action == "REDACT" and ob.state == "IDENTIFIABLE":
                    return True
                if action == "ANONYMIZE" and ob.state != "ANONYMIZED":
                    return True
        return False

    def _assign_analytics(self) -> None:
        """Anonymised analytics profiles carry no identifier: attribute them to clean (COMPLETE-like)
        cases through the 'Policy action completed' anonymisation events of the same reporting batch."""
        events = self._events("ANONYMIZE_RECORD", "analytics_platform")
        owned = self._claimed()
        todo = []
        for p in self.plans.values():
            if not (p.deletion and p.person):
                continue
            if any(category_of(r) in ("ANALYTICS_PROFILE",) for r in p.resources):
                continue
            if any(category_of(r) == "ACCOUNT_TOMBSTONE" for r in p.resources):
                continue
            if self._has_violation(p):
                continue
            todo.append(p)
        cands: dict[str, set[str]] = {}
        for p in todo:
            rep = P(p.request["reported_at"])
            cands[p.case_id] = {
                a["resource_id"] for a in events
                if a["resource_id"] not in owned and "Policy action completed" in a["details"] + "Policy action completed"
                and -60 <= (P(a["event_time"]) - rep).total_seconds() / 60.0 <= 15
                and self._anonymous_analytics(a["resource_id"], p)}
        self._assign(todo, cands, "analytics", {a["resource_id"]: a["event_time"] for a in events})

    def _anonymous_analytics(self, rid: str, p: Plan) -> bool:
        ob = self._observe_any(rid, p.request["audit_at"])
        return ob is not None and ob.state == "ANONYMIZED"

    # ------------------------------------------------------------------ state
    def _typed(self, f: Fact) -> tuple[str, str]:
        """(category, state) of a fact under the resource's canonical type."""
        cat = self.res_category.get(f.resource_id, f.category)
        if cat == "SUPPORT_ATTACHMENT" and f.category == "SUPPORT_MESSAGE":
            return cat, "FOUND"                  # a ticket row naming the person = the attachment exists
        return cat, f.state

    def _latest(self, fs: list[Fact]) -> Fact:
        tmax = max(f.t for f in fs)
        return sorted((f for f in fs if f.t == tmax), key=lambda f: SEVERITY[f.state], reverse=True)[0]

    def _observe_any(self, rid: str, audit_at: str) -> Observed | None:
        """Latest eligible observation of a resource anywhere (case has no anchor file)."""
        facts = [f for f in self.facts_by_res.get(rid, ())
                 if f.t <= audit_at and self.store.captured_at(f.file_id) <= audit_at]
        best: tuple[str, str, Observed] | None = None
        if facts:
            f = self._latest(facts)
            tcat, tstate = self._typed(f)
            best = (f.t, self.store.captured_at(f.file_id), Observed(rid, tcat, tstate, f.file_id, "fact"))
        cat = best[2].category if best else (self.res_category.get(rid) or category_of(rid))
        if cat in DELETE_LIKE or cat == "USER_PROFILE":
            have = {f.file_id for f in self.facts_by_res.get(rid, ())}
            for (fid, c), t in self.coverage_t.items():
                if c != cat or fid in have or t > audit_at or self.store.captured_at(fid) > audit_at:
                    continue
                cand = (t, self.store.captured_at(fid), Observed(rid, cat, "NOT_FOUND", fid, "omission"))
                if best is None or cand[:2] > best[:2]:
                    best = cand
        return best[2] if best else None

    def observe(self, rid: str, plan: Plan) -> Observed | None:
        audit_at = plan.request["audit_at"]
        anchor = plan.anchor
        if not anchor:
            return self._observe_any(rid, audit_at)
        fs = [f for f in self.facts_by_file_res.get((anchor, rid), ()) if f.t <= audit_at]
        if fs:
            f = self._latest(fs)
            cat, state = self._typed(f)
            return Observed(rid, cat, state, anchor, "fact")
        cat = self.res_category.get(rid) or category_of(rid)
        # not listed in the anchor: use the latest record-level observation elsewhere (its file may have
        # been captured after audit_at, in which case the anchor is the citable file)
        other = [f for f in self.facts_by_res.get(rid, ()) if f.t <= audit_at]
        omission_t = self.coverage_t.get((anchor, cat)) if cat in DELETE_LIKE else None
        if other:
            f = self._latest(other)
            if omission_t is None or f.t > omission_t:
                fid = f.file_id if self.store.captured_at(f.file_id) <= audit_at else anchor
                tcat, tstate = self._typed(f)
                return Observed(rid, tcat, tstate, fid, "fact-other")
        if omission_t is not None:
            return Observed(rid, cat, "NOT_FOUND", anchor, "omission")
        if cat == "USER_PROFILE":                    # absent accounts are often simply not listed
            return Observed(rid, cat, "NOT_FOUND", anchor, "assumed")
        return None

    # ------------------------------------------------------------------ assess
    def assess(self, request: dict[str, str]) -> CaseAssessment:
        cid = request["case_id"]
        plan = self.plans.get(cid)
        if plan is None:
            self.prepare([request])
            plan = self.plans[cid]
        if not plan.deletion:
            return CaseAssessment(cid, False, notes=["non-deletion request"])
        if plan.person is None:
            return CaseAssessment(cid, True, notes=["unresolved identity"])
        res: list[ResourceAssessment] = []
        flows: list[FlowAssessment] = []
        restores: list[RestoreAssessment] = []
        for rid in sorted(plan.resources):
            ob = self.observe(rid, plan)
            if ob is None:
                continue
            system = system_of(rid)
            if ob.category == "DATA_FLOW":
                flows.append(FlowAssessment(system, rid, ob.state == "ACTIVE", ob.file_id))
            elif ob.category == "BACKUP_ARCHIVE":
                restores.append(RestoreAssessment(system, rid, ob.state == "BLOCKED", ob.file_id))
            else:
                action = self.rules.get(ob.category)
                if action is None:
                    continue
                res.append(ResourceAssessment(system, rid, Treatment(action), STATE_MAP[ob.state], ob.file_id))
        notes = [f"user={plan.person.user_id}", f"anchor={plan.anchor}"] + plan.notes
        return CaseAssessment(cid, True, res, flows, restores, notes=notes)
