#!/usr/bin/env python3
# pylint: disable=missing-docstring
"""
Gửi thử bulk upload Debit Note (multipart) để kiểm tra mạng / nginx / gunicorn.

- Sinh file giả trong RAM (PDF giả chỉ là bytes lặp, ~200KB mỗi file).
- Gửi theo đợt (chunk) để tránh một request ~300MB+ với 1500 × 200KB.

Cách dùng:

  cd frappe-backend
  pip install requests   # nếu chưa có

  export FRAPPE_BASE_URL=https://prod.sis.wellspring.edu.vn
  export FRAPPE_ORDER_ID=<ID đơn SIS Finance Order>
  export FRAPPE_TOKEN='<JWT như trong localStorage frappe_token>'
  python3 scripts/stress_bulk_debit_upload.py --total 1500 --size-kb 200 --chunk 60

Tham số JWT thường kèm header giống FE (Bearer + X-Frappe-*).

Tên file mặc định PREFIX_000001.pdf … sẽ KHÔNG khớp học sinh thật
→ backend trả lỗi theo file nhưng vẫn parse multipart / hit DB nhẹ (stress hợp lý cho tầng HTTP).
Nếu muốn thử ít nhất vài file thành công: --prefix WS123 và đảm bảo có student_code trong đơn.

Lưu ý: chỉ chạy trên môi trường cho phép test; không dùng trên prod nếu policy cấm.
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import time
from urllib.parse import quote


def parse_args():
    # Comment tiếng Việt: tham số dòng lệnh
    p = argparse.ArgumentParser(description="Stress test bulk_upload_debit_notes")
    p.add_argument("--base-url", default=os.environ.get("FRAPPE_BASE_URL", "").rstrip("/"))
    p.add_argument("--order-id", default=os.environ.get("FRAPPE_ORDER_ID", ""))
    p.add_argument("--token", default=os.environ.get("FRAPPE_TOKEN", ""))
    p.add_argument("--total", type=int, default=1500, help="Tổng số file gửi")
    p.add_argument("--size-kb", type=int, default=200, help="Kích thước mỗi file (KB)")
    p.add_argument("--chunk", type=int, default=60, help="Số file mỗi request HTTP")
    p.add_argument(
        "--prefix",
        default="STRESSTEST",
        help="Tiền tố tên file (mã học sinh pseudo), ví dụ WS112233",
    )
    p.add_argument("--timeout", type=int, default=1200, help="Timeout một request (giây)")
    return p.parse_args()


def build_payload(size_kb: int) -> bytes:
    """Nội dung giả có kích thước cố định (không parse được PDF nhưng đủ nặng mạng)."""
    chunk = os.urandom(4096)
    target = max(1024, size_kb * 1024)
    out = io.BytesIO()
    while out.tell() < target:
        need = target - out.tell()
        out.write(chunk[:need] if need < len(chunk) else chunk)
    return out.getvalue()


def frappe_headers(token: str) -> dict[str, str]:
    # Đồng bộ với frappe-sis-frontend api.ts (Bearer + X-Frappe-*)
    t = token.strip()
    return {
        "Authorization": f"Bearer {t}",
        "X-Frappe-Token": t,
        "X-Frappe-CSRF-Token": t,
        "Accept": "application/json",
    }


def main() -> int:
    args = parse_args()
    if not args.base_url:
        print("Thiếu FRAPPE_BASE_URL hoặc --base-url", file=sys.stderr)
        return 2
    if not args.order_id:
        print("Thiếu FRAPPE_ORDER_ID hoặc --order-id", file=sys.stderr)
        return 2
    if not args.token:
        print("Thiếu FRAPPE_TOKEN hoặc --token (JWT trong localStorage frappe_token)", file=sys.stderr)
        return 2

    try:
        import requests
    except ImportError:
        print("Cần cài requests: pip install requests", file=sys.stderr)
        return 2

    url = (
        f"{args.base_url}/api/method/erp.api.erp_sis.finance.bulk_upload_debit_notes"
        f"?order_id={quote(args.order_id, safe='')}"
    )
    blob = build_payload(args.size_kb)
    headers = frappe_headers(args.token)

    total_sent = 0
    batches = (args.total + args.chunk - 1) // args.chunk
    t0 = time.perf_counter()

    for batch_idx in range(batches):
        n = min(args.chunk, args.total - total_sent)
        if n <= 0:
            break
        file_tuples = []
        for i in range(n):
            idx = total_sent + i + 1
            name = f"{args.prefix}_{idx:06d}.pdf"
            file_tuples.append(("files", (name, io.BytesIO(blob), "application/pdf")))

        data_form = {"order_id": args.order_id}
        t_req = time.perf_counter()
        try:
            r = requests.post(
                url,
                data=data_form,
                files=file_tuples,
                headers=headers,
                timeout=args.timeout,
            )
        except requests.exceptions.RequestException as e:
            print(f"Đợt {batch_idx + 1}/{batches}: Lỗi HTTP {e}", file=sys.stderr)
            return 1

        elapsed = time.perf_counter() - t_req
        total_sent += n
        print(
            f"Đợt {batch_idx + 1}/{batches}: POST {r.status_code} | {n} file | {elapsed:.1f}s "
            f"| body ~{len(blob) * n / (1024 * 1024):.1f} MB (payload)"
        )
        try:
            body = r.json()
        except Exception:
            print(r.text[:2000], file=sys.stderr)
            return 1

        wrapped = body.get("message")
        msg_body = wrapped if isinstance(wrapped, dict) else body

        ok = isinstance(msg_body, dict) and msg_body.get("success") is True
        batch_data = msg_body.get("data") if isinstance(msg_body, dict) else None

        if isinstance(batch_data, dict):
            print(
                f"  → success_count={batch_data.get('success_count')} "
                f"error_count={batch_data.get('error_count')} total(batch)={batch_data.get('total')}"
            )

        if r.status_code >= 400 or not ok:
            print(f"Lỗi: HTTP {r.status_code} | {msg_body}", file=sys.stderr)
            return 1

    dur = time.perf_counter() - t0
    print(f"Xong {total_sent} file trong {dur:.1f}s ({dur / max(total_sent, 1) * 1000:.1f} ms/file trung bình)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
