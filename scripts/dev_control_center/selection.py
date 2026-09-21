"""Tk-free selection state: epochs, stamped state, candidate provenance, modal guard.

App delegates to these classes so the asynchronous-consistency rules can be
tested without a display. The App implements the small ``view`` interface.
"""

from __future__ import annotations

from dataclasses import dataclass
import enum
import logging
from pathlib import Path
from typing import Any, Callable, Mapping

from . import loader
from .core import (
    GitHubState,
    RepoDefinition,
    RepoEntrypoints,
    RepoState,
    candidate_sha_is_valid,
)
from .loader import (
    BACKGROUND_POOL,
    GITHUB_POOL,
    GLOBAL,
    LOCAL_POOL,
    Coordinator,
    NoticeKind,
    TerminalNotice,
    WorkerResult,
)
from .timing import TIMING

log = logging.getLogger(__name__)

DEV_MANAGEMENT = "development-management"
KIND_LOCAL = "local"
KIND_GITHUB = "github"
KIND_SUGGEST = "suggest"
GLOBAL_REMOTE_REPOS = "remote_repos"
GLOBAL_SELF_UPDATE = "self_update"


class Origin(str, enum.Enum):
    NONE = "NONE"
    USER = "USER"
    AI = "AI"
    AUTO = "AUTO"


class CandidateProvenance:
    """The ONLY writer of candidate text and its origin.

    Invariant: origin == NONE iff the text is empty. Every operation checks it
    on exit and rolls back (no-op + error log) if a write would break it.
    """

    def __init__(self, authority: Callable[[str], GitHubState | None]) -> None:
        self._authority = authority
        self.candidate_by_repo: dict[str, str] = {}
        self.candidate_origin: dict[str, Origin] = {}

    def text(self, repo: str) -> str:
        return self.candidate_by_repo.get(repo, "")

    def origin(self, repo: str) -> Origin:
        return self.candidate_origin.get(repo, Origin.NONE)

    def _set(self, repo: str, text: str, origin: Origin) -> bool:
        before = (self.text(repo), self.origin(repo))
        self.candidate_by_repo[repo] = text
        self.candidate_origin[repo] = origin
        if (origin is Origin.NONE) != (text == ""):
            self.candidate_by_repo[repo], self.candidate_origin[repo] = before
            log.error("candidate provenance invariant rejected write: %r %s", text, origin)
            return False
        return True

    def user_edit(self, repo: str, text: str) -> bool:
        text = text.strip()
        return self._set(repo, text, Origin.USER if text else Origin.NONE)

    def ai_result(self, repo: str, sha: str) -> bool:
        sha = sha.strip().lower()
        return self._set(repo, sha, Origin.AI) if sha else False

    def auto_reflect(self, repo: str, sha: str, github_record: GitHubState | None) -> bool:
        sha = sha.strip().lower()
        record = self._authority(repo)
        if (
            self.origin(repo) is not Origin.NONE
            or self.text(repo)
            or github_record is None
            or github_record is not record
            or github_record.error
            or not candidate_sha_is_valid(sha)
            or sha != github_record.branch_sha.strip().lower()
        ):
            return False
        return self._set(repo, sha, Origin.AUTO)

    def normalize(self, repo: str, canonical: str) -> bool:
        current = self.text(repo)
        canonical = canonical.strip()
        if not current or not canonical or current.lower() != canonical.lower():
            return False
        return self._set(repo, canonical, self.origin(repo))

    def clear_auto(self, repo: str) -> bool:
        if self.origin(repo) is not Origin.AUTO:
            return False
        return self._set(repo, "", Origin.NONE)


@dataclass(frozen=True)
class Stamped:
    value: Any
    token: int
    epoch: int


@dataclass(frozen=True)
class LocalSnapshot:
    repo_state: RepoState
    entrypoints: RepoEntrypoints


@dataclass(frozen=True)
class IntentSnapshot:
    kind: str
    fields: Mapping[str, Any]


