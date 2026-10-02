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


NO_TESTS_MARKER = ("TEST RUNNER: 0 tests ran. This is usually a test command / discovery problem "
                   "(pattern, quoting, working directory), not an implementation bug.")
_RAN_COUNT = re.compile(r"(?m)^Ran (\d+) tests? in ")
_NO_TESTS = re.compile(r"(?m)^(?:NO TESTS RAN\b|collected 0 items\b|=+ no tests ran\b)")
_RUNNER_UNAVAILABLE = re.compile(
    r"(?mi)(?:is not recognized as an internal or external command|内部コマンドまたは外部コマンド"
    r"|^\S*: (?:\d+: )?\S+: (?:command )?not found\s*$"
    r"|python[\w.]*(?:\.exe)?: No module named [\w.]+\s*$"      # `python -m <runner>` without the runner
    r"|python[\w.]*(?:\.exe)?: can't open file )")

RUNNER_NO_TESTS = "no_tests"
RUNNER_UNAVAILABLE = "runner_unavailable"


def zero_tests_ran(output: str) -> bool:
    """True when a test runner's own summary says nothing was tested (unittest / pytest).
    For unittest only the last summary counts, so nested runner output inside tests is ignored."""
    counts = _RAN_COUNT.findall(output)
    if counts:
        return counts[-1] == "0"
    return bool(_NO_TESTS.search(output))


def classify_runner_problem(text: str) -> str:
    """Classify a Tests failure caused by the command / runner rather than by the code:
    `no_tests`, `runner_unavailable`, or "" for an ordinary test failure."""
    if NO_TESTS_MARKER in text:
        return RUNNER_NO_TESTS
    if _RUNNER_UNAVAILABLE.search(text):
        return RUNNER_UNAVAILABLE
    return ""


_PLAIN_SECTION = re.compile(r"^\s*(?:範囲外|制約|関連ファイル|目的|背景|前提|注意|補足|out of scope|constraints?|notes?)", re.IGNORECASE)
_PLAIN_SECTION_MAX = 40
# Copying a rendered Markdown page folds single line breaks into spaces, so a title can arrive followed by
# its whole text on one long line. These titles are recognised at any length (when followed by a space,
# a bracket or a colon), so an acceptance section cannot swallow the "out of scope" / "constraints" text.
_STRONG_SECTION = re.compile(r"^\s*(?:範囲外|制約|関連ファイル|out of scope|constraints?)(?=[\s（(:：]|$)", re.IGNORECASE)


def _opens_section(line: str) -> bool:
    stripped = line.strip()
    return (stripped.startswith("#") or bool(_STRONG_SECTION.match(stripped))
            or (len(stripped) <= _PLAIN_SECTION_MAX and bool(_PLAIN_SECTION.match(stripped))))


def extract_acceptance(task: str) -> str:
    """Acceptance criteria section of the TaskSpec (marker line up to the next heading or
    40 lines), or an empty string when the TaskSpec has no such section."""
    lines = task.splitlines()
    for index, line in enumerate(lines):
        if re.search(r"受入条件|受け入れ条件|acceptance", line, re.IGNORECASE):
            block = [line]
            for follow in lines[index + 1:index + 41]:
                if _opens_section(follow) and len(block) > 1:
                    break
                block.append(follow)
            return "\n".join(block).strip()
    return ""


_BULLET = re.compile(r"^\s*(?:[-*・●]|\d+[.)、])\s*(.+\S)\s*$")
MAX_CRITERIA = 20
# Findings of these categories may block without pointing at a fixed criterion, provided they carry evidence:
# they are defects in the change itself, not extra requirements.
DEFECT_CATEGORIES = ("bug", "regression", "safety")


_ACCEPTANCE_MARK = re.compile(r"^.*?(?:受入条件|受け入れ条件|acceptance criteria|acceptance)\s*[:：]?", re.IGNORECASE)
_INLINE_BULLET = re.compile(r"(?:^|\s+)・\s*")


def _inline_items(line: str) -> list[str]:
    """Split "・A ・B ・C" (bullets folded onto one line by copy / paste). A "・" inside a word is kept."""
    return [part.strip() for part in _INLINE_BULLET.split(line.strip()) if part.strip()]


