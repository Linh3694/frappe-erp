#!/usr/bin/env bash
# Áp dụng patch thủ công lên cây Frappe (core), không nằm trong repo khi bạn chỉ cài `bench get-app erp`.
# Chạy từ máy local / CI sau khi: bench clone, trước khi dùng Socket.IO + JWT từ SPA.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ERP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PATCH_FILE="${ERP_DIR}/patches/core/frappe-version-15-realtime-jwt-handshake.patch"
TARGET_SUBPATH="realtime/middlewares/authenticate.js"

# Cho phép override: FRAPPE_DIR=/path/to/bench/apps/frappe ./scripts/apply-frappe-core-patches.sh
if [[ -n "${FRAPPE_DIR:-}" ]]; then
  :
else
  FRAPPE_DIR="$(cd "${ERP_DIR}/../frappe" && pwd)"
fi

TARGET_FILE="${FRAPPE_DIR}/${TARGET_SUBPATH}"

if [[ ! -f "$PATCH_FILE" ]]; then
  echo "Thiếu file patch: $PATCH_FILE" >&2
  exit 1
fi

if [[ ! -f "$TARGET_FILE" ]]; then
  echo "Không tìm thấy Frappe tại: $TARGET_FILE" >&2
  echo "Gán FRAPPE_DIR= đường tới thư mục apps/frappe nếu bench không ở cùng cấp với app erp." >&2
  exit 1
fi

# Đã áp rồi thì bỏ qua (an toàn chạy lại nhiều lần)
if grep -q "socket\.handshake\.auth" "$TARGET_FILE" 2>/dev/null; then
  echo "Patch realtime JWT (handshake.auth) dường như đã áp dụng — bỏ qua: $TARGET_FILE"
  exit 0
fi

cd "$FRAPPE_DIR"
cp -a "${TARGET_SUBPATH}" "${TARGET_SUBPATH}.pre-erp-jwt-bak.$(date +%Y%m%d%H%M%S)"
patch -p1 < "$PATCH_FILE"
echo "Đã apply patch: $PATCH_FILE -> $TARGET_FILE"
echo "Backup: ${TARGET_FILE}.pre-erp-jwt-bak.* (cùng thư mục)"
