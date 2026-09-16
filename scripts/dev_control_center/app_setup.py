"""Final Control Center UI semantics for repository setup/bootstrap.

The base App owns lifecycle execution. This wrapper changes the first action from
"start a ChatGPT session" to "bring the selected repo onto the canonical
Development Control Center lifecycle".
"""

from __future__ import annotations

import argparse
import sys
import tkinter as tk
from tkinter import messagebox

from .app import App as BaseApp, self_check
from .core import ControlCenterConfigError, RepoDefinition, RepoEntrypoints


def build_setup_prompt(definition: RepoDefinition, entrypoints: RepoEntrypoints) -> str:
    """Build a repo-specific bootstrap/standards prompt from detected entrypoints."""
    release_name = entrypoints.release_label
    return (
        f"対象repo: {definition.full_name}\n"
        f"expected branch: {definition.branch}\n"
        f"repo type: {definition.repo_type}\n\n"
        "このrepoを Development Control Center の標準ライフサイクルへSETUPしてください。\n"
        "development-management/OPERATING_CONTRACT.md と PROJECT_BOOTSTRAP.md を正本として扱ってください。\n\n"
        "Control Centerの現在検出:\n"
        f"- SYNC: {entrypoints.sync.state}\n"
        f"- RUN_DEV: {entrypoints.run.state}\n"
        f"- BUILD: {entrypoints.build.state}\n"
        f"- {release_name}: {entrypoints.release.state}\n\n"
        "A — ChatGPT fast pathでGitHub上の対象repoを確認し、既存資産を壊さず標準運用へ載せてください。\n"
        "READYの正式入口は原則作り直さず、MISSING / MULTIPLEだけを優先して解消してください。\n"
        "Windows desktop repoでは、必要に応じて tracked な SYNC_CLICK_ME.cmd / scripts/SYNC_CANDIDATE.ps1、"
        "RUN_DEV.cmd、BUILD_EXE_CLICK_ME.cmd、UPDATE_SHARED_FOLDER.cmd（またはそのrepoの正式同等入口）を整備してください。\n"
        "SYNCは完全40桁candidate SHAを固定し、expected origin / branch / tracked cleanを確認し、"
        "reset --hard / stash / 自動branch切替でローカル作業を消さないfail-close設計にしてください。\n"
        "実運用データ・秘密情報はGit管理へ入れないでください。development-management側の登録が既にある場合は重複追加しません。\n"
        "必要なテストと利用可能な自動検証を行い、expected branchへ反映してください。GitHub Actionsは補助検証です。\n"
        "完了時は、各入口のREADY/MISSING状態、変更内容、未確認事項、完全40桁candidate SHAを明示してください。\n"
        "candidate確定後はここで停止し、RUN / BUILD / UPDATEは実行しないでください。"
    )


class App(BaseApp):
    """Base Control Center with setup/bootstrap semantics for the first button."""

    def _build(self) -> None:
        super()._build()
        self.startup_button.configure(text="SETUP / 標準化")

    def copy_startup_set(self) -> None:
        if not self.current or not self.entrypoints:
            return
        prompt = build_setup_prompt(self.current, self.entrypoints)
        self._copy_to_clipboard(prompt)
        self._log(f"{self.current.name}: 標準ライフサイクルSETUP指示をコピーしました。")
        messagebox.showinfo(
            "SETUP / 標準化",
            "選択repoをControl Center標準運用へ載せるSETUP指示をコピーしました。\n現在のChatGPTへ貼り付けてください。",
        )


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
