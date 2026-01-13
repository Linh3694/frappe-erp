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
    
    def validate(self):
        """Validate dữ liệu trước khi lưu"""
        self.validate_milestones()
        self.validate_fee_lines()
        self.validate_status_transition()
    
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
        """Kiểm tra có thể thêm học sinh không"""
        return self.status in ['draft', 'students_added']
    
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
        """Cập nhật thống kê năm tài chính sau khi thêm đơn hàng"""
        self.update_finance_year_statistics()
    
    def on_trash(self):
        """Cập nhật thống kê năm tài chính sau khi xóa đơn hàng"""
        self.update_finance_year_statistics()
    
    def update_finance_year_statistics(self):
        """Cập nhật thống kê cho năm tài chính"""
        try:
            finance_year = frappe.get_doc("SIS Finance Year", self.finance_year_id)
            finance_year.update_statistics()
        except Exception:
            pass
