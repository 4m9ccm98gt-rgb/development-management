"""Final Control Center UI semantics for repository setup/bootstrap.

The base App owns normal lifecycle execution. This wrapper makes SETUP mean
"bring the selected repo onto the canonical lifecycle" and provides a single
central bootstrap-sync only when that repo does not yet have its own formal
SYNC entrypoint.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox

from .app import App as BaseApp, DM_ROOT, REPOS_ROOT, self_check
from .core import ControlCenterConfigError, candidate_sha_is_valid


class App(BaseApp):
    """Control Center with repo bootstrap semantics and one-time central SYNC."""

    def _build(self) -> None:
        super()._build()

    def _set_button_states(self) -> None:
        super()._set_button_states()
        if not self.current or not self.entrypoints:
            return

        missing_sync = self.entrypoints.sync.state == "MISSING"
        self.sync_button.configure(text="SYNC (初回)" if missing_sync else "SYNC")
        if not missing_sync:
            return

        busy = self.active_process is not None
        safe = bool(self.repo_state and self.repo_state.safe_for_lifecycle(self.current))
        candidate = self.candidate_var.get().strip()
        if safe and not busy and candidate_sha_is_valid(candidate) and not self._candidate_matches_local():
            self.sync_button.configure(state="normal")

    def launch(self, action: str) -> None:
        if (
            action == "sync"
            and self.current
            and self.entrypoints
            and self.entrypoints.sync.state == "MISSING"
        ):
            self._launch_bootstrap_sync()
            return
        super().launch(action)

    def _launch_bootstrap_sync(self) -> None:
        if not self.current or not self.repo_state or self.active_process is not None:
            return
        if not self.repo_state.safe_for_lifecycle(self.current):
            messagebox.showerror("STOP", "正式repo / branch / origin / tracked clean の安全条件を満たしていません。")
            return

        candidate = self.candidate_var.get().strip()
        if not candidate_sha_is_valid(candidate):
            messagebox.showerror("STOP", "candidateは完全40桁SHAで指定してください。")
            return
        if self._candidate_matches_local():
            return

        repo_root = REPOS_ROOT / self.current.name
        script = DM_ROOT / "scripts" / "BOOTSTRAP_REPO_SYNC.ps1"
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-RepoRoot",
            str(repo_root),
            "-ExpectedRepo",
            self.current.full_name,
            "-TargetBranch",
            self.current.branch,
            "-ExpectedSha",
            candidate,
        ]
        try:
            flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            process = subprocess.Popen(command, cwd=repo_root, creationflags=flags)
        except OSError as exc:
            messagebox.showerror("初回SYNC起動失敗", str(exc))
            return

        self.active_process = (process, self.current.name, "sync")
        self._log(f"{self.current.name}: 中央bootstrap SYNC → {candidate[:12]}")
        self.banner_var.set("初回SYNC実行中。正式SYNC入口を含むcandidateへ安全にfast-forwardします。")
        self._set_button_states()
        self.master.after(750, self._poll)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args(argv)
    if args.self_check:
        return self_check()
    try:
        root = tk.Tk()
        App(root)
        root.mainloop()
    except (OSError, ControlCenterConfigError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
