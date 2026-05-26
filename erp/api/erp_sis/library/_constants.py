# DocType constants
LOOKUP_DTYPE = "SIS Library Lookup"
TITLE_DTYPE = "SIS Library Title"
COPY_DTYPE = "SIS Library Book Copy"
ACTIVITY_DTYPE = "SIS Library Activity"
EVENT_DTYPE = "SIS Library Event"
EVENT_DAY_DTYPE = "SIS Library Event Day"
BOOK_INTRO_DTYPE = "SIS Library Book Introduction"
TRANSACTION_DTYPE = "SIS Library Transaction"
TRANSACTION_ITEM_DTYPE = "SIS Library Transaction Item"
FINE_DTYPE = "SIS Library Fine"
SETTINGS_DTYPE = "SIS Library Settings"

DEFAULT_LOAN_DAYS = 20  # Fallback khi chưa có SIS Library Settings
DEFAULT_LIBRARY_SETTINGS = {
    "default_loan_days": 20,
    "max_books_per_student": 0,
}

VALID_LOOKUP_TYPES = {
    "convention",      # Mã quy ước: code (mã đặc biệt), storage (nơi lưu trữ), language (ngôn ngữ)
    "document_type",   # Phân loại tài liệu: name_vi (tên đầu mục), code (mã)
    "series",          # Tùng thư: name_vi (tên tùng thư)
    "author",          # Tác giả: name_vi (tên tác giả)
}

STATUS_MAP = {"available", "borrowed", "reserved", "overdue", "lost", "damaged"}
ALLOWED_ROLES = {"System Manager", "SIS Library"}
