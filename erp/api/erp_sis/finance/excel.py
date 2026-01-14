"""
Excel Import/Export APIs
Xử lý import/export dữ liệu số tiền học sinh qua Excel.
"""

import frappe
from frappe import _
import json
import re

from erp.utils.api_response import (
    validation_error_response,
    error_response,
    success_response
)

from .utils import _check_admin_permission


def _calculate_totals_v2(order_student_doc, order_doc, debug=False):
    """
    Tính toán các dòng total/subtotal dựa trên formula.
    Đồng thời cập nhật total_amount trên order_student_doc.
    
    Args:
        debug: Nếu True, sẽ print debug info
    """
    debug_info = []
    
    # Lấy tất cả amounts theo line_number
    line_amounts = {}
    for fee_line in order_student_doc.fee_lines:
        if fee_line.amounts_json:
            try:
                amounts_data = json.loads(fee_line.amounts_json)
                line_amounts[fee_line.line_number] = amounts_data
                if debug and amounts_data:
                    debug_info.append(f"Line {fee_line.line_number} ({fee_line.line_type}): {amounts_data}")
            except:
                line_amounts[fee_line.line_number] = {}
    
    # Lấy danh sách milestone keys với format mới: {scheme}_{number}
    milestone_keys = [
        f"{m.payment_scheme or 'yearly'}_{m.milestone_number}" 
        for m in order_doc.milestones
    ]
    
    if debug:
        debug_info.append(f"Milestone keys: {milestone_keys}")
        debug_info.append(f"Line amounts keys: {list(line_amounts.keys())}")
    
    # Tính toán các dòng có formula
    total_line_amounts = {}  # Lưu amounts của dòng total
    
    for fee_line in order_student_doc.fee_lines:
        order_line = order_doc.get_fee_line(fee_line.line_number)
        
        # Nếu là dòng total nhưng KHÔNG có formula, lấy giá trị trực tiếp từ amounts_json
        if fee_line.line_type == 'total' and (not order_line or not order_line.formula):
            if fee_line.amounts_json:
                try:
                    total_line_amounts = json.loads(fee_line.amounts_json)
                    if debug:
                        debug_info.append(f"Total line (no formula) amounts: {total_line_amounts}")
                except:
                    pass
            continue
        
        # Skip nếu không có formula
        if not order_line or not order_line.formula:
            continue
        
        formula = order_line.formula
        calculated_amounts = {}
        
        for m_key in milestone_keys:
            eval_formula = formula
            matches = re.findall(r'\(([0-9.]+)\)', formula)
            
            for match in matches:
                value = line_amounts.get(match, {}).get(m_key, 0) or 0
                eval_formula = eval_formula.replace(f"({match})", str(value))
            
            try:
                result = eval(eval_formula)
                calculated_amounts[m_key] = result
            except:
                calculated_amounts[m_key] = 0
        
        fee_line.amounts_json = json.dumps(calculated_amounts)
        fee_line.is_calculated = 1
        
        # Lưu lại amounts của dòng total (line_type='total')
        if fee_line.line_type == 'total':
            total_line_amounts = calculated_amounts
            line_amounts[fee_line.line_number] = calculated_amounts
            if debug:
                debug_info.append(f"Total line (with formula) amounts: {total_line_amounts}")
    
    # Cập nhật total_amount cho order_student_doc
    # total_amount = giá trị của dòng total theo milestone được chọn
    calculated_total = 0
    
    if total_line_amounts:
        # Ưu tiên 1: Lấy giá trị milestone đầu tiên của yearly (thường là tổng phải đóng cả năm)
        first_yearly_key = None
        for m_key in milestone_keys:
            if m_key.startswith('yearly_'):
                first_yearly_key = m_key
                break
        
        if first_yearly_key and first_yearly_key in total_line_amounts:
            calculated_total = total_line_amounts[first_yearly_key]
        else:
            # Fallback: Lấy milestone đầu tiên có giá trị
            for m_key in milestone_keys:
                if m_key in total_line_amounts and total_line_amounts[m_key]:
                    calculated_total = total_line_amounts[m_key]
                    break
    
    # Nếu không có dòng total, tính tổng từ các dòng item (không phải category/subtotal)
    if not calculated_total:
        if debug:
            debug_info.append("Fallback: Tính từ các dòng item")
        
        for fee_line in order_student_doc.fee_lines:
            # Chỉ tính các dòng item (không phải category, subtotal, total)
            if fee_line.line_type == 'item' and fee_line.amounts_json:
                try:
                    amounts = json.loads(fee_line.amounts_json)
                    if debug and amounts:
                        debug_info.append(f"Item line {fee_line.line_number}: keys={list(amounts.keys())}")
                    
                    # Lấy is_deduction từ order_line (vì Student Order Line không có field này)
                    order_line = order_doc.get_fee_line(fee_line.line_number)
                    is_deduction = order_line.is_deduction if order_line else False
                    
                    # Ưu tiên yearly_1, fallback sang milestone đầu tiên
                    found_key = False
                    for m_key in milestone_keys:
                        if m_key.startswith('yearly_') and m_key in amounts:
                            # Nếu là khoản trừ (is_deduction), trừ đi
                            value = amounts.get(m_key, 0) or 0
                            if is_deduction:
                                calculated_total -= abs(value)
                            else:
                                calculated_total += value
                            found_key = True
                            break
                    
                    if not found_key:
                        # Fallback: lấy milestone đầu tiên
                        for m_key in milestone_keys:
                            if m_key in amounts:
                                value = amounts.get(m_key, 0) or 0
                                if is_deduction:
                                    calculated_total -= abs(value)
                                else:
                                    calculated_total += value
                                break
                except Exception as e:
                    if debug:
                        debug_info.append(f"Error parsing item {fee_line.line_number}: {str(e)}")
    
    # Lưu milestone_amounts_json để hỗ trợ thanh toán theo mốc
    if total_line_amounts:
        order_student_doc.milestone_amounts_json = json.dumps(total_line_amounts)
        if debug:
            debug_info.append(f"Saved milestone_amounts_json: {total_line_amounts}")
    
    # Cập nhật total_amount
    if calculated_total:
        order_student_doc.total_amount = calculated_total
        order_student_doc.outstanding_amount = calculated_total - (order_student_doc.paid_amount or 0)
        
        # Cập nhật payment_status
        if order_student_doc.paid_amount and order_student_doc.paid_amount >= order_student_doc.total_amount:
            order_student_doc.payment_status = 'paid'
        elif order_student_doc.paid_amount and order_student_doc.paid_amount > 0:
            order_student_doc.payment_status = 'partial'
        else:
            order_student_doc.payment_status = 'unpaid'
    
    # Cập nhật data_status nếu có số tiền
    if calculated_total or any(fl.amounts_json for fl in order_student_doc.fee_lines):
        order_student_doc.data_status = 'complete'
    
    if debug:
        debug_info.append(f"Final calculated_total: {calculated_total}")
        debug_info.append(f"total_line_amounts: {total_line_amounts}")
        frappe.log_error('\n'.join(debug_info), "Calculate Totals V2 Debug")


