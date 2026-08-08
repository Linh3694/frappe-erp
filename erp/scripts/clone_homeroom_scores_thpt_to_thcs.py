# Copyright (c) 2026, Wellspring International School
"""
Thay bộ lựa chọn Điểm chủ nhiệm của THCS bằng bản sao của THPT.

    # 1. Rà soát (KHÔNG ghi gì) — luôn chạy trước:
    bench --site <site> execute erp.scripts.clone_homeroom_scores_thpt_to_thcs.run

    # 2. Chạy thật:
    bench --site <site> execute erp.scripts.clone_homeroom_scores_thpt_to_thcs.run \
        --kwargs "{'dry_run': 0}"

    # Đổi ngày áp dụng / loại điểm nếu cần:
    bench --site <site> execute erp.scripts.clone_homeroom_scores_thpt_to_thcs.run \
        --kwargs "{'dry_run': 0, 'effective_date': '2026-08-10', 'score_type': 'homeroom'}"

Hai bước, chạy trong CÙNG một transaction (lỗi giữa chừng thì rollback cả hai):

    1. TẮT (is_active = 0) mọi lựa chọn `score_type` hiện có của THCS.
       KHÔNG xoá — bản ghi cũ vẫn còn để dữ liệu điểm đã nhập trước đây tra ngược được.

    2. CLONE mọi lựa chọn `score_type` đang bật của THPT sang THCS: tạo bản ghi mới
       (cùng title_vn/title_en/value/color) + một đợt áp dụng điểm ở `effective_date`.

Về giá trị điểm của bản clone: `value` gốc đặt luôn bằng value của THPT, đồng thời tạo
một SIS Class Log Score Version ở `effective_date` cùng giá trị đó. Nghĩa là điểm không
đổi trước/sau ngày áp dụng — đợt ở đây đóng vai trò MỐC GHI NHẬN, để sau này sửa điểm
thì thêm đợt mới chứ không ghi đè lịch sử. Muốn "trước ngày áp dụng thì chưa có điểm",
chạy với `base_value: 0`.

An toàn khi chạy lại (idempotent): lựa chọn nào của THCS đã trùng title_vn với bản THPT
đang bật sẽ được BỎ QUA, không tạo trùng.
"""

from __future__ import annotations

import frappe
from frappe.utils import getdate

DEFAULT_EFFECTIVE_DATE = "2026-08-10"
VERSION_DOCTYPE = "SIS Class Log Score Version"


def _resolve_stage(keyword: str) -> dict | None:
    """Tìm SIS Education Stage theo từ khoá trong title_vn (vd 'Cơ sở', 'Phổ thông')."""
    rows = frappe.get_all(
        "SIS Education Stage",
        filters={"title_vn": ["like", f"%{keyword}%"]},
        fields=["name", "title_vn", "title_en"],
    )
    if len(rows) == 1:
        return rows[0]
    if not rows:
        print(f"❌ Không tìm thấy cấp học khớp '{keyword}'")
        return None
    print(f"❌ Có {len(rows)} cấp học khớp '{keyword}', không đoán được:")
    for r in rows:
        print(f"   - {r['name']}: {r['title_vn']}")
    return None


