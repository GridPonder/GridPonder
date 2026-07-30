"""Confine the agent to its sandbox directory.

Without this the sandbox is a convention, not a boundary: the agent process
inherits the invoking user's filesystem view, so `open()` on the pack returns
the level JSON — board, action limit, and gold path included. Everything the
socket protocol withholds is then one file read away, and a benchmark score
means nothing beyond "the agent chose not to look".

Two mechanisms, same interface:

`bwrap` — bubblewrap, unprivileged user namespaces, no daemon, no root, and a
few milliseconds of setup. The agent gets a root filesystem assembled from
read-only host paths plus its own sandbox, and nothing else. This is the default
because a sweep starts one per level and the confinement that matters here is
filesystem-only.

`docker` — a container. Slower to start and needs an image that already has the
agent CLI in it, and in exchange it can cap memory and CPU, cut the network
entirely, and run the same way on someone else's machine. Reach for it when a
benchmark result has to be reproducible off this laptop.

Paths that were never mounted do not exist for the agent — ENOENT, not
"permission denied", which invites retries.

Network is shared by default under both, because a hosted model is unreachable
without it. That is the deliberate hole: the agent can talk to its API, not to
the filesystem. Under docker it can be closed with `network="none"`, which is
worth doing for any agent that runs locally.
"""
from __future__ import annotations

import functools
import os
import shutil
import subprocess
from pathlib import Path

MODES = ("none", "bwrap", "docker")

# Read-only system paths the agent needs to run at all. Anything absent on the
# host is skipped rather than failing the run: distributions disagree about
# which of these are real directories and which are compatibility symlinks.
_SYSTEM_ROBIND = ("/usr", "/etc", "/opt")
# Merged-/usr layouts expose these as symlinks; recreate them rather than
# binding, so the sandbox matches the host's own resolution.
_MERGED_LINKS = {"/bin": "usr/bin", "/sbin": "usr/sbin",
                 "/lib": "usr/lib", "/lib64": "usr/lib64"}
# Files under /etc that are commonly symlinks pointing *outside* /etc, which
# binding /etc alone leaves dangling. On systemd-resolved hosts
# /etc/resolv.conf points into /run, so without this DNS fails inside the
# sandbox and a hosted agent cannot reach its API at all.
_RESOLVED_FILES = ("/etc/resolv.conf",)

# Default image for docker mode. It has to contain the agent CLI already —
# see Dockerfile next to this module, and `docker_image` in harness.yaml.
DEFAULT_IMAGE = "gridponder-harness:latest"
# Probe used to prove a path is out of reach. `sh -c test` rather than python,
# because a container image is not obliged to ship an interpreter.
_EXISTS_PROBE = '[ -e "$1" ] && exit 1 || exit 0'



class IsolationUnavailable(RuntimeError):
    """The requested confinement cannot be provided on this host."""


def available(mode: str) -> bool:
    if mode == "none":
        return True
    if mode == "bwrap":
        return shutil.which("bwrap") is not None and _userns_allowed()
    if mode == "docker":
        if shutil.which("docker") is None:
            return False
        # A docker binary with no reachable daemon is the common failure, and
        # it fails at `docker run` rather than at import, i.e. after the sweep
        # has already started.
        probe = subprocess.run(["docker", "info"], capture_output=True)
        return probe.returncode == 0
    raise ValueError(f"unknown isolation mode: {mode!r}")


def image_exists(image: str) -> bool:
    return subprocess.run(["docker", "image", "inspect", image],
                          capture_output=True).returncode == 0


@functools.lru_cache(maxsize=8)
def _supports_no_new_privileges(image: str) -> bool:
    """Whether this host can run the image with `no-new-privileges`.

    Some Docker/AppArmor combinations refuse to exec anything at all under that
    flag ("operation not permitted" before the command runs). Probed rather
    than assumed, because the alternative is either dropping a hardening flag
    everywhere or having every container fail on hosts where it works fine.
    Capabilities are dropped and the process runs non-root regardless, so this
    is defence in depth rather than the boundary itself.
    """
    probe = subprocess.run(
        ["docker", "run", "--rm", "--security-opt", "no-new-privileges",
         image, "true"],
        capture_output=True,
    )
    return probe.returncode == 0


def _userns_allowed() -> bool:
    """bwrap needs unprivileged user namespaces, which some hosts disable."""
    knob = Path("/proc/sys/kernel/unprivileged_userns_clone")
    if knob.is_file():
        try:
            return knob.read_text().strip() != "0"
        except OSError:
            return False
    return True


