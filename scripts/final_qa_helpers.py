#!/usr/bin/env python3
"""Fail-closed helpers for the exact-tree final QA workflow."""

from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import html.parser
import json
import math
import os
import platform
import re
import signal
import stat
import subprocess
import sys
import time

from collections import Counter
from pathlib import Path
from typing import Any, Callable, Protocol

EXPECTED_IDS = (
    "cratecheck-deployment-ready",
    "cratecheck-namespace-exists",
    "cratecheck-configmap-present",
    "eso-helmrelease-ready",
    "eso-secretstore-ready",
    "eso-externalsecret-ready",
    "eso-projected-secret-exists",
)
EXPECTED_NAMES = {
    "cratecheck-deployment-ready": "CrateCheck deployment ready",
    "cratecheck-namespace-exists": "CrateCheck namespace exists",
    "cratecheck-configmap-present": "CrateCheck check ConfigMap present",
    "eso-helmrelease-ready": "ESO HelmRelease ready",
    "eso-secretstore-ready": "ESO smoke SecretStore ready",
    "eso-externalsecret-ready": "ESO smoke ExternalSecret ready",
    "eso-projected-secret-exists": "ESO projected smoke Secret exists",
}
RED_IDS = {"eso-externalsecret-ready", "eso-projected-secret-exists"}
STATUSES = {"green", "red", "yellow", "unknown"}
MUTATED_STATES = {"suspended", "source_deleted", "restore_required"}


def restoration_required(state: str) -> bool:
    assert state == "none" or state in MUTATED_STATES, "unknown mutation state"
    return state in MUTATED_STATES


class APIError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"GitHub API HTTP {status}: {message}")
        self.status = status


class AuthoritativeRefReadbackError(RuntimeError):
    """A successful create could not be authoritatively confirmed in time."""


class AuthoritativeRefConflict(RuntimeError):
    """The authoritative ref exists, but does not have the requested identity."""


REF_READBACK_TIMEOUT = 20.0
REF_READBACK_INTERVAL = 0.5


class DeployKeysAPI(Protocol):
    def list(self, *, guard: Callable[[], None]) -> list[dict[str, Any]]: ...
    def get(self, key_id: int, *, guard: Callable[[], None]) -> dict[str, Any] | None: ...
    def create(self, title: str, key: str) -> dict[str, Any] | None: ...
    def delete(self, key_id: int, *, guard: Callable[[], None]) -> None: ...


class RefsAPI(Protocol):
    def get(self, ref: str) -> dict[str, Any] | None: ...
    def create(self, ref: str, sha: str) -> dict[str, Any] | None: ...
    def delete(self, ref: str) -> None: ...


def restore_cluster(context: str, run=subprocess.run) -> None:
    """Restore the controlled-red fixture; every command is context-bound."""
    commands = (
        ["kubectl", "--context", context, "config", "current-context"],
        ["flux", "--context", context, "resume", "kustomization", "external-secrets-operator-smoke", "-n", "flux-system"],
        ["flux", "--context", context, "reconcile", "kustomization", "external-secrets-operator-smoke", "-n", "flux-system", "--timeout=180s"],
        ["kubectl", "--context", context, "wait", "--for=condition=Ready", "kustomization/external-secrets-operator-smoke", "-n", "flux-system", "--timeout=180s"],
        ["kubectl", "--context", context, "get", "secret", "eso-smoke-source", "-n", "kubecrate-system"],
        ["kubectl", "--context", context, "wait", "--for=jsonpath={.status.conditions[?(@.type==\"Ready\")].status}=True", "externalsecret/eso-smoke-projection", "-n", "kubecrate-system", "--timeout=180s"],
    )
    for index, command in enumerate(commands):
        result = run(command, text=True, capture_output=True)
        if result.returncode:
            raise RuntimeError(f"restoration command failed: {' '.join(command)}")
        if index == 0 and result.stdout.strip() != context:
            raise RuntimeError(f"restoration context mismatch: {result.stdout.strip() or 'none'}")


def _assert_ref(obj: Any, ref: str, sha: str) -> None:
    assert isinstance(obj, dict), "ref response must be an object"
    assert obj.get("ref") == ref, "ref response identity mismatch"
    target = obj.get("object")
    assert isinstance(target, dict), "ref response object missing"
    assert target.get("type") == "commit", "ref target must be a commit"
    assert target.get("sha") == sha, "ref SHA mismatch"


def _private_evidence_dir(root: Path) -> tuple[Path, int]:
    """Create/open a private evidence root using a descriptor-relative no-follow walk."""
    raw = os.fspath(root)
    assert raw, "empty evidence path refused"
    parts = Path(raw).parts
    assert ".." not in parts, "evidence path traversal refused"
    absolute = os.path.isabs(raw)
    components = list(parts[1:] if absolute else parts)
    assert components and all(part not in {"", ".", ".."} for part in components), "invalid evidence path"
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    directory_fd = os.open("/" if absolute else ".", flags)
    resolved = Path("/") if absolute else Path.cwd()
    try:
        for index, component in enumerate(components):
            final = index == len(components) - 1
            try:
                child_fd = os.open(component, flags, dir_fd=directory_fd)
                created = False
            except FileNotFoundError:
                os.mkdir(component, 0o700, dir_fd=directory_fd)
                child_fd = os.open(component, flags, dir_fd=directory_fd)
                created = True
            info = os.fstat(child_fd)
            mode = stat.S_IMODE(info.st_mode)
            trusted_sticky = info.st_uid == 0 and bool(mode & stat.S_ISVTX)
            if final:
                assert info.st_uid == os.getuid(), "evidence directory must be owned by current user"
                assert mode == 0o700, "existing evidence directory must have mode 0700"
            elif not created:
                assert info.st_uid in {0, os.getuid()}, "unsafe evidence parent owner"
                assert not (mode & 0o022) or trusted_sticky, "unsafe writable evidence parent"
            os.close(directory_fd)
            directory_fd = child_fd
            resolved /= component
        return resolved, directory_fd
    except BaseException:
        os.close(directory_fd)
        raise


def _validated_marker(path: Path, evidence_root: Path, *, must_exist: bool) -> tuple[Path, int]:
    root, directory_fd = _private_evidence_dir(evidence_root)
    marker = Path(os.path.abspath(path))
    try:
        assert marker.parent == root, "marker must be directly under the expected evidence root"
        assert marker.name not in {"", ".", ".."}, "invalid marker name"
        try:
            info = os.lstat(marker.name, dir_fd=directory_fd)
        except FileNotFoundError:
            assert not must_exist, "marker does not exist"
        else:
            assert stat.S_ISREG(info.st_mode), "marker destination must be a regular file"
            assert info.st_uid == os.getuid(), "marker must be owned by current user"
            assert stat.S_IMODE(info.st_mode) == 0o600, "marker must have mode 0600"
        return marker, directory_fd
    except BaseException:
        os.close(directory_fd)
        raise


def _open_marker(path: Path, evidence_root: Path, *, writable: bool = False) -> tuple[Path, int, int, os.stat_result]:
    marker, directory_fd = _validated_marker(path, evidence_root, must_exist=True)
    try:
        access = os.O_RDWR if writable else os.O_RDONLY
        fd = os.open(marker.name, access | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory_fd)
        info = os.fstat(fd)
        assert stat.S_ISREG(info.st_mode), "marker must be a regular file"
        assert info.st_uid == os.getuid(), "marker must be owned by current user"
        assert stat.S_IMODE(info.st_mode) == 0o600, "marker must have mode 0600"
        return marker, directory_fd, fd, info
    except BaseException:
        os.close(directory_fd)
        raise


def _assert_entry_identity(name: str, directory_fd: int, opened: os.stat_result) -> None:
    current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    assert stat.S_ISREG(current.st_mode), "marker entry is no longer a regular file"
    assert (current.st_dev, current.st_ino) == (opened.st_dev, opened.st_ino), "marker entry was replaced"


class HeldMarkerEvidence:
    """Open, point-in-time-authenticated deploy-key evidence owned by its caller."""
    def __init__(self, name: str, directory_fd: int, fd: int,
                 opened: os.stat_result, expected: dict[str, Any]):
        self.name = name
        self.directory_fd = directory_fd
        self.fd = fd
        self.opened = opened
        self.expected = expected

    def verify(self) -> None:
        _verify_held_marker(self)

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1
        if self.directory_fd >= 0:
            os.close(self.directory_fd)
            self.directory_fd = -1


