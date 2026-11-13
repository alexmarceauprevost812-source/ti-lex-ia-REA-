"""Le raccourci `ti-lex` : créé par scripts/installer-raccourci.sh."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "installer-raccourci.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash requis")


def _install(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / "scripts" / "installer-raccourci.sh")
    home = tmp_path / "home"
    home.mkdir()
    env = {**os.environ, "HOME": str(home)}
    subprocess.run(["bash", str(repo / "scripts" / "installer-raccourci.sh")],
                   check=True, capture_output=True, text=True, env=env)
    return repo, home, env


def test_creates_executable_ti_lex_command(tmp_path):
    _, home, _ = _install(tmp_path)
    cmd = home / ".local" / "bin" / "ti-lex"
    assert cmd.is_file() and os.access(cmd, os.X_OK)


def test_shortcut_starts_the_tui_with_default_models(tmp_path):
    repo, home, env = _install(tmp_path)
    stub = repo / ".venv" / "bin" / "lexos-tui"
    stub.parent.mkdir(parents=True)
    stub.write_text('#!/usr/bin/env bash\necho "rea=$TILEX_REA_MODEL chat=$TILEX_CHAT_MODEL '
                    'cwd=$(pwd) args=$*"\n')
    stub.chmod(0o755)
    out = subprocess.run([str(home / ".local" / "bin" / "ti-lex"), "--workspace", "x"],
                         capture_output=True, text=True, env=env, check=True).stdout
    assert "rea=marceau-ia" in out and "chat=asselin" in out
    assert f"cwd={repo.resolve()}" in out and "args=--workspace x" in out


def test_shortcut_models_can_be_overridden(tmp_path):
    repo, home, env = _install(tmp_path)
    stub = repo / ".venv" / "bin" / "lexos-tui"
    stub.parent.mkdir(parents=True)
    stub.write_text('#!/usr/bin/env bash\necho "rea=$TILEX_REA_MODEL"\n')
    stub.chmod(0o755)
    out = subprocess.run([str(home / ".local" / "bin" / "ti-lex")], capture_output=True,
                         text=True, check=True, env={**env, "TILEX_REA_MODEL": "autre"}).stdout
    assert "rea=autre" in out


def test_shortcut_explains_when_not_installed(tmp_path):
    _, home, env = _install(tmp_path)
    done = subprocess.run([str(home / ".local" / "bin" / "ti-lex")], capture_output=True,
                          text=True, env=env)
    assert done.returncode == 1
    assert "pip install -e ." in done.stderr
