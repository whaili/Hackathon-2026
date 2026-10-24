#!/bin/bash
# Runs N trials alternating 查询游戏状态 / 拿起钥匙 against a deployed game
# backend through the real Lingxi voice path, classifying each trial as a
# real tool call or not by diffing the deployment host's `POST /mcp` log
# count before/after -- this avoids relying on subjective reading of the
# AI's reply text.
#
# Usage:
#   bash batch_test.sh [trials] [ssh_host] [docker_container]
#
# Requires: say.py to have already generated tools/audio/query_state.pcm
# and tools/audio/pick_key.pcm (see README.md in this directory), and SSH
# access to the deployment host to read backend logs.
set -u
cd "$(dirname "$0")"

TRIALS="${1:-10}"
SSH_HOST="${2:-jfcs1026}"
CONTAINER="${3:-dont-let-it-hear-game}"
RESULTS_FILE="batch_results.tsv"
echo -e "trial\tphrase\tmcp_post_count\toutcome\treply_snippet" > "$RESULTS_FILE"

get_log_count() {
  ssh "$SSH_HOST" "docker logs $CONTAINER 2>&1 | grep -c 'POST /mcp'"
}

for i in $(seq 1 "$TRIALS"); do
  if (( i % 2 == 1 )); then
    phrase="query_state"
    pcm="audio/query_state.pcm"
  else
    phrase="pick_key"
    pcm="audio/pick_key.pcm"
  fi

  before=$(get_log_count)
  out=$(timeout 35 python3 -u e2e_test.py "$pcm" 2>&1)
  after=$(get_log_count)
  delta=$((after - before))

  reply=$(echo "$out" | grep -o "'state': 'sentence_start', 'text': '[^']*'" | sed "s/'state': 'sentence_start', 'text': '//;s/'$//" | tr '\n' ' ' | cut -c1-120)

  if [ "$delta" -ge 4 ]; then
    outcome="OK(tool_called)"
  elif [ "$delta" -eq 3 ]; then
    outcome="FAIL(list_only)"
  else
    outcome="WEIRD(delta=$delta)"
  fi

  echo -e "${i}\t${phrase}\t${delta}\t${outcome}\t${reply}" | tee -a "$RESULTS_FILE"
  sleep 1
done

echo
echo "=== summary ==="
awk -F'\t' 'NR>1 {c[$4]++} END {for (k in c) print k, c[k]}' "$RESULTS_FILE"
