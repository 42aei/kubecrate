#!/usr/bin/env python3
"""Fail-closed helpers for the exact-tree final QA workflow."""

from __future__ import annotations

import argparse
import html.parser
import json
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
MUTATED_STATES = {"suspended", "source_deleted"}


def restoration_required(state: str) -> bool:
    assert state == "none" or state in MUTATED_STATES, "unknown mutation state"
    return state in MUTATED_STATES


class APIError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"GitHub API HTTP {status}: {message}")
        self.status = status


class RefsAPI(Protocol):
    def get(self, ref: str) -> dict[str, Any] | None: ...
    def create(self, ref: str, sha: str) -> dict[str, Any]: ...
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


def create_owned_ref(api: RefsAPI, ref: str, sha: str) -> None:
    assert ref.startswith("refs/heads/"), "only an exact heads ref is allowed"
    assert api.get(ref) is None, "QA ref already exists"
    created = api.create(ref, sha)
    _assert_ref(created, ref, sha)
    _assert_ref(api.get(ref), ref, sha)


def delete_owned_ref(api: RefsAPI, ref: str, sha: str) -> None:
    current = api.get(ref)
    assert current is not None, "owned QA ref unexpectedly absent before deletion"
    _assert_ref(current, ref, sha)
    api.delete(ref)
    assert api.get(ref) is None, "QA ref deletion absence not proved"


class GitHubRefsAPI:
    def __init__(self, repo: str):
        self.repo = repo

    def _request(self, method: str, endpoint: str, fields: dict[str, str] | None = None) -> tuple[int, Any]:
        command = ["gh", "api", "--include", "-X", method, endpoint]
        for key, value in (fields or {}).items():
            command.extend(["-f", f"{key}={value}"])
        result = subprocess.run(command, text=True, capture_output=True)
        raw = result.stdout or result.stderr
        blocks = raw.replace("\r\n", "\n").split("\n\n")
        header = next((b for b in blocks if b.startswith("HTTP/")), "")
        try:
            status = int(header.splitlines()[0].split()[1])
        except (IndexError, ValueError):
            raise APIError(0, "missing or malformed HTTP status")
        body = blocks[-1].strip() if blocks else ""
        parsed: Any = None
        if body:
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError as exc:
                raise APIError(status, "malformed JSON response") from exc
        if result.returncode and status != 404:
            message = parsed.get("message", "request failed") if isinstance(parsed, dict) else "request failed"
            raise APIError(status, message)
        return status, parsed

    @staticmethod
    def endpoint_ref(ref: str) -> str:
        assert ref.startswith("refs/heads/")
        return ref.removeprefix("refs/")

    def get(self, ref: str) -> dict[str, Any] | None:
        status, body = self._request("GET", f"repos/{self.repo}/git/ref/{self.endpoint_ref(ref)}")
        if status == 404:
            return None
        if status != 200:
            raise APIError(status, "unexpected ref lookup response")
        return body

    def create(self, ref: str, sha: str) -> dict[str, Any]:
        status, body = self._request("POST", f"repos/{self.repo}/git/refs", {"ref": ref, "sha": sha})
        if status != 201:
            raise APIError(status, "unexpected ref create response")
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
    for command in ("create-ref", "delete-ref"):
        p = sub.add_parser(command)
        p.add_argument("--repo", required=True)
        p.add_argument("--ref", required=True)
        p.add_argument("--sha", required=True)
    for command in ("validate-json", "validate-html"):
        p = sub.add_parser(command)
        p.add_argument("--phase", choices=("green", "red"), required=True)
        p.add_argument("path", type=Path)
    p = sub.add_parser("restore")
    p.add_argument("--context", required=True)
    args = parser.parse_args()
    if args.command == "create-ref":
        create_owned_ref(GitHubRefsAPI(args.repo), args.ref, args.sha)
    elif args.command == "delete-ref":
        delete_owned_ref(GitHubRefsAPI(args.repo), args.ref, args.sha)
    elif args.command == "validate-json":
        validate_status(json.loads(args.path.read_text()), args.phase)
    elif args.command == "validate-html":
        validate_html(args.path.read_text(), args.phase)
    else:
        restore_cluster(args.context)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, APIError, json.JSONDecodeError) as exc:
        print(f"final-qa-helper: ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
