# -*- coding: utf-8 -*-
"""
Report Card Constants
=====================

Centralized constants cho Report Card module.
Tránh hardcoded values và đảm bảo consistency.
"""


class ApprovalStatus:
    """Các trạng thái phê duyệt của báo cáo học tập."""
    DRAFT = "draft"
    ENTRY = "entry"
    SUBMITTED = "submitted"
    LEVEL_1_APPROVED = "level_1_approved"
    LEVEL_2_APPROVED = "level_2_approved"
    REVIEWED = "reviewed"
    PUBLISHED = "published"
    REJECTED = "rejected"
    
    @classmethod
    def all_statuses(cls):
        """Trả về list tất cả statuses theo thứ tự."""
        return [
            cls.DRAFT, cls.ENTRY, cls.SUBMITTED,
            cls.LEVEL_1_APPROVED, cls.LEVEL_2_APPROVED,
            cls.REVIEWED, cls.PUBLISHED, cls.REJECTED
        ]
    
    @classmethod
    def can_submit_from(cls):
        """Statuses có thể submit."""
        return [cls.DRAFT, cls.ENTRY, cls.REJECTED]
    
    @classmethod
    def can_approve_l1_from(cls):
        """Statuses có thể approve Level 1."""
        return [cls.SUBMITTED]
    
    @classmethod
    def can_approve_l2_from(cls):
        """Statuses có thể approve Level 2."""
        return [cls.SUBMITTED, cls.LEVEL_1_APPROVED]
    
    @classmethod
    def can_review_from(cls):
        """Statuses có thể review (Level 3)."""
        return [cls.LEVEL_2_APPROVED]
    
    @classmethod
    def can_publish_from(cls):
        """Statuses có thể publish (Level 4)."""
        return [cls.REVIEWED]


# Thứ tự ưu tiên trạng thái (thấp đến cao)
# Dùng để so sánh và xác định status thấp nhất trong batch
STATUS_PRIORITY = {
    ApprovalStatus.REJECTED: -1,  # Rejected có ưu tiên đặc biệt
    ApprovalStatus.DRAFT: 0,
    ApprovalStatus.ENTRY: 1,
    ApprovalStatus.SUBMITTED: 2,
    ApprovalStatus.LEVEL_1_APPROVED: 3,
    ApprovalStatus.LEVEL_2_APPROVED: 4,
    ApprovalStatus.REVIEWED: 5,
    ApprovalStatus.PUBLISHED: 6,
}

# Thứ tự status cho việc so sánh (không bao gồm rejected)
STATUS_ORDER = [
    ApprovalStatus.DRAFT,
    ApprovalStatus.ENTRY,
    ApprovalStatus.REJECTED,
    ApprovalStatus.SUBMITTED,
    ApprovalStatus.LEVEL_1_APPROVED,
    ApprovalStatus.LEVEL_2_APPROVED,
    ApprovalStatus.REVIEWED,
    ApprovalStatus.PUBLISHED
]


class SectionType:
    """Các loại section trong báo cáo học tập."""
    HOMEROOM = "homeroom"
    SCORES = "scores"
    SUBJECT_EVAL = "subject_eval"
    MAIN_SCORES = "main_scores"
    IELTS = "ielts"
    COMMENTS = "comments"
    ALL = "all"
    
    @classmethod
    def vn_sections(cls):
        """Sections cho chương trình Việt Nam."""
        return [cls.SCORES, cls.HOMEROOM, cls.SUBJECT_EVAL]
    
    @classmethod
    def intl_sections(cls):
        """Sections cho chương trình Quốc tế."""
        return [cls.MAIN_SCORES, cls.IELTS, cls.COMMENTS]
    
    @classmethod
    def all_board_types(cls):
        """Tất cả board types."""
        return [cls.SCORES, cls.SUBJECT_EVAL, cls.MAIN_SCORES, cls.IELTS, cls.COMMENTS]


# Mapping section -> tên hiển thị tiếng Việt
SECTION_NAME_MAP = {
    SectionType.HOMEROOM: "Nhận xét GVCN",
    SectionType.SCORES: "Bảng điểm",
    SectionType.SUBJECT_EVAL: "Đánh giá môn học",
    SectionType.MAIN_SCORES: "Điểm INTL",
    SectionType.IELTS: "IELTS",
    SectionType.COMMENTS: "Nhận xét",
    SectionType.ALL: "Tất cả",
}


class PendingLevel:
    """Các level chờ duyệt."""
    LEVEL_1 = "level_1"
    LEVEL_2 = "level_2"
    REVIEW = "review"
    PUBLISH = "publish"


class ProgramType:
    """Loại chương trình học."""
    VN = "vn"
    INTL = "intl"