@frappe.whitelist()
def export_order_excel_template(order_id=None):
    """
    Export Excel template để admin điền số tiền.
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền xuất template", logs=logs)
        
        if not order_id:
            order_id = frappe.request.args.get('order_id')
        
        if not order_id:
            return validation_error_response("Thiếu order_id", {"order_id": ["Bắt buộc"]})
        
        order_doc = frappe.get_doc("SIS Finance Order", order_id)
        
        # Build headers
        headers = ["student_code", "student_name", "class_title"]
        header_labels = ["Mã học sinh", "Tên học sinh", "Lớp"]
        
        # Sắp xếp milestones theo payment_scheme rồi milestone_number
        sorted_milestones = sorted(
            order_doc.milestones, 
            key=lambda m: (m.payment_scheme or 'yearly', m.milestone_number)
        )
        
        # Thêm các cột số tiền theo từng line và milestone
        for line in order_doc.fee_lines:
            # Bỏ qua dòng tự động tính (total, subtotal có formula)
            if line.line_type in ['total', 'subtotal'] and line.formula:
                continue
            
            for milestone in sorted_milestones:
                scheme = milestone.payment_scheme or 'yearly'
                # Key format: {line_number}_{scheme}_{milestone_number}
                col_name = f"{line.line_number}_{scheme}_{milestone.milestone_number}"
                headers.append(col_name)
                
                # Label hiển thị
                scheme_label = "Năm" if scheme == 'yearly' else "Kỳ"
                header_labels.append(f"{line.line_number} - {scheme_label} {milestone.milestone_number}: {milestone.title}")
        
        headers.append("note")
        header_labels.append("Ghi chú")
        
        # Get students
        students = frappe.get_all(
            "SIS Finance Order Student",
            filters={"order_id": order_id},
            fields=["name", "student_code", "student_name", "class_title", "notes"]
        )
        
        # Build rows
        rows = []
        for student in students:
            row = {
                "student_code": student.student_code,
                "student_name": student.student_name,
                "class_title": student.class_title,
                "note": student.notes or ""
            }
            
            # Thêm các cột số tiền (rỗng)
            for line in order_doc.fee_lines:
                if line.line_type in ['total', 'subtotal'] and line.formula:
                    continue
                for milestone in sorted_milestones:
                    scheme = milestone.payment_scheme or 'yearly'
                    col_name = f"{line.line_number}_{scheme}_{milestone.milestone_number}"
                    row[col_name] = ""
            
            rows.append(row)
        
        return success_response(
            data={
                "headers": headers,
                "header_labels": header_labels,
                "rows": rows,
                "order_title": order_doc.title,
                "milestones": [
                    {
                        "payment_scheme": m.payment_scheme or 'yearly',
                        "number": m.milestone_number, 
                        "title": m.title,
                        "key": f"{m.payment_scheme or 'yearly'}_{m.milestone_number}"
                    } for m in sorted_milestones
                ],
                "fee_lines": [{"number": l.line_number, "title_vn": l.title_vn, "title_en": l.title_en} for l in order_doc.fee_lines]
            },
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def import_student_fee_data():
    """
    Import số tiền từ Excel.
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền import", logs=logs)
        
        files = frappe.request.files
        if 'file' not in files:
            return validation_error_response("Thiếu file", {"file": ["File Excel là bắt buộc"]})
        
        file = files['file']
        
        # Lấy order_id từ form data - thử nhiều cách vì multipart form khác với JSON
        order_id = (
            frappe.form_dict.get('order_id') or 
            frappe.request.form.get('order_id') or
            frappe.request.values.get('order_id')
        )
        
        logs.append(f"Debug: form_dict={frappe.form_dict}, request.form={dict(frappe.request.form)}")
        
        if not order_id:
            return validation_error_response("Thiếu order_id", {"order_id": ["Bắt buộc"]})
        
        order_doc = frappe.get_doc("SIS Finance Order", order_id)
        
        if not order_doc.can_import_data():
            return error_response(f"Không thể import khi status = {order_doc.status}")
        
        logs.append(f"Import số tiền cho đơn hàng: {order_id}")
        
        # Đọc Excel - skip dòng 1 (label tiếng Việt), dùng dòng 2 làm header
        import pandas as pd
        df = pd.read_excel(file, header=1)  # header=1 nghĩa là dòng thứ 2 (0-indexed)
        
        logs.append(f"Columns in Excel: {list(df.columns)}")
        
        # Validate cột student_code
        if 'student_code' not in df.columns:
            return validation_error_response(
                "Thiếu cột student_code", 
                {"file": [f"Cần có cột student_code. Các cột hiện tại: {list(df.columns)[:5]}..."]}
            )
        
        success_count = 0
        error_count = 0
        errors = []
        
        for idx, row in df.iterrows():
            try:
                student_code = str(row['student_code']).strip()
                
                # Tìm Order Student
                order_student = frappe.db.get_value(
                    "SIS Finance Order Student",
                    {"order_id": order_id, "student_code": student_code},
                    "name"
                )
                
                if not order_student:
                    errors.append({"row": idx + 2, "error": f"Không tìm thấy học sinh: {student_code}"})
                    error_count += 1
                    continue
                
                order_student_doc = frappe.get_doc("SIS Finance Order Student", order_student)
                
                # Cập nhật số tiền cho từng line
                for fee_line in order_student_doc.fee_lines:
                    if fee_line.is_calculated:
                        continue
                    
                    amounts = {}
                    for milestone in order_doc.milestones:
                        scheme = milestone.payment_scheme or 'yearly'
                        # Dùng key format mới: {line_number}_{scheme}_{milestone_number}
                        col_name = f"{fee_line.line_number}_{scheme}_{milestone.milestone_number}"
                        if col_name in row and pd.notna(row[col_name]):
                            try:
                                # Key trong amounts_json: {scheme}_{milestone_number}
                                amounts[f"{scheme}_{milestone.milestone_number}"] = float(row[col_name])
                            except (ValueError, TypeError):
                                pass
                    
                    if amounts:
                        fee_line.amounts_json = json.dumps(amounts)
                
                # Tính toán các dòng total/subtotal
                _calculate_totals_v2(order_student_doc, order_doc)
                
                # Cập nhật note
                if 'note' in row and pd.notna(row['note']):
                    order_student_doc.notes = str(row['note'])
                
                order_student_doc.save(ignore_permissions=True)
                success_count += 1
                
            except Exception as e:
                errors.append({"row": idx + 2, "error": str(e), "student_code": row.get('student_code', '')})
                error_count += 1
        
        frappe.db.commit()
        
        # Cập nhật statistics
        order_doc.update_statistics()
        order_doc.update_status_based_on_students()
        
        logs.append(f"Import xong: {success_count} thành công, {error_count} lỗi")
        
        return success_response(
            data={
                "success_count": success_count,
                "error_count": error_count,
                "total_count": len(df),
                "errors": errors[:20]
            },
            message=f"Import thành công {success_count}/{len(df)} dòng",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Import Student Fee Data Error")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def recalculate_order_totals(order_id=None):
    """
    Tính lại total_amount cho tất cả Order Students trong một Order.
    Sử dụng khi cần fix dữ liệu đã import nhưng chưa cập nhật total_amount đúng.
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền thực hiện", logs=logs)
        
        # Nhận order_id từ nhiều nguồn: JSON body, form_dict, hoặc query params
        if not order_id:
            if frappe.request.is_json:
                data = frappe.request.json or {}
                order_id = data.get('order_id')
            else:
                order_id = frappe.form_dict.get('order_id') or frappe.request.args.get('order_id')
        
        if not order_id:
            return validation_error_response("Thiếu order_id", {"order_id": ["Bắt buộc"]})
        
        order_doc = frappe.get_doc("SIS Finance Order", order_id)
        logs.append(f"Recalculate totals cho Order: {order_id}")
        
        # Debug: Log cấu trúc milestones
        milestone_keys = [
            f"{m.payment_scheme or 'yearly'}_{m.milestone_number}" 
            for m in order_doc.milestones
        ]
        logs.append(f"Milestone keys: {milestone_keys}")
        
        # Debug: Log cấu trúc fee_lines
        fee_line_types = [(fl.line_number, fl.line_type, fl.formula or '') for fl in order_doc.fee_lines]
        logs.append(f"Fee line types: {fee_line_types}")
        
        # Lấy tất cả Order Students
        order_students = frappe.get_all(
            "SIS Finance Order Student",
            filters={"order_id": order_id},
            pluck="name"
        )
        
        updated_count = 0
        debug_first_student = None
        
        for os_name in order_students:
            os_doc = frappe.get_doc("SIS Finance Order Student", os_name)
            
            # Debug: Log fee_lines của student đầu tiên
            if not debug_first_student:
                debug_first_student = {
                    "name": os_doc.name,
                    "fee_lines": [
                        {
                            "line_number": fl.line_number,
                            "line_type": fl.line_type,
                            "amounts_json": fl.amounts_json
                        }
                        for fl in os_doc.fee_lines
                    ]
                }
                logs.append(f"First student fee_lines: {json.dumps(debug_first_student, ensure_ascii=False)}")
            
            # Tính lại totals (debug cho student đầu tiên)
            is_first = (updated_count == 0)
            _calculate_totals_v2(os_doc, order_doc, debug=is_first)
            os_doc.save(ignore_permissions=True)
            updated_count += 1
            
            # Debug: Log kết quả sau khi tính
            if is_first:
                logs.append(f"After calculate - total_amount: {os_doc.total_amount}, outstanding: {os_doc.outstanding_amount}")
        
        frappe.db.commit()
        logs.append(f"Đã cập nhật {updated_count} học sinh")
        
        return success_response(
            data={
                "order_id": order_id,
                "updated_count": updated_count,
                "debug": {
                    "milestone_keys": milestone_keys,
                    "fee_line_types": fee_line_types,
                    "first_student": debug_first_student
                }
            },
            message=f"Đã tính lại totals cho {updated_count} học sinh",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Recalculate Order Totals Error")
        return error_response(f"Lỗi: {str(e)}", logs=logs)
