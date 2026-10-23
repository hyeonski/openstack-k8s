#!/usr/bin/env bash
# Small public workflow; existing runners retain ownership, guards and evidence.
set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
scenario="${1:-}"
action="${2:-run}"
steps=()
case "${scenario}:${action}" in
  s1:run) steps=(graduation-s1-prepare graduation-s1-spread graduation-s1-verify graduation-s1-auto graduation-s1-auto-cleanup graduation-s1-cleanup) ;;
  s1:status) steps=(graduation-s1-status graduation-s1-auto-status) ;;
  s1:cleanup) steps=(graduation-s1-auto-cleanup graduation-s1-cleanup) ;;
  s2:run) steps=(graduation-s2 graduation-s2-cleanup) ;;
  s2:status) steps=(graduation-s2-status) ;;
  s2:cleanup) steps=(graduation-s2-cleanup) ;;
  s3:run) steps=(graduation-s3 graduation-s3-cleanup) ;;
  s3:status) steps=(graduation-s3-status) ;;
  s3:cleanup) steps=(graduation-s3-cleanup) ;;
  s4:run) steps=(graduation-s4-run) ;;
  s4:status) steps=(graduation-s4-workflow-status graduation-s4-run-status graduation-s4-status) ;;
  s4:cleanup) steps=(graduation-s4-cleanup) ;;
  s4:resume) steps=(graduation-s4-resume) ;;
  *) echo 'Use SCENARIO=s1|s2|s3|s4 ACTION=run|status|cleanup (resume: s4 only).' >&2; exit 2 ;;
esac
for step in "${steps[@]}"; do
  if make --no-print-directory -C "${PROJECT_ROOT}" "${step}"; then
    continue
  else
    result=$?
    echo "Stopped at ${step}; inspect ACTION=status and the retained evidence before cleanup/resume." >&2
    exit "${result}"
  fi
done