def _stable_marker_metadata(info: os.stat_result) -> tuple[int, ...]:
    # atime is intentionally excluded because reading may update it.
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _exact_json_value(actual: Any, expected: Any) -> bool:
    """Compare JSON values without Python's bool/int equality coercion."""
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return (actual.keys() == expected.keys() and
                all(_exact_json_value(actual[key], value)
                    for key, value in expected.items()))
    if isinstance(expected, list):
        return (len(actual) == len(expected) and
                all(_exact_json_value(left, right)
                    for left, right in zip(actual, expected)))
    return actual == expected


def _verify_held_marker(evidence: HeldMarkerEvidence) -> None:
    """Fully authenticate one held marker at a single immediate boundary."""
    assert evidence.fd >= 0 and evidence.directory_fd >= 0, "deploy-key evidence is closed"
    before = os.fstat(evidence.fd)
    path_info = _entry_info(evidence.name, evidence.directory_fd)
    _assert_marker_inode(before, links=1, label="held deploy-key evidence",
                         authoritative=evidence.opened)
    _assert_marker_inode(path_info, links=1, label="deploy-key evidence pathname",
                         authoritative=before)
    duplicate = os.dup(evidence.fd)
    try:
        os.lseek(duplicate, 0, os.SEEK_SET)
        with os.fdopen(duplicate, encoding="utf-8") as stream:
            duplicate = -1
            payload = json.load(stream)
            assert stream.read() == "", "deploy-key evidence has trailing content"
    finally:
        if duplicate >= 0:
            os.close(duplicate)
    after = os.fstat(evidence.fd)
    path_after = _entry_info(evidence.name, evidence.directory_fd)
    _assert_marker_inode(after, links=1, label="held deploy-key evidence after read",
                         authoritative=evidence.opened)
    _assert_marker_inode(path_after, links=1, label="deploy-key evidence pathname after read",
                         authoritative=after)
    assert _stable_marker_metadata(before) == _stable_marker_metadata(after), \
        "deploy-key evidence metadata changed during verification"
    assert _exact_json_value(payload, evidence.expected), \
        "deploy-key evidence payload mismatch"


def _held_marker(name: str, directory_fd: int, fd: int, opened: os.stat_result,
                 expected: dict[str, Any]) -> HeldMarkerEvidence:
    evidence = HeldMarkerEvidence(name, directory_fd, fd, opened, expected)
    evidence.verify()
    return evidence


def _verify_all(evidence: list[HeldMarkerEvidence]) -> None:
    for item in evidence:
        item.verify()


def _durable_unlink(name: str, directory_fd: int, *, missing_ok: bool = False) -> None:
    try:
        os.unlink(name, dir_fd=directory_fd)
    except FileNotFoundError:
        if not missing_ok:
            raise
    else:
        os.fsync(directory_fd)


def _assert_marker_inode(info: os.stat_result, *, links: int, label: str,
                         authoritative: os.stat_result | None = None) -> None:
    """Require a caller-owned private regular inode with an exact link count."""
    assert stat.S_ISREG(info.st_mode), f"{label}: must be a regular file"
    assert info.st_uid == os.getuid(), f"{label}: must be owned by current user"
    assert stat.S_IMODE(info.st_mode) == 0o600, f"{label}: must have mode 0600"
    assert info.st_nlink == links, f"{label}: unexpected link count"
    if authoritative is not None:
        assert (info.st_dev, info.st_ino) == (authoritative.st_dev, authoritative.st_ino), \
            f"{label}: inode identity mismatch"


def _entry_info(name: str, directory_fd: int) -> os.stat_result:
    return os.stat(name, dir_fd=directory_fd, follow_symlinks=False)


_AT_EMPTY_PATH = 0x1000
_AT_SYMLINK_FOLLOW = 0x400
_LIBC = ctypes.CDLL(None, use_errno=True)
_LINKAT = _LIBC.linkat
_LINKAT.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p,
                    ctypes.c_int)
_LINKAT.restype = ctypes.c_int

_RENAME_NOREPLACE = 1
_RENAMEAT2 = getattr(_LIBC, "renameat2", None)
if _RENAMEAT2 is not None:
    _RENAMEAT2.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                           ctypes.c_char_p, ctypes.c_uint)
    _RENAMEAT2.restype = ctypes.c_int

_PROC_SUPER_MAGIC = 0x9FA0


class _LinuxX8664StatFS(ctypes.Structure):
    """glibc struct statfs layout for Linux x86_64 only."""
    _fields_ = (
        ("f_type", ctypes.c_long),
        ("f_bsize", ctypes.c_long),
        ("f_blocks", ctypes.c_ulong),
        ("f_bfree", ctypes.c_ulong),
        ("f_bavail", ctypes.c_ulong),
        ("f_files", ctypes.c_ulong),
        ("f_ffree", ctypes.c_ulong),
        ("f_fsid", ctypes.c_int * 2),
        ("f_namelen", ctypes.c_long),
        ("f_frsize", ctypes.c_long),
        ("f_flags", ctypes.c_long),
        ("f_spare", ctypes.c_long * 4),
    )


_FSTATFS = _LIBC.fstatfs
_FSTATFS.argtypes = (ctypes.c_int, ctypes.POINTER(_LinuxX8664StatFS))
_FSTATFS.restype = ctypes.c_int


def _fstatfs_magic(fd: int) -> int:
    """Return filesystem magic, refusing unverified ctypes layouts."""
    if sys.platform != "linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise RuntimeError("procfs fallback requires Linux x86_64")
    if ctypes.sizeof(_LinuxX8664StatFS) != 120:
        raise RuntimeError("unexpected Linux x86_64 statfs layout")
    info = _LinuxX8664StatFS()
    if _FSTATFS(fd, ctypes.byref(info)) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    return info.f_type


def _proc_source_info(proc_fd: int, source: str) -> tuple[os.stat_result, str, os.stat_result]:
    """Observe one procfs fd magic link without and with following it."""
    entry = os.stat(source, dir_fd=proc_fd, follow_symlinks=False)
    target = os.readlink(source, dir_fd=proc_fd)
    followed = os.stat(source, dir_fd=proc_fd, follow_symlinks=True)
    return entry, target, followed


def _assert_proc_source(proc_fd: int, source: str, authoritative: os.stat_result,
                        *, links: int) -> None:
    entry, target, followed = _proc_source_info(proc_fd, source)
    if not stat.S_ISLNK(entry.st_mode) or not target:
        raise RuntimeError("procfs numeric fd entry must be a nonempty magic symlink")
    _assert_marker_inode(
        followed, links=links, label="procfs marker source", authoritative=authoritative)


def _assert_published_marker(fd: int, proc_fd: int, source: str, directory_fd: int,
                             name: str, authoritative: os.stat_result) -> None:
    _assert_proc_source(proc_fd, source, authoritative, links=1)
    _assert_marker_inode(
        os.fstat(fd), links=1, label="opened marker through procfs fallback",
        authoritative=authoritative)
    _assert_marker_inode(
        _entry_info(name, directory_fd), links=1,
        label="published marker through procfs fallback", authoritative=authoritative)


