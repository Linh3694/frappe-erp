#!/usr/bin/env bash
# Kiem tra suc khoe CDN VM3 theo CDN-Design.md muc 12.2
# In ra stdout moi dong: <SEVERITY>\t<KEY>\t<MESSAGE>
# SEVERITY: WARN | CRIT ; KEY dung de chong lap alert
#
# Phan tich log tach RIENG TUNG BUCKET. Truoc day gop chung nen hai van de:
#   * su co ky o mot bucket bi pha loang trong traffic cua bucket khac
#     (hoc bong traffic thap, social traffic cao => 403 hoc bong khong bao gio
#     dat nguong 20% neu tinh gop);
#   * nhieu tu bot quet Internet (/robots.txt, /.ssh/id_ed25519, /backup.tar.gz)
#     duoc tinh vao mau, lam loang ti le tu choi that.
# Nay chi xet request co prefix la bucket da biet, va canh bao theo tung bucket.
set -uo pipefail

LOG=/var/log/nginx/cdn.access.log
WINDOW_MIN=${WINDOW_MIN:-15}

# Prefix duoc coi la media that. Them bucket moi thi them vao day.
BUCKETS="social-posts social-chat social-avatars scholarship student-photos sis-content discipline"

# Nguong toi thieu de mot ti le co y nghia thong ke — tranh bao dong gia luc vang
MIN_SAMPLE_DENY=30
MIN_SAMPLE_CACHE=50

emit() { printf "%s\t%s\t%s\n" "$1" "$2" "$3"; }

# --- 1. Disk /data ---
USE=$(df --output=pcent /data | tail -1 | tr -dc "0-9")
AVAIL=$(df -h --output=avail /data | tail -1 | tr -d " ")
if   [ "$USE" -ge 85 ]; then emit CRIT disk "Disk /data dat ${USE}% (nguong khan 85%). Con ${AVAIL} trong."
elif [ "$USE" -ge 75 ]; then emit WARN disk "Disk /data dat ${USE}% (nguong canh bao 75%). Con ${AVAIL} trong."
fi

# --- 2. MinIO health ---
if ! curl -sf -m 5 http://127.0.0.1:9000/minio/health/live -o /dev/null; then
  emit CRIT minio "MinIO khong phan hoi /minio/health/live tren 127.0.0.1:9000. Toan bo media (social + hoc bong) dang khong phuc vu duoc."
fi

# --- 3. Cert het han ---
CERT=/etc/letsencrypt/live/media.wellspring.edu.vn/fullchain.pem
if [ -f "$CERT" ]; then
  END=$(date -d "$(openssl x509 -enddate -noout -in "$CERT" | cut -d= -f2)" +%s)
  DAYS=$(( (END - $(date +%s)) / 86400 ))
  if   [ "$DAYS" -le 7 ];  then emit CRIT cert "Chung chi TLS media.wellspring.edu.vn con ${DAYS} ngay. Kiem tra certbot.timer."
  elif [ "$DAYS" -le 14 ]; then emit WARN cert "Chung chi TLS media.wellspring.edu.vn con ${DAYS} ngay."
  fi
fi

# --- 4. Phan tich log theo tung bucket ---
SINCE=$(date -d "-${WINDOW_MIN} min" +%Y-%m-%dT%H:%M:%S)

