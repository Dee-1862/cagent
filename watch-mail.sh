#!/usr/bin/env bash
# Wait for new agent mail without spending model usage.
#
# Polls GitHub every INTERVAL seconds and exits as soon as the other side's
# outbox changes, printing the new lines. Run it in the background from your
# agent; when it exits, read the mail and reply, then start it again.
#
# Usage (from any checkout of the repo):
#   bash watch-mail.sh deekshith-to-rishit.md     # Rishit's agents watch this
#   bash watch-mail.sh rishit-to-deekshith.md     # Deekshith's agents watch this
# Optional: INTERVAL=180 (seconds), MAX_HOURS=8
set -euo pipefail

FILE="${1:?usage: watch-mail.sh <outbox file to watch>}"
INTERVAL="${INTERVAL:-180}"
MAX_HOURS="${MAX_HOURS:-8}"
REF="origin/agent-mail"

git fetch -q origin agent-mail
before="$(git show "$REF:$FILE" 2>/dev/null || true)"
deadline=$(( $(date +%s) + MAX_HOURS * 3600 ))

while [ "$(date +%s)" -lt "$deadline" ]; do
  sleep "$INTERVAL"
  git fetch -q origin agent-mail || continue
  after="$(git show "$REF:$FILE" 2>/dev/null || true)"
  if [ "$after" != "$before" ]; then
    echo "NEW MAIL in $FILE ($(git log -1 --format='%h %s' "$REF"))"
    diff <(printf '%s\n' "$before") <(printf '%s\n' "$after") | sed -n 's/^> //p'
    exit 0
  fi
done
echo "No new mail in $FILE after $MAX_HOURS hours."
