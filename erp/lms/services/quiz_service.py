"""Quiz builder, attempt, auto-grade MCQ/TF, chấm essay thủ công."""

import json
import random

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

from erp.lms.utils.enrollment import get_student_id_for_user, validate_section_enrollment
from erp.lms.utils.permissions import is_lms_staff, require_lms_staff

# Câu hỏi cần GV chấm tay
MANUAL_GRADE_TYPES = frozenset({"essay", "short_answer", "matching"})


def create_quiz(data: dict) -> dict:
	require_lms_staff()
	doc = frappe.get_doc({"doctype": "LMS Quiz", **data})
	if not doc.campus_id and doc.course:
		doc.campus_id = frappe.db.get_value("LMS Course", doc.course, "campus_id")
	doc.insert()
	_ensure_grade_column_for_quiz(doc)
	return doc.as_dict()


def start_attempt(quiz_id: str, user: str | None = None) -> dict:
	user = user or frappe.session.user
	student_id = get_student_id_for_user(user)
	if not student_id:
		frappe.throw("Chỉ học sinh mới làm quiz")

	quiz = frappe.get_doc("LMS Quiz", quiz_id)
	if quiz.section:
		validate_section_enrollment(quiz.section, user, min_role="student")

	attempt_count = frappe.db.count("LMS Quiz Attempt", {"quiz": quiz_id, "student_id": student_id})
	if quiz.allowed_attempts and quiz.allowed_attempts > 0 and attempt_count >= quiz.allowed_attempts:
		frappe.throw("Đã hết lượt làm bài")

	started_at = now_datetime()
	expires_at = None
	if quiz.time_limit and int(quiz.time_limit) > 0:
		expires_at = add_to_date(started_at, minutes=int(quiz.time_limit))

	doc = frappe.get_doc(
		{
			"doctype": "LMS Quiz Attempt",
			"quiz": quiz_id,
			"student_id": student_id,
			"started_at": started_at,
			"expires_at": expires_at,
			"workflow_state": "in_progress",
			"responses_json": "{}",
		}
	)
	doc.insert(ignore_permissions=True)

	raw_questions = _load_quiz_questions_raw(quiz_id)
	if quiz.shuffle_questions:
		random.shuffle(raw_questions)
	doc.question_order_json = json.dumps([q["question_id"] for q in raw_questions])
	doc.save(ignore_permissions=True)

	questions = [_serialize_question_for_student(q, quiz) for q in raw_questions]
	return {
		"attempt": doc.as_dict(),
		"questions": questions,
		"time_limit_minutes": quiz.time_limit or 0,
		"expires_at": expires_at,
	}


def submit_attempt(attempt_id: str, responses: dict, user: str | None = None) -> dict:
	user = user or frappe.session.user
	student_id = get_student_id_for_user(user)
	doc = frappe.get_doc("LMS Quiz Attempt", attempt_id)
	quiz = frappe.get_doc("LMS Quiz", doc.quiz)

	if not is_lms_staff(user):
		if doc.student_id != student_id:
			frappe.throw("Không có quyền", frappe.PermissionError)
		if doc.workflow_state != "in_progress":
			frappe.throw("Attempt không còn ở trạng thái in_progress")
		if quiz.section:
			validate_section_enrollment(quiz.section, user, min_role="student")
		_check_attempt_not_expired(doc)

	if isinstance(responses, str):
		responses = json.loads(responses)
	doc.responses_json = json.dumps(responses or {})
	doc.finished_at = now_datetime()
	doc.workflow_state = "submitted"

	questions = _load_questions_for_attempt(doc)
	score = _auto_grade_attempt(doc, questions)
	doc.score = score

	needs_manual = any(q.get("question_type") in MANUAL_GRADE_TYPES for q in questions)
	if needs_manual:
		doc.workflow_state = "submitted"
	else:
		doc.workflow_state = "graded"
		_sync_attempt_to_grade_entry(doc)

	doc.save(ignore_permissions=True)

	if doc.workflow_state == "graded":
		_trigger_mastery_unlock(doc)

	result = doc.as_dict()
	show_answers = _should_show_correct_answers(quiz, doc)
	if show_answers:
		result["show_answers"] = _build_answer_key(questions)
	return result


