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


def test_install_removes_old_ti_lex_alias_that_would_hide_the_command(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / "scripts" / "installer-raccourci.sh")
    home = tmp_path / "home"
    home.mkdir()
    bashrc = home / ".bashrc"
    bashrc.write_text("export A=1\n\n# >>> lexos (ti-lex) >>>\n"
                      "alias ti-lex='PYTHONPATH=\"/vieux\" python3 -m lexos'\n"
                      "alias lexos='ti-lex'\n# <<< lexos (ti-lex) <<<\nexport B=2\n")
    env = {**os.environ, "HOME": str(home)}
    for _ in range(2):                                   # relançable sans risque
        subprocess.run(["bash", str(repo / "scripts" / "installer-raccourci.sh")],
                       check=True, capture_output=True, text=True, env=env)
    texte = bashrc.read_text()
    assert "alias ti-lex" not in texte and "alias lexos" not in texte
    assert "export A=1" in texte and "export B=2" in texte   # le reste n'est pas touché
    assert (home / ".bashrc.ti-lex.bak").is_file()


# ------------------------------------------------------------------ Termux (téléphone)
TERMUX = Path(__file__).resolve().parent.parent / "scripts" / "installer-termux.sh"


def _termux(tmp_path, *args):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True, exist_ok=True)
    for script in (SCRIPT, TERMUX):
        shutil.copy(script, repo / "scripts" / script.name)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    fakebin = tmp_path / "bin"
    fakebin.mkdir(exist_ok=True)
    (fakebin / "pkg").write_text('#!/usr/bin/env bash\necho "$*" >> "$HOME/pkg.log"\n')
    (fakebin / "curl").write_text("#!/usr/bin/env bash\nexit 7\n")      # le PC ne répond pas
    for f in fakebin.iterdir():
        f.chmod(0o755)
    env = {**os.environ, "HOME": str(home), "PATH": f"{fakebin}:{os.environ['PATH']}",
           "PREFIX": "/data/data/com.termux/files/usr", "TILEX_SKIP_PIP": "1",
           "TILEX_PYTHON": shutil.which("python3")}
    done = subprocess.run(["bash", str(repo / "scripts" / "installer-termux.sh"), *args],
                          capture_output=True, text=True, env=env)
    return done, home


def test_termux_installe_les_paquets_et_le_raccourci(tmp_path):
    done, home = _termux(tmp_path)
    assert done.returncode == 0, done.stderr
    assert "install -y python git curl" in (home / "pkg.log").read_text()
    assert (home / ".local" / "bin" / "ti-lex").is_file()
    assert (tmp_path / "repo" / ".venv" / "bin" / "python").exists()
    assert "pkg install ollama" in done.stdout              # IA sur le téléphone : explique
    assert "OLLAMA_HOST" not in (home / ".bashrc").read_text()


def test_termux_avec_ip_du_pc_relancable_sans_doublon(tmp_path):
    _termux(tmp_path, "192.168.0.42", "11434")
    done, home = _termux(tmp_path, "192.168.0.50", "11434")  # nouvelle IP : remplace
    assert done.returncode == 0, done.stderr
    texte = (home / ".bashrc").read_text()
    assert texte.count('export OLLAMA_HOST="http://192.168.0.50:11434"') == 1
    assert "192.168.0.42" not in texte
    assert "ne répond pas" in done.stdout
