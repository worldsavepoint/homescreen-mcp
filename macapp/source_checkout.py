"""Export the exact tracked project inputs used for an official native build."""
import argparse
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile


def export_project(root, target):
    commit = subprocess.check_output(["git", "-C", root, "rev-parse", "--verify", "HEAD"], text=True).strip()
    if subprocess.check_output(["git", "-C", root, "status", "--porcelain", "--untracked-files=all"]):
        raise ValueError("Use a clean release checkout or a local source rebuild")
    target.mkdir()
    with subprocess.Popen(["git", "-C", root, "archive", commit], stdout=subprocess.PIPE) as git:
        with tarfile.open(fileobj=git.stdout, mode="r|") as archive:
            for member in archive:
                name = PurePosixPath(member.name)
                if name.is_absolute() or any(p in ("..", ".git") for p in name.parts):
                    raise ValueError("Invalid tracked release member")
                path = target / name
                if member.isdir():
                    path.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("xb") as file:
                        shutil.copyfileobj(archive.extractfile(member), file)
                    path.chmod(0o755 if member.mode & 0o111 else 0o644)
                else:
                    raise ValueError("Unsupported tracked release member type")
        if git.wait():
            raise ValueError("Could not export release commit")
    return commit


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        print(export_project(args.root, args.destination))
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{error}\n")
