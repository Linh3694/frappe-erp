# Copyright (c) 2026, Wellspring and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now


class SISFinanceOrder(Document):
    """
    Doctype quản lý đơn hàng/khoản phí trong năm tài chính.
    
    Cấu trúc mới:
    - Hỗ trợ nhiều mốc deadline (milestones)
    - Cấu trúc các dòng khoản phí (fee_lines) - không có số tiền mặc định
    - Số tiền được lưu riêng cho từng học sinh trong SIS Finance Order Student
    - Hỗ trợ gửi nhiều đợt thông báo (Send Batch)
    """
    
    def before_insert(self):
        """Thiết lập các giá trị mặc định khi tạo mới"""
        if not self.created_by:
            self.created_by = frappe.session.user
        if not self.created_at:
            self.created_at = now()
        if not self.status:
            self.status = 'draft'
    
    def before_save(self):
        """Cập nhật thời gian sửa đổi"""
        self.updated_at = now()
    
    # Giới hạn độ sâu chuỗi cha để tránh vòng lặp / lỗi dữ liệu
    _MAX_PARENT_CHAIN_DEPTH = 20

    def validate(self):
        """Validate dữ liệu trước khi lưu"""
        self.validate_milestones()
        self.validate_fee_lines()
        self.validate_status_transition()
        self.validate_parent_order()

    def validate_parent_order(self):
        """Đơn cha: cùng finance_year_id, cùng order_type; không trùng; không chu trình; cha chưa bị đơn khác thay thế."""
        if not self.parent_order_id:
            return
        if self.parent_order_id == self.name:
            frappe.throw("Không thể kế thừa chính đơn hàng này")

        try:
            parent = frappe.get_doc("SIS Finance Order", self.parent_order_id)
        except frappe.DoesNotExistError:
            frappe.throw("Đơn hàng cha không tồn tại")

        if parent.finance_year_id != self.finance_year_id:
            frappe.throw("Đơn cha phải cùng năm tài chính")
        if (parent.order_type or "") != (self.order_type or ""):
            frappe.throw("Đơn cha phải cùng loại đơn hàng (order_type)")

        # Cha đã bị đơn khác thay thế (trừ khi chính đơn này là đơn đang sửa = đang giữ quyền thay thế)
        p_sup = frappe.db.get_value(
            "SIS Finance Order",
            self.parent_order_id,
            ["is_superseded", "superseded_by"],
            as_dict=True,
        )
        if p_sup and p_sup.get("is_superseded") and p_sup.get("superseded_by") and p_sup.get("superseded_by") != self.name:
            frappe.throw("Đơn hàng cha đã bị thay thế bởi đơn khác. Chọn đơn cha khác hoặc gỡ thay thế ở đơn cũ.")

        # Tránh chu trình: từ cha bước lên, nếu gặp tên đơn hiện tại thì tạo vòng
        walk = self.parent_order_id
        depth = 0
        while walk and depth < self._MAX_PARENT_CHAIN_DEPTH:
            if walk == self.name:
                frappe.throw("Quan hệ kế thừa tạo chu trình (A → B → … → A). Hãy chọn đơn cha hợp lệ.")
            walk = frappe.db.get_value("SIS Finance Order", walk, "parent_order_id")
            depth += 1
        if depth >= self._MAX_PARENT_CHAIN_DEPTH:
            frappe.throw("Chuỗi đơn cha quá sâu (vui lòng kiểm tra dữ liệu)")
    
    def validate_milestones(self):
        """Kiểm tra các mốc deadline"""
        if self.milestones:
            # Debug: Log chi tiết milestones
            frappe.log(f"[validate_milestones] Total milestones: {len(self.milestones)}")
            for idx, m in enumerate(self.milestones):
                frappe.log(f"  [{idx}] scheme={repr(m.payment_scheme)}, number={m.milestone_number}, title={m.title}")
            
            # Kiểm tra milestone_number không trùng trong cùng payment_scheme
            # VD: yearly có mốc 1,2 và semester cũng có mốc 1,2 là OK
            from collections import defaultdict
            scheme_numbers = defaultdict(list)
            
            for m in self.milestones:
                # Đảm bảo payment_scheme không rỗng - default là 'yearly'
                scheme = m.payment_scheme if m.payment_scheme else 'yearly'
                scheme_numbers[scheme].append(m.milestone_number)
            
            frappe.log(f"[validate_milestones] Grouped: {dict(scheme_numbers)}")
            
            for scheme, numbers in scheme_numbers.items():
                if len(numbers) != len(set(numbers)):
                    scheme_label = 'Đóng cả năm' if scheme == 'yearly' else 'Đóng theo kỳ'
                    frappe.throw(f"Số mốc trong '{scheme_label}' không được trùng nhau")
            
            # Sắp xếp theo payment_scheme rồi milestone_number
            self.milestones.sort(key=lambda x: (x.payment_scheme or 'yearly', x.milestone_number))
    
    def validate_fee_lines(self):
        """Kiểm tra các dòng khoản phí"""
        if self.fee_lines:
            # Kiểm tra line_number không trùng
            numbers = [l.line_number for l in self.fee_lines]
            if len(numbers) != len(set(numbers)):
                frappe.throw("Số thứ tự dòng không được trùng nhau")
    
    def validate_status_transition(self):
        """Kiểm tra chuyển đổi trạng thái hợp lệ"""
        if self.is_new():
            return
        
        old_status = frappe.db.get_value("SIS Finance Order", self.name, "status")
        
        # Các trạng thái cho phép chuyển đổi
        valid_transitions = {
            'draft': ['students_added', 'closed'],
            'students_added': ['draft', 'data_imported', 'closed'],
            'data_imported': ['students_added', 'published', 'closed'],
            'published': ['closed'],
            'closed': []  # Không thể chuyển từ closed
        }
        
        if old_status and self.status != old_status:
            if self.status not in valid_transitions.get(old_status, []):
                frappe.throw(f"Không thể chuyển từ trạng thái '{old_status}' sang '{self.status}'")
    
    def update_statistics(self):
        """Cập nhật thống kê cho đơn hàng"""
        # Đếm số học sinh trong đơn hàng (dùng Order Student mới)
        self.total_students = frappe.db.count(
            "SIS Finance Order Student",
            {"order_id": self.name}
        )
        
        # Đếm số học sinh đã có đầy đủ số tiền
        self.data_completed_count = frappe.db.count(
            "SIS Finance Order Student",
            {"order_id": self.name, "data_status": "complete"}
        )
        
        # Tính tổng đã thu và còn phải thu
        summary = frappe.db.sql("""
            SELECT 
                COALESCE(SUM(total_amount), 0) as total_amount,
                COALESCE(SUM(paid_amount), 0) as total_paid
            FROM `tabSIS Finance Order Student`
            WHERE order_id = %s
        """, (self.name,), as_dict=True)
        
        if summary:
            total_amount = summary[0].get('total_amount', 0)
            self.total_collected = summary[0].get('total_paid', 0)
            self.total_outstanding = total_amount - self.total_collected
            
            # Tính tỷ lệ thu
            if total_amount > 0:
                self.collection_rate = (self.total_collected / total_amount) * 100
            else:
                self.collection_rate = 0
        
        self.db_update()
    
    def update_status_based_on_students(self):
        """Cập nhật status dựa trên trạng thái học sinh"""
        if self.status == 'draft' and self.total_students > 0:
            self.status = 'students_added'
            self.db_update()
        elif self.status == 'students_added' and self.data_completed_count == self.total_students and self.total_students > 0:
            self.status = 'data_imported'
            self.db_update()
    
    def get_milestone(self, milestone_number):
        """Lấy thông tin mốc deadline theo số mốc"""
        for milestone in self.milestones:
            if milestone.milestone_number == milestone_number:
                return milestone
        return None
    
    def get_fee_line(self, line_number):
        """Lấy thông tin dòng khoản phí theo STT"""
        for line in self.fee_lines:
            if line.line_number == line_number:
                return line
        return None
    
    def can_add_students(self):
        """Kiểm tra có thể thêm học sinh không - cho phép ở mọi status trừ closed"""
        return self.status != 'closed'
    
    def can_import_data(self):
        """Kiểm tra có thể import số tiền không"""
        return self.status in ['students_added', 'data_imported'] and self.total_students > 0
    
    def can_publish(self):
        """Kiểm tra có thể publish không"""
        return (
            self.status == 'data_imported' and 
            self.total_students > 0 and 
            self.data_completed_count == self.total_students
        )
    
    def can_create_send_batch(self):
        """Kiểm tra có thể tạo đợt gửi không"""
        return self.status in ['data_imported', 'published']
    
    def after_insert(self):
        """đồng bộ kế thừa cha-con + thống kê năm tài chính"""
        self._sync_parent_supersession_flags(previous_parent_id=None)
        self.update_finance_year_statistics()

    def on_update(self):
        """Khi đổi parent_order_id: cập nhật cờ trên đơn cha cũ / mới (tránh lệch dữ liệu)."""
        try:
            doc_before = self.get_doc_before_save()
        except Exception:
            doc_before = None
        previous_parent_id = (doc_before or {}).get("parent_order_id") if doc_before else None
        self._sync_parent_supersession_flags(previous_parent_id=previous_parent_id)

    def _sync_parent_supersession_flags(self, previous_parent_id=None):
        """
        Đơn con (self) kế thừa từ parent_order_id: đánh dấu cha là bị thay thế.
        Dùng frappe.db.set_value để tránh đệ quy hook Document của đơn cha.
        """
        # Gỡ cờ ở cha cũ nếu đổi cha hoặc bỏ kế thừa
        if previous_parent_id and previous_parent_id != (self.parent_order_id or None):
            old_sb = frappe.db.get_value("SIS Finance Order", previous_parent_id, "superseded_by")
            if old_sb == self.name:
                frappe.db.set_value(
                    "SIS Finance Order",
                    previous_parent_id,
                    {"is_superseded": 0, "superseded_by": None},
                )

        if not self.parent_order_id and previous_parent_id:
            prev_sb = frappe.db.get_value("SIS Finance Order", previous_parent_id, "superseded_by")
            if prev_sb == self.name:
                frappe.db.set_value(
                    "SIS Finance Order",
                    previous_parent_id,
                    {"is_superseded": 0, "superseded_by": None},
                )
            return

        if self.parent_order_id:
            frappe.db.set_value(
                "SIS Finance Order",
                self.parent_order_id,
                {"is_superseded": 1, "superseded_by": self.name},
            )
    
    def on_trash(self):
        """
        Chặn xóa nếu còn đơn con kế thừa; gỡ cờ đơn cha; cập nhật thống kê năm.
        """
        child = frappe.db.get_value(
            "SIS Finance Order",
            {"parent_order_id": self.name},
            "name",
        )
        if child:
            frappe.throw(
                f"Không thể xóa đơn hàng: đơn {child} đang kế thừa từ đơn này. Gỡ kế thừa ở đơn con trước."
            )
        if self.parent_order_id:
            sup_by = frappe.db.get_value("SIS Finance Order", self.parent_order_id, "superseded_by")
            if sup_by == self.name:
                frappe.db.set_value(
                    "SIS Finance Order",
                    self.parent_order_id,
                    {"is_superseded": 0, "superseded_by": None},
                )
        self.update_finance_year_statistics()
    
    def update_finance_year_statistics(self):
        """Cập nhật thống kê cho năm tài chính"""
        try:
            finance_year = frappe.get_doc("SIS Finance Year", self.finance_year_id)
            finance_year.update_statistics()
        except Exception:
            pass
