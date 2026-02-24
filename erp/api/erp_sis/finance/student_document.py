"""
Student Document APIs
Quản lý upload/xem/xóa file tài liệu (Debit Note, Receipt, Invoice) cho từng học sinh trong order.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime

from erp.utils.api_response import (
    validation_error_response,
    list_response,
    error_response,
    success_response
)

from .utils import _check_admin_permission, _get_request_data


@frappe.whitelist()
def upload_student_document():
    """
    Upload tài liệu cho học sinh trong order.
    
    Args (form data):
        order_student_id: ID của SIS Finance Order Student
        document_type: Loại tài liệu (debit_note / receipt / invoice)
        file: File upload
        notes: Ghi chú (optional)
    
    Returns:
        Thông tin document vừa tạo
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền upload tài liệu", logs=logs)
        
        # Lấy dữ liệu từ form
        order_student_id = frappe.form_dict.get('order_student_id')
        document_type = frappe.form_dict.get('document_type')
        notes = frappe.form_dict.get('notes', '')
        
        # Validate inputs
        if not order_student_id:
            return validation_error_response("Thiếu order_student_id", {"order_student_id": ["Bắt buộc"]})
        if not document_type:
            return validation_error_response("Thiếu document_type", {"document_type": ["Bắt buộc"]})
        if document_type not in ['debit_note', 'receipt', 'invoice']:
            return validation_error_response("document_type không hợp lệ", {"document_type": ["Phải là debit_note, receipt hoặc invoice"]})
        
        # Kiểm tra order_student_id tồn tại
        if not frappe.db.exists("SIS Finance Order Student", order_student_id):
            return error_response(f"Không tìm thấy học sinh với ID: {order_student_id}", logs=logs)
        
        # Lấy file từ request
        files = frappe.request.files
        if 'file' not in files:
            return validation_error_response("Thiếu file", {"file": ["Bắt buộc"]})
        
        uploaded_file = files['file']
        file_name = uploaded_file.filename
        
        logs.append(f"Uploading file: {file_name} for student: {order_student_id}")
        
        # Lưu file vào Frappe File Manager
        file_doc = frappe.get_doc({
            "doctype": "File",
            "file_name": file_name,
            "attached_to_doctype": "SIS Finance Order Student",
            "attached_to_name": order_student_id,
            "content": uploaded_file.read(),
            "is_private": 1
        })
        file_doc.insert(ignore_permissions=True)
        
        logs.append(f"File saved: {file_doc.file_url}")
        
        # Tạo document record
        doc = frappe.get_doc({
            "doctype": "SIS Finance Student Document",
            "order_student_id": order_student_id,
            "document_type": document_type,
            "file_url": file_doc.file_url,
            "file_name": file_name,
            "notes": notes,
            "uploaded_by": frappe.session.user,
            "uploaded_at": now_datetime()
        })
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        
        logs.append(f"Document created: {doc.name}")
        
        return success_response(
            data={
                "name": doc.name,
                "order_student_id": doc.order_student_id,
                "document_type": doc.document_type,
                "file_url": doc.file_url,
                "file_name": doc.file_name,
                "notes": doc.notes,
                "uploaded_by": doc.uploaded_by,
                "uploaded_at": str(doc.uploaded_at) if doc.uploaded_at else None
            },
            message=f"Đã upload {_get_document_type_label(document_type)}",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Upload Student Document Error")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def get_student_documents(order_student_id=None):
    """
    Lấy danh sách tài liệu của học sinh.
    
    Args:
        order_student_id: ID của SIS Finance Order Student
    
    Returns:
        Danh sách documents
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        if not order_student_id:
            order_student_id = frappe.request.args.get('order_student_id')
        
        if not order_student_id:
            return validation_error_response("Thiếu order_student_id", {"order_student_id": ["Bắt buộc"]})
        
        documents = frappe.get_all(
            "SIS Finance Student Document",
            filters={"order_student_id": order_student_id},
            fields=[
                "name", "order_student_id", "document_type", 
                "file_url", "file_name", "notes",
                "uploaded_by", "uploaded_at", "creation"
            ],
            order_by="creation desc"
        )
        
        # Chuyển đổi datetime thành string
        for doc in documents:
            if doc.get('uploaded_at'):
                doc['uploaded_at'] = str(doc['uploaded_at'])
            if doc.get('creation'):
                doc['creation'] = str(doc['creation'])
            doc['document_type_label'] = _get_document_type_label(doc.get('document_type'))
        
        return list_response(documents, logs=logs)
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def delete_student_document():
    """
    Xóa tài liệu của học sinh.
    
    Args (JSON body):
        document_id: ID của SIS Finance Student Document
    
    Returns:
        Kết quả xóa
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền xóa tài liệu", logs=logs)
        
        data = _get_request_data()
        document_id = data.get('document_id')
        
        if not document_id:
            return validation_error_response("Thiếu document_id", {"document_id": ["Bắt buộc"]})
        
        # Kiểm tra document tồn tại
        if not frappe.db.exists("SIS Finance Student Document", document_id):
            return error_response(f"Không tìm thấy tài liệu với ID: {document_id}", logs=logs)
        
        # Lấy thông tin document trước khi xóa
        doc = frappe.get_doc("SIS Finance Student Document", document_id)
        file_url = doc.file_url
        document_type = doc.document_type
        
        # Xóa document
        frappe.delete_doc("SIS Finance Student Document", document_id, ignore_permissions=True)
        
        # Xóa file (optional - có thể giữ lại nếu cần)
        if file_url:
            try:
                file_doc = frappe.get_doc("File", {"file_url": file_url})
                if file_doc:
                    frappe.delete_doc("File", file_doc.name, ignore_permissions=True)
                    logs.append(f"Đã xóa file: {file_url}")
            except Exception as file_error:
                logs.append(f"Không thể xóa file: {str(file_error)}")
        
        frappe.db.commit()
        
        return success_response(
            data={"document_id": document_id},
            message=f"Đã xóa {_get_document_type_label(document_type)}",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Delete Student Document Error")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


def _get_document_type_label(document_type):
    """Lấy label tiếng Việt cho document_type"""
    labels = {
        'debit_note': 'Debit Note',
        'receipt': 'Biên lai',
        'invoice': 'Hóa đơn'
    }
    return labels.get(document_type, document_type)
