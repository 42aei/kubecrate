#!/usr/bin/env python3
"""Fail-closed helpers for the exact-tree final QA workflow."""

from __future__ import annotations

import argparse
import html.parser
import json
import os
import re
import stat
import subprocess
import sys

from collections import Counter
from pathlib import Path
from typing import Any, Protocol

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


def _open_marker(path: Path, evidence_root: Path) -> tuple[Path, int, int, os.stat_result]:
    marker, directory_fd = _validated_marker(path, evidence_root, must_exist=True)
    try:
        fd = os.open(marker.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory_fd)
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


def _durable_unlink(name: str, directory_fd: int, *, missing_ok: bool = False) -> None:
    try:
        os.unlink(name, dir_fd=directory_fd)
    except FileNotFoundError:
        if not missing_ok:
            raise
    else:
        os.fsync(directory_fd)


def _write_marker(path: Path, repo: str, ref: str, sha: str, state: str, *, evidence_root: Path) -> None:
    path, directory_fd = _validated_marker(path, evidence_root, must_exist=False)
    payload = {"repo": repo, "ref": ref, "sha": sha, "state": state}
    temporary = f".{path.name}.tmp-{os.getpid()}-{os.urandom(8).hex()}"
    fd = -1
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            fd = -1
            json.dump(payload, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path.name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        os.fsync(directory_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        os.close(directory_fd)


def _create_marker_exclusive(path: Path, repo: str, ref: str, sha: str, state: str,
                             *, evidence_root: Path) -> None:
    """Durably publish a marker without ever replacing an existing entry."""
    path, directory_fd = _validated_marker(path, evidence_root, must_exist=False)
    payload = {"repo": repo, "ref": ref, "sha": sha, "state": state}
    temporary = f".{path.name}.tmp-{os.getpid()}-{os.urandom(8).hex()}"
    fd = -1
    temporary_exists = False
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory_fd)
        temporary_exists = True
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            fd = -1
            json.dump(payload, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path.name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
                follow_symlinks=False)
        os.fsync(directory_fd)
        os.unlink(temporary, dir_fd=directory_fd)
        temporary_exists = False
        os.fsync(directory_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        if temporary_exists:
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
            else:
                os.fsync(directory_fd)
        os.close(directory_fd)


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


def create_owned_ref(api: RefsAPI, ref: str, sha: str, *, repo: str = "", marker: Path | None = None,
                     evidence_root: Path | None = None) -> None:
    assert ref.startswith("refs/heads/"), "only an exact heads ref is allowed"
    uncertain = marker.with_suffix(marker.suffix + ".uncertain") if marker else None
    if uncertain:
        assert marker is not None and evidence_root is not None
        _assert_fresh_marker_destinations(marker, uncertain, evidence_root)
    assert api.get(ref) is None, "QA ref already exists"
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
            raise
        post_error = exc
    if post_error is None and created is not None:
        try:
            _assert_ref(created, ref, sha)
        except AssertionError as exc:
            post_error = exc

    try:
        _assert_ref(api.get(ref), ref, sha)
    except BaseException as readback_error:
        if post_error is not None:
            post_error.add_note(f"authoritative GET also failed: {readback_error}")
            raise post_error from readback_error
        raise
    if post_error is not None:
        raise post_error

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

    def _request(self, method: str, endpoint: str, fields: dict[str, str] | None = None) -> tuple[int, Any]:
        # Successful gh API calls print a body-only JSON document on stdout.
        # Do not parse gh's mixed-LF/CRLF --include framing on this path: the
        # process return code already establishes success and each method has
        # one expected GitHub status. stderr remains diagnostic-only.
        success_status = {"GET": 200, "POST": 201, "DELETE": 204}.get(method)
        if success_status is None:
            raise APIError(0, f"unsupported HTTP method: {method}")
        command = ["gh", "api", "-X", method, endpoint]
        if method == "DELETE":
            command.append("--silent")
        for key, value in (fields or {}).items():
            command.extend(["-f", f"{key}={value}"])
        result = subprocess.run(command, text=True, capture_output=True)
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
    args = parser.parse_args()
    if args.command == "create-ref":
        create_owned_ref(GitHubRefsAPI(args.repo), args.ref, args.sha, repo=args.repo, marker=args.marker,
                         evidence_root=args.evidence_root)
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
    else:
        restore_cluster(args.context)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, APIError, json.JSONDecodeError, OSError) as exc:
        print(f"final-qa-helper: ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
