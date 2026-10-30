"""Does `request_text` authorise deletion?

Rules first (cheap, deterministic, multilingual). The default is "deletion": audit requests that
only ask to *verify* a deletion ("confirm the profile is gone") are still deletion-audit cases.
A request is NOT_APPLICABLE only when it explicitly keeps the account/data (negated deletion,
"leave it in place") or is plainly about access, correction, export or marketing opt-out.

An optional LLM (see prompts/01_intent_classifier.md) may adjudicate the low-confidence results.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

# explicit negation / scoping of deletion: the person wants to keep the account or its records
STRONG_NON_DELETION = re.compile(
    r"(do not (?:close|delete|remove|erase)|don't (?:delete|close|remove|erase)|not (?:asking|requesting) (?:for )?(?:deletion|to delete|erasure)"
    r"|not a request to (?:erase|delete|remove)|without (?:removing|deleting)|leave (?:the |my )?(?:account|profile)"
    r"|keep (?:the |my )?account|continue (?:using|to use)|still (?:need|use|want) (?:the |my )?(?:account|it)"
    r"|(?:marketing|mailing) lists only|ne (?:pas )?supprimez pas|no (?:elimin|borr)e|nicht l[öo]schen)", re.I)

# subject matter that is clearly access / correction / export / opt-out
TOPIC_NON_DELETION = re.compile(
    r"(copy of (?:last year|the information|the data)|send me a copy|need a copy|download my|portable format"
    r"|is misspelled|resetting the login|change the email|stop the promotional|unsubscribe|opt[- ]out"
    r"|what personal information|replace it with the new one)", re.I)

DELETION = re.compile(
    r"(delet|erase|erasure|remov|clos(?:e|ure)|wipe|purge|forget|eliminat|supprim|suppression|effac|fermer"
    r"|eliminar|borrar|supresi|cerrar|exclu[ií]|exclus[aã]o|apag|encerr|l[öo]sch|entfern|cancell|elimin"
    r"|rimuov|verwijder|削除|消去|退会|삭제|탈퇴|删除|注销|удал|gone|cannot identify)", re.I)

# a complaint about something that WAS deleted, plus a request to bring it back: the opposite of a deletion request
PASSIVE_DELETION = re.compile(r"\b(?:was|were|got|been|is|are|gets)\s+(?:\w+\s+){0,3}(?:deleted|removed|erased|closed)\b", re.I)
RESTORE_ASK = re.compile(r"\b(?:restore|reinstate|bring (?:it|them|my \w+) back|recover|undo)\b|\bwant (?:it|them|my \w+) back\b", re.I)
EXPLICIT_DELETE_ASK = re.compile(
    r"\b(?:please\s+|kindly\s+)?(?:delete|erase|remove)\s+(?:my|all|the|this|our|any)\b|\bi\s+(?:want|would like|request|ask)\b[^.?!]{0,30}\b(?:delet|eras|remov)", re.I)


@dataclass(frozen=True)
class Intent:
    deletion: bool
    confidence: float
    reason: str


def classify(text: str, llm=None, model: str = "claude-sonnet-5-5") -> Intent:
    """Rules first. Only a low-confidence rule result (<0.7) is sent to the optional LLM; the shipped dataset
    never reaches that branch (every request is decided with confidence >= 0.9)."""
    rule = classify_rules(text)
    if llm is None or rule.confidence >= 0.7:
        return rule
    try:
        raw = llm.complete(model=model, system=LLM_SYSTEM, prompt=LLM_PROMPT.format(text=text), max_tokens=200, tag="intent")
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0))
        verdict = str(data["intent"]).upper()
        if verdict in ("DELETE", "NOT_DELETE") and float(data.get("confidence", 0)) >= 0.6:
            return Intent(verdict == "DELETE", float(data["confidence"]), "llm: " + str(data.get("reason", ""))[:120])
    except Exception:                       # malformed answer: stay with the conservative rule result
        pass
    return Intent(False, rule.confidence, rule.reason + "; llm unsure -> conservative NOT_DELETE")


LLM_SYSTEM = "You classify customer privacy requests for an e-commerce company. Output JSON only."
LLM_PROMPT = (
    'Request text:\n"""\n{text}\n"""\n\n'
    "Does the customer ask for their account and/or personal data to be deleted, erased, forgotten or verified "
    'as deleted? Judge the final stated wish ("please don\'t delete my account" is NOT_DELETE).\n'
    'Return exactly: {{"intent": "DELETE" | "NOT_DELETE", "reason": "<=25 words", "confidence": 0.0-1.0}}')


def classify_rules(text: str) -> Intent:
    t = text.strip()
    strong = STRONG_NON_DELETION.search(t)
    if strong:
        return Intent(False, 0.95, f"explicitly keeps account/data: {strong.group(0)!r}")
    if PASSIVE_DELETION.search(t) and RESTORE_ASK.search(t) and not EXPLICIT_DELETE_ASK.search(t):
        return Intent(False, 0.9, "complains that data was deleted and asks for it back")
    topic = TOPIC_NON_DELETION.search(t)
    dele = DELETION.search(t)
    if topic and not dele:
        return Intent(False, 0.9, f"access/correction/export/opt-out request: {topic.group(0)!r}")
    if topic and dele:
        return Intent(True, 0.6, f"mixed signals ({topic.group(0)!r} vs {dele.group(0)!r}); deletion wins")
    if dele:
        return Intent(True, 0.95, f"deletion phrase: {dele.group(0)!r}")
    return Intent(True, 0.5, "no explicit signal; treated as a deletion-verification request")