def wrap(
    argv: list[str],
    *,
    sandbox: Path,
    mode: str = "bwrap",
    credentials: list[Path] | None = None,
    tools: list[Path] | None = None,
    writable: list[Path] | None = None,
    env: dict[str, str] | None = None,
    image: str = DEFAULT_IMAGE,
    network: str = "bridge",
    memory: str | None = None,
    cpus: str | None = None,
) -> list[str]:
    """Return `argv` rewritten to run confined to `sandbox`.

    `credentials` are host paths exposed read-write so a hosted agent can reach
    its own API keys and session state; a *directory* named here is replaced by
    an empty tmpfs rather than exposed, because a credential directory usually
    also holds history. `tools` are read-only, for an agent whose own program
    lives in this repo and would otherwise be as invisible as the pack.
    Everything on either list is visible to the agent, so neither may name
    anything under the pack tree.

    The sandbox is mounted at its real absolute path under both mechanisms.
    `play` resolves the socket relative to its own location, so moving it would
    break the one channel the agent is supposed to have.

    `env` is the environment the agent needs that the mechanism would otherwise
    drop. bwrap inherits the caller's environment, so it is only strictly needed
    for docker, which starts from the image's — an API key exported in the shell
    simply is not there, and the agent fails to authenticate with nothing in the
    isolation layer to explain why.

    `image`, `network`, `memory` and `cpus` apply to docker mode only.
    """
    if mode == "none":
        return list(argv)
    if mode == "docker":
        return _docker_wrap(argv, sandbox=sandbox, credentials=credentials,
                            tools=tools, writable=writable, env=env,
                            image=image, network=network, memory=memory,
                            cpus=cpus)
    if mode != "bwrap":
        raise ValueError(f"unknown isolation mode: {mode!r}")
    if not available("bwrap"):
        raise IsolationUnavailable(
            "bwrap is missing or unprivileged user namespaces are disabled; "
            "install bubblewrap or pass --isolation none and treat the scores "
            "as unverified"
        )

    sandbox = sandbox.resolve()
    cmd = [
        "bwrap",
        # Reap the agent if the supervisor dies, so a crash cannot leave a
        # model running against a socket nobody is listening on.
        "--die-with-parent",
        "--unshare-all", "--share-net",
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
    ]
    for path in _SYSTEM_ROBIND:
        if Path(path).is_dir():
            cmd += ["--ro-bind", path, path]
    for link, target in _MERGED_LINKS.items():
        if Path(link).is_symlink():
            cmd += ["--symlink", target, link]
        elif Path(link).is_dir():
            cmd += ["--ro-bind", link, link]
    # Bind the directory the symlink points *into*, not the file itself:
    # /etc is read-only here, so bwrap cannot create a mount point on top of a
    # dangling link, but giving the link a real target works.
    for path in _RESOLVED_FILES:
        link = Path(path)
        if not link.is_symlink():
            continue
        target_dir = link.resolve().parent
        if target_dir.is_dir():
            cmd += ["--ro-bind", str(target_dir), str(target_dir)]

    home = Path(os.path.expanduser("~"))
    cmd += ["--tmpfs", str(home)]
    for cred in credentials or []:
        cred = Path(cred)
        if not cred.exists():
            continue
        if cred.is_dir():
            # Never bind a whole credential directory. ~/.claude holds the
            # transcript of every past session, and on this repo those contain
            # printed gold paths — an agent with Bash could grep the answer out
            # of its own tool's history. A tmpfs gives the CLI somewhere to
            # write without showing it anything that was there before.
            cmd += ["--tmpfs", str(cred)]
        else:
            cmd += ["--bind", str(cred), str(cred)]
    for tool in tools or []:
        tool = Path(tool).resolve()
        if tool.exists():
            cmd += ["--ro-bind", str(tool), str(tool)]
    # After the tmpfs mounts above, so a path under /tmp — where a socket goes
    # when the sandbox path is too long for AF_UNIX — survives into the
    # namespace. Read-write because connecting to a unix socket needs it.
    for path in writable or []:
        path = Path(path)
        if path.exists():
            cmd += ["--bind", str(path), str(path)]

    cmd += [
        "--bind", str(sandbox), str(sandbox),
        "--chdir", str(sandbox),
        "--setenv", "HOME", str(home),
        "--",
    ]
    return cmd + list(argv)


