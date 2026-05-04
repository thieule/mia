#!/usr/bin/env bash
# Xóa toàn bộ task file-based của working queue (pending / processing / done / failed + state).
# Nên dừng gateway Mia tech (start.py) trước khi chạy.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
WQ="${WORKING_QUEUE_DIR:-"$ROOT/workspace/working_queue"}"

if [[ ! -d "$WQ" ]]; then
  echo "Không thấy thư mục queue: $WQ" >&2
  exit 1
fi

echo "Reset working queue tại: $WQ"
shopt -s nullglob
for d in pending processing done failed; do
  for f in "$WQ/$d"/*.json; do
    rm -f "$f"
    echo "  removed $f"
  done
done
for f in "$WQ/state/items"/*.json; do
  rm -f "$f"
  echo "  removed $f"
done
rm -f "$WQ/state/summary.json" "$WQ/state/ledger.jsonl" 2>/dev/null || true
echo "  removed state/summary.json state/ledger.jsonl (nếu có)"

if [[ -d "$WQ/projects" ]]; then
  find "$WQ/projects" -type f -name '*.json' -print -delete 2>/dev/null || true
fi

echo "Xong. Khởi động lại gateway Mia tech nếu đang tắt."