# Mot dong ket qua cho moi bucket: <bucket> <tot> <hit> <cacheable> <403> <410> <5xx> <p95>
STATS=$(gawk -F"\t" -v since="$SINCE" -v buckets="$BUCKETS" '
  BEGIN {
    n = split(buckets, b, " ")
    for (i = 1; i <= n; i++) known[b[i]] = 1
  }
  $1 >= since {
    # $5 la $uri, dang /<bucket>/<duong dan>
    split($5, seg, "/")
    bk = seg[2]
    if (!(bk in known)) next          # bo qua nhieu tu bot quet

    tot[bk]++
    if ($3 == "HIT") hit[bk]++
    is_cacheable = ($3 == "HIT" || $3 == "MISS" || $3 == "EXPIRED" || $3 == "STALE" || $3 == "UPDATING" || $3 == "REVALIDATED")
    if (is_cacheable) cacheable[bk]++
    if ($2 == 403) c403[bk]++
    if ($2 == 410) c410[bk]++
    if ($2 >= 500 && $2 < 600) c5xx[bk]++
    # p95 chi tinh tren request DI QUA CACHE va KHONG phai legacy.
    #
    #   * Video chay proxy_cache off, stream theo Range ($3 = "-") — latency cao
    #     la ban chat cua no chu khong phai su co.
    #   * File duoi legacy/ la anh cu chua qua pipeline nen: trung binh 1,78 MB
    #     (co file 2,7 MB) so voi 41 KB cua anh moi. Voi kich thuoc do thi 200ms
    #     la bat kha thi vi bi chan boi bang thong, khong phai boi CDN. De vao
    #     se sinh canh bao vinh vien va lam moi nguoi quen bo qua alert.
    #
    # SLO p95 vi vay chi ap cho noi dung DA qua pipeline — thu ma ta kiem soat
    # duoc kich thuoc. Van de anh legacy nang duoc theo doi rieng (job nen nen,
    # CDN-Design.md muc 9).
    if (is_cacheable && $5 !~ /\/legacy\//) rt[bk][++cnt[bk]] = $4 + 0
  }
  END {
    for (bk in tot) {
      m = asort(rt[bk])
      idx = int(m * 0.95); if (idx < 1) idx = 1; if (idx > m) idx = m
      p95 = (m > 0) ? rt[bk][idx] : 0
      printf "%s %d %d %d %d %d %d %.3f %d\n", bk, tot[bk], hit[bk]+0, cacheable[bk]+0,
             c403[bk]+0, c410[bk]+0, c5xx[bk]+0, p95, cnt[bk]+0
    }
  }' "$LOG" 2>/dev/null)

while read -r BK TOT HIT CACHEABLE C403 C410 C5XX P95 NP95; do
  [ -z "${BK:-}" ] && continue

  # Ti le tu choi — dau hieu lech secret hoac lech dong ho.
  # Tach theo bucket vi moi bucket mot duong ky rieng:
  #   social-*    ky boi social-service/services/cdn/sign.js
  #   scholarship ky boi erp/common/cdn_sign.py
  # Lech mot ben thi ben kia van binh thuong.
  if [ "$TOT" -ge "$MIN_SAMPLE_DENY" ]; then
    DENY=$(( C403 + C410 ))
    PCT=$(( DENY * 100 / TOT ))
    if [ "$PCT" -ge 20 ]; then
      case "$BK" in
        scholarship|student-photos|sis-content) NGUON="erp/common/cdn_sign.py" ;;
        *)           NGUON="social-service/services/cdn/sign.js" ;;
      esac
      emit CRIT "signdeny-${BK}" "Bucket ${BK}: 403/410 chiem ${PCT}% (${C403} x 403, ${C410} x 410) tren ${TOT} request trong ${WINDOW_MIN} phut. Nghi lech CDN_LINK_SECRET giua ${NGUON} va nginx VM3, hoac lech dong ho NTP."
    fi
  fi

  # Cache hit
  if [ "$CACHEABLE" -ge "$MIN_SAMPLE_CACHE" ]; then
    RATE=$(( HIT * 100 / CACHEABLE ))
    # Nguong theo bucket. 70% hop voi bucket co tap lam viec NONG va NHO (feed,
    # avatar: it anh, nhieu nguoi xem cung luc). student-photos va sis-content la
    # danh muc DUOI DAI: do duoc 432 request tren 369 URI rieng biet, chi 58 URI
    # duoc goi lai — tran hit rate vi vay chi khoang 15%, khong the dat 70% du
    # CDN hoan toan binh thuong. Giu 70% o day = WARN vinh vien.
    # (proxy_cache_key la "$uri", KHONG gom query, nen vong quay chu ky khong
    #  phai nguyen nhan — dung de thong bao goi y sai huong nhu truoc.)
    # student-photos: do duoc 432 request / 369 URI rieng biet => TRAN hit rate
    # chi ~15%, thuc do 10%. Nguong 5% van bat duoc su co that (cache bi xoa
    # sach => 0%) ma khong bao dong khi moi thu binh thuong.
    # sis-content: dang 68% vi traffic kiem thu lap lai, ve lau dai se xuong theo
    # kieu duoi dai; 25% la muc con y nghia.
    case "$BK" in
      student-photos) CACHE_MIN=5  ;;
      sis-content)    CACHE_MIN=25 ;;
      *)              CACHE_MIN=70 ;;
    esac
    [ "$RATE" -lt "$CACHE_MIN" ] && emit WARN "cachehit-${BK}" "Bucket ${BK}: cache hit rate ${RATE}% tren ${CACHEABLE} request cache duoc (nguong ${CACHE_MIN}%). Kiem tra cache vua bi xoa, hoac tap truy cap doi sang duoi dai hon binh thuong."
  fi

  # p95 latency — mau da loai video va legacy (xem chu thich trong gawk)
  if [ "${NP95:-0}" -ge "$MIN_SAMPLE_DENY" ]; then
    # BO QUA p95 voi hai bucket anh LON — cung ly do da loai video va legacy/.
    #
    # Cot latency trong log la $request_time (xem /etc/nginx/conf.d/cdn-log.conf),
    # tinh CA thoi gian day du lieu ve MAY KHACH. Do that 2026-07-30:
    #   student-photos  p50=0.473  p95=6.044  max=7.587   (~640 KB/anh)
    #   sis-content     p50=0.002  p95=0.826  max=5.751   (~190 KB, news 1,4 MB)
    #   social-chat     p50=0.020  p95=0.195              (41 KB — vua khop 0.2s)
    # 640 KB / 6 s = ~107 KB/s: day la bang thong 4G cua dien thoai, KHONG phai
    # hieu nang CDN. Moi nguong dat cho hai bucket nay chi do bang thong client,
    # nen se sinh WARN vinh vien va lam moi nguoi quen bo qua alert.
    #
    # Muon do dung hieu nang CDN cho nhung bucket nay thi phai ghi them
    # $upstream_response_time vao log_format roi canh bao theo cot do — viec nay
    # doi cot log nen phai sua song song ca gawk o tren, chua lam.
    case "$BK" in
      student-photos|sis-content) LIMIT="" ;;
      *)                          LIMIT=0.2 ;;
    esac
    if [ -n "$LIMIT" ]; then
      SLOW=$(gawk -v p="$P95" -v l="$LIMIT" 'BEGIN { print (p > l) ? 1 : 0 }')
      [ "$SLOW" = "1" ] && emit WARN "latency-${BK}" "Bucket ${BK}: p95 latency ${P95}s (nguong ${LIMIT}s) tren ${NP95} request anh da qua pipeline."
    fi
  fi

  # Loi upstream tu MinIO
  [ "$C5XX" -ge 10 ] && emit CRIT "upstream-${BK}" "Bucket ${BK}: ${C5XX} loi 5xx tu MinIO trong ${WINDOW_MIN} phut."
done <<< "$STATS"

# --- 5. NTP ---
if ! timedatectl show -p NTPSynchronized --value | grep -q yes; then
  emit WARN ntp "Dong ho he thong CHUA dong bo NTP. secure_link so sanh timestamp; lech qua vai phut se sinh 410 hang loat."
fi
