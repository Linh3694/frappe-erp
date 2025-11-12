"""
File Operation Logging Handler
Logs file uploads, updates, and deletes for audit trail
"""

import frappe
from erp.utils.centralized_logger import log_file_operation, log_error


def log_file_upload(doc, method=None, **kwargs):
    """Hook called after file upload"""
    try:
        user = frappe.session.user
        filename = doc.file_name
        filesize_kb = (doc.file_size or 0) / 1024
        doctype = doc.attached_to_doctype
        docname = doc.attached_to_name
        is_private = doc.is_private
        
        log_file_operation(
            user=user,
            operation='upload',
            filename=filename,
            filesize_kb=filesize_kb,
            doctype=doctype,
            docname=docname,
            is_private=is_private,
            details={
                'file_url': doc.file_url,
                'content_type': doc.content_type,
                'timestamp': frappe.utils.now()
            }
        )
    except Exception as e:
        frappe.errprint(f"Error logging file upload: {str(e)}")


def log_file_update(doc, method=None, **kwargs):
    """Hook called when file is updated"""
    try:
        user = frappe.session.user
        filename = doc.file_name
        filesize_kb = (doc.file_size or 0) / 1024
        doctype = doc.attached_to_doctype
        docname = doc.attached_to_name
        is_private = doc.is_private
        
        log_file_operation(
            user=user,
            operation='update',
            filename=filename,
            filesize_kb=filesize_kb,
            doctype=doctype,
            docname=docname,
            is_private=is_private,
            details={
                'file_url': doc.file_url,
                'content_type': doc.content_type,
                'timestamp': frappe.utils.now()
            }
        )
    except Exception as e:
        frappe.errprint(f"Error logging file update: {str(e)}")


def log_file_delete(doc, method=None, **kwargs):
    """Hook called when file is deleted"""
    try:
        user = frappe.session.user
        filename = doc.file_name
        filesize_kb = (doc.file_size or 0) / 1024
        doctype = doc.attached_to_doctype
        docname = doc.attached_to_name
        is_private = doc.is_private
        
        log_file_operation(
            user=user,
            operation='delete',
            filename=filename,
            filesize_kb=filesize_kb,
            doctype=doctype,
            docname=docname,
            is_private=is_private,
            details={
                'file_url': doc.file_url,
                'content_type': doc.content_type,
                'timestamp': frappe.utils.now()
            }
        )
    except Exception as e:
        frappe.errprint(f"Error logging file delete: {str(e)}")

