from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class UpdateStatus:
    title: str
    detail: str
    can_install: bool = False


class UpdateManager:
    def __init__(self, project_dir: Path, install_method: str = "source"):
        self.project_dir = project_dir
        self.install_method = install_method

    def check(self) -> UpdateStatus:
        if self.install_method == "homebrew":
            return UpdateStatus(
                "Managed by Homebrew",
                "This vplay install is managed by Homebrew. Update it from the shell with:\n\nbrew update && brew upgrade vplay",
            )
        if self.install_method == "portable":
            return UpdateStatus(
                "Portable build",
                "This vplay install is a portable binary. Download the latest macOS binary from:\n\nhttps://github.com/rztrace/vplay/releases/latest\n\nThen replace this executable.",
            )
        if not (self.project_dir / ".git").is_dir():
            return UpdateStatus("No update source", "This vplay checkout is not initialized as a git repository.")
        branch = self._git("branch", "--show-current").stdout.strip()
        if not branch:
            return UpdateStatus("Detached checkout", "vplay is not on a branch. Updates need a branch with an upstream.")
        upstream = self._git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", check=False)
        if upstream.returncode != 0:
            return UpdateStatus(
                "No update remote",
                "The vplay repository is ready, but this branch has no upstream remote yet.",
            )
        fetch = self._git("fetch", "--quiet", check=False)
        if fetch.returncode != 0:
            return UpdateStatus("Update check failed", (fetch.stderr or fetch.stdout).strip() or "git fetch failed")
        local = self._git("rev-parse", "HEAD").stdout.strip()
        remote = self._git("rev-parse", "@{u}").stdout.strip()
        if local == remote:
            return UpdateStatus("vplay is current", f"Branch {branch} is already at {local[:10]}.")
        changes = self._git("diff", "--name-only", "HEAD..@{u}", check=False).stdout.splitlines()
        binary = next((item for item in changes if item in {"dist/vplay", "bin/vplay"} or item.startswith("dist/vplay")), "")
        detail = f"Upstream has {remote[:10]} available for branch {branch}."
        if binary:
            detail += f"\nUpdate binary found: {binary}"
        else:
            detail += "\nNo packaged binary was found; install will fast-forward the source checkout and reinstall the package."
        if self._dirty():
            detail += "\nWorking tree has local edits, so install is blocked until they are committed or stashed."
            return UpdateStatus("Update available", detail, can_install=False)
        return UpdateStatus("Update available", detail, can_install=True)

    def install(self) -> UpdateStatus:
        if self.install_method == "homebrew":
            return UpdateStatus("Managed by Homebrew", "Run: brew update && brew upgrade vplay")
        if self.install_method == "portable":
            return UpdateStatus(
                "Portable build",
                "Download the latest macOS binary from https://github.com/rztrace/vplay/releases/latest and replace this executable.",
            )
        if self._dirty():
            return UpdateStatus("Install blocked", "Working tree has local edits. Commit or stash them before updating.")
        pull = self._git("pull", "--ff-only", check=False)
        if pull.returncode != 0:
            return UpdateStatus("Install failed", (pull.stderr or pull.stdout).strip() or "git pull failed")
        pip = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", str(self.project_dir)],
            capture_output=True,
            text=True,
        )
        if pip.returncode != 0:
            return UpdateStatus("Package reinstall failed", (pip.stderr or pip.stdout).strip())
        return UpdateStatus("Update installed", "vplay was updated. Restart vplay to run the new code.")

    def _dirty(self) -> bool:
        return bool(self._git("status", "--porcelain", check=False).stdout.strip())

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", "-C", str(self.project_dir), *args],
            capture_output=True,
            text=True,
        )
        if check and result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout).strip())
        return result