def _has_inline_bullets(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("・") or bool(re.search(r"\s+・", stripped))


def criteria_from_acceptance(block: str) -> list[dict]:
    """Fixed criteria from a TaskSpec acceptance section: one per bullet / numbered line; when the text
    carries no bullet marks at all (e.g. pasted as plain text), one per non-empty line. Bullets folded onto
    one line by copy / paste ("受入条件 ・A ・B") are split back into separate criteria."""
    lines = block.splitlines()
    body = lines[1:]   # first line is the section heading
    if lines:
        remainder = _ACCEPTANCE_MARK.sub("", lines[0], count=1).strip()
        if remainder and _has_inline_bullets(remainder):
            body = [remainder] + body
    bullets, plain = [], []
    for line in body:
        if not line.strip():
            continue
        if _has_inline_bullets(line):
            bullets += _inline_items(line)
        elif m := _BULLET.match(line):
            bullets.append(m.group(1).strip())
        else:
            plain.append(line.strip())
    items = bullets or plain
    return [{"id": f"C{i}", "text": text} for i, text in enumerate(items[:MAX_CRITERIA], 1)]


def parse_criteria(text: str) -> list[dict]:
    """Criteria drafted by the Reviewer: {"criteria": ["...", ...]}. Strict; raises ReviewParseError."""
    value = extract_json_object(text)
    raw = value.get("criteria")
    if not isinstance(raw, list):
        raise ReviewParseError("criteria must be an array")
    items = []
    for entry in raw:
        item = _text(entry.get("text") if isinstance(entry, dict) else entry)
        if item:
            items.append(item)
    if not items:
        raise ReviewParseError("no criteria given")
    return [{"id": f"C{i}", "text": text} for i, text in enumerate(items[:MAX_CRITERIA], 1)]


def format_criteria(criteria: list[dict]) -> str:
    return "\n".join(f"- {c['id']}: {c['text']}" for c in criteria) or "(none)"


def apply_fixed_criteria(verdict: ReviewVerdict, criteria: list[dict], *, final: bool) -> tuple[ReviewVerdict, list[dict]]:
    """Enforce "criteria are fixed before implementation" in code, not only in the prompt.

    A blocking finding stands only when it cites a fixed criterion id (`criterion`) or is a defect
    (bug / regression / safety) with concrete evidence. Anything else is kept for the record but
    downgraded to `minor`, so it can no longer send the Main AI (and the Reviewer) around another loop.
    In a final review, a FAIL that has no blocking finding left becomes PASS. Returns the verdict and
    the list of downgraded findings."""
    if not criteria:
        return verdict, []
    ids = {c["id"].upper() for c in criteria}
    kept, dropped = [], []
    for finding in verdict.findings:
        entry = dict(finding)
        if entry["severity"] in BLOCKING:
            cited = _text(entry.get("criterion")).upper() in ids
            defect = _text(entry.get("category")).lower() in DEFECT_CATEGORIES and bool(_text(entry.get("evidence")))
            if not (cited or defect):
                entry["severity"] = "minor"
                entry["downgraded"] = "not a fixed criterion and not an evidenced defect"
                dropped.append(entry)
        kept.append(entry)
    if not dropped:
        return verdict, []
    blocking = [f for f in kept if f["severity"] in BLOCKING]
    if verdict.verdict == "FAIL" and not blocking and final:
        new_verdict = "PASS"
        instructions = ""
    else:
        new_verdict = verdict.verdict
        instructions = _assemble_instructions(verdict.summary, verdict.root_cause,
                                              "" if not blocking else verdict.instructions, kept)
    return ReviewVerdict(
        verdict=new_verdict, summary=verdict.summary, findings=tuple(kept), root_cause=verdict.root_cause,
        instructions=instructions or verdict.summary, needs_human_reason=verdict.needs_human_reason,
        fingerprint=review_fingerprint(kept, verdict.summary if not kept else ""),
    ), dropped


def tail(text: str, limit: int) -> str:
    return text if len(text) <= limit else "…(truncated)…\n" + text[-limit:]


def head(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "\n…(truncated; inspect the files directly)"
