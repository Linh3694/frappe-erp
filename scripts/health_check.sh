#!/bin/bash
# Health check gunicorn — phân biệt down thật vs chậm/nghẽn.
# Không auto-restart khi chỉ timeout (degraded): tránh cắt worker lúc peak Hikvision 16-17h.
# Chỉ restart khi connection refused / không listen, và vượt ngưỡng cứng.
#
# Deploy (be-02): sau git pull app erp, copy vào bench:
#   cp apps/erp/scripts/health_check.sh /srv/app/frappe-bench/scripts/health_check.sh
#   chown frappe:frappe /srv/app/frappe-bench/scripts/health_check.sh
#   chmod +x /srv/app/frappe-bench/scripts/health_check.sh
# Cron (frappe): * * * * * /srv/app/frappe-bench/scripts/health_check.sh
# Log: /srv/app/frappe-bench/logs/health_check.log

LOG_FILE="/srv/app/frappe-bench/logs/health_check.log"
HARD_FAILURE_COUNT_FILE="/tmp/gunicorn_hard_failure_count"
SOFT_FAILURE_COUNT_FILE="/tmp/gunicorn_soft_failure_count"
# Down cứng (connection refused): restart sau N lần liên tiếp
MAX_HARD_FAILURES=5
# Timeout / HTTP lỗi: chỉ log, không restart
CURL_TIMEOUT_SEC=20
HOST_HEADER="prod.sis.wellspring.edu.vn"
PING_URL="http://127.0.0.1:8000/api/method/frappe.ping"

# Cửa sổ tan học: không bao giờ auto-restart (chỉ log)
HOUR=$(date +%H)
IN_PEAK_WINDOW=0
if [ "$HOUR" -eq 16 ] || [ "$HOUR" -eq 17 ]; then
	# 16:00–17:59
	IN_PEAK_WINDOW=1
fi

ts() { date '+%Y-%m-%d %H:%M:%S'; }

# Khởi tạo counter
[ -f "$HARD_FAILURE_COUNT_FILE" ] || echo "0" > "$HARD_FAILURE_COUNT_FILE"
[ -f "$SOFT_FAILURE_COUNT_FILE" ] || echo "0" > "$SOFT_FAILURE_COUNT_FILE"

# Port 8000 có đang listen không? (down cứng nếu không)
if ! ss -lntp 2>/dev/null | grep -q ':8000 '; then
	if ! netstat -lntp 2>/dev/null | grep -q ':8000 '; then
		LISTEN_OK=0
	else
		LISTEN_OK=1
	fi
else
	LISTEN_OK=1
fi

# curl: tách HTTP code và exit code
CURL_ERR_FILE=$(mktemp)
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -m "$CURL_TIMEOUT_SEC" \
	-H "Host: ${HOST_HEADER}" \
	"$PING_URL" 2>"$CURL_ERR_FILE")
CURL_EXIT=$?
CURL_ERR=$(tr '\n' ' ' <"$CURL_ERR_FILE" | head -c 200)
rm -f "$CURL_ERR_FILE"

# Phân loại
# curl 7 = Failed to connect; 52 empty reply; 56 recv failure ≈ down/reset
# curl 28 = timeout → degraded (worker bận), KHÔNG restart
STATE="ok"
if [ "$LISTEN_OK" -eq 0 ]; then
	STATE="hard_down"
elif [ "$CURL_EXIT" -eq 7 ] || [ "$CURL_EXIT" -eq 52 ] || [ "$CURL_EXIT" -eq 56 ]; then
	STATE="hard_down"
elif [ "$CURL_EXIT" -eq 28 ]; then
	STATE="soft_timeout"
elif [ "$HTTP_CODE" = "200" ]; then
	STATE="ok"
elif [ -z "$HTTP_CODE" ] || [ "$HTTP_CODE" = "000" ]; then
	# 000 thường là connect fail hoặc timeout — xem exit code
	if [ "$CURL_EXIT" -eq 28 ]; then
		STATE="soft_timeout"
	else
		STATE="hard_down"
	fi
else
	# 5xx / khác: degraded, không restart
	STATE="soft_http"
fi

if [ "$STATE" = "ok" ]; then
	echo "0" > "$HARD_FAILURE_COUNT_FILE"
	echo "0" > "$SOFT_FAILURE_COUNT_FILE"
	exit 0
fi

if [ "$STATE" = "soft_timeout" ] || [ "$STATE" = "soft_http" ]; then
	soft=$(cat "$SOFT_FAILURE_COUNT_FILE")
	soft=$((soft + 1))
	echo "$soft" > "$SOFT_FAILURE_COUNT_FILE"
	# Reset hard counter — vẫn còn process, chỉ chậm
	echo "0" > "$HARD_FAILURE_COUNT_FILE"
	echo "$(ts) - DEGRADED ($STATE) soft=$soft http=$HTTP_CODE curl_exit=$CURL_EXIT err=${CURL_ERR:-none} (no restart)" >> "$LOG_FILE"
	exit 0
fi

# hard_down
hard=$(cat "$HARD_FAILURE_COUNT_FILE")
hard=$((hard + 1))
echo "$hard" > "$HARD_FAILURE_COUNT_FILE"
echo "$(ts) - HARD_DOWN hard=$hard/$MAX_HARD_FAILURES http=$HTTP_CODE curl_exit=$CURL_EXIT listen=$LISTEN_OK err=${CURL_ERR:-none}" >> "$LOG_FILE"

if [ "$hard" -lt "$MAX_HARD_FAILURES" ]; then
	exit 0
fi

if [ "$IN_PEAK_WINDOW" -eq 1 ]; then
	echo "$(ts) - HARD_DOWN đạt ngưỡng nhưng trong cửa sổ 16-17h: KHÔNG restart, cần xử lý tay" >> "$LOG_FILE"
	# Giữ counter ở ngưỡng để log mỗi phút, không reset (tránh restart ngay 18:00 nếu vẫn down)
	exit 0
fi

echo "$(ts) - Restarting gunicorn after $MAX_HARD_FAILURES hard failures..." >> "$LOG_FILE"
cd /srv/app/frappe-bench || exit 1
sudo supervisorctl restart frappe-bench-web: >> "$LOG_FILE" 2>&1
echo "0" > "$HARD_FAILURE_COUNT_FILE"
echo "0" > "$SOFT_FAILURE_COUNT_FILE"
echo "$(ts) - Restart completed" >> "$LOG_FILE"
exit 0