class Messages:
    """Các message chuẩn hóa cho API responses."""
    
    # Success messages
    TEMPLATE_CREATED = "Tạo mẫu báo cáo thành công"
    TEMPLATE_UPDATED = "Cập nhật mẫu báo cáo thành công"
    TEMPLATE_DELETED = "Xóa mẫu báo cáo thành công"
    TEMPLATE_FETCHED = "Lấy thông tin mẫu báo cáo thành công"
    
    REPORT_CREATED = "Tạo báo cáo học tập thành công"
    REPORT_UPDATED = "Cập nhật báo cáo học tập thành công"
    REPORT_DELETED = "Xóa báo cáo học tập thành công"
    
    REPORTS_SUBMITTED = "Đã submit {count} báo cáo thành công"
    REPORTS_APPROVED = "Đã duyệt {count} báo cáo thành công"
    REPORTS_REJECTED = "Đã trả về {count} báo cáo"
    REPORTS_REVIEWED = "Đã review {count} báo cáo thành công"
    REPORTS_PUBLISHED = "Đã xuất bản {count} báo cáo thành công"
    
    APPROVAL_L1_SUCCESS = "Đã duyệt Level 1 thành công. Chuyển sang Level 2."
    APPROVAL_L2_SUCCESS = "Đã duyệt Level 2 thành công. Chuyển sang Review."
    REVIEW_SUCCESS = "Đã Review thành công. Chuyển sang phê duyệt xuất bản."
    PUBLISH_SUCCESS = "Đã xuất bản báo cáo thành công. Phụ huynh có thể xem báo cáo."
    
    CONFIG_SAVED = "Đã lưu cấu hình phê duyệt thành công"
    CONFIG_FETCHED = "Lấy cấu hình phê duyệt thành công"
    
    # Error messages
    TEMPLATE_NOT_FOUND = "Không tìm thấy mẫu báo cáo"
    REPORT_NOT_FOUND = "Không tìm thấy báo cáo học tập"
    CLASS_NOT_FOUND = "Không tìm thấy lớp học"
    STUDENT_NOT_FOUND = "Không tìm thấy học sinh"
    SUBJECT_NOT_FOUND = "Không tìm thấy môn học"
    
    PERMISSION_DENIED = "Bạn không có quyền thực hiện thao tác này"
    ACCESS_DENIED_CAMPUS = "Không có quyền truy cập: Dữ liệu thuộc trường khác"
    ACCESS_DENIED_TEMPLATE = "Không có quyền truy cập template này"
    ACCESS_DENIED_REPORT = "Không có quyền truy cập báo cáo này"
    
    INVALID_STATUS = "Trạng thái báo cáo không hợp lệ"
    INVALID_STATUS_FOR_SUBMIT = "Báo cáo đã ở trạng thái '{status}', không thể submit"
    INVALID_STATUS_FOR_APPROVAL = "Báo cáo cần ở trạng thái '{required}'. Hiện tại: '{current}'"
    
    NO_REPORTS_FOUND = "Không tìm thấy báo cáo nào"
    NO_REPORTS_TO_APPROVE = "Không tìm thấy báo cáo nào để duyệt"
    NO_REPORTS_TO_REJECT = "Không tìm thấy báo cáo nào để trả về"
    
    CANNOT_DELETE_PUBLISHED = "Không thể xóa báo cáo đã xuất bản"
    
    # Validation messages
    REQUIRED_FIELD = "Trường {field} là bắt buộc"
    TEMPLATE_ID_REQUIRED = "template_id là bắt buộc"
    CLASS_ID_REQUIRED = "class_id là bắt buộc"
    REPORT_ID_REQUIRED = "report_id là bắt buộc"
    REASON_REQUIRED = "Lý do trả về là bắt buộc"
    SECTION_REQUIRED = "section là bắt buộc"
    
    TEMPLATE_DUPLICATE = "Đã tồn tại template cho {program_type} - {semester_part} - {school_year}"
    
    # Approval specific messages
    APPROVAL_L1_PERMISSION_DENIED = "Bạn không có quyền duyệt Level 1 cho báo cáo này"
    APPROVAL_L2_PERMISSION_DENIED = "Bạn không có quyền duyệt Level 2 cho báo cáo này"
    REVIEW_PERMISSION_DENIED = "Bạn không có quyền Review (Level 3) cho báo cáo này"
    PUBLISH_PERMISSION_DENIED = "Bạn không có quyền xuất bản (Level 4) báo cáo này"
    
    # Comment/Subject validation
    COMMENT_TITLE_NOT_FOUND = "Không thể tạo mẫu báo cáo: Một hoặc nhiều tiêu đề nhận xét không tồn tại hoặc đã bị xóa."
    ACTUAL_SUBJECT_NOT_FOUND = "Không thể tạo mẫu báo cáo: Một hoặc nhiều môn học không tồn tại hoặc đã bị xóa."
    TITLE_TOO_LONG = "Tiêu đề quá dài. Vui lòng rút ngắn tiêu đề và thử lại."


class ErrorCode:
    """Mã lỗi chuẩn hóa."""
    NOT_FOUND = "NOT_FOUND"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    INVALID_STATUS = "INVALID_STATUS"
    MISSING_PARAMS = "MISSING_PARAMS"
    NO_REPORTS = "NO_REPORTS"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    TEMPLATE_CREATE_ERROR = "TEMPLATE_CREATE_ERROR"
    TEMPLATE_UPDATE_ERROR = "TEMPLATE_UPDATE_ERROR"
    LINK_VALIDATION_ERROR = "LINK_VALIDATION_ERROR"
    COMMENT_TITLE_NOT_FOUND = "COMMENT_TITLE_NOT_FOUND"
    ACTUAL_SUBJECT_NOT_FOUND = "ACTUAL_SUBJECT_NOT_FOUND"
    TITLE_TOO_LONG = "TITLE_TOO_LONG"
    SERVER_ERROR = "SERVER_ERROR"
    INVALID_LEVEL = "INVALID_LEVEL"
