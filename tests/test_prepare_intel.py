"""Intel dependency preparation rejects unsupported hosts and unverified sources."""
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "macapp/prepare_intel.sh"


def command(folder, name, body):
    path = folder / name
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(0o755)
    return path


@pytest.mark.parametrize("system,architecture,translated", [
    ("Darwin", "arm64", "0"),
    ("Linux", "x86_64", "0"),
    ("Darwin", "x86_64", "1"),
])
def test_unsupported_host_stops_before_downloads(tmp_path, system, architecture, translated):
    commands = tmp_path / "bin"
    commands.mkdir()
    command(commands, "uname", f'if [[ "$1" == "-s" ]]; then echo {system}; else echo {architecture}; fi\n')
    command(commands, "sysctl", f"echo {translated}\n")
    marker = tmp_path / "download-attempt"
    command(commands, "curl", f'touch "{marker}"\nexit 97\n')
    output = tmp_path / "prepared"
    result = subprocess.run(["bash", str(SCRIPT), "python3.12", str(output)],
                            env={**os.environ, "PATH": f"{commands}:{os.environ['PATH']}"},
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert "native Intel macOS" in result.stderr
    assert not marker.exists()
    assert not output.exists()


def test_openssl_checksum_failure_stops_before_source_execution(tmp_path):
    commands = tmp_path / "bin"
    commands.mkdir()
    command(commands, "uname", 'if [[ "$1" == "-s" ]]; then echo Darwin; else echo x86_64; fi\n')
    command(commands, "sysctl", "echo 0\n")
    python = command(commands, "python", "exit 0\n")
    command(commands, "rustup", "exit 0\n")
    command(commands, "curl", '''while [[ "$#" -gt 0 ]]; do
  if [[ "$1" == "--output" ]]; then printf tampered > "$2"; exit 0; fi
  shift
done
exit 98
''')
    marker = tmp_path / "archive-executed"
    command(commands, "tar", f'touch "{marker}"\nexit 96\n')
    output = tmp_path / "prepared"
    result = subprocess.run(["bash", str(SCRIPT), str(python), str(output)],
                            env={**os.environ, "PATH": f"{commands}:{os.environ['PATH']}"},
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert "checksum" in (result.stdout + result.stderr).lower()
    assert not marker.exists()
    assert not output.exists()