def _link_fd(fd: int, directory_fd: int, name: str) -> None:
    """Atomically give an anonymous inode a name without replacing an entry."""
    encoded = os.fsencode(name)
    if _LINKAT(fd, b"", directory_fd, encoded, _AT_EMPTY_PATH) == 0:
        return
    error = ctypes.get_errno()
    if error != 2:
        raise OSError(error, os.strerror(error), name)

    # Unprivileged Linux can deny AT_EMPTY_PATH even for an inode opened by this
    # process. Pin the literal /proc/self/fd directory and fail closed unless it
    # is procfs. Procfs may expose the directory as root-owned or caller-owned,
    # so require a directory owned by either, with owner search permission and
    # no group/other writes; do not incorrectly require the current uid.
    proc_fd = -1
    try:
        proc_fd = os.open("/proc/self/fd", os.O_RDONLY | os.O_DIRECTORY |
                          os.O_NOFOLLOW | os.O_CLOEXEC)
        if _fstatfs_magic(proc_fd) != _PROC_SUPER_MAGIC:
            raise RuntimeError("pinned fd directory has unexpected procfs filesystem magic")
        proc_info = os.fstat(proc_fd)
        proc_path_info = os.stat("/proc/self/fd", follow_symlinks=True)
        proc_mode = stat.S_IMODE(proc_info.st_mode)
        if ((proc_info.st_dev, proc_info.st_ino) !=
                (proc_path_info.st_dev, proc_path_info.st_ino)):
            raise RuntimeError("pinned fd directory is not this process /proc/self/fd")
        if (not stat.S_ISDIR(proc_info.st_mode) or proc_info.st_uid not in {0, os.geteuid()} or
                not proc_mode & stat.S_IXUSR or proc_mode & 0o022):
            raise RuntimeError("unsafe pinned /proc/self/fd directory metadata")

        source_text = str(fd)
        source = os.fsencode(source_text)
        opened = os.fstat(fd)
        _assert_marker_inode(opened, links=0, label="opened fallback marker")
        _assert_proc_source(proc_fd, source_text, opened, links=0)
        # Repeat immediately before linkat so a substituted source observation
        # cannot be accepted based only on the initial check.
        _assert_proc_source(proc_fd, source_text, opened, links=0)
        if _LINKAT(proc_fd, source, directory_fd, encoded, _AT_SYMLINK_FOLLOW) != 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), name)
        # Once published, never unlink on mismatch: the final name is durable
        # diagnostic evidence. Verify source, open fd, and destination both
        # before and after the directory durability barrier.
        _assert_published_marker(fd, proc_fd, source_text, directory_fd, name, opened)
        os.fsync(directory_fd)
        _assert_published_marker(fd, proc_fd, source_text, directory_fd, name, opened)
    finally:
        if proc_fd >= 0:
            os.close(proc_fd)


def _create_json_marker_exclusive(path: Path, payload: dict[str, Any], *, evidence_root: Path) -> None:
    """Durably publish an anonymous JSON marker inode without pathname cleanup."""
    path, directory_fd = _validated_marker(path, evidence_root, must_exist=False)
    fd = -1
    try:
        if not hasattr(os, "O_TMPFILE"):
            raise RuntimeError("anonymous O_TMPFILE marker creation unavailable")
        try:
            fd = os.open(".", os.O_TMPFILE | os.O_RDWR | os.O_CLOEXEC, 0o600,
                         dir_fd=directory_fd)
        except OSError as error:
            raise RuntimeError(
                f"anonymous O_TMPFILE marker creation unavailable: {error}") from error

        os.fchmod(fd, 0o600)
        authoritative = os.fstat(fd)
        _assert_marker_inode(authoritative, links=0, label="opened anonymous marker")
        with os.fdopen(os.dup(fd), "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())

        prepared = os.fstat(fd)
        _assert_marker_inode(
            prepared, links=0, label="prepared anonymous marker", authoritative=authoritative)
        _link_fd(fd, directory_fd, path.name)

        opened_after = os.fstat(fd)
        final_after = _entry_info(path.name, directory_fd)
        _assert_marker_inode(
            opened_after, links=1, label="opened marker after publication",
            authoritative=authoritative)
        _assert_marker_inode(
            final_after, links=1, label="published marker", authoritative=authoritative)

        os.fsync(directory_fd)

        opened_final = os.fstat(fd)
        final = _entry_info(path.name, directory_fd)
        _assert_marker_inode(
            opened_final, links=1, label="opened final marker", authoritative=authoritative)
        _assert_marker_inode(
            final, links=1, label="final marker", authoritative=authoritative)
    finally:
        if fd >= 0:
            os.close(fd)
        os.close(directory_fd)


def _rename_noreplace(source: str, destination: str, directory_fd: int) -> None:
    """Atomically move a directory entry without replacing another entry."""
    if _RENAMEAT2 is None:
        raise RuntimeError("renameat2 unavailable for safe marker consumption")
    if _RENAMEAT2(directory_fd, os.fsencode(source), directory_fd,
                  os.fsencode(destination), _RENAME_NOREPLACE) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), source, destination)


def _consume_open_marker(marker: Path, directory_fd: int, fd: int,
                         opened: os.stat_result, expected: dict[str, Any]) -> HeldMarkerEvidence:
    """Atomically retire an authenticated marker as non-active audit evidence."""
    retired = f".retired-deploy-key-{os.urandom(16).hex()}-{marker.name}"
    evidence = HeldMarkerEvidence(marker.name, directory_fd, fd, opened, expected)
    evidence.verify()
    _rename_noreplace(marker.name, retired, directory_fd)
    os.fsync(directory_fd)
    evidence.name = retired
    try:
        evidence.verify()
    except AssertionError as exc:
        # Retain the moved entry as diagnostic evidence on a race.  Never
        # remove an inode merely because it occupies the expected path.
        raise AssertionError(
            "deploy-key auxiliary marker was replaced during consumption") from exc
    return evidence


def _consume_marker(path: Path, evidence_root: Path, expected: dict[str, Any]) -> None:
    """Authenticate and durably retire one exact marker inode."""
    marker, directory_fd, fd, opened = _open_marker(path, evidence_root)
    retired: HeldMarkerEvidence | None = None
    try:
        retired = _consume_open_marker(marker, directory_fd, fd, opened, expected)
    finally:
        if retired is not None:
            retired.close()
        else:
            os.close(fd); os.close(directory_fd)


def _create_marker_exclusive(path: Path, repo: str, ref: str, sha: str, state: str,
                             *, evidence_root: Path) -> None:
    _create_json_marker_exclusive(
        path, {"repo": repo, "ref": ref, "sha": sha, "state": state},
        evidence_root=evidence_root)


def _assert_fresh_marker_destinations(marker: Path, uncertain: Path, evidence_root: Path) -> None:
    """Descriptor-safely require both evidence destinations to be absent."""
    root, directory_fd = _private_evidence_dir(evidence_root)
    owned = Path(os.path.abspath(marker))
    pending = Path(os.path.abspath(uncertain))
    try:
        assert owned.parent == root and pending.parent == root, "markers must be directly under the evidence root"
        for path in (owned, pending):
            assert path.name not in {"", ".", ".."}, "invalid marker name"
            try:
                entry = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            assert stat.S_ISREG(entry.st_mode), f"{path.name}: unsafe marker entry"
            assert entry.st_uid == os.getuid(), f"{path.name}: unsafe marker owner"
            assert stat.S_IMODE(entry.st_mode) == 0o600, f"{path.name}: unsafe marker mode"
            raise AssertionError(f"{path.name}: existing marker refuses fresh create")
    finally:
        os.close(directory_fd)


def _authoritative_ref_result(obj: Any, ref: str, sha: str) -> str:
    """Classify a post-create GET without including its response in diagnostics."""
    if obj is None:
        return "absent"
    if not isinstance(obj, dict):
        return "malformed"
    target = obj.get("object")
    if not isinstance(obj.get("ref"), str) or not isinstance(target, dict):
        return "malformed"
    if not isinstance(target.get("type"), str) or not isinstance(target.get("sha"), str):
        return "malformed"
    if obj["ref"] != ref or target["type"] != "commit" or target["sha"] != sha:
        return "conflict"
    return "exact"


