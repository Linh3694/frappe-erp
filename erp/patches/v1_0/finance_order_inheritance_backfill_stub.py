"""
Kế thừa đơn hàng (parent_order_id): stub patch — không tự backfill dữ liệu.

Dữ liệu cũ vẫn dùng tuition_paid_elsewhere + filter is_superseded trên PH.
Nếu sau này cần gán parent_order_id hàng loạt từ cờ cũ, thêm script riêng / chạy thủ công.
"""


def execute():
    # Không thay đổi DB — tránh rủi ro gán sai quan hệ cha-con tự động
    pass