def grade_attempt(
	attempt_id: str,
	question_scores: dict | None = None,
	overall_score: float | None = None,
	feedback: str | None = None,
) -> dict:
	"""GV chấm attempt có câu essay/short_answer."""
	require_lms_staff()
	doc = frappe.get_doc("LMS Quiz Attempt", attempt_id)
	if doc.workflow_state not in ("submitted", "graded"):
		frappe.throw("Attempt không ở trạng thái chờ chấm")

	questions = _load_questions_for_attempt(doc)
	if isinstance(question_scores, str):
		question_scores = json.loads(question_scores)

	if question_scores:
		doc.score = _merge_manual_scores(doc, questions, question_scores)
	elif overall_score is not None:
		doc.score = float(overall_score)
	else:
		doc.score = _auto_grade_attempt(doc, questions)

	if feedback:
		doc.feedback = feedback
	doc.workflow_state = "graded"
	doc.save(ignore_permissions=True)
	_sync_attempt_to_grade_entry(doc)
	_trigger_mastery_unlock(doc)
	return doc.as_dict()


def _trigger_mastery_unlock(attempt):
	"""Sau khi quiz graded — đánh giá mastery unlock module tiếp theo."""
	try:
		from erp.lms.services.mastery_service import evaluate_unlock

		quiz = frappe.get_doc("LMS Quiz", attempt.quiz)
		evaluate_unlock(
			student_id=attempt.student_id,
			quiz_id=attempt.quiz,
			section_id=quiz.section,
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "lms.mastery.evaluate_unlock")


def list_quiz_attempts(quiz_id: str, section_id: str | None = None) -> list:
	"""Danh sách attempt — staff xem queue chấm."""
	require_lms_staff()
	if section_id:
		quiz_section = frappe.db.get_value("LMS Quiz", quiz_id, "section")
		if quiz_section and quiz_section != section_id:
			frappe.throw("Quiz không thuộc section này")

	filters = {"quiz": quiz_id}
	rows = frappe.get_all(
		"LMS Quiz Attempt",
		filters=filters,
		fields=[
			"name", "quiz", "student_id", "workflow_state",
			"started_at", "finished_at", "score", "expires_at",
		],
		order_by="modified desc",
	)
	for row in rows:
		row["student_name"] = frappe.db.get_value("CRM Student", row.student_id, "student_name")
	return rows


def _check_attempt_not_expired(attempt):
	if not attempt.expires_at:
		return
	if get_datetime(now_datetime()) > get_datetime(attempt.expires_at):
		frappe.throw("Đã hết thời gian làm bài")


def _load_quiz_questions_raw(quiz_id: str) -> list:
	links = frappe.get_all(
		"LMS Quiz Question",
		filters={"quiz": quiz_id},
		fields=["name", "question", "position", "points_override"],
		order_by="position asc",
	)
	out = []
	for link in links:
		q = frappe.get_doc("LMS Question", link.question)
		out.append(
			{
				"quiz_question": link.name,
				"question_id": q.name,
				"question_type": q.question_type,
				"prompt_html": q.prompt_html,
				"answers_json": q.answers_json,
				"points": link.points_override or q.points,
			}
		)
	return out


def _load_questions_for_attempt(attempt) -> list:
	raw = _load_quiz_questions_raw(attempt.quiz)
	if not attempt.question_order_json:
		return raw
	try:
		order = json.loads(attempt.question_order_json or "[]")
	except json.JSONDecodeError:
		return raw
	by_id = {q["question_id"]: q for q in raw}
	return [by_id[qid] for qid in order if qid in by_id]


