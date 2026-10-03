"""Fixed-format TaskSpec input: a JSON spec file that gives acceptance criteria (and,
optionally, the target repository) directly, instead of having them extracted from the
free-form task text by wording rules (which can cut a criterion or mix in a heading).

Pure functions (no I/O besides reading the given spec file); the caller decides what to
do with a parsed `Spec` (orchestrator.prepare_run stores it unchanged in criteria /
criteria_source / spec.json).
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re

from .common import OrchestratorError

MAX_SPEC_CRITERIA = 20
MAX_CRITERION_CHARS = 1000


class SpecError(OrchestratorError):
    code = "SPEC_INVALID"


@dataclass(frozen=True)
class Spec:
    criteria: tuple[dict, ...]
    target_repo: str | None = None

    def to_record(self) -> dict:
        return {"schema_version": 1, "criteria": [dict(c) for c in self.criteria], "target_repo": self.target_repo}


def _fail(message: str) -> None:
    raise SpecError(f"仕様ファイルが不正です: {message}")


def parse_spec_text(text: str) -> Spec:
    """Strict: any violation of the fixed format refuses the whole spec (no partial use)."""
    try:
        value = json.loads(text)
    except ValueError as exc:
        _fail(f"JSONを解析できません: {exc}")
    if not isinstance(value, dict):
        _fail("JSONオブジェクトである必要があります")
    if "schema_version" in value:
        raw_version = value["schema_version"]
        if isinstance(raw_version, bool) or not isinstance(raw_version, int) or raw_version != 1:
            _fail(f"schema_versionは1である必要があります（{raw_version!r}）")
    raw_criteria = value.get("criteria")
    if not isinstance(raw_criteria, list) or not raw_criteria:
        _fail("criteriaは1件以上の配列が必須です")
    if len(raw_criteria) > MAX_SPEC_CRITERIA:
        _fail(f"criteriaは{MAX_SPEC_CRITERIA}件までです（{len(raw_criteria)}件）")
    items: list[dict] = []
    seen_ids: set[str] = set()
    for index, entry in enumerate(raw_criteria, 1):
        if not isinstance(entry, dict):
            _fail(f"criteria[{index}]はオブジェクトである必要があります")
        raw_text = entry.get("text")
        if not isinstance(raw_text, str) or not raw_text.strip():
            _fail(f"criteria[{index}].textが空、または空白のみです")
        if len(raw_text) > MAX_CRITERION_CHARS:
            _fail(f"criteria[{index}].textが{MAX_CRITERION_CHARS}文字を超えています（{len(raw_text)}文字）")
        raw_id = entry.get("id")
        cid: str | None
        if raw_id is None:
            cid = None
        elif isinstance(raw_id, str) and raw_id.strip():
            cid = raw_id.strip()
            if cid in seen_ids:
                _fail(f"criteria[{index}].id「{cid}」が重複しています")
            seen_ids.add(cid)
        else:
            _fail(f"criteria[{index}].idが空です")
        items.append({"id": cid, "text": raw_text.strip()})
    counter = 0
    numbered: list[dict] = []
    for item in items:
        if item["id"] is None:
            counter += 1
            auto_id = f"C{counter}"
            if auto_id in seen_ids:
                _fail(f"自動採番ID「{auto_id}」が明示されたidと重複しています")
            numbered.append({"id": auto_id, "text": item["text"]})
        else:
            numbered.append(item)
    raw_target = value.get("target_repo")
    if raw_target is not None and not isinstance(raw_target, str):
        _fail("target_repoは文字列である必要があります")
    target_repo = raw_target.strip() if isinstance(raw_target, str) and raw_target.strip() else None
    return Spec(criteria=tuple(numbered), target_repo=target_repo)


def load_spec_file(path: Path) -> Spec:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SpecError(f"仕様ファイルを読み込めません: {path} ({exc})") from exc
    return parse_spec_text(text)


_TARGET_LINE = re.compile(r"^[ \t　]*対象リポジトリ[ \t　]*[:：][ \t　]*(.*)$")
_TARGET_STOP = re.compile(r"[\s　（(]")


def extract_target_repo_name(task: str) -> str | None:
    """The word right after a "対象リポジトリ:" / "対象リポジトリ：" line, within the first 10
    lines of `task` only. A bracketed note after the name (e.g. "development-management（DCC）")
    and full/half-width spelling of the colon are both handled. None when there is no such line."""
    for line in task.splitlines()[:10]:
        match = _TARGET_LINE.match(line)
        if not match:
            continue
        rest = match.group(1).strip()
        if not rest:
            continue
        stop = _TARGET_STOP.search(rest)
        name = (rest[:stop.start()] if stop else rest).strip()
        if name:
            return name
    return None
