#!/usr/bin/env bash
# Áp bản sửa Socket.IO (JWT qua handshake.auth) lên cây Frappe bằng cách copy file overlay
# theo major version (15/16). An toàn để chạy trên prod:
#   - Phát hiện pristine upstream vs đã patched vs custom (từ chối nếu lạ, trừ khi FORCE=1)
#   - Backup *.pre-erp-jwt-bak.<ts> trước khi ghi
#   - Kiểm tra cú pháp bằng `node --check`; nếu lỗi, tự động rollback backup
#   - Idempotent, DRY_RUN, lệnh phụ `verify`
#
# Lệnh:
#   ./scripts/apply-frappe-core-patches.sh           # áp dụng (mặc định)
#   ./scripts/apply-frappe-core-patches.sh verify    # chỉ kiểm tra trạng thái
#   ./scripts/apply-frappe-core-patches.sh revert    # khôi phục từ backup gần nhất
#
# Biến môi trường:
#   FRAPPE_DIR=...            bắt buộc khi cấu trúc bench khác chuẩn
#   FRAPPE_OVERLAY_MAJOR=15|16 bỏ qua auto-detect version
#   FORCE=1                   ghi đè ngay cả khi file đích "lạ" (có custom hotfix khác)
#   DRY_RUN=1                 in việc sẽ làm, không thay đổi gì

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ERP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
TARGET_SUBPATH="realtime/middlewares/authenticate.js"
CMD="${1:-apply}"

if [[ -n "${FRAPPE_DIR:-}" ]]; then
	:
else
	FRAPPE_DIR="$(cd "${ERP_DIR}/../frappe" && pwd)"
fi

TARGET_FILE="${FRAPPE_DIR}/${TARGET_SUBPATH}"
INIT_PY="${FRAPPE_DIR}/frappe/__init__.py"

log() { printf '[apply-core-patch] %s\n' "$*"; }
warn() { printf '[apply-core-patch][warn] %s\n' "$*" >&2; }
die() { printf '[apply-core-patch][error] %s\n' "$*" >&2; exit 1; }

# Hash SHA-256 của file (dùng shasum/sha256sum)
hash_file() {
	if command -v sha256sum >/dev/null 2>&1; then
		sha256sum "$1" | awk '{print $1}'
	else
		shasum -a 256 "$1" | awk '{print $1}'
	fi
}

[[ -f "$INIT_PY" ]] || die "Không tìm thấy Frappe: $INIT_PY (đặt FRAPPE_DIR=...)"
[[ -f "$TARGET_FILE" ]] || die "Thiếu file đích: $TARGET_FILE"

if [[ -n "${FRAPPE_OVERLAY_MAJOR:-}" ]]; then
	MAJOR="${FRAPPE_OVERLAY_MAJOR}"
else
	MAJOR="$(
		python3 -c "
import re, sys
t = open(sys.argv[1], encoding='utf-8', errors='replace').read()
m = re.search(r\"__version__\\s*=\\s*['\\\"]([0-9]+)\", t)
print(m.group(1) if m else '0')
" "$INIT_PY"
	)"
fi

OVERLAY="${ERP_DIR}/patches/overlay/v${MAJOR}/realtime/middlewares/authenticate.js"

# SHA-256 của pristine upstream (frappe/frappe raw) đã chốt.
# Nếu Frappe vá hotfix và đổi hash, script sẽ từ chối (tránh ghi đè mù).
PRISTINE_V15_SHA256="3c153527523c584b04a465a1167d6fbc3c585e8e72c26eadf2d7b3c42d36ddc9"
PRISTINE_V16_SHA256="a150cbedb44008a24ae697a6173d33493eb8e1bac71887579801a3b522e2c220"

pristine_sha_for_major() {
	case "$1" in
		15) echo "$PRISTINE_V15_SHA256" ;;
		16) echo "$PRISTINE_V16_SHA256" ;;
		*)  echo "" ;;
	esac
}

# Trạng thái hiện tại của file đích:
#   patched   — đã có "socket.handshake.auth" (khớp cách patch của chúng ta)
#   pristine  — khớp SHA upstream đã chốt cho major tương ứng
#   unknown   — khác cả hai (có thể upstream đổi, hoặc có hotfix tay khác)
classify_target() {
	if grep -q "socket\.handshake\.auth" "$TARGET_FILE"; then
		echo "patched"; return
	fi
	local have
	have="$(hash_file "$TARGET_FILE")"
	local want
	want="$(pristine_sha_for_major "$MAJOR")"
	if [[ -n "$want" && "$have" == "$want" ]]; then
		echo "pristine"
	else
		echo "unknown"
	fi
}

