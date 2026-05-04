import subprocess


def safe_exec(
    args: list[str],
    cwd: str | None = None,
    capture_output: bool = False,
    check: bool = False,
) -> subprocess.CompletedProcess:
    """Run a subprocess with shell disabled. Args must be a pre-split list."""
    return subprocess.run(args, shell=False, cwd=cwd, capture_output=capture_output, check=check)
