#!/usr/bin/env bash
# Chay cdn-checks.sh, chong lap alert, gui email qua email-service.
set -uo pipefail
. /opt/cdn/alert.env
STATE=/var/lib/cdn-alert
mkdir -p "$STATE"
NOW=$(date +%s)
REPEAT=$(( ${ALERT_REPEAT_HOURS:-6} * 3600 ))

send_mail() {
  local subject="$1" body="$2"
  local payload code
  payload=$(jq -n \
    --arg to "$ALERT_TO" \
    --arg from "$ALERT_FROM" \
    --arg subject "$subject" \
    --arg body "$body" \
    '{to: [$to], from: $from, subject: $subject, contentType: "HTML", body: $body}')

  local args=(-s -m 20 -o /tmp/cdn-alert-resp.json -w "%{http_code}"
              -X POST "$ALERT_EMAIL_ENDPOINT" -H "Content-Type: application/json")
  if [ -n "${ALERT_API_KEY:-}" ]; then
    args+=(-H "x-api-key: ${ALERT_API_KEY}")
  fi
  args+=(--data-binary "$payload")

  code=$(curl "${args[@]}")
  if [ "$code" = "200" ]; then
    logger -t cdn-alert "sent: $subject"
    return 0
  fi
  logger -t cdn-alert "FAILED (http $code): $subject -- $(head -c 300 /tmp/cdn-alert-resp.json 2>/dev/null)"
  return 1
}

html() {
  local sev="$1" msg="$2"
  local color="#b45309"
  [ "$sev" = "CRIT" ] && color="#b91c1c"
  [ "$sev" = "OK" ] && color="#15803d"
  cat <<HTML
<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;font-size:14px;line-height:1.6">
  <p style="margin:0 0 12px"><span style="background:${color};color:#fff;padding:2px 8px;border-radius:3px;font-weight:600">${sev}</span>
  &nbsp;<strong>CDN ${ALERT_HOST}</strong></p>
  <p style="margin:0 0 12px">${msg}</p>
  <hr style="border:0;border-top:1px solid #e5e7eb;margin:16px 0">
  <p style="margin:0;color:#6b7280;font-size:12px">
    VM3 &middot; $(hostname) &middot; $(date "+%Y-%m-%d %H:%M:%S %Z")<br>
    Disk /data: $(df -h --output=pcent,avail /data | tail -1 | tr -s " ") &middot;
    Uptime: $(uptime -p)
  </p>
</div>
HTML
}

SEEN=$(mktemp)
trap 'rm -f "$SEEN"' EXIT

while IFS=$'\t' read -r SEV KEY MSG; do
  [ -z "${KEY:-}" ] && continue
  echo "$KEY" >> "$SEEN"
  F="$STATE/$KEY"
  if [ -f "$F" ]; then
    read -r LAST_SEV LAST_TS < "$F"
    # gui lai neu leo thang WARN->CRIT, hoac qua ALERT_REPEAT_HOURS
    if [ "$SEV" = "$LAST_SEV" ] && [ $(( NOW - LAST_TS )) -lt "$REPEAT" ]; then
      continue
    fi
  fi
  if send_mail "[$SEV] CDN $ALERT_HOST - $KEY" "$(html "$SEV" "$MSG")"; then
    echo "$SEV $NOW" > "$F"
  fi
done < <(/opt/cdn/bin/cdn-checks.sh)

# Bao phuc hoi cho cac key da het canh bao
for F in "$STATE"/*; do
  [ -e "$F" ] || continue
  KEY=$(basename "$F")
  if grep -qx "$KEY" "$SEEN" 2>/dev/null; then
    continue
  fi
  if send_mail "[OK] CDN $ALERT_HOST - $KEY da phuc hoi" \
       "$(html OK "Canh bao <strong>${KEY}</strong> khong con. He thong tro lai binh thuong.")"; then
    rm -f "$F"
  fi
done

exit 0