def _serialize_question_for_student(q: dict, quiz) -> dict:
	"""Ẩn đáp án đúng khi học sinh làm bài."""
	answers = json.loads(q.get("answers_json") or "{}")
	qtype = q.get("question_type")
	safe_answers = {}

	if qtype == "multiple_choice":
		safe_answers = {"options": answers.get("options", [])}
	elif qtype == "true_false":
		safe_answers = {"type": "true_false"}
	elif qtype == "matching":
		safe_answers = {"pairs": answers.get("pairs", [])}
	elif qtype == "numerical":
		safe_answers = {"tolerance": answers.get("tolerance")}

	return {
		"quiz_question": q["quiz_question"],
		"question_id": q["question_id"],
		"question_type": qtype,
		"prompt_html": q["prompt_html"],
		"answers_json": json.dumps(safe_answers),
		"points": q.get("points"),
	}


def _should_show_correct_answers(quiz, attempt) -> bool:
	policy = quiz.show_correct_answers or "after_due"
	if policy == "never":
		return False
	if policy == "after_submit":
		return attempt.workflow_state in ("submitted", "graded")
	# after_due — quiz chưa có due_at, chỉ hiện sau khi đã nộp
	return attempt.workflow_state in ("submitted", "graded")


def _build_answer_key(questions: list) -> dict:
	out = {}
	for q in questions:
		answers = json.loads(q.get("answers_json") or "{}")
		if answers.get("correct") is not None:
			out[q["question_id"]] = answers.get("correct")
	return out


def _auto_grade_attempt(attempt, questions: list | None = None) -> float:
	responses = json.loads(attempt.responses_json or "{}")
	questions = questions or _load_questions_for_attempt(attempt)
	total = 0.0
	earned = 0.0
	for q in questions:
		points = float(q.get("points") or 0)
		total += points
		qid = q["question_id"]
		user_ans = responses.get(qid)
		if user_ans is None:
			continue
		answers = json.loads(q.get("answers_json") or "{}")
		qtype = q.get("question_type")
		if qtype in ("multiple_choice", "true_false"):
			correct = answers.get("correct")
			if str(user_ans) == str(correct):
				earned += points
		elif qtype == "numerical":
			try:
				correct = float(answers.get("correct", 0))
				tolerance = float(answers.get("tolerance") or 0)
				if abs(float(user_ans) - correct) <= tolerance:
					earned += points
			except (TypeError, ValueError):
				pass
	return round(earned, 2) if total else 0.0


def _merge_manual_scores(attempt, questions: list, question_scores: dict) -> float:
	responses = json.loads(attempt.responses_json or "{}")
	total = 0.0
	earned = 0.0
	for q in questions:
		points = float(q.get("points") or 0)
		total += points
		qid = q["question_id"]
		if qid in question_scores:
			earned += min(float(question_scores[qid]), points)
		elif q.get("question_type") in ("multiple_choice", "true_false", "numerical"):
			answers = json.loads(q.get("answers_json") or "{}")
			user_ans = responses.get(qid)
			if user_ans is not None and q.get("question_type") in ("multiple_choice", "true_false"):
				if str(user_ans) == str(answers.get("correct")):
					earned += points
	return round(earned, 2)


def _ensure_grade_column_for_quiz(quiz):
	if not quiz.section:
		return
	if frappe.db.exists("LMS Grade Column", {"quiz": quiz.name}):
		return
	frappe.get_doc(
		{
			"doctype": "LMS Grade Column",
			"section": quiz.section,
			"title": quiz.title,
			"points_possible": 100,
			"column_type": "quiz",
			"quiz": quiz.name,
			"campus_id": quiz.campus_id,
		}
	).insert(ignore_permissions=True)


def _sync_attempt_to_grade_entry(attempt):
	quiz = frappe.get_doc("LMS Quiz", attempt.quiz)
	if not quiz.section:
		return
	column = frappe.db.get_value("LMS Grade Column", {"quiz": quiz.name})
	if not column:
		return
	existing = frappe.db.get_value(
		"LMS Grade Entry",
		{"column": column, "student_id": attempt.student_id},
	)
	payload = {"score": attempt.score, "entered_by": frappe.session.user}
	if existing:
		frappe.db.set_value("LMS Grade Entry", existing, payload)
	else:
		frappe.get_doc(
			{
				"doctype": "LMS Grade Entry",
				"column": column,
				"student_id": attempt.student_id,
				**payload,
			}
		).insert(ignore_permissions=True)
