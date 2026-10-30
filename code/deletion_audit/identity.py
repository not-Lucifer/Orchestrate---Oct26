"""Identity resolution: request email -> user_id -> every identifier the person has ever had.

Sources: `user_identities.csv` (current snapshot) and `user_audit_log.csv` (historical changes of
email / phone / email_hash). A request email may be a current or a historical address. Old values
still appear in legacy systems, so they are all linking keys.
"""
from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from .evidence import link_keys, norm_email


@dataclass
class Person:
    user_id: str
    name: str = ""
    emails: set[str] = field(default_factory=set)       # current + historical, lower-cased
    keys: set[str] = field(default_factory=set)         # emails, tel:digits, sha256 hashes, user_id
    current_email: str = ""
    names: set[str] = field(default_factory=set)


class IdentityIndex:
    def __init__(self, dataset: str | Path):
        ds = Path(dataset)
        self.people: dict[str, Person] = {}
        self.key_owner: dict[str, set[str]] = {}
        with open(ds / "user_identities.csv", newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                p = Person(r["user_id"], r["name"], current_email=norm_email(r["email"]))
                p.emails.add(p.current_email)
                p.names.add(r["name"].strip().lower())
                p.keys.update(link_keys(r["email"], r["phone"], r["email_hash"], r["user_id"]))
                p.keys.add(hashlib.sha256(p.current_email.encode()).hexdigest())
                self.people[p.user_id] = p
        with open(ds / "user_audit_log.csv", newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                p = self.people.get(r["user_id"])
                if p is None:
                    continue
                for v in (r["old_value"], r["new_value"]):
                    ks = link_keys(v)
                    p.keys.update(ks)
                    if r["field_name"] == "email":
                        e = norm_email(v)
                        p.emails.add(e)
                        p.keys.add(hashlib.sha256(e.encode()).hexdigest())
        for p in self.people.values():
            for k in p.keys:
                self.key_owner.setdefault(k, set()).add(p.user_id)

    def resolve_email(self, email: str) -> Person | None:
        owners = self.key_owner.get(norm_email(email), set())
        if len(owners) == 1:
            return self.people[next(iter(owners))]
        return None

    def owners_of(self, keys) -> set[str]:
        out: set[str] = set()
        for k in keys:
            out |= self.key_owner.get(k, set())
        return out
