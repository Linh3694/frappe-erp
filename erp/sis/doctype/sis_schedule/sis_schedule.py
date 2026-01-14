# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate


class SISSchedule(Document):
    """
    SIS Schedule - Quản lý các thời gian biểu theo khoảng thời gian áp dụng.
    
    Một Schedule chứa nhiều Timetable Column (các tiết học).
    Mỗi Schedule áp dụng cho một khoảng thời gian cụ thể (start_date - end_date).
    """
    
    def validate(self):
        """Validate trước khi save"""
        self.validate_date_range()
        self.validate_overlapping_schedules()
    
    def validate_date_range(self):
        """Kiểm tra ngày bắt đầu phải trước ngày kết thúc"""
        if self.start_date and self.end_date:
            # Chuyển đổi sang datetime.date để so sánh an toàn
            start = getdate(self.start_date)
            end = getdate(self.end_date)
            if start > end:
                frappe.throw(_("Ngày bắt đầu phải trước ngày kết thúc"))
    
    def validate_overlapping_schedules(self):
        """
        Kiểm tra không có schedule trùng lặp cho cùng education_stage và campus
        trong cùng khoảng thời gian.
        """
        if not self.start_date or not self.end_date:
            return
        
        # Chuyển đổi date của schedule hiện tại sang datetime.date
        current_start = getdate(self.start_date)
        current_end = getdate(self.end_date)
        
        # Tìm các schedule khác có cùng education_stage, campus, school_year
        # và có date range trùng lặp
        filters = {
            "education_stage_id": self.education_stage_id,
            "campus_id": self.campus_id,
            "school_year_id": self.school_year_id,
            "is_active": 1,
            "name": ["!=", self.name] if self.name else ["is", "set"]
        }
        
        overlapping = frappe.get_all(
            "SIS Schedule",
            filters=filters,
            fields=["name", "schedule_name", "start_date", "end_date"]
        )
        
        for schedule in overlapping:
            # Chuyển đổi date của schedule khác sang datetime.date để so sánh an toàn
            other_start = getdate(schedule.start_date)
            other_end = getdate(schedule.end_date)
            
            # Kiểm tra trùng lặp: A.start <= B.end AND A.end >= B.start
            if (current_start <= other_end and current_end >= other_start):
                frappe.throw(
                    _("Thời gian biểu '{0}' ({1} - {2}) đang trùng lặp với thời gian biểu '{3}' ({4} - {5})").format(
                        self.schedule_name,
                        current_start,
                        current_end,
                        schedule.schedule_name,
                        other_start,
                        other_end
                    )
                )
    
    def on_trash(self):
        """Kiểm tra trước khi xóa"""
        # Kiểm tra có Timetable Column nào đang sử dụng schedule này không
        columns = frappe.get_all(
            "SIS Timetable Column",
            filters={"schedule_id": self.name},
            fields=["name", "period_name"]
        )
        
        if columns:
            column_names = ", ".join([c.period_name for c in columns[:5]])
            if len(columns) > 5:
                column_names += f" và {len(columns) - 5} tiết khác"
            
            frappe.throw(
                _("Không thể xóa thời gian biểu này vì đang có {0} tiết học sử dụng: {1}").format(
                    len(columns),
                    column_names
                )
            )