latest_backup() {
	ls -1 "${TARGET_FILE}.pre-erp-jwt-bak."* 2>/dev/null | sort | tail -n1
}

verify_cmd() {
	log "FRAPPE_DIR = $FRAPPE_DIR"
	log "Frappe major = $MAJOR"
	log "Target       = $TARGET_FILE"
	log "Target sha256= $(hash_file "$TARGET_FILE")"
	log "State        = $(classify_target)"
	if [[ -f "$OVERLAY" ]]; then
		log "Overlay      = $OVERLAY"
		log "Overlay sha  = $(hash_file "$OVERLAY")"
	else
		warn "Chưa có overlay cho v${MAJOR} tại $OVERLAY"
	fi
	local bk
	bk="$(latest_backup || true)"
	[[ -n "$bk" ]] && log "Backup gần nhất = $bk" || true
}

node_syntax_check() {
	local f="$1"
	if ! command -v node >/dev/null 2>&1; then
		warn "Không tìm thấy 'node' — bỏ qua syntax check. Vui lòng cài Node trước khi đưa lên prod."
		return 0
	fi
	node --check "$f"
}

apply_cmd() {
	# Tiền điều kiện
	if [[ "$MAJOR" != "15" && "$MAJOR" != "16" ]]; then
		die "Không hỗ trợ auto-overlay cho Frappe major=$MAJOR. Đặt FRAPPE_OVERLAY_MAJOR=15 hoặc 16 nếu layout giống bản đó."
	fi
	[[ -f "$OVERLAY" ]] || die "Thiếu overlay: $OVERLAY"

	local state
	state="$(classify_target)"
	log "Frappe major = $MAJOR; state = $state"

	case "$state" in
		patched)
			log "Đã áp dụng sẵn — bỏ qua: $TARGET_FILE"
			exit 0
			;;
		pristine)
			log "File đích là bản upstream đã chốt (sha khớp) — an toàn để overlay."
			;;
		unknown)
			if [[ "${FORCE:-0}" != "1" ]]; then
				warn "File đích KHÁC upstream đã chốt cho v${MAJOR} (có thể Frappe ra hotfix hoặc đã có hotfix tay khác)."
				warn "Target sha256: $(hash_file "$TARGET_FILE")"
				warn "Expect sha256: $(pristine_sha_for_major "$MAJOR")"
				warn "Để tránh break prod, lệnh dừng lại. Kiểm tra diff với overlay, hoặc chạy lại với FORCE=1 nếu bạn chắc chắn overlay tương thích."
				warn "Gợi ý: diff -u \"$TARGET_FILE\" \"$OVERLAY\" | less"
				exit 2
			fi
			warn "FORCE=1 — vẫn ghi đè dù file đích lạ."
			;;
	esac

	local ts backup
	ts="$(date +%Y%m%d%H%M%S)"
	backup="${TARGET_FILE}.pre-erp-jwt-bak.${ts}"

	if [[ "${DRY_RUN:-0}" == "1" ]]; then
		log "[DRY_RUN] sẽ backup:   $backup"
		log "[DRY_RUN] sẽ ghi:       $TARGET_FILE  (<- $OVERLAY)"
		log "[DRY_RUN] sẽ node --check $TARGET_FILE"
		exit 0
	fi

	cp -a "$TARGET_FILE" "$backup"
	log "Backup: $backup"
	cp -a "$OVERLAY" "$TARGET_FILE"
	log "Đã ghi: $TARGET_FILE"

	if ! node_syntax_check "$TARGET_FILE"; then
		warn "node --check THẤT BẠI — khôi phục backup để không ảnh hưởng dịch vụ."
		cp -a "$backup" "$TARGET_FILE"
		die "Đã rollback. Vui lòng kiểm tra overlay v${MAJOR}."
	fi

	log "OK. Chạy \`bench restart\` để node-socketio nạp lại middleware."
}

revert_cmd() {
	local bk
	bk="$(latest_backup || true)"
	[[ -n "$bk" ]] || die "Không thấy backup *.pre-erp-jwt-bak.* nào để khôi phục."
	if [[ "${DRY_RUN:-0}" == "1" ]]; then
		log "[DRY_RUN] sẽ khôi phục: $bk -> $TARGET_FILE"
		exit 0
	fi
	cp -a "$bk" "$TARGET_FILE"
	log "Đã khôi phục: $TARGET_FILE (từ $bk). Chạy \`bench restart\`."
}

case "$CMD" in
	apply)  apply_cmd ;;
	verify) verify_cmd ;;
	revert) revert_cmd ;;
	*)      die "Lệnh không hiểu: $CMD (dùng: apply | verify | revert)" ;;
esac
