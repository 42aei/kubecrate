#!/usr/bin/env bash
set -Eeuo pipefail
pid="$1"
log="$2"
url="$3"
timeout="${4:-20}"
interval="${5:-0.25}"
attempts="$(python3 -c 'import math,sys; print(max(1, math.ceil(float(sys.argv[1])/float(sys.argv[2]))))' "${timeout}" "${interval}")"
for (( attempt=1; attempt<=attempts; attempt++ )); do
  if ! kill -0 "${pid}" 2>/dev/null; then
    printf 'port-forward exited early; see %s\n' "${log}" >&2
    exit 1
  fi
  if curl --fail --silent "${url}" >/dev/null 2>&1; then
    exit 0
  fi
  sleep "${interval}"
done
printf 'port-forward readiness timed out; see %s\n' "${log}" >&2
exit 1