def create_owned_ref(api: RefsAPI, ref: str, sha: str, *, repo: str = "", marker: Path | None = None,
                     evidence_root: Path | None = None,
                     readback_timeout: float = REF_READBACK_TIMEOUT,
                     readback_interval: float = REF_READBACK_INTERVAL,
                     sleep: Callable[[float], None] = time.sleep,
                     monotonic: Callable[[], float] = time.monotonic) -> None:
    assert ref.startswith("refs/heads/"), "only an exact heads ref is allowed"
    valid_timeout = (
        type(readback_timeout) in (int, float)
        and math.isfinite(readback_timeout)
        and readback_timeout >= 0
    )
    valid_interval = (
        type(readback_interval) in (int, float)
        and math.isfinite(readback_interval)
        and readback_interval > 0
    )
    assert valid_timeout and valid_interval, "invalid ref readback bounds"
    uncertain = marker.with_suffix(marker.suffix + ".uncertain") if marker else None
    if uncertain:
        assert marker is not None and evidence_root is not None
        _assert_fresh_marker_destinations(marker, uncertain, evidence_root)
    try:
        assert api.get(ref) is None, "pre-create ref lookup found that QA ref already exists"
    except APIError as exc:
        raise APIError(exc.status, "pre-create ref lookup failed") from exc
    if uncertain:
        assert evidence_root is not None
        # Persist the attempt before POST so termination during or immediately
        # after remote creation cannot erase the only cleanup diagnostic.
        _create_marker_exclusive(
            uncertain, repo, ref, sha, "created-unverified", evidence_root=evidence_root)

    created: dict[str, Any] | None = None
    post_error: BaseException | None = None
    try:
        created = api.create(ref, sha)
    except APIError as exc:
        # status=201 denotes a successful POST whose response could not be
        # parsed/validated. It still requires authoritative readback. Nonzero
        # outcomes (including a racing 422) retain uncertainty and fail closed.
        if exc.status != 201:
            raise APIError(exc.status, "post-create ref request failed") from exc
        post_error = exc
    if post_error is None and created is not None:
        try:
            _assert_ref(created, ref, sha)
        except AssertionError as exc:
            post_error = exc

    deadline = monotonic() + readback_timeout
    attempts = 0
    last_category = "unknown"
    last_error: BaseException | None = None
    while True:
        attempts += 1
        try:
            result = _authoritative_ref_result(api.get(ref), ref, sha)
            if result == "exact":
                break
            if result == "conflict":
                raise AuthoritativeRefConflict(
                    "post-create authoritative ref ownership conflict")
            last_category = result
            last_error = None
        except AuthoritativeRefConflict:
            raise
        except APIError as exc:
            if exc.status not in {0, 200, 404} and exc.status < 500:
                raise APIError(
                    exc.status, "post-create authoritative ref readback failed") from exc
            last_category = f"api-{exc.status}"
            last_error = exc

        now = monotonic()
        if now >= deadline:
            error = AuthoritativeRefReadbackError(
                "post-create authoritative ref readback did not converge "
                f"(attempts={attempts}, last={last_category})")
            if post_error is not None:
                error.add_note(
                    f"provisional POST diagnostic: {type(post_error).__name__}")
            raise error from last_error
        sleep(min(readback_interval, deadline - now))

    # A return-code-successful POST only proves that GitHub accepted the
    # request. Its body is diagnostic: gh may emit no body, non-object JSON,
    # malformed output, or a mismatched object. The exact authoritative GET
    # above is the ownership proof in every successful-POST case.
    if marker:
        assert evidence_root is not None
        _create_marker_exclusive(marker, repo, ref, sha, "owned", evidence_root=evidence_root)
        assert uncertain is not None
        marker, directory_fd, fd, info = _open_marker(uncertain, evidence_root)
        try:
            os.close(fd)
            _assert_entry_identity(marker.name, directory_fd, info)
            _durable_unlink(marker.name, directory_fd)
        finally:
            os.close(directory_fd)


def cleanup_private(evidence_root: Path) -> None:
    """Delete only ordinary files in the confined private evidence child."""
    _, directory_fd = _private_evidence_dir(evidence_root)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        try:
            private_fd = os.open("private", flags, dir_fd=directory_fd)
        except FileNotFoundError:
            return
        try:
            assert os.fstat(private_fd).st_uid == os.getuid(), "private evidence must be caller-owned"
            names = os.listdir(private_fd)
            for name in names:
                entry = os.stat(name, dir_fd=private_fd, follow_symlinks=False)
                assert stat.S_ISREG(entry.st_mode), "private evidence contains unsafe entry"
            for name in names:
                os.unlink(name, dir_fd=private_fd)
            os.fsync(private_fd)
        finally:
            os.close(private_fd)
        os.rmdir("private", dir_fd=directory_fd)
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _marker_state_at(directory_fd: int, name: str, *, expected_repo: str, expected_ref: str,
                     expected_sha: str, expected_state: str) -> tuple[str, int | None, os.stat_result | None]:
    """Inspect one marker through the evidence descriptor without following links."""
    try:
        entry = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return "absent", None, None
    assert stat.S_ISREG(entry.st_mode), f"{name}: unsafe marker entry"
    assert entry.st_uid == os.getuid(), f"{name}: unsafe marker owner"
    assert stat.S_IMODE(entry.st_mode) == 0o600, f"{name}: unsafe marker mode"
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory_fd)
    try:
        opened = os.fstat(fd)
        assert stat.S_ISREG(opened.st_mode), f"{name}: unsafe opened marker"
        assert (entry.st_dev, entry.st_ino) == (opened.st_dev, opened.st_ino), f"{name}: marker was replaced"
        with os.fdopen(os.dup(fd), encoding="utf-8") as stream:
            obj = json.load(stream)
        assert isinstance(obj, dict), f"{name}: malformed marker"
        assert obj.get("state") == expected_state, f"{name}: marker state mismatch"
        assert obj.get("repo") == expected_repo, f"{name}: marker repository mismatch"
        assert obj.get("ref") == expected_ref, f"{name}: marker ref mismatch"
        assert obj.get("sha") == expected_sha, f"{name}: marker SHA mismatch"
        _assert_entry_identity(name, directory_fd, opened)
        return ("owned-valid" if expected_state == "owned" else "uncertain-valid"), fd, opened
    except BaseException:
        os.close(fd)
        raise


def _assert_marker_absent(directory_fd: int, name: str, *, expected_repo: str, expected_ref: str,
                          expected_sha: str, expected_state: str) -> None:
    state, fd, _ = _marker_state_at(
        directory_fd, name, expected_repo=expected_repo, expected_ref=expected_ref,
        expected_sha=expected_sha, expected_state=expected_state)
    if fd is not None:
        os.close(fd)
    assert state == "absent", f"{name}: expected absent marker, got {state}"


def cleanup_ref_markers(owned_marker: Path, uncertain_marker: Path, *, evidence_root: Path,
                        expected_repo: str, expected_ref: str, expected_sha: str,
                        branch_created: bool, api: RefsAPI | None = None) -> tuple[str, str]:
    """Fail-closed marker inspection and marker-gated owned-ref cleanup."""
    root, directory_fd = _private_evidence_dir(evidence_root)
    owned = Path(os.path.abspath(owned_marker))
    uncertain = Path(os.path.abspath(uncertain_marker))
    assert owned.parent == root and uncertain.parent == root, "markers must be directly under the evidence root"
    assert owned.name not in {"", ".", ".."} and uncertain.name not in {"", ".", ".."}, "invalid marker name"
    owned_fd: int | None = None
    try:
        uncertain_state, uncertain_fd, _ = _marker_state_at(
            directory_fd, uncertain.name, expected_repo=expected_repo, expected_ref=expected_ref,
            expected_sha=expected_sha, expected_state="created-unverified")
        if uncertain_fd is not None:
            os.close(uncertain_fd)
        owned_state, owned_fd, owned_info = _marker_state_at(
            directory_fd, owned.name, expected_repo=expected_repo, expected_ref=expected_ref,
            expected_sha=expected_sha, expected_state="owned")
        if not branch_created and owned_state == "absent":
            assert uncertain_state == "absent", (
                f"ownership diagnostics retained: owned={owned_state} uncertain={uncertain_state}")
            _assert_marker_absent(directory_fd, uncertain.name, expected_repo=expected_repo,
                                  expected_ref=expected_ref, expected_sha=expected_sha,
                                  expected_state="created-unverified")
            _assert_marker_absent(directory_fd, owned.name, expected_repo=expected_repo,
                                  expected_ref=expected_ref, expected_sha=expected_sha,
                                  expected_state="owned")
            return owned_state, uncertain_state

        # An owned-valid marker is itself the durable record that create-ref
        # completed. It closes the tiny window before the shell can set
        # BRANCH_CREATED=true after the helper returns.
        assert owned_state == "owned-valid", f"created branch requires owned-valid marker, got {owned_state}"
        assert uncertain_state == "absent", f"created branch has unresolved uncertainty: {uncertain_state}"
        assert owned_fd is not None and owned_info is not None
        _assert_entry_identity(owned.name, directory_fd, owned_info)
        _assert_marker_absent(directory_fd, uncertain.name, expected_repo=expected_repo,
                              expected_ref=expected_ref, expected_sha=expected_sha,
                              expected_state="created-unverified")
        refs = api or GitHubRefsAPI(expected_repo)
        current = refs.get(expected_ref)
        assert current is not None, "owned QA ref unexpectedly absent before deletion"
        _assert_ref(current, expected_ref, expected_sha)
        _assert_entry_identity(owned.name, directory_fd, owned_info)
        _assert_marker_absent(directory_fd, uncertain.name, expected_repo=expected_repo,
                              expected_ref=expected_ref, expected_sha=expected_sha,
                              expected_state="created-unverified")
        refs.delete(expected_ref)
        assert refs.get(expected_ref) is None, "QA ref deletion absence not proved"
        _assert_entry_identity(owned.name, directory_fd, owned_info)
        _assert_marker_absent(directory_fd, uncertain.name, expected_repo=expected_repo,
                              expected_ref=expected_ref, expected_sha=expected_sha,
                              expected_state="created-unverified")
        _durable_unlink(owned.name, directory_fd)
        return owned_state, uncertain_state
    finally:
        if owned_fd is not None:
            os.close(owned_fd)
        os.close(directory_fd)


