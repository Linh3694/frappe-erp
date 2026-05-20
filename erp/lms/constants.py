# Trạng thái video / transcode
VIDEO_STATUS_DRAFT = "draft"
VIDEO_STATUS_UPLOADING = "uploading"
VIDEO_STATUS_PROCESSING = "processing"
VIDEO_STATUS_READY = "ready"
VIDEO_STATUS_FAILED = "failed"

VIDEO_STATUSES = [
	VIDEO_STATUS_DRAFT,
	VIDEO_STATUS_UPLOADING,
	VIDEO_STATUS_PROCESSING,
	VIDEO_STATUS_READY,
	VIDEO_STATUS_FAILED,
]

# Khóa học
COURSE_STATE_DRAFT = "draft"
COURSE_STATE_PUBLISHED = "published"
COURSE_STATE_CONCLUDED = "concluded"

# Enrollment
ENROLLMENT_ROLE_STUDENT = "student"
ENROLLMENT_ROLE_TEACHER = "teacher"
ENROLLMENT_ROLE_TA = "ta"
ENROLLMENT_ROLE_DESIGNER = "designer"
ENROLLMENT_ROLE_OBSERVER = "observer"

ENROLLMENT_STATUS_ACTIVE = "active"
ENROLLMENT_STATUS_INACTIVE = "inactive"

# Module item types
MODULE_ITEM_TYPES = [
	"page",
	"video",
	"assignment",
	"quiz",
	"file",
	"external_url",
	"discussion",
	"subheader",
	"text",
]