def _docker_wrap(
    argv: list[str],
    *,
    sandbox: Path,
    credentials: list[Path] | None,
    tools: list[Path] | None,
    writable: list[Path] | None,
    env: dict[str, str] | None,
    image: str,
    network: str,
    memory: str | None,
    cpus: str | None,
) -> list[str]:
    """Run the agent in a container.

    Nothing of the host filesystem is mounted except the sandbox and whatever
    was explicitly listed, so the repo is absent by construction rather than by
    an unmount — the container starts from the image's own root. That is the
    real difference from bwrap, where the default is "share everything" and
    every hidden path is one we remembered to hide.

    The agent runs as the invoking uid so files it leaves in the sandbox belong
    to the user rather than to root.
    """
    if not available("docker"):
        raise IsolationUnavailable(
            "docker is missing or its daemon is unreachable; use "
            "--isolation bwrap, or --isolation none and treat the scores as "
            "unverified"
        )
    if not image_exists(image):
        raise IsolationUnavailable(
            f"image {image!r} is not present. Build it with:\n"
            f"    docker build -t {image} "
            f"{Path(__file__).resolve().parent}\n"
            f"The image has to contain the agent CLI; the sandbox provides "
            f"only RULES.md and ./play."
        )

    sandbox = sandbox.resolve()
    home = Path(os.path.expanduser("~"))
    cmd = [
        "docker", "run", "--rm", "-i",
        f"--network={network}",
        # The agent has no reason to gain privileges, and a benchmark should
        # not be the thing that finds out otherwise.
        "--cap-drop", "ALL",
        f"--user={os.getuid()}:{os.getgid()}",
        # An empty home, so a credential *file* can be mounted into it without
        # dragging along whatever else the host keeps there.
        "--tmpfs", f"{home}:exec",
        "--env", f"HOME={home}",
    ]
    # A container does not inherit the caller's environment. Whatever the agent
    # adapter asked for has to be named, or a hosted model arrives with no
    # credentials and fails in a way that looks like a bad run rather than a
    # missing variable. Only what the adapter listed: forwarding the whole
    # environment would put the repo's own paths back inside the container.
    for key, value in (env or {}).items():
        cmd += ["--env", f"{key}={value}"]
    if _supports_no_new_privileges(image):
        cmd += ["--security-opt", "no-new-privileges"]
    if memory:
        cmd += [f"--memory={memory}"]
    if cpus:
        cmd += [f"--cpus={cpus}"]

    for cred in credentials or []:
        cred = Path(cred)
        if not cred.exists():
            continue
        if cred.is_dir():
            # Same rule as bwrap: a credential directory is history as well as
            # credentials, so it becomes an empty writable mount.
            cmd += ["--tmpfs", f"{cred}:exec"]
        else:
            cmd += ["-v", f"{cred}:{cred}"]
    for tool in tools or []:
        tool = Path(tool).resolve()
        if tool.exists():
            cmd += ["-v", f"{tool}:{tool}:ro"]
    for path in writable or []:
        path = Path(path)
        if path.exists():
            cmd += ["-v", f"{path}:{path}"]

    cmd += [
        "-v", f"{sandbox}:{sandbox}",
        f"--workdir={sandbox}",
        image,
    ]
    return cmd + list(argv)


def verify(sandbox: Path, must_be_unreadable: Path, *, mode: str = "bwrap",
           must_be_visible: list[Path] | None = None, **kwargs) -> None:
    """Raise unless `must_be_unreadable` really is out of reach from inside.

    Called before a scored sweep. The mount list is easy to widen by accident —
    one extra bind for a missing library, one credential directory that also
    holds history — and a leak here silently invalidates every number
    downstream, so it is checked against the live configuration rather than
    assumed. `kwargs` are forwarded to `wrap`, so the check runs against the
    same image and mounts the agent will get.
    """
    if mode == "none":
        return
    # Positive control first. A mount that silently does not work looks exactly
    # like an agent that played badly: on a daemon started with PrivateTmp, a
    # `-v /tmp/x:/tmp/x` bind mounts an empty directory instead of the host's,
    # so the agent finds no RULES.md and scores zero without anything failing.
    sentinel = sandbox / ".mount-check"
    sentinel.write_text("ok", encoding="utf-8")
    required = [sentinel, *(must_be_visible or [])]
    try:
        for path in required:
            reachable = subprocess.run(
                wrap(["/bin/sh", "-c", _EXISTS_PROBE, "sh", str(path)],
                     sandbox=sandbox, mode=mode, **kwargs),
                capture_output=True, text=True,
            )
            # The probe exits 1 when the path exists, which here is success.
            if reachable.returncode == 0:
                raise IsolationUnavailable(
                    f"{path} is not visible inside the confinement, so the "
                    f"agent would score zero without anything failing. Under "
                    f"docker this usually means the daemon runs with a "
                    f"private /tmp; keep the sandbox and the socket off /tmp "
                    f"({reachable.stdout}{reachable.stderr})".strip()
                )
    finally:
        sentinel.unlink(missing_ok=True)

    argv = wrap(
        ["/bin/sh", "-c", _EXISTS_PROBE, "sh", str(must_be_unreadable)],
        sandbox=sandbox, mode=mode, **kwargs,
    )
    result = subprocess.run(argv, capture_output=True, text=True)
    if result.returncode != 0:
        raise IsolationUnavailable(
            f"{must_be_unreadable} is reachable from inside the sandbox; "
            f"refusing to score a run the agent could have read the answer in "
            f"({result.stdout}{result.stderr})".strip()
        )