class GitHubDeployKeysAPI:
    MAX_LIST_PAGES = 100
    def __init__(self, repo: str):
        self.repo = repo
        self._refs = GitHubRefsAPI(repo)

    def _request(self, method: str, endpoint: str, fields: dict[str, Any] | None = None) -> tuple[int, Any]:
        return self._refs._request(method, endpoint, fields)

    def list(self, *, guard: Callable[[], None]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for page in range(1, self.MAX_LIST_PAGES + 1):
            guard()
            status, body = self._request(
                "GET", f"repos/{self.repo}/keys?per_page=100&page={page}")
            if status != 200 or not isinstance(body, list) or not all(
                    isinstance(item, dict) for item in body):
                raise APIError(status, "deploy-key list page must be an array of objects")
            if len(body) > 100:
                raise APIError(status, "deploy-key list page exceeds requested size")
            result.extend(body)
            if len(body) < 100:
                return result
        raise APIError(0, "deploy-key pagination exceeded safety bound")

    def get(self, key_id: int, *, guard: Callable[[], None]) -> dict[str, Any] | None:
        guard()
        status, body = self._request("GET", f"repos/{self.repo}/keys/{key_id}")
        if status == 404:
            if not isinstance(body, dict) or body.get("message") != "Not Found":
                raise APIError(status, "malformed deploy-key absence response")
            return None
        if status != 200 or not isinstance(body, dict):
            raise APIError(status, "deploy-key response must be an object")
        return body

    def create(self, title: str, key: str) -> dict[str, Any] | None:
        status, body = self._request(
            "POST", f"repos/{self.repo}/keys", {"title": title, "key": key, "read_only": True})
        if status != 201:
            raise APIError(status, "unexpected deploy-key create response")
        if body is None:
            return None
        if not isinstance(body, dict):
            raise APIError(status, "deploy-key create response must be an object")
        return body

    def delete(self, key_id: int, *, guard: Callable[[], None]) -> None:
        guard()
        status, _ = self._request("DELETE", f"repos/{self.repo}/keys/{key_id}")
        if status != 204:
            raise APIError(status, "unexpected deploy-key delete response")


def _public_key_fingerprint(key: str) -> str:
    """Return the OpenSSH SHA256 fingerprint of the decoded public-key blob."""
    assert isinstance(key, str), "public key must be text"
    normalized = key.strip()
    assert "\n" not in normalized and "\r" not in normalized, "public key must be one line"
    fields = normalized.split()
    assert len(fields) >= 2, "public key algorithm and blob are required"
    algorithm = fields[0]
    assert algorithm == "ssh-ed25519", "only ssh-ed25519 public keys are supported"
    try:
        blob = base64.b64decode(fields[1], validate=True)
    except ValueError as exc:
        raise AssertionError("public key blob is malformed base64") from exc
    assert fields[1] == base64.b64encode(blob).decode("ascii"), \
        "public key blob must use canonical base64"

    def ssh_string(offset: int, label: str) -> tuple[bytes, int]:
        assert len(blob) - offset >= 4, f"public key blob {label} length is truncated"
        length = int.from_bytes(blob[offset:offset + 4], "big")
        offset += 4
        assert length <= len(blob) - offset, f"public key blob {label} is truncated"
        return blob[offset:offset + length], offset + length

    embedded_raw, offset = ssh_string(0, "algorithm")
    try:
        embedded = embedded_raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise AssertionError("public key blob algorithm is malformed") from exc
    assert embedded == algorithm, "public key algorithm does not match decoded blob"
    key_material, offset = ssh_string(offset, "key")
    assert len(key_material) == 32, "ssh-ed25519 public key must be exactly 32 bytes"
    assert offset == len(blob), "public key blob has trailing bytes"
    digest = base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")
    return f"SHA256:{digest}"


def _assert_deploy_key(obj: Any, title: str, fingerprint: str,
                       key_id: int | None = None) -> int:
    assert isinstance(obj, dict), "deploy-key response must be an object"
    value = obj.get("id")
    assert type(value) is int and value > 0, "deploy-key id must be a positive integer"
    if key_id is not None:
        assert value == key_id, "deploy-key id mismatch"
    assert obj.get("title") == title, "deploy-key title mismatch"
    key = obj.get("key")
    assert isinstance(key, str), "deploy-key public key is missing"
    assert _public_key_fingerprint(key) == fingerprint, "deploy-key public key fingerprint mismatch"
    for field in ("read_only", "verified", "enabled"):
        assert type(obj.get(field)) is bool and obj[field] is True, f"deploy-key {field} must be true"
    return value


def _validate_key_list(items: Any) -> list[tuple[dict[str, Any], int, str, str]]:
    """Strictly normalize a complete authoritative deploy-key listing."""
    assert isinstance(items, list), "deploy-key list must be complete array"
    normalized = []
    for item in items:
        assert isinstance(item, dict), "deploy-key list entry must be an object"
        title = item.get("title")
        assert isinstance(title, str) and title, "deploy-key list title is malformed"
        key = item.get("key")
        assert isinstance(key, str), "deploy-key list public key is missing"
        fingerprint = _public_key_fingerprint(key)
        key_id = _assert_deploy_key(item, title, fingerprint)
        normalized.append((item, key_id, title, fingerprint))
    return normalized


def _assert_unique_exact_key(items: Any, *, key_id: int, title: str,
                             fingerprint: str) -> dict[str, Any]:
    normalized = _validate_key_list(items)
    exact = [item for item, item_id, item_title, item_fingerprint in normalized
             if item_id == key_id and item_title == title and item_fingerprint == fingerprint]
    assert len(exact) == 1, "exact deploy-key is not uniquely listed"
    assert sum(item_title == title for _, _, item_title, _ in normalized) == 1, \
        "deploy-key title is not unique"
    assert sum(item_fingerprint == fingerprint for _, _, _, item_fingerprint in normalized) == 1, \
        "deploy-key fingerprint is not unique"
    assert sum(item_id == key_id for _, item_id, _, _ in normalized) == 1, \
        "deploy-key id is not unique"
    return exact[0]


def _assert_key_absent(items: Any, *, key_id: int, title: str, fingerprint: str) -> None:
    normalized = _validate_key_list(items)
    assert not any(item_id == key_id or item_title == title or item_fingerprint == fingerprint
                   for _, item_id, item_title, item_fingerprint in normalized), \
        "deleted deploy-key identity remains in authoritative list"


def _read_private_file(evidence_root: Path, name: str) -> str:
    _, root_fd = _private_evidence_dir(evidence_root)
    private_fd = -1
    fd = -1
    try:
        private_fd = os.open("private", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                             dir_fd=root_fd)
        info = os.fstat(private_fd)
        assert info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700, "private directory must be 0700"
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=private_fd)
        opened = os.fstat(fd)
        assert stat.S_ISREG(opened.st_mode) and opened.st_uid == os.getuid(), "unsafe private file"
        assert stat.S_IMODE(opened.st_mode) == 0o600, "private file must be 0600"
        with os.fdopen(os.dup(fd), encoding="utf-8") as stream:
            return stream.read()
    finally:
        if fd >= 0: os.close(fd)
        if private_fd >= 0: os.close(private_fd)
        os.close(root_fd)


def write_public_key(evidence_root: Path, encoded: str) -> None:
    try:
        decoded = base64.b64decode(encoded, validate=True)
        assert encoded == base64.b64encode(decoded).decode("ascii"), \
            "identity.pub must use canonical base64"
        raw = decoded.decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise AssertionError("identity.pub is not valid base64 UTF-8") from exc
    _public_key_fingerprint(raw)
    _, root_fd = _private_evidence_dir(evidence_root)
    private_fd = -1
    fd = -1
    try:
        try:
            os.mkdir("private", 0o700, dir_fd=root_fd)
        except FileExistsError:
            pass
        private_fd = os.open("private", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                             dir_fd=root_fd)
        info = os.fstat(private_fd)
        assert info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700, "private directory must be 0700"
        fd = os.open("identity.pub", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=private_fd)
        os.fchmod(fd, 0o600)
        os.write(fd, raw.strip().encode() + b"\n")
        os.fsync(fd); os.fsync(private_fd)
    finally:
        if fd >= 0: os.close(fd)
        if private_fd >= 0: os.close(private_fd)
        os.close(root_fd)


