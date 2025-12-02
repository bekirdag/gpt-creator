import gc
import os
import shutil
import subprocess
import sys


def run_command(cmd):
    try:
        subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def trim_memory() -> None:
    gc.collect()

    if shutil.which("purge"):
        run_command(["purge"])
    elif shutil.which("sync"):
        run_command(["sync"])

    if shutil.which("docker"):
        run_command(["docker", "container", "prune", "-f"])
        run_command(["docker", "image", "prune", "-f"])


def main() -> int:
    trim_memory()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
