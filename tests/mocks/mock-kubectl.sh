#!/bin/bash
# Mock kubectl: intercepts apply boundaries, succeeds on wait commands.
# Set LOG_DIR env var to control where rendered YAML and logs are written.

LOG_DIR="${LOG_DIR:-/tmp/mock-kubectl-logs}"
mkdir -p "$LOG_DIR"

echo "mock-kubectl: $*" >> "$LOG_DIR/kubectl-calls.log"

apply_mode=""
apply_target=""
for ((i=1; i<=$#; i++)); do
  arg="${!i}"
  if [ "$arg" = "apply" ]; then
    next_idx=$((i+1))
    if [ $next_idx -le $# ]; then
      flag="${!next_idx}"
      target_idx=$((next_idx+1))
      target="${!target_idx}"
      if [ "$flag" = "-k" ]; then
        apply_mode="-k"
        apply_target="$target"
      elif [ "$flag" = "-f" ]; then
        apply_mode="-f"
        apply_target="$target"
      fi
    fi
    break
  fi
done

if [ -n "$apply_mode" ]; then
  echo "APPLY_BOUNDARY: $apply_mode $apply_target" >> "$LOG_DIR/apply-boundary.log"
  if [ "$apply_mode" = "-k" ] && [ -n "$apply_target" ]; then
    if command -v kustomize &>/dev/null; then
      kustomize build "$apply_target" >> "$LOG_DIR/apply-rendered.yaml" 2>>"$LOG_DIR/kustomize-stderr.log"
      echo "RENDERED_BYTES: $(wc -c < "$LOG_DIR/apply-rendered.yaml" 2>/dev/null || echo 0)" >> "$LOG_DIR/apply-boundary.log"
    fi
  elif [ "$apply_mode" = "-f" ] && [ "$apply_target" = "-" ]; then
    cat >> "$LOG_DIR/apply-rendered.yaml"
    echo "RENDERED_BYTES: $(wc -c < "$LOG_DIR/apply-rendered.yaml" 2>/dev/null || echo 0)" >> "$LOG_DIR/apply-boundary.log"
  fi
fi

exit 0
