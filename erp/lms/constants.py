# LMS constants — trạng thái, role, loại nội dung

VIDEO_STATUS_DRAFT = "draft"
VIDEO_STATUS_UPLOADING = "uploading"
VIDEO_STATUS_PROCESSING = "processing"
VIDEO_STATUS_READY = "ready"
VIDEO_STATUS_FAILED = "failed"

COURSE_STATE_DRAFT = "draft"
COURSE_STATE_PUBLISHED = "published"
COURSE_STATE_CONCLUDED = "concluded"

ENROLLMENT_ROLE_STUDENT = "student"
ENROLLMENT_ROLE_TEACHER = "teacher"
ENROLLMENT_ROLE_TA = "ta"
ENROLLMENT_ROLE_DESIGNER = "designer"
ENROLLMENT_ROLE_OBSERVER = "observer"
ENROLLMENT_STATUS_ACTIVE = "active"
ENROLLMENT_STATUS_INACTIVE = "inactive"

MODULE_ITEM_TYPES = [
	"page", "video", "assignment", "quiz", "file", "external_url",
	"discussion", "subheader", "text",
]

SUBMISSION_STATE_UNSUBMITTED = "unsubmitted"
SUBMISSION_STATE_SUBMITTED = "submitted"
SUBMISSION_STATE_GRADED = "graded"
SUBMISSION_STATE_NEEDS_REVISION = "needs_revision"

QUESTION_TYPES = [
	"multiple_choice", "true_false", "short_answer", "essay", "matching", "numerical",
]

GRADE_COLUMN_TYPES = ["assignment", "quiz", "manual", "discussion"]

CALENDAR_EVENT_TYPES = ["due", "quiz", "assignment", "live", "custom"]

QUIZ_SCORE_POLICY = ["highest", "latest", "average"]

SHOW_ANSWERS = ["after_submit", "after_due", "never"]
