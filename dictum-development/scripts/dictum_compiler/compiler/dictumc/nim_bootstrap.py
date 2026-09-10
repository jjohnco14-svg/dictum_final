"""
dictumc.nim_bootstrap — makes `--backend nim` work with zero manual setup.

Problem this closes: `dictumc_cli.py --backend nim --run` used to shell
out to a bare `nim` on PATH (`_compile_nim()` in dictumc_cli.py), which
meant every user had to separately `apt install nim` / download it
themselves before the Nim backend did anything. That's the "other
download" this module removes: dictumc now finds or fetches its own
Nim compiler the same way it already auto-provisions its own models
in the sibling agent-product line -- check for a local copy first,
fetch a real one if there isn't one, then get on with the actual work.

Resolution order, first hit wins:
  1. A previously-vendored Nim under VENDOR_DIR (from a prior run of
     this same bootstrap) -- so the download only ever happens once
     per machine.
  2. `nim` already on PATH -- respects a real existing install (apt,
     choosenim, homebrew, ...) instead of duplicating it.
  3. Auto-download the official prebuilt release for this OS/arch from
     nim-lang.org into VENDOR_DIR, extract it, verify it actually
     runs, and use that from then on.
  4. macOS has no official prebuilt tarball -- try Homebrew if it's
     present (`brew install nim`), otherwise raise a clear, actionable
     error rather than silently failing or guessing a path.

Nothing here downloads or installs anything the FIRST time
`get_nim_executable()` is called with `auto_install=False` -- callers
that only want to *check* availability (e.g. a `--check-nim` flag)
should pass that.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from typing import Optional

# Bump this when a new Nim stable lands. Confirmed via nim-lang.org as
# the current stable release at the time this module was written
# (2.2.10, released 2026-04-24) -- update the version string here,
# nothing else needs to change, since every URL below is built from it.
NIM_VERSION = "2.2.10"

COMPILER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR_DIR = os.path.join(COMPILER_DIR, "vendor", "nim")

_DOWNLOAD_TIMEOUT = 300  # seconds; the Windows archive bundles MinGW and runs ~120MB


class NimBootstrapError(RuntimeError):
    """Raised when no usable Nim compiler could be found or installed."""


def _platform_key() -> str:
    """A short, stable key identifying this OS+arch for the vendor dir."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    is_64 = machine in ("x86_64", "amd64") or sys.maxsize > 2**32
    if system == "linux":
        return "linux_x64" if is_64 else "linux_x32"
    if system == "windows":
        return "windows_x64" if is_64 else "windows_x32"
    if system == "darwin":
        return "macos"
    return f"{system}_{machine}"


def _vendored_nim_path() -> str:
    """Where a vendored Nim's `nim` executable would live, if present."""
    exe = "nim.exe" if platform.system().lower() == "windows" else "nim"
    return os.path.join(VENDOR_DIR, _platform_key(), "bin", exe)


def _verify_nim(nim_path: str) -> bool:
    """Actually run `nim --version` -- existence of the file is not enough
    (a partial download or bad extraction can leave a non-executable or
    broken binary behind)."""
    if not os.path.isfile(nim_path):
        return False
    try:
        result = subprocess.run(
            [nim_path, "--version"],
            capture_output=True, text=True, timeout=15,
        )
        return result.returncode == 0 and "Nim Compiler" in result.stdout
    except (OSError, subprocess.SubprocessError):
        return False


def _download_url() -> Optional[str]:
    key = _platform_key()
    if key == "linux_x64":
        return f"https://nim-lang.org/download/nim-{NIM_VERSION}-linux_x64.tar.xz"
    if key == "linux_x32":
        return f"https://nim-lang.org/download/nim-{NIM_VERSION}-linux_x32.tar.xz"
    if key == "windows_x64":
        # Bundles MinGW, so Windows users also get a working C backend
        # for free -- the Nim backend still needs a C compiler under
        # the hood (`nim c` transpiles to C, see emit_nim.py's module
        # docstring), and most Windows machines don't have gcc on PATH.
        return f"https://nim-lang.org/download/nim-{NIM_VERSION}_x64.zip"
    if key == "windows_x32":
        return f"https://nim-lang.org/download/nim-{NIM_VERSION}_x32.zip"
    # macOS: nim-lang.org does not publish a prebuilt macOS tarball;
    # see _install_macos() for the Homebrew fallback.
    return None


def _report(quiet: bool, msg: str) -> None:
    if not quiet:
        print(f"dictumc: {msg}", file=sys.stderr)


def _extract_archive(archive_path: str, dest_dir: str) -> None:
    os.makedirs(dest_dir, exist_ok=True)
    if archive_path.endswith(".zip"):
        with zipfile.ZipFile(archive_path) as zf:
            zf.extractall(dest_dir)
    else:
        with tarfile.open(archive_path) as tf:
            tf.extractall(dest_dir)  # noqa: S202 -- trusted, pinned nim-lang.org release


