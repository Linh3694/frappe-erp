# Copyright (c) 2026, Wellspring and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime, get_datetime


class SISMenuRegistrationPeriod(Document):
    """
    Kỳ đăng ký suất ăn Á/Âu
    Quản lý các kỳ đăng ký suất ăn cho học sinh
    """

    def before_insert(self):
        """Thiết lập thông tin khi tạo mới"""
        self.created_by = frappe.session.user
        self.created_at = now_datetime()
        self.updated_at = now_datetime()

    def before_save(self):
        """Cập nhật thời gian khi lưu"""
        self.updated_at = now_datetime()
        self.validate_parent_timeline()
        self.validate_teacher_timeline()
        self.validate_registration_dates()
        self.validate_month_year()
        self.validate_education_stages()
        
        # Backward compatibility: sync với deprecated fields
        self._sync_deprecated_fields()

    def validate_parent_timeline(self):
        """Kiểm tra timeline phụ huynh"""
        if self.parent_start_datetime and self.parent_end_datetime:
            start = get_datetime(self.parent_start_datetime)
            end = get_datetime(self.parent_end_datetime)
            if start >= end:
                frappe.throw("Thời gian bắt đầu phụ huynh phải trước thời gian kết thúc")

    def validate_teacher_timeline(self):
        """Kiểm tra timeline giáo viên chủ nhiệm"""
        if self.teacher_start_datetime and self.teacher_end_datetime:
            start = get_datetime(self.teacher_start_datetime)
            end = get_datetime(self.teacher_end_datetime)
            if start >= end:
                frappe.throw("Thời gian bắt đầu GVCN phải trước thời gian kết thúc")

    def validate_registration_dates(self):
        """Kiểm tra danh sách ngày đăng ký"""
        if not self.registration_dates or len(self.registration_dates) == 0:
            frappe.throw("Phải chọn ít nhất một ngày đăng ký suất ăn")
        
        # Kiểm tra trùng lặp ngày
        dates = [str(d.date) for d in self.registration_dates]
        if len(dates) != len(set(dates)):
            frappe.throw("Không được chọn trùng ngày đăng ký")
        
        # Sắp xếp ngày theo thứ tự tăng dần
        self.registration_dates = sorted(self.registration_dates, key=lambda x: x.date)

    def validate_month_year(self):
        """Kiểm tra tháng trong khoảng 1-12"""
        if self.month and (self.month < 1 or self.month > 12):
            frappe.throw("Tháng phải trong khoảng từ 1 đến 12")

    def validate_education_stages(self):
        """Kiểm tra phải có ít nhất một cấp học"""
        if not self.education_stages or len(self.education_stages) == 0:
            frappe.throw("Phải chọn ít nhất một cấp học áp dụng")
        
        # Kiểm tra trùng lặp cấp học
        stage_ids = [stage.education_stage_id for stage in self.education_stages]
        if len(stage_ids) != len(set(stage_ids)):
            frappe.throw("Không được chọn trùng cấp học")

    def _sync_deprecated_fields(self):
        """Đồng bộ với deprecated fields để backward compatibility"""
        # Lấy date từ datetime cho deprecated fields
        if self.parent_start_datetime:
            self.start_date = get_datetime(self.parent_start_datetime).date()
        if self.parent_end_datetime:
            self.end_date = get_datetime(self.parent_end_datetime).date()

    def get_registration_dates_list(self):
        """Trả về danh sách ngày đăng ký dạng string"""
        return [str(d.date) for d in self.registration_dates] if self.registration_dates else []

    def is_within_parent_timeline(self):
        """Kiểm tra hiện tại có trong timeline phụ huynh không"""
        now = now_datetime()
        if self.parent_start_datetime and self.parent_end_datetime:
            start = get_datetime(self.parent_start_datetime)
            end = get_datetime(self.parent_end_datetime)
            return start <= now <= end
        return False

    def is_within_teacher_timeline(self):
        """Kiểm tra hiện tại có trong timeline GVCN không"""
        now = now_datetime()
        if self.teacher_start_datetime and self.teacher_end_datetime:
            start = get_datetime(self.teacher_start_datetime)
            end = get_datetime(self.teacher_end_datetime)
            return start <= now <= end
        return False