def extract_public_key(secret_json: str) -> str:
    secret = json.loads(secret_json)
    assert isinstance(secret, dict), "Secret response must be an object"
    data = secret.get("data")
    assert isinstance(data, dict), "Secret data must be an object"
    encoded = data.get("identity.pub")
    assert isinstance(encoded, str) and encoded, "Secret identity.pub must be a non-empty string"
    return encoded


def create_deploy_key(api: DeployKeysAPI, title: str, public_key: str, *, repo: str,
                      marker: Path, evidence_root: Path) -> int:
    uncertain = marker.with_suffix(marker.suffix + ".uncertain")
    outcome = uncertain.with_suffix(uncertain.suffix + ".outcome")
    _assert_fresh_marker_destinations(marker, uncertain, evidence_root)
    _assert_fresh_marker_destinations(marker, outcome, evidence_root)
    fingerprint = _public_key_fingerprint(public_key)
    # Creation has no ownership evidence to authenticate yet.  Keep this
    # explicit at every read so cleanup-capable API methods can never silently
    # omit their guard contract.
    def _creation_guard() -> None:
        return None

    before = _validate_key_list(api.list(guard=_creation_guard))
    assert not any(item_title == title or item_fingerprint == fingerprint
                   for _, _, item_title, item_fingerprint in before), \
        "deploy-key title or fingerprint already exists"
    identity = {"repo": repo, "title": title, "fingerprint": fingerprint}
    attempt = {"state": "create-attempting", **identity}
    _create_json_marker_exclusive(uncertain, attempt, evidence_root=evidence_root)
    try:
        created = api.create(title, public_key.strip())
    except APIError as exc:
        if exc.status == 422:
            _create_json_marker_exclusive(
                outcome, {"state": "create-rejected", **identity}, evidence_root=evidence_root)
        raise
    _create_json_marker_exclusive(
        outcome, {"state": "created-unverified", **identity}, evidence_root=evidence_root)
    key_id = _assert_deploy_key(created, title, fingerprint)
    _assert_deploy_key(api.get(key_id, guard=_creation_guard), title, fingerprint, key_id)
    _assert_unique_exact_key(api.list(guard=_creation_guard), key_id=key_id, title=title,
                             fingerprint=fingerprint)
    _, attempt_dir_fd, attempt_fd, attempt_info = _load_key_marker(
        uncertain, evidence_root, "create-attempting", repo, title, fingerprint)
    _, outcome_dir_fd, outcome_fd, outcome_info = _load_key_marker(
        outcome, evidence_root, "created-unverified", repo, title, fingerprint)
    owned = {**identity, "state": "owned", "key_id": key_id}
    try:
        _create_json_marker_exclusive(marker, owned, evidence_root=evidence_root)
        _consume_open_marker(outcome, outcome_dir_fd, outcome_fd, outcome_info,
                             {"state": "created-unverified", **identity})
        _consume_open_marker(uncertain, attempt_dir_fd, attempt_fd, attempt_info, attempt)
    finally:
        os.close(outcome_fd); os.close(outcome_dir_fd)
        os.close(attempt_fd); os.close(attempt_dir_fd)
    return key_id


def _load_key_marker(path: Path, evidence_root: Path, state: str, repo: str, title: str,
                     fingerprint: str) -> tuple[dict[str, Any], int, int, os.stat_result]:
    marker, directory_fd, fd, info = _open_marker(path, evidence_root)
    with os.fdopen(os.dup(fd), encoding="utf-8") as stream:
        obj = json.load(stream)
    assert isinstance(obj, dict) and obj.get("state") == state, "deploy-key marker state mismatch"
    assert obj.get("repo") == repo and obj.get("title") == title, "deploy-key marker identity mismatch"
    assert obj.get("fingerprint") == fingerprint, "deploy-key marker fingerprint mismatch"
    return obj, directory_fd, fd, info


