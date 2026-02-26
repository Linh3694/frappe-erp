"""
Finance API Module
Quản lý tài chính cho SIS - Admin/Registrar APIs

Re-export tất cả functions từ các sub-modules để giữ backward compatibility.
Frontend gọi API qua path: /api/method/erp.api.erp_sis.finance.<function_name>
"""

# Finance Year APIs
from .finance_year import (
    get_finance_years,
    get_finance_year,
    create_finance_year,
    update_finance_year,
    delete_finance_year,
    toggle_finance_year_active,
    sync_students
)

# Finance Student APIs
from .finance_student import (
    get_finance_students,
    get_student_orders
)

# Order APIs (basic CRUD)
from .order import (
    get_orders,
    get_order,
    create_order,
    update_order,
    delete_order,
    assign_order_to_students,
    assign_order_to_all_students,
    toggle_order_active
)

# Order Items APIs
from .order_items import (
    get_order_items,
    update_payment_status,
    import_payment_status
)

# Statistics APIs
from .statistics import (
    get_finance_year_statistics,
    export_finance_data
)

# Order Structure APIs (v2 with milestones)
from .order_structure import (
    create_order_simple,
    create_order_with_structure,
    get_order_with_structure,
    update_order_structure,
    add_students_to_order_v2,
    get_order_students_v2,
    get_paid_tuition_students
)

# Payment APIs
from .payment import (
    update_order_student_payment,
    record_milestone_payment
)

# Excel Import/Export APIs
from .excel import (
    export_simple_template,
    import_simple_amounts,
    export_order_excel_template,
    import_student_fee_data,
    recalculate_order_totals
)

# Debit Note & Send Batch APIs
from .debit_note import (
    create_send_batch,
    get_send_batches,
    get_unpaid_students,
    get_debit_note_preview,
    get_debit_note_history
)

# Fee Notification APIs
from .notification import (
    create_fee_notification,
    get_fee_notifications,
    delete_fee_notification,
    send_fee_notification
)

# Student Document APIs (upload debit_note, receipt, invoice)
from .student_document import (
    upload_student_document,
    get_student_documents,
    delete_student_document,
    bulk_upload_debit_notes
)

# Export tất cả functions để giữ backward compatibility
__all__ = [
    # Finance Year
    'get_finance_years',
    'get_finance_year',
    'create_finance_year',
    'update_finance_year',
    'delete_finance_year',
    'toggle_finance_year_active',
    'sync_students',
    
    # Finance Student
    'get_finance_students',
    'get_student_orders',
    
    # Order (basic CRUD)
    'get_orders',
    'get_order',
    'create_order',
    'update_order',
    'delete_order',
    'assign_order_to_students',
    'assign_order_to_all_students',
    'toggle_order_active',
    
    # Order Items
    'get_order_items',
    'update_payment_status',
    'import_payment_status',
    
    # Statistics
    'get_finance_year_statistics',
    'export_finance_data',
    
    # Order Structure (v2)
    'create_order_simple',
    'create_order_with_structure',
    'get_order_with_structure',
    'update_order_structure',
    'add_students_to_order_v2',
    'get_order_students_v2',
    'get_paid_tuition_students',
    
    # Payment
    'update_order_student_payment',
    'record_milestone_payment',
    
    # Excel Import/Export
    'export_simple_template',
    'import_simple_amounts',
    'export_order_excel_template',
    'import_student_fee_data',
    'recalculate_order_totals',
    
    # Debit Note & Send Batch
    'create_send_batch',
    'get_send_batches',
    'get_unpaid_students',
    'get_debit_note_preview',
    'get_debit_note_history',
    
    # Fee Notification
    'create_fee_notification',
    'get_fee_notifications',
    'delete_fee_notification',
    'send_fee_notification',
    
    # Student Document
    'upload_student_document',
    'get_student_documents',
    'delete_student_document',
    'bulk_upload_debit_notes',
]