class ModalGuard:
    """While a confirmation dialog is open, results/notices are held (not applied)."""

    def __init__(self) -> None:
        self._intent: IntentSnapshot | None = None

    @property
    def active(self) -> bool:
        return self._intent is not None

    def begin(self, intent: IntentSnapshot) -> None:
        self._intent = intent

    def end(self) -> IntentSnapshot | None:
        intent, self._intent = self._intent, None
        return intent

    def finish(self, capture: Callable[[], Mapping[str, Any]]) -> bool:
        """End the dialog; True only if the world still matches the snapshot."""
        intent = self.end()
        return intent is not None and dict(intent.fields) == dict(capture())


class Loaders:
    """The blocking work each request kind performs (runs on worker threads)."""

    def __init__(self, repos_root: Path) -> None:
        self.repos_root = repos_root

    def local(self, definition: RepoDefinition, cancel) -> LocalSnapshot:
        from .core import discover_entrypoints, inspect_repo

        root = self.repos_root / definition.name
        state = inspect_repo(root, definition, cancel=cancel)
        entries = discover_entrypoints(
            root, definition.repo_type,
            application_implemented=definition.application_implemented, cancel=cancel,
        )
        return LocalSnapshot(state, entries)

    def github(self, definition: RepoDefinition, cancel) -> GitHubState:
        from .core import fetch_github_state

        return fetch_github_state(definition, cancel=cancel)

    def suggest(self, definition: RepoDefinition, cancel) -> str:
        from .core import suggest_test_command

        return suggest_test_command(self.repos_root / definition.name)