def _key_marker_exists(path: Path, evidence_root: Path) -> bool:
    root, directory_fd = _private_evidence_dir(evidence_root)
    marker = Path(os.path.abspath(path))
    try:
        assert marker.parent == root and marker.name not in {"", ".", ".."}, \
            "deploy-key marker must be directly under evidence root"
        try:
            info = os.stat(marker.name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        assert stat.S_ISREG(info.st_mode), "unsafe deploy-key marker entry"
        assert info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o600, \
            "unsafe deploy-key marker ownership or mode"
        return True
    finally:
        os.close(directory_fd)


def cleanup_deploy_key_markers(api: DeployKeysAPI, *, repo: str, title: str,
                               marker: Path, evidence_root: Path) -> None:
    uncertain = marker.with_suffix(marker.suffix + ".uncertain")
    outcome = uncertain.with_suffix(uncertain.suffix + ".outcome")
    if _key_marker_exists(marker, evidence_root):
        marker, directory_fd, fd, info = _open_marker(marker, evidence_root)
        with os.fdopen(os.dup(fd), encoding="utf-8") as stream:
            initial = json.load(stream)
        assert isinstance(initial, dict) and isinstance(initial.get("fingerprint"), str)
        obj, directory_fd2, fd2, info2 = _load_key_marker(
            marker, evidence_root, "owned", repo, title, initial["fingerprint"])
        os.close(fd); os.close(directory_fd)
        directory_fd, fd, info = directory_fd2, fd2, info2
        try:
            key_id = obj.get("key_id"); assert type(key_id) is int and key_id > 0
            expected_owned = {"state": "owned", "repo": repo, "title": title,
                              "fingerprint": initial["fingerprint"], "key_id": key_id}
            assert obj == expected_owned, "deploy-key owned marker has unexpected fields"
            identity = {"repo": repo, "title": title,
                        "fingerprint": initial["fingerprint"]}
            auxiliaries: list[tuple[Path, int, int, os.stat_result, dict[str, Any]]] = []
            held: list[HeldMarkerEvidence] = []
            try:
                if _key_marker_exists(uncertain, evidence_root):
                    expected_attempt = {"state": "create-attempting", **identity}
                    attempt_obj, attempt_dir_fd, attempt_fd, attempt_info = _load_key_marker(
                        uncertain, evidence_root, "create-attempting", repo, title,
                        initial["fingerprint"])
                    auxiliaries.append((uncertain, attempt_dir_fd, attempt_fd,
                                        attempt_info, expected_attempt))
                    assert attempt_obj == expected_attempt, \
                        "deploy-key attempt marker has unexpected fields"
                if _key_marker_exists(outcome, evidence_root):
                    expected_outcome = {"state": "created-unverified", **identity}
                    outcome_obj, outcome_dir_fd, outcome_fd, outcome_info = _load_key_marker(
                        outcome, evidence_root, "created-unverified", repo, title,
                        initial["fingerprint"])
                    auxiliaries.append((outcome, outcome_dir_fd, outcome_fd,
                                        outcome_info, expected_outcome))
                    assert outcome_obj == expected_outcome, \
                        "deploy-key outcome marker has unexpected fields"
                # Keep every authenticated descriptor open until all auxiliaries
                # have been inspected, then consume while owned remains linked.
                for auxiliary in reversed(auxiliaries):
                    held.append(_consume_open_marker(*auxiliary))
                owned_evidence = _held_marker(marker.name, directory_fd, fd, info, expected_owned)
                all_evidence = [owned_evidence, *held]
                _assert_deploy_key(api.get(key_id, guard=lambda: _verify_all(all_evidence)),
                                   title, initial["fingerprint"], key_id)
                _assert_unique_exact_key(api.list(guard=lambda: _verify_all(all_evidence)),
                                         key_id=key_id, title=title,
                                     fingerprint=initial["fingerprint"])
                api.delete(key_id, guard=lambda: _verify_all(all_evidence))
                assert api.get(key_id, guard=lambda: _verify_all(all_evidence)) is None, \
                    "deploy-key deletion absence not proved"
                _assert_key_absent(api.list(guard=lambda: _verify_all(all_evidence)),
                                   key_id=key_id, title=title,
                                   fingerprint=initial["fingerprint"])
                _verify_all(all_evidence)
                retired_owned = _consume_open_marker(
                    marker, directory_fd, fd, info, expected_owned)
                # Ownership of these two descriptors moved to the held object.
                fd = directory_fd = -1
                retired_owned.close()
            finally:
                consumed_fds = {evidence.fd for evidence in held}
                for evidence in held:
                    evidence.close()
                # Any auxiliary not successfully retired still owns its tuple fds.
                for auxiliary in auxiliaries:
                    if auxiliary[2] not in consumed_fds:
                        os.close(auxiliary[2]); os.close(auxiliary[1])

        finally:
            if fd >= 0: os.close(fd)
            if directory_fd >= 0: os.close(directory_fd)
        return
    if _key_marker_exists(uncertain, evidence_root):
        uncertain, directory_fd, fd, info = _open_marker(uncertain, evidence_root)
        with os.fdopen(os.dup(fd), encoding="utf-8") as stream:
            initial = json.load(stream)
        assert isinstance(initial, dict) and isinstance(initial.get("fingerprint"), str)
        state = initial.get("state")
        assert state == "create-attempting", "deploy-key marker state mismatch"
        _, directory_fd2, fd2, info2 = _load_key_marker(
            uncertain, evidence_root, state, repo, title, initial["fingerprint"])
        fingerprint = initial["fingerprint"]
        os.close(fd); os.close(directory_fd)
        directory_fd, fd, info = directory_fd2, fd2, info2
        outcome_dir_fd = outcome_fd = -1
        retired_evidence: list[HeldMarkerEvidence] = []
        try:
            expected_attempt = {"state": "create-attempting", "repo": repo,
                                "title": title, "fingerprint": fingerprint}
            assert initial == expected_attempt, "deploy-key attempt marker has unexpected fields"
            assert _key_marker_exists(outcome, evidence_root), \
                "deploy-key attempt has no durable outcome; retained without deletion"
            outcome_path, outcome_dir_fd, outcome_fd, outcome_info = _open_marker(
                outcome, evidence_root)
            with os.fdopen(os.dup(outcome_fd), encoding="utf-8") as stream:
                outcome_initial = json.load(stream)
            outcome_state = outcome_initial.get("state") if isinstance(outcome_initial, dict) else None
            assert outcome_state in {"created-unverified", "create-rejected"}, \
                "deploy-key outcome marker state mismatch"
            assert outcome_initial.get("repo") == repo and outcome_initial.get("title") == title, \
                "deploy-key outcome marker identity mismatch"
            assert outcome_initial.get("fingerprint") == fingerprint, \
                "deploy-key outcome marker fingerprint mismatch"
            expected_outcome = {"state": outcome_state, "repo": repo, "title": title,
                                "fingerprint": fingerprint}
            assert outcome_initial == expected_outcome, \
                "deploy-key outcome marker has unexpected fields"
            attempt_evidence = _held_marker(
                uncertain.name, directory_fd, fd, info, expected_attempt)
            outcome_evidence = _held_marker(
                outcome_path.name, outcome_dir_fd, outcome_fd, outcome_info, expected_outcome)
            evidence = [attempt_evidence, outcome_evidence]
            normalized = _validate_key_list(api.list(guard=lambda: _verify_all(evidence)))
            if outcome_state == "create-rejected":
                assert not any(item_title == title or item_fingerprint == fingerprint
                               for _, _, item_title, item_fingerprint in normalized), \
                    "rejected deploy-key identity exists; marker retained without deletion"
                _verify_all(evidence)
                retired_evidence.append(_consume_open_marker(
                    outcome, outcome_dir_fd, outcome_fd, outcome_info, expected_outcome))
                outcome_fd = outcome_dir_fd = -1
                retired_evidence.append(_consume_open_marker(
                    uncertain, directory_fd, fd, info, expected_attempt))
                fd = directory_fd = -1
                return
            matches = [(item, key_id) for item, key_id, item_title, item_fingerprint in normalized
                       if item_title == title and item_fingerprint == fingerprint]
            assert sum(item_title == title for _, _, item_title, _ in normalized) <= 1, \
                "deploy-key title is not unique"
            assert sum(item_fingerprint == fingerprint for _, _, _, item_fingerprint in normalized) <= 1, \
                "deploy-key fingerprint is not unique"
            if matches:
                candidate, key_id = matches[0]
                _assert_deploy_key(candidate, title, fingerprint, key_id)
                _assert_deploy_key(api.get(key_id, guard=lambda: _verify_all(evidence)),
                                   title, fingerprint, key_id)
                api.delete(key_id, guard=lambda: _verify_all(evidence))
                assert api.get(key_id, guard=lambda: _verify_all(evidence)) is None, \
                    "deploy-key deletion absence not proved"
                _assert_key_absent(api.list(guard=lambda: _verify_all(evidence)),
                                   key_id=key_id, title=title,
                                   fingerprint=fingerprint)
            _verify_all(evidence)
            retired_evidence.append(_consume_open_marker(
                outcome, outcome_dir_fd, outcome_fd, outcome_info, expected_outcome))
            outcome_fd = outcome_dir_fd = -1
            retired_evidence.append(_consume_open_marker(
                uncertain, directory_fd, fd, info, expected_attempt))
            fd = directory_fd = -1
        finally:
            for retired in retired_evidence:
                retired.close()
            if outcome_fd >= 0: os.close(outcome_fd)
            if outcome_dir_fd >= 0: os.close(outcome_dir_fd)
            if fd >= 0: os.close(fd)
            if directory_fd >= 0: os.close(directory_fd)
        return
    if _key_marker_exists(outcome, evidence_root):
        raise AssertionError(
            "deploy-key orphan outcome retained without API access or deletion")


class GitHubRefsAPI:
    def __init__(self, repo: str):
        self.repo = repo

    @staticmethod
    def _parse_response(raw: str) -> tuple[int, Any]:
        normalized = raw.replace("\r\n", "\n")
        matches = list(re.finditer(r"(?m)^HTTP/[^\s]+\s+([^\s]+)[^\n]*\n", normalized))
        if not matches:
            raise APIError(0, "missing or malformed HTTP status")
        final = matches[-1]
        try:
            status = int(final.group(1))
        except ValueError as exc:
            raise APIError(0, "missing or malformed HTTP status") from exc
        response = normalized[final.end():]
        separator = response.find("\n\n")
        if separator < 0:
            raise APIError(status, "missing HTTP header terminator")
        body = response[separator + 2:].strip()
        parsed: Any = None
        if body:
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError as exc:
                raise APIError(status, "malformed JSON response") from exc
        return status, parsed

    @staticmethod
    def _parse_body(raw: str, status: int) -> Any:
        body = raw.strip()
        if not body:
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise APIError(status, "malformed JSON response") from exc

    def _request(self, method: str, endpoint: str, fields: dict[str, Any] | None = None) -> tuple[int, Any]:
        # Successful gh API calls print a body-only JSON document on stdout.
        # Do not parse gh's mixed-LF/CRLF --include framing on this path: the
        # process return code already establishes success and each method has
        # one expected GitHub status. stderr remains diagnostic-only.
        success_status = {"GET": 200, "POST": 201, "DELETE": 204}.get(method)
        if success_status is None:
            raise APIError(0, f"unsupported HTTP method: {method}")
        command = ["gh", "api", "-X", method, endpoint]
        input_text = None
        if method == "DELETE":
            command.append("--silent")
        if fields:
            # Keep public-key and ref payloads out of argv/process listings and
            # command logs. gh accepts an exact JSON body from stdin.
            command.extend(["--input", "-"])
            input_text = json.dumps(fields, separators=(",", ":"))
        result = subprocess.run(command, text=True, capture_output=True, input=input_text)
        if not result.returncode:
            return success_status, self._parse_body(result.stdout, success_status)

        matches = re.findall(r"\(HTTP (\d{3})\)", result.stderr)
        if not matches:
            raise APIError(0, result.stderr.strip() or "request failed without HTTP status")
        status = int(matches[-1])
        parsed = self._parse_body(result.stdout, status)
        message = parsed.get("message", "request failed") if isinstance(parsed, dict) else "request failed"
        if status != 404:
            raise APIError(status, message)
        return status, parsed

    @staticmethod
    def endpoint_ref(ref: str) -> str:
        assert ref.startswith("refs/heads/")
        return ref.removeprefix("refs/")

    def get(self, ref: str) -> dict[str, Any] | None:
        status, body = self._request("GET", f"repos/{self.repo}/git/ref/{self.endpoint_ref(ref)}")
        if status == 404:
            if not isinstance(body, dict) or body.get("message") != "Not Found":
                raise APIError(status, "malformed ref absence response")
            return None
        if status != 200:
            raise APIError(status, "unexpected ref lookup response")
        if not isinstance(body, dict):
            raise APIError(status, "ref response must be an object")
        return body

    def create(self, ref: str, sha: str) -> dict[str, Any] | None:
        status, body = self._request("POST", f"repos/{self.repo}/git/refs", {"ref": ref, "sha": sha})
        if status != 201:
            raise APIError(status, "unexpected ref create response")
        if body is None:
            return None
        if not isinstance(body, dict):
            raise APIError(status, "ref response must be an object")
        return body

    def delete(self, ref: str) -> None:
        status, _ = self._request("DELETE", f"repos/{self.repo}/git/refs/{self.endpoint_ref(ref)}")
        if status != 204:
            raise APIError(status, "unexpected ref delete response")


def validate_status(data: Any, phase: str) -> None:
    assert phase in {"green", "red"}
    assert isinstance(data, dict), "status response must be an object"
    checks = data.get("checks")
    summary = data.get("summary")
    assert isinstance(checks, list) and len(checks) == 7, "exactly seven checks required"
    assert all(isinstance(c, dict) for c in checks)
    ids = [c.get("id") for c in checks]
    assert all(isinstance(i, str) for i in ids)
    assert len(set(ids)) == len(ids), "duplicate check IDs"
    assert set(ids) == set(EXPECTED_IDS), "check ID set mismatch"
    statuses = {c["id"]: c.get("status") for c in checks}
    assert all(s in STATUSES for s in statuses.values()), "invalid check status"
    assert isinstance(summary, dict), "summary missing"
    counts = Counter(statuses.values())
    for key in STATUSES:
        assert type(summary.get(key)) is int and summary[key] == counts[key], f"summary {key} mismatch"
    assert type(summary.get("total")) is int and summary["total"] == 7
    if phase == "green":
        assert data.get("status") == "green"
        assert counts["green"] == 7
    else:
        assert data.get("status") in {"red", "yellow", "unknown"}
        changed = {i for i, status in statuses.items() if status != "green"}
        assert changed and changed <= RED_IDS, "only source-dependent ESO checks may be non-green"


class _StatusHTMLParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.cards: list[dict[str, Any]] = []
        self.card: dict[str, Any] | None = None
        self.in_title = False
        self.in_h3 = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = set((values.get("class") or "").split())
        if tag == "article" and "check" in classes:
            self.card = {"status": values.get("data-status"), "name": "", "badge_statuses": []}
        elif self.card is not None and "check-title" in classes:
            self.in_title = True
        elif self.card is not None and self.in_title and tag == "h3":
            self.in_h3 = True
        elif self.card is not None and self.in_title and "badge" in classes:
            self.card["badge_statuses"].extend(classes & STATUSES)

    def handle_data(self, data: str) -> None:
        if self.card is not None and self.in_h3:
            self.card["name"] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "h3":
            self.in_h3 = False
        elif tag == "div" and self.in_title:
            self.in_title = False
        elif tag == "article" and self.card is not None:
            self.card["name"] = self.card["name"].strip()
            self.cards.append(self.card)
            self.card = None


def validate_html(document: str, phase: str) -> None:
    parser = _StatusHTMLParser()
    parser.feed(document)
    assert len(parser.cards) == 7, "UI must contain exactly seven structured check cards"
    by_name = {card["name"]: card for card in parser.cards}
    assert len(by_name) == 7 and set(by_name) == set(EXPECTED_NAMES.values()), "UI check names mismatch"
    statuses = {check_id: by_name[name]["status"] for check_id, name in EXPECTED_NAMES.items()}
    for check_id, status in statuses.items():
        assert status in STATUSES, f"invalid UI status for {check_id}"
        assert status in by_name[EXPECTED_NAMES[check_id]]["badge_statuses"], f"UI badge/status mismatch for {check_id}"
    if phase == "green":
        assert set(statuses.values()) == {"green"}, "UI is not exact green"
    else:
        changed = {i for i, status in statuses.items() if status != "green"}
        assert changed and changed <= RED_IDS, "unexpected UI red check"


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("create-ref")
    p.add_argument("--repo", required=True)
    p.add_argument("--ref", required=True)
    p.add_argument("--sha", required=True)
    p.add_argument("--marker", required=True, type=Path)
    p.add_argument("--evidence-root", required=True, type=Path)
    p.add_argument("--readback-timeout", type=float, default=REF_READBACK_TIMEOUT,
                   help=argparse.SUPPRESS)
    p.add_argument("--readback-interval", type=float, default=REF_READBACK_INTERVAL,
                   help=argparse.SUPPRESS)
    p = sub.add_parser("cleanup-ref-markers")
    p.add_argument("--owned-marker", required=True, type=Path)
    p.add_argument("--uncertain-marker", required=True, type=Path)
    p.add_argument("--evidence-root", required=True, type=Path)
    p.add_argument("--repo", required=True)
    p.add_argument("--ref", required=True)
    p.add_argument("--sha", required=True)
    p.add_argument("--branch-created", choices=("true", "false"), required=True)
    for command in ("validate-json", "validate-html"):
        p = sub.add_parser(command)
        p.add_argument("--phase", choices=("green", "red"), required=True)
        p.add_argument("path", type=Path)
    p = sub.add_parser("restore")
    p.add_argument("--context", required=True)
    p = sub.add_parser("prepare-evidence")
    p.add_argument("--evidence-root", required=True, type=Path)
    p = sub.add_parser("cleanup-private")
    p.add_argument("--evidence-root", required=True, type=Path)
    p = sub.add_parser("write-public-key")
    p.add_argument("--evidence-root", required=True, type=Path)
    sub.add_parser("extract-public-key")
    p = sub.add_parser("create-deploy-key")
    p.add_argument("--repo", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--evidence-root", required=True, type=Path)
    p.add_argument("--marker", required=True, type=Path)
    p = sub.add_parser("cleanup-deploy-key-markers")
    p.add_argument("--repo", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--evidence-root", required=True, type=Path)
    p.add_argument("--marker", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "create-ref":
        create_owned_ref(GitHubRefsAPI(args.repo), args.ref, args.sha, repo=args.repo, marker=args.marker,
                         evidence_root=args.evidence_root, readback_timeout=args.readback_timeout,
                         readback_interval=args.readback_interval)
    elif args.command == "cleanup-ref-markers":
        owned_state, uncertain_state = cleanup_ref_markers(
            args.owned_marker, args.uncertain_marker, evidence_root=args.evidence_root,
            expected_repo=args.repo, expected_ref=args.ref, expected_sha=args.sha,
            branch_created=args.branch_created == "true")
        print(f"owned={owned_state} uncertain={uncertain_state}")
    elif args.command == "validate-json":
        validate_status(json.loads(args.path.read_text()), args.phase)
    elif args.command == "validate-html":
        validate_html(args.path.read_text(), args.phase)
    elif args.command == "prepare-evidence":
        _, fd = _private_evidence_dir(args.evidence_root)
        os.close(fd)
    elif args.command == "cleanup-private":
        cleanup_private(args.evidence_root)
    elif args.command == "write-public-key":
        write_public_key(args.evidence_root, sys.stdin.read().strip())
    elif args.command == "extract-public-key":
        print(extract_public_key(sys.stdin.read()), end="")
    elif args.command == "create-deploy-key":
        public_key = _read_private_file(args.evidence_root, "identity.pub")
        key_id = create_deploy_key(
            GitHubDeployKeysAPI(args.repo), args.title, public_key, repo=args.repo,
            marker=args.marker, evidence_root=args.evidence_root)
        print(key_id)
    elif args.command == "cleanup-deploy-key-markers":
        cleanup_deploy_key_markers(
            GitHubDeployKeysAPI(args.repo), repo=args.repo, title=args.title,
            marker=args.marker, evidence_root=args.evidence_root)
    else:
        restore_cluster(args.context)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, APIError, AuthoritativeRefReadbackError,
            AuthoritativeRefConflict, json.JSONDecodeError, OSError) as exc:
        print(f"final-qa-helper: ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