def run(
    dry_run: int = 1,
    effective_date: str = DEFAULT_EFFECTIVE_DATE,
    score_type: str = "homeroom",
    base_value: float | None = None,
    from_stage: str | None = None,
    to_stage: str | None = None,
):
    """
    dry_run       : 1 = chỉ in ra sẽ làm gì (mặc định). 0 = ghi thật.
    effective_date: ngày áp dụng của đợt điểm cho các bản clone.
    score_type    : loại điểm cần xử lý (mặc định 'homeroom' = Điểm chủ nhiệm).
    base_value    : ghi đè `value` gốc của bản clone. None = giữ nguyên value của THPT.
    from_stage    : ID cấp học nguồn. None = tự tìm theo 'Phổ thông'.
    to_stage      : ID cấp học đích. None = tự tìm theo 'Cơ sở'.
    """
    dry_run = int(dry_run)
    effective = getdate(effective_date)

    if from_stage:
        source = {"name": from_stage, "title_vn": from_stage}
    else:
        source = _resolve_stage("Phổ thông")
    if to_stage:
        target = {"name": to_stage, "title_vn": to_stage}
    else:
        target = _resolve_stage("Cơ sở")

    if not source or not target:
        print("Dừng — chỉ định thủ công qua from_stage / to_stage.")
        return

    print(f"{'[RÀ SOÁT]' if dry_run else '[CHẠY THẬT]'} loại điểm: {score_type}")
    print(f"  Nguồn : {source['name']} ({source.get('title_vn')})")
    print(f"  Đích  : {target['name']} ({target.get('title_vn')})")
    print(f"  Ngày áp dụng cho bản clone: {effective}")
    print()

    # ---------- Bước 1: tắt lựa chọn hiện có của cấp đích ----------
    existing = frappe.get_all(
        "SIS Class Log Score",
        filters={"type": score_type, "education_stage": target["name"]},
        fields=["name", "title_vn", "value", "is_active"],
        order_by="value desc, title_vn asc",
    )
    to_deactivate = [r for r in existing if r.get("is_active")]
    print(f"Bước 1 — tắt {len(to_deactivate)}/{len(existing)} lựa chọn hiện có của cấp đích")
    for r in to_deactivate[:10]:
        print(f"   - {r['name']}  {r['title_vn'][:60]}")
    if len(to_deactivate) > 10:
        print(f"   … và {len(to_deactivate) - 10} mục nữa")
    print()

    # ---------- Bước 2: clone từ cấp nguồn ----------
    source_rows = frappe.get_all(
        "SIS Class Log Score",
        filters={"type": score_type, "education_stage": source["name"], "is_active": 1},
        fields=["name", "title_vn", "title_en", "value", "color", "campus_id"],
        order_by="value desc, title_vn asc",
    )

    # Tên đã có ở cấp đích (kể cả bản vừa bị tắt) — tránh tạo trùng khi chạy lại
    existing_titles = {
        (r.get("title_vn") or "").strip().lower()
        for r in existing
    }

    to_clone = [
        r for r in source_rows
        if (r.get("title_vn") or "").strip().lower() not in existing_titles
    ]
    skipped = len(source_rows) - len(to_clone)

    print(f"Bước 2 — clone {len(to_clone)}/{len(source_rows)} lựa chọn đang bật của cấp nguồn")
    if skipped:
        print(f"   (bỏ qua {skipped} mục đã có cùng tên ở cấp đích)")
    for r in to_clone[:10]:
        value = r.get("value") if base_value is None else base_value
        print(f"   + {value:>5}  {(r.get('title_vn') or '')[:60]}")
    if len(to_clone) > 10:
        print(f"   … và {len(to_clone) - 10} mục nữa")
    print()

    if dry_run:
        print("RÀ SOÁT — chưa ghi gì. Chạy lại với --kwargs \"{'dry_run': 0}\" để thực hiện.")
        return

    # ---------- Ghi ----------
    deactivated = 0
    created = 0
    versioned = 0
    try:
        for r in to_deactivate:
            frappe.db.set_value("SIS Class Log Score", r["name"], "is_active", 0)
            deactivated += 1

        has_version_table = frappe.db.table_exists(VERSION_DOCTYPE)
        if not has_version_table:
            print(f"⚠️  Chưa có bảng {VERSION_DOCTYPE} (thiếu bench migrate) — bỏ qua phần đợt áp dụng")

        for r in to_clone:
            value = r.get("value") if base_value is None else base_value
            doc = frappe.get_doc(
                {
                    "doctype": "SIS Class Log Score",
                    "type": score_type,
                    "title_vn": (r.get("title_vn") or "").strip(),
                    "title_en": (r.get("title_en") or "").strip(),
                    "value": value or 0,
                    "color": r.get("color"),
                    "education_stage": target["name"],
                    "is_active": 1,
                    "is_default": 0,
                    "campus_id": r.get("campus_id"),
                }
            )
            doc.insert(ignore_permissions=True)
            created += 1

            if has_version_table:
                version = frappe.get_doc(
                    {
                        "doctype": VERSION_DOCTYPE,
                        "class_log_score": doc.name,
                        "effective_date": effective,
                        "value": r.get("value") or 0,
                        "campus_id": r.get("campus_id"),
                    }
                )
                version.insert(ignore_permissions=True)
                versioned += 1

        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        print("❌ Lỗi giữa chừng — đã rollback, dữ liệu giữ nguyên như trước khi chạy:")
        print(frappe.get_traceback())
        raise

    # Danh mục lựa chọn được cache 30 phút — xoá để FE thấy ngay
    try:
        frappe.cache().delete_keys("class_log_options:")
    except Exception as e:
        print(f"⚠️  Không xoá được cache class_log_options ({e}) — chờ tối đa 30 phút hoặc bench restart")

    print(f"✅ Đã tắt {deactivated} lựa chọn cũ của cấp đích")
    print(f"✅ Đã tạo {created} lựa chọn mới, kèm {versioned} đợt áp dụng ngày {effective}")