class SelectionState:
    def __init__(
        self,
        coordinator: Coordinator,
        definitions: list[RepoDefinition],
        view: Any,
        loaders: Any,
        *,
        scheduler: Any = None,
        debounce_ms: int = 150,
    ) -> None:
        self.coordinator = coordinator
        self.definitions = definitions
        self._by_name = {d.name: d for d in definitions}
        self.view = view
        self.loaders = loaders
        self.scheduler = scheduler
        self.debounce_ms = debounce_ms
        self.current: RepoDefinition | None = None
        self.lifecycle_epoch: dict[str, int] = {d.name: 0 for d in definitions}
        self.state_generation = 0
        self.self_update_epoch = 0
        self.provenance = CandidateProvenance(self.authoritative_github)
        self._local: dict[str, Stamped] = {}
        self._github: dict[str, Stamped] = {}
        self.display_cache: dict[str, GitHubState] = {}
        self.needs_reload: set[str] = set()
        self.post_action_notice: dict[str, str] = {}
        self.github_loading = False
        self.guard = ModalGuard()
        self._debounce: Any = None
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    # ------------------------------------------------------------ accessors
    def authoritative_local(self, repo: str) -> LocalSnapshot | None:
        stamp = self._local.get(repo)
        if stamp is not None and stamp.epoch == self.lifecycle_epoch.get(repo):
            return stamp.value
        return None

    def authoritative_github(self, repo: str) -> GitHubState | None:
        stamp = self._github.get(repo)
        if stamp is not None and stamp.epoch == self.lifecycle_epoch.get(repo):
            return stamp.value
        return None

    # ---------------------------------------------------------- invalidation
    def invalidate(self, repo: str, reason: str) -> None:
        """The one place stale state is discarded. USER/AI candidates are kept."""
        self._local.pop(repo, None)
        stale = self._github.pop(repo, None)
        if stale is not None and not stale.value.error:
            self.display_cache[repo] = stale.value
        self.provenance.clear_auto(repo)
        self.state_generation += 1

    def new_epoch(self, repo: str, reason: str, *, self_update: bool = False) -> int:
        """Start a new REPO-scope load batch: bump epoch, invalidate, cancel old work."""
        self.lifecycle_epoch[repo] = self.lifecycle_epoch.get(repo, 0) + 1
        self.invalidate(repo, reason)
        self.coordinator.cancel_repo_scope(repo, reason)
        if self.current is not None and self.current.name == repo:
            self.github_loading = True
        if self_update and repo == DEV_MANAGEMENT:
            self.self_update_epoch += 1
        return self.lifecycle_epoch[repo]

    def process_boundary(self, repo: str, reason: str) -> bool:
        """_begin_process/_end_process: True if the self-update result was invalidated."""
        self.new_epoch(repo, reason, self_update=True)
        return repo == DEV_MANAGEMENT

    # ------------------------------------------------------------- selection
    def select(self, name: str) -> None:
        definition = self._by_name[name]
        if self.current is not None and self.current.name != name:
            self.leave(self.current.name)
        self.enter(definition)

    def leave(self, repo: str) -> None:
        self._cancel_debounce()
        self.coordinator.cancel_repo_scope(repo, "leave")
        self.provenance.clear_auto(repo)
        self._local.pop(repo, None)
        stale = self._github.pop(repo, None)
        if stale is not None and not stale.value.error:
            self.display_cache[repo] = stale.value

    def enter(self, definition: RepoDefinition) -> None:
        name = definition.name
        self._cancel_debounce()
        self.current = definition
        self.lifecycle_epoch[name] = self.lifecycle_epoch.get(name, 0) + 1
        self.coordinator.cancel_repo_scope(name, "enter")
        self.invalidate(name, "enter")
        self.github_loading = True
        TIMING.mark(f"select:{name}")
        TIMING.mark(f"select-gh:{name}")
        self.view.on_loading(name)
        self.needs_reload.discard(name)
        epoch = self.lifecycle_epoch[name]
        if self.scheduler is None:
            self._fire(name, epoch)
        else:
            self._debounce = self.scheduler.after(
                self.debounce_ms, lambda: self._fire(name, epoch)
            )

    def _cancel_debounce(self) -> None:
        if self._debounce is not None and self.scheduler is not None:
            self.scheduler.cancel(self._debounce)
        self._debounce = None

    def _fire(self, name: str, epoch: int) -> None:
        self._debounce = None
        if (
            self._closed
            or self.current is None
            or self.current.name != name
            or self.lifecycle_epoch.get(name) != epoch
        ):
            return
        self.submit_local(name)
        self.submit_github(name)
        self.view.on_request_suggestion(name)

    # ------------------------------------------------------------ submitting
    def submit_local(self, repo: str) -> None:
        d = self._by_name[repo]
        self.coordinator.submit(
            (repo, KIND_LOCAL), lambda cancel: self.loaders.local(d, cancel),
            pool=LOCAL_POOL, epoch=self.lifecycle_epoch[repo],
        )

    def submit_github(self, repo: str) -> None:
        d = self._by_name[repo]
        self.github_loading = True
        self.coordinator.submit(
            (repo, KIND_GITHUB), lambda cancel: self.loaders.github(d, cancel),
            pool=GITHUB_POOL, epoch=self.lifecycle_epoch[repo],
        )

    def reload_local(self, repo: str) -> None:
        """Forced LOCAL reload under the current epoch (fail closed while loading)."""
        self._local.pop(repo, None)
        self.state_generation += 1
        self.submit_local(repo)

    def submit_suggest(self, repo: str) -> None:
        d = self._by_name[repo]
        self.coordinator.submit(
            (repo, KIND_SUGGEST), lambda cancel: self.loaders.suggest(d, cancel),
            pool=LOCAL_POOL, epoch=self.lifecycle_epoch[repo],
        )

    def submit_global(self, name: str, fn: Callable, extra: dict[str, Any] | None = None) -> None:
        extra = dict(extra or {})
        if name == GLOBAL_SELF_UPDATE:
            extra["self_update_epoch"] = self.self_update_epoch
        self.coordinator.submit((GLOBAL, name), fn, pool=BACKGROUND_POOL, extra=extra)

    # ------------------------------------------------------------------ pump
    def pump(self) -> None:
        """Heartbeat: run the watchdog, then apply messages unless a dialog is open."""
        if self._closed:
            return
        self.coordinator.tick()
        if self.guard.active:
            return
        for message in self.coordinator.drain():
            self._dispatch(message)

    def _valid(self, message: WorkerResult | TerminalNotice) -> bool:
        if self._closed or not self.coordinator.is_latest(message.token, message.key):
            return False
        if message.repo is not None:
            return (
                self.current is not None
                and self.current.name == message.repo
                and message.epoch == self.lifecycle_epoch.get(message.repo)
            )
        if message.key[1] == GLOBAL_SELF_UPDATE:
            return message.extra.get("self_update_epoch") == self.self_update_epoch
        return True

    def _dispatch(self, message: WorkerResult | TerminalNotice) -> None:
        if not self._valid(message):
            return
        repo, kind = message.repo, message.key[1]
        if repo is None:
            if isinstance(message, TerminalNotice):
                self.view.on_global_notice(kind, message)
            else:
                self.view.on_global_result(kind, message)
            return
        if isinstance(message, TerminalNotice):
            self._apply_notice(repo, kind, message)
        else:
            self._apply_result(repo, kind, message)

    def _apply_result(self, repo: str, kind: str, message: WorkerResult) -> None:
        stamp_args = (message.token, message.epoch)
        if kind == KIND_LOCAL:
            if message.error is not None:
                self._local.pop(repo, None)
                self.view.on_local_unavailable(repo, f"読込失敗: {message.error}")
            else:
                self._local[repo] = Stamped(message.payload, *stamp_args)
                self.view.on_local(repo, message.payload)
            TIMING.since_mark(f"select:{repo}", record_as="select-to-LOCAL-shown")
            self.view.on_lifecycle()
            self._consume_post_notice(repo)
        elif kind == KIND_GITHUB:
            state = (
                GitHubState(error=str(message.error))
                if message.error is not None else message.payload
            )
            self._apply_github(repo, state, stamp_args)
        elif kind == KIND_SUGGEST and message.error is None:
            self.view.on_suggestion(repo, message.payload)

    def _apply_github(self, repo: str, state: GitHubState, stamp_args: tuple[int, int]) -> None:
        self._github[repo] = Stamped(state, *stamp_args)
        self.github_loading = False
        self.view.on_github(repo, state)
        if state.candidate_ready and self.provenance.auto_reflect(
            repo, state.branch_sha, self.authoritative_github(repo)
        ):
            self.view.on_candidate_text(self.provenance.text(repo))
            self.view.on_log(
                f"{repo}: expected branch HEADをcandidateへ自動反映 "
                f"{state.branch_sha[:12]} / CI={state.ci_state}"
            )
        if state.candidate_blocked_by_pr and state.latest_pr:
            self.view.on_log(
                f"{repo}: open PR #{state.latest_pr.number} は表示のみ。"
                f"candidateはexpected branch HEAD {state.branch_sha[:12]} を使用します。"
            )
        TIMING.since_mark(f"select-gh:{repo}", record_as="select-to-GITHUB-shown")
        self.view.on_lifecycle()

    def _apply_notice(self, repo: str, kind: str, notice: TerminalNotice) -> None:
        if kind == KIND_LOCAL:
            self._local.pop(repo, None)
            self.view.on_local_unavailable(repo, self._local_notice_text(notice))
            self.view.on_lifecycle()
            self._consume_post_notice(repo)
        elif kind == KIND_GITHUB:
            text = (
                notice.message if notice.kind is NoticeKind.ABANDON_CAP
                else "GitHub取得タイムアウト"
            )
            self._apply_github(repo, GitHubState(error=text), (notice.token, notice.epoch))

    @staticmethod
    def _local_notice_text(notice: TerminalNotice) -> str:
        if notice.kind is NoticeKind.ABANDON_CAP:
            return loader.ABANDON_CAP_MESSAGE
        return "読込タイムアウト（ファイルシステム/gitが応答しません）— 「再読込」で再試行"

    def _consume_post_notice(self, repo: str) -> None:
        text = self.post_action_notice.pop(repo, None)
        if text:
            self.view.on_post_notice(text)

    # ----------------------------------------------------------------- close
    def close(self) -> None:
        self._closed = True
        self._cancel_debounce()
        self.coordinator.close()