def _find_extracted_root(dest_dir: str) -> str:
    """Nim's archives contain a single top-level `nim-{version}/` dir;
    find it rather than hardcoding the exact folder name (release
    naming has changed across major versions before)."""
    entries = [e for e in os.listdir(dest_dir) if os.path.isdir(os.path.join(dest_dir, e))]
    for e in entries:
        if e.lower().startswith("nim"):
            return os.path.join(dest_dir, e)
    if len(entries) == 1:
        return os.path.join(dest_dir, entries[0])
    raise NimBootstrapError(
        f"downloaded Nim archive didn't extract the expected single "
        f"'nim-*' directory into {dest_dir} (found: {entries!r})"
    )


def _install_prebuilt(quiet: bool) -> str:
    url = _download_url()
    if url is None:
        raise NimBootstrapError("no prebuilt Nim archive for this platform")

    target_dir = os.path.join(VENDOR_DIR, _platform_key())
    os.makedirs(VENDOR_DIR, exist_ok=True)

    ext = ".zip" if url.endswith(".zip") else ".tar.xz"
    with tempfile.TemporaryDirectory() as tmp:
        archive_path = os.path.join(tmp, "nim" + ext)
        _report(quiet, f"downloading Nim {NIM_VERSION} from {url} (one-time setup)...")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "dictumc-nim-bootstrap"})
            with urllib.request.urlopen(req, timeout=_DOWNLOAD_TIMEOUT) as resp, \
                 open(archive_path, "wb") as out:
                shutil.copyfileobj(resp, out)
        except Exception as e:  # noqa: BLE001 -- surface as our own error type
            raise NimBootstrapError(f"failed to download Nim from {url}: {e}") from e

        _report(quiet, "extracting...")
        extract_tmp = os.path.join(tmp, "extracted")
        _extract_archive(archive_path, extract_tmp)
        extracted_root = _find_extracted_root(extract_tmp)

        if os.path.isdir(target_dir):
            shutil.rmtree(target_dir)
        shutil.move(extracted_root, target_dir)

    exe = _vendored_nim_path()
    if platform.system().lower() != "windows":
        os.chmod(exe, 0o755)
        # Nim's bin/ dir also ships nimble/nimgrep/etc as siblings --
        # make sure those are executable too since `nim c` shells out
        # to some of them indirectly on certain configs.
        bin_dir = os.path.dirname(exe)
        for name in os.listdir(bin_dir):
            path = os.path.join(bin_dir, name)
            if os.path.isfile(path):
                os.chmod(path, 0o755)

    if not _verify_nim(exe):
        raise NimBootstrapError(
            f"downloaded and extracted Nim to {exe}, but it failed to "
            f"run -- the archive may be corrupt or this platform's "
            f"build needs a system dependency Nim expects to already "
            f"be present (a C compiler: gcc/clang on Linux, or the "
            f"bundled MinGW on Windows)."
        )
    _report(quiet, f"Nim {NIM_VERSION} ready at {exe}")
    return exe


def _install_macos(quiet: bool) -> str:
    if shutil.which("brew"):
        _report(quiet, "no official prebuilt Nim for macOS; installing via Homebrew "
                        "(one-time setup)...")
        try:
            subprocess.run(["brew", "install", "nim"], check=True, timeout=900)
        except (subprocess.SubprocessError, OSError) as e:
            raise NimBootstrapError(f"'brew install nim' failed: {e}") from e
        found = shutil.which("nim")
        if found and _verify_nim(found):
            return found
    raise NimBootstrapError(
        "no usable Nim compiler found, and this platform (macOS) has no "
        "official prebuilt binary to auto-download. Install Homebrew "
        "(https://brew.sh) and re-run, or install Nim yourself: "
        "https://nim-lang.org/install.html"
    )


def get_nim_executable(auto_install: bool = True, quiet: bool = False) -> str:
    """Return a path to a working `nim` executable, installing one
    automatically if `auto_install` is True and none is found.

    Raises NimBootstrapError with an actionable message if no Nim
    compiler is available and (if auto_install) none could be
    provisioned automatically.
    """
    vendored = _vendored_nim_path()
    if _verify_nim(vendored):
        return vendored

    on_path = shutil.which("nim")
    if on_path and _verify_nim(on_path):
        return on_path

    if not auto_install:
        raise NimBootstrapError(
            "no Nim compiler found (checked the vendored copy and PATH). "
            "Run with --install-nim, or `python3 -m dictumc.nim_bootstrap`, "
            "to fetch one automatically."
        )

    if platform.system().lower() == "darwin":
        return _install_macos(quiet)
    return _install_prebuilt(quiet)


def main(argv=None) -> int:
    """CLI entry point: `python3 -m dictumc.nim_bootstrap` or the
    download_nim.sh/.bat wrapper scripts both call this."""
    try:
        path = get_nim_executable(auto_install=True, quiet=False)
    except NimBootstrapError as e:
        print(f"dictumc: error: {e}", file=sys.stderr)
        return 1
    print(f"dictumc: Nim compiler ready: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
