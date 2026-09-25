"""Reviewer verdict parsing, failure / review fingerprints and prompt context helpers.

Pure functions (no I/O) so the loop's decisions are unit-testable without any provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re

from .common import OrchestratorError

SEVERITIES = ("blocker", "major", "minor", "note")
BLOCKING = ("blocker", "major")
VERDICTS = ("PASS", "FAIL", "NEEDS_HUMAN")


class ReviewParseError(OrchestratorError):
    code = "REVIEW_UNPARSABLE"


@dataclass(frozen=True)
class ReviewVerdict:
    verdict: str
    summary: str
    findings: tuple[dict, ...] = ()
    root_cause: str = ""
    instructions: str = ""          # what Main AI is told, assembled from the review
    needs_human_reason: str = ""
    fingerprint: str = ""

    @property
    def passed(self) -> bool:
        return self.verdict == "PASS"

    @property
    def needs_human(self) -> bool:
        return self.verdict == "NEEDS_HUMAN"

    def to_record(self) -> dict:
        return {"verdict": self.verdict, "summary": self.summary, "findings": list(self.findings),
                "root_cause": self.root_cause, "instructions": self.instructions,
                "needs_human_reason": self.needs_human_reason, "fingerprint": self.fingerprint}


def extract_json_object(text: str) -> dict:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s*```$", "", candidate)
    try:
        value = json.loads(candidate)
    except ValueError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start < 0 or end <= start:
            raise ReviewParseError("review result did not contain a JSON object") from None
        try:
            value = json.loads(candidate[start:end + 1])
        except ValueError as exc:
            raise ReviewParseError("review result JSON could not be parsed") from exc
    if not isinstance(value, dict):
        raise ReviewParseError("review result must be a JSON object")
    return value


_VERDICT_ALIASES = {
    "PASS": "PASS", "PASSED": "PASS", "APPROVE": "PASS", "APPROVED": "PASS", "OK": "PASS",
    "FAIL": "FAIL", "FAILED": "FAIL", "CHANGES_REQUESTED": "FAIL", "REQUEST_CHANGES": "FAIL",
    "CHANGES_REQUIRED": "FAIL", "REJECT": "FAIL",
    "NEEDS_HUMAN": "NEEDS_HUMAN", "NEED_HUMAN": "NEEDS_HUMAN", "HUMAN": "NEEDS_HUMAN",
}


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def parse_review(text: str, *, failure_mode: bool) -> ReviewVerdict:
    """Strict: an ambiguous review is refused rather than interpreted.

    * PASS may carry only non-blocking (minor / note) findings, and is invalid while
      Tests are failing (failure_mode).
    * FAIL must give Main something concrete to do.
    * NEEDS_HUMAN must say why.
    """
    value = extract_json_object(text)
    raw = _text(value.get("verdict")).upper().replace("-", "_").replace(" ", "_")
    verdict = _VERDICT_ALIASES.get(raw)
    if verdict is None:
        raise ReviewParseError(f"invalid verdict: {raw or '<missing>'}")
    raw_findings = value.get("findings", [])
    if raw_findings is None:
        raw_findings = []
    if not isinstance(raw_findings, list):
        raise ReviewParseError("findings must be an array")
    findings = []
    for item in raw_findings:
        if not isinstance(item, dict):
            continue
        entry = dict(item)
        severity = _text(entry.get("severity")).lower() or "major"
        entry["severity"] = severity if severity in SEVERITIES else "major"
        findings.append(entry)
    summary = _text(value.get("summary"))
    if not summary:
        raise ReviewParseError("review summary is empty")
    blocking = [f for f in findings if f["severity"] in BLOCKING]
    root_cause = _text(value.get("root_cause"))
    instructions = _text(value.get("instructions_for_main"))
    reason = _text(value.get("needs_human_reason"))

    if verdict == "PASS":
        if failure_mode:
            raise ReviewParseError("PASS is not valid while Tests are failing")
        if blocking:
            raise ReviewParseError("PASS returned together with blocking findings; refusing ambiguous review")
    elif verdict == "FAIL":
        actionable = instructions or any(_text(f.get("instruction")) for f in findings)
        if not actionable:
            raise ReviewParseError("FAIL without a concrete instruction for the Main AI")
    elif not reason:
        raise ReviewParseError("NEEDS_HUMAN without needs_human_reason")

    return ReviewVerdict(
        verdict=verdict, summary=summary, findings=tuple(findings), root_cause=root_cause,
        instructions=_assemble_instructions(summary, root_cause, instructions, findings),
        needs_human_reason=reason, fingerprint=review_fingerprint(findings, summary if not findings else ""),
    )


def _assemble_instructions(summary: str, root_cause: str, instructions: str, findings: list[dict]) -> str:
    parts = []
    if root_cause:
        parts.append(f"Root cause (Reviewer): {root_cause}")
    if instructions:
        parts.append(f"Instructions:\n{instructions}")
    listed = []
    for index, finding in enumerate(findings, 1):
        where = _text(finding.get("file"))
        line = f"{index}. [{finding['severity']}] {where + ': ' if where else ''}{_text(finding.get('problem'))}"
        if _text(finding.get("evidence")):
            line += f"\n   evidence: {_text(finding['evidence'])}"
        if _text(finding.get("instruction")):
            line += f"\n   fix: {_text(finding['instruction'])}"
        listed.append(line)
    if listed:
        parts.append("Findings:\n" + "\n".join(listed))
    return "\n\n".join(parts) or summary


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def review_fingerprint(findings: list[dict], fallback: str = "") -> str:
    """Stable identity of *what the Reviewer is asking for*, ignoring wording noise."""
    keys = sorted({
        f"{_text(f.get('file')).lower()}|{re.sub(r'[^a-z0-9]+', ' ', _text(f.get('problem')).lower())[:120].strip()}"
        for f in findings if f.get("severity") in BLOCKING
    })
    return _hash("\n".join(keys) or fallback)


_NOISE = [
    (re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?"), "<time>"),
    (re.compile(r"\b\d+(?:\.\d+)?\s*(?:seconds?|secs?|ms|s)\b"), "<duration>"),
    (re.compile(r"\bin \d+\.\d+s\b"), "in <duration>"),
    (re.compile(r"0x[0-9a-fA-F]+"), "<addr>"),
    (re.compile(r"(?i)[a-z]:[\\/][^\s\"'<>|]*?(?:temp|tmp|ai-orch-)[^\s\"'<>|]*"), "<tmp>"),
    (re.compile(r"/tmp/[^\s\"']+"), "<tmp>"),
    (re.compile(r"\bline \d+\b"), "line N"),
    (re.compile(r"(?<=[\w.]):\d+(?::\d+)?\b"), ":N"),
    (re.compile(r"\b[0-9a-f]{7,40}\b"), "<sha>"),
    (re.compile(r"\s+"), " "),
]
_KEY_LINE = re.compile(r"\b(FAIL|FAILED|ERROR|Error|Exception|assert\w*|AssertionError|Traceback|not ok|TIMEOUT|HANG)\b")


def normalize_failure_text(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        for pattern, replacement in _NOISE:
            line = pattern.sub(replacement, line)
        line = line.strip()
        if line:
            lines.append(line)
    return lines


def failure_fingerprint(text: str) -> tuple[str, str]:
    """(fingerprint, short summary). Durations, timestamps, temp paths, addresses and line
    numbers are not evidence of progress, so they are normalised away; the failing test
    names and error messages are what identify 'the same problem'."""
    lines = normalize_failure_text(text)
    key = [line for line in lines if _KEY_LINE.search(line)] or lines[-25:]
    unique = sorted(set(key))
    summary = " | ".join(unique[:4])[:400]
    return _hash("\n".join(unique)[:50_000]), summary


def extract_acceptance(task: str) -> str:
    """Acceptance criteria section of the TaskSpec (marker line up to the next heading or
    40 lines), or an empty string when the TaskSpec has no such section."""
    lines = task.splitlines()
    for index, line in enumerate(lines):
        if re.search(r"受入条件|受け入れ条件|acceptance", line, re.IGNORECASE):
            block = [line]
            for follow in lines[index + 1:index + 41]:
                if follow.lstrip().startswith("#") and len(block) > 1:
                    break
                block.append(follow)
            return "\n".join(block).strip()
    return ""


def tail(text: str, limit: int) -> str:
    return text if len(text) <= limit else "…(truncated)…\n" + text[-limit:]


def head(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "\n…(truncated; inspect the files directly)"
