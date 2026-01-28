# -*- coding: utf-8 -*-
# Copyright (c) 2025, Linh Nguyen and contributors
# For license information, please see license.txt

"""
Parent Portal Analytics Dashboard API
Endpoints for fetching analytics data for the dashboard
"""

from __future__ import unicode_literals
import frappe
from frappe.utils import today, add_days, get_datetime
import json
from datetime import datetime, timedelta


@frappe.whitelist()
def get_dashboard_summary():
	"""
	Get summary statistics - LẤY TRỰC TIẾP TỪ DATABASE
	
	Response includes:
	- total_guardians: Tổng số guardians có thể đăng nhập
	- eligible_guardians: Alias của total_guardians
	- activated_guardians: Số guardians đã đăng nhập ít nhất 1 lần
	- activation_rate: Tỷ lệ kích hoạt (%)
	- active_guardians_today: DAU
	- active_guardians_7d: WAU
	- active_guardians_30d: MAU
	- new_guardians: Số người login lần đầu hôm nay
	"""
	try:
		from erp.api.analytics.portal_analytics import get_analytics_from_database
		
		today_date = today()
		yesterday_date = add_days(today_date, -1)
		
		# Lấy data trực tiếp từ database (realtime)
		db_stats = get_analytics_from_database()
		
		# Build response data
		response_data = {
			'total_guardians': db_stats['total_eligible'],
			'eligible_guardians': db_stats['total_eligible'],
			'activated_guardians': db_stats['activated_users'],
			'activation_rate': round((db_stats['activated_users'] / db_stats['total_eligible'] * 100), 1) if db_stats['total_eligible'] > 0 else 0,
			'active_guardians_today': db_stats['dau'],
			'active_guardians_7d': db_stats['wau'],
			'active_guardians_30d': db_stats['mau'],
			'new_guardians': db_stats['new_users_today']
		}
		
		# Changes - so sánh với ngày hôm qua
		yesterday_dau = frappe.db.sql("""
			SELECT COUNT(DISTINCT guardian) 
			FROM `tabPortal Guardian Activity`
			WHERE activity_date = %s
		""", (yesterday_date,))[0][0] or 0
		
		changes = {
			'active_today': 0,
			'total': 0
		}
		
		if yesterday_dau > 0:
			changes['active_today'] = round(
				((db_stats['dau'] - yesterday_dau) / yesterday_dau) * 100, 1
			)
		
		return {
			"success": True,
			"data": {
				"today": response_data,
				"changes": changes,
				"date": today_date
			}
		}
		
	except Exception as e:
		import traceback
		frappe.log_error(f"Error getting dashboard summary: {str(e)}\n{traceback.format_exc()}", "Dashboard API Error")
		return {
			"success": False,
			"message": str(e)
		}


@frappe.whitelist()
def get_user_trends(period="30d"):
	"""
	Get user activity trends - LẤY TỪ Portal Guardian Activity
	Args:
		period: "7d" or "30d"
	Returns: list of daily active user counts
	"""
	try:
		from erp.api.analytics.portal_analytics import get_eligible_guardians_count
		
		# Calculate date range
		days = 7 if period == "7d" else 30
		end_date = today()
		start_date = add_days(end_date, -days)
		
		# Lấy total eligible (cố định)
		total_eligible = get_eligible_guardians_count()
		
		# Lấy DAU cho từng ngày từ Portal Guardian Activity
		daily_stats = frappe.db.sql("""
			SELECT 
				activity_date as date,
				COUNT(DISTINCT guardian) as active_users
			FROM `tabPortal Guardian Activity`
			WHERE activity_date BETWEEN %s AND %s
			GROUP BY activity_date
			ORDER BY activity_date ASC
		""", (start_date, end_date), as_dict=True)
		
		# Tạo dict để lookup
		stats_by_date = {str(item.date): item.active_users for item in daily_stats}
		
		# Generate full date range với 0 cho ngày không có data
		trend_data = []
		current_date = datetime.strptime(str(start_date), "%Y-%m-%d")
		end_date_dt = datetime.strptime(str(end_date), "%Y-%m-%d")
		
		while current_date <= end_date_dt:
			date_str = current_date.strftime("%Y-%m-%d")
			trend_data.append({
				"date": date_str,
				"active_users": stats_by_date.get(date_str, 0),
				"total_users": total_eligible
			})
			current_date += timedelta(days=1)
		
		return {
			"success": True,
			"data": trend_data,
			"period": period
		}
		
	except Exception as e:
		import traceback
		frappe.log_error(f"Error getting user trends: {str(e)}\n{traceback.format_exc()}", "Dashboard API Error")
		return {
			"success": False,
			"message": str(e)
		}


@frappe.whitelist()
def get_module_usage(period="30d"):
	"""
	Get module usage statistics - LẤY TỪ Portal Guardian Activity
	
	Args:
		period: "7d" or "30d"
	Returns: dict with module names and usage counts
	"""
	try:
		from erp.utils.module_tracker import get_module_usage_stats
		
		# Chuyển đổi period sang số ngày
		days = 7 if period == "7d" else 30
		
		# Lấy stats từ module tracker
		stats = get_module_usage_stats(days=days)
		
		return {
			"success": True,
			"data": stats.get("data", []),
			"total_calls": stats.get("total_calls", 0)
		}
		
	except Exception as e:
		import traceback
		frappe.log_error(f"Error getting module usage: {str(e)}\n{traceback.format_exc()}", "Dashboard API Error")
		return {
			"success": False,
			"message": str(e)
		}


@frappe.whitelist()
def get_feedback_ratings(page=1, page_size=20):
	"""
	Get feedback ratings from Parent Portal
	Returns list of "Đánh giá" type feedbacks, newest first
	Args:
		page: Page number (default 1)
		page_size: Number of items per page (default 20)
	"""
	try:
		# Calculate offset
		page = int(page)
		page_size = int(page_size)
		offset = (page - 1) * page_size
		
		# Get total count
		total_count = frappe.db.count("Feedback", {
			"feedback_type": "Đánh giá"
		})
		
		# Get feedback ratings with guardian name
		feedbacks = frappe.db.sql("""
			SELECT 
				f.name,
				f.guardian,
				f.rating,
				f.rating_comment,
				f.submitted_at,
				g.guardian_name as guardian_name
			FROM `tabFeedback` f
			LEFT JOIN `tabCRM Guardian` g ON f.guardian = g.name
			WHERE f.feedback_type = 'Đánh giá'
			ORDER BY f.submitted_at DESC
			LIMIT %s OFFSET %s
		""", (page_size, offset), as_dict=True)
		
		# Calculate average rating
		avg_rating_data = frappe.db.sql("""
			SELECT AVG(rating) as avg_rating, COUNT(*) as total_count
			FROM `tabFeedback`
			WHERE feedback_type = 'Đánh giá' AND rating IS NOT NULL
		""", as_dict=True)
		
		avg_rating = 0
		rating_count = 0
		if avg_rating_data and len(avg_rating_data) > 0:
			# Rating is stored as 0-1, convert to 1-5 scale
			avg_rating_normalized = avg_rating_data[0].get('avg_rating', 0) or 0
			avg_rating = round(avg_rating_normalized * 5, 1)
			rating_count = avg_rating_data[0].get('total_count', 0)
		
		# Format feedback data
		formatted_feedbacks = []
		for fb in feedbacks:
			# Convert rating from 0-1 to 1-5 scale
			star_rating = round((fb.rating or 0) * 5) if fb.rating else 0
			
			formatted_feedbacks.append({
				"name": fb.name,
				"guardian": fb.guardian,
				"guardian_name": fb.guardian_name or fb.guardian,
				"rating": star_rating,
				"rating_comment": fb.rating_comment or "",
				"submitted_at": str(fb.submitted_at) if fb.submitted_at else ""
			})
		
		return {
			"success": True,
			"data": {
				"feedbacks": formatted_feedbacks,
				"total_count": total_count,
				"page": page,
				"page_size": page_size,
				"total_pages": (total_count + page_size - 1) // page_size,
				"average_rating": avg_rating,
				"rating_count": rating_count
			}
		}
		
	except Exception as e:
		frappe.log_error(f"Error getting feedback ratings: {str(e)}", "Dashboard API Error")
		return {
			"success": False,
			"message": str(e)
		}


@frappe.whitelist()
def trigger_analytics_aggregation():
	"""
	Manually trigger analytics aggregation
	Useful for testing or on-demand updates
	"""
	try:
		from erp.api.analytics.portal_analytics import aggregate_portal_analytics
		result = aggregate_portal_analytics()
		return result
	except Exception as e:
		frappe.log_error(f"Error triggering analytics aggregation: {str(e)}", "Dashboard API Error")
		return {
			"success": False,
			"message": str(e)
		}


@frappe.whitelist()
def get_login_history(days=30, limit=50):
	"""
	Get recent login history từ Portal Guardian Activity
	
	Args:
		days: Số ngày lấy lịch sử (default 30)
		limit: Số records tối đa (default 50)
	"""
	try:
		today_date = today()
		start_date = add_days(today_date, -int(days))
		
		# Lấy login records từ Portal Guardian Activity
		logins = frappe.db.sql("""
			SELECT 
				a.guardian,
				a.activity_date,
				a.activity_type,
				a.last_activity_at,
				g.guardian_id,
				g.guardian_name,
				g.phone_number
			FROM `tabPortal Guardian Activity` a
			INNER JOIN `tabCRM Guardian` g ON a.guardian = g.name
			WHERE a.activity_date >= %s
			AND a.activity_type = 'otp_login'
			ORDER BY a.last_activity_at DESC
			LIMIT %s
		""", (start_date, int(limit)), as_dict=True)
		
		# Format response
		formatted_logins = []
		for login in logins:
			formatted_logins.append({
				"guardian_id": login.guardian_id,
				"guardian_name": login.guardian_name,
				"phone_number": login.phone_number,
				"login_datetime": str(login.last_activity_at) if login.last_activity_at else str(login.activity_date),
				"date": str(login.activity_date),
				"activity_type": "OTP Login"
			})
		
		# Summary
		unique_guardians = len(set(l['guardian_id'] for l in formatted_logins))
		
		return {
			"success": True,
			"data": {
				"logins": formatted_logins,
				"summary": {
					"total_logins": len(formatted_logins),
					"unique_guardians": unique_guardians,
					"days_queried": int(days)
				}
			}
		}
		
	except Exception as e:
		import traceback
		frappe.log_error(f"Error getting login history: {str(e)}\n{traceback.format_exc()}", "Dashboard API Error")
		return {
			"success": False,
			"message": str(e)
		}


@frappe.whitelist()
def get_push_subscriptions(search="", page=1, page_size=50, filter_type="all"):
	"""
	Lấy danh sách Push Subscriptions của tất cả Parent
	
	Args:
		search: Tìm kiếm theo tên hoặc email
		page: Số trang
		page_size: Số records mỗi trang
		filter_type: Lọc theo loại - "all", "with_subs", "without_subs", hoặc device name cụ thể
	"""
	try:
		page = int(page)
		page_size = int(page_size)
		offset = (page - 1) * page_size
		
		# Base query với join để lấy thông tin parent
		base_where = """
			WHERE hr.role = 'Parent'
			AND u.enabled = 1
		"""
		
		# Thêm điều kiện search
		search_condition = ""
		search_params = []
		if search:
			search_condition = """
				AND (u.full_name LIKE %s OR u.name LIKE %s)
			"""
			search_like = f"%{search}%"
			search_params = [search_like, search_like]
		
		# Thêm điều kiện filter
		filter_condition = ""
		filter_join = "LEFT"
		filter_params = []
		
		if filter_type == "with_subs":
			# Chỉ lấy parents có subscription
			filter_condition = " AND ps.name IS NOT NULL"
			filter_join = "INNER"
		elif filter_type == "without_subs":
			# Chỉ lấy parents không có subscription
			filter_condition = " AND ps.name IS NULL"
		elif filter_type and filter_type not in ["all", ""]:
			# Filter theo device name cụ thể
			filter_condition = " AND ps.device_name = %s"
			filter_params = [filter_type]
			filter_join = "INNER"
		
		# Query lấy danh sách parents - sử dụng subquery để đếm chính xác
		# Đầu tiên lấy danh sách user IDs thỏa mãn điều kiện
		user_ids_sql = f"""
			SELECT DISTINCT u.name
			FROM `tabUser` u
			INNER JOIN `tabHas Role` hr ON hr.parent = u.name
			{filter_join} JOIN `tabPush Subscription` ps ON ps.user = u.name
			{base_where}
			{search_condition}
			{filter_condition}
			ORDER BY u.full_name ASC
			LIMIT %s OFFSET %s
		"""
		
		user_ids_result = frappe.db.sql(
			user_ids_sql, 
			search_params + filter_params + [page_size, offset], 
			as_dict=True
		)
		user_ids = [r['name'] for r in user_ids_result]
		
		# Đếm tổng số để phân trang
		count_sql = f"""
			SELECT COUNT(DISTINCT u.name)
			FROM `tabUser` u
			INNER JOIN `tabHas Role` hr ON hr.parent = u.name
			{filter_join} JOIN `tabPush Subscription` ps ON ps.user = u.name
			{base_where}
			{search_condition}
			{filter_condition}
		"""
		total_count = frappe.db.sql(count_sql, search_params + filter_params)[0][0] or 0
		
		# Lấy chi tiết subscriptions của các users
		parents_list = []
		if user_ids:
			# Lấy thông tin user
			users_data = frappe.db.sql("""
				SELECT name as email, full_name, enabled
				FROM `tabUser`
				WHERE name IN %s
				ORDER BY full_name ASC
			""", (user_ids,), as_dict=True)
			
			# Lấy tất cả subscriptions của các users này
			subs_data = frappe.db.sql("""
				SELECT user, name as subscription_name, device_name, created_at, last_used
				FROM `tabPush Subscription`
				WHERE user IN %s
				ORDER BY created_at DESC
			""", (user_ids,), as_dict=True)
			
			# Group subscriptions theo user
			subs_by_user = {}
			for sub in subs_data:
				if sub['user'] not in subs_by_user:
					subs_by_user[sub['user']] = []
				subs_by_user[sub['user']].append({
					'name': sub['subscription_name'],
					'device_name': sub['device_name'] or 'Unknown',
					'created_at': str(sub['created_at']) if sub['created_at'] else None,
					'last_used': str(sub['last_used']) if sub['last_used'] else None
				})
			
			# Build parents list
			for user in users_data:
				parents_list.append({
					'email': user['email'],
					'full_name': user['full_name'],
					'enabled': user['enabled'],
					'subscriptions': subs_by_user.get(user['email'], [])
				})
		
		# Thống kê tổng quan (không áp dụng filter để luôn hiển thị stats đầy đủ)
		stats_sql = """
			SELECT 
				COUNT(DISTINCT u.name) as total_parents,
				COUNT(DISTINCT CASE WHEN ps.name IS NOT NULL THEN u.name END) as parents_with_subs,
				COUNT(ps.name) as total_subscriptions
			FROM `tabUser` u
			INNER JOIN `tabHas Role` hr ON hr.parent = u.name
			LEFT JOIN `tabPush Subscription` ps ON ps.user = u.name
			WHERE hr.role = 'Parent'
			AND u.enabled = 1
		"""
		stats = frappe.db.sql(stats_sql, as_dict=True)[0]
		
		# Thống kê theo device
		device_stats_sql = """
			SELECT 
				ps.device_name,
				COUNT(*) as count
			FROM `tabPush Subscription` ps
			INNER JOIN `tabUser` u ON u.name = ps.user
			INNER JOIN `tabHas Role` hr ON hr.parent = u.name
			WHERE hr.role = 'Parent'
			AND u.enabled = 1
			GROUP BY ps.device_name
			ORDER BY count DESC
		"""
		device_stats = frappe.db.sql(device_stats_sql, as_dict=True)
		
		return {
			"success": True,
			"data": {
				"parents": parents_list,
				"total_count": total_count,
				"page": page,
				"page_size": page_size,
				"total_pages": (total_count + page_size - 1) // page_size if total_count > 0 else 1,
				"stats": {
					"total_parents": stats['total_parents'],
					"parents_with_subs": stats['parents_with_subs'],
					"parents_without_subs": stats['total_parents'] - stats['parents_with_subs'],
					"total_subscriptions": stats['total_subscriptions'],
					"activation_rate": round(stats['parents_with_subs'] / stats['total_parents'] * 100, 1) if stats['total_parents'] > 0 else 0
				},
				"device_stats": device_stats,
				"current_filter": filter_type
			}
		}
		
	except Exception as e:
		import traceback
		frappe.log_error(f"Error getting push subscriptions: {str(e)}\n{traceback.format_exc()}", "Dashboard API Error")
		return {
			"success": False,
			"message": str(e)
		}


@frappe.whitelist()
def debug_analytics():
	"""
	Debug API để kiểm tra trạng thái data trong database.
	"""
	try:
		today_date = today()
		date_7d_ago = add_days(today_date, -7)
		
		# Kiểm tra bảng Portal Guardian Activity
		total_activities = frappe.db.count("Portal Guardian Activity")
		
		# Lấy activities hôm nay
		today_activities = frappe.db.sql("""
			SELECT * FROM `tabPortal Guardian Activity`
			WHERE activity_date = %s
		""", (today_date,), as_dict=True)
		
		# Lấy activities trong 7 ngày
		week_activities = frappe.db.sql("""
			SELECT activity_date, COUNT(*) as count, COUNT(DISTINCT guardian) as unique_guardians
			FROM `tabPortal Guardian Activity`
			WHERE activity_date >= %s
			GROUP BY activity_date
			ORDER BY activity_date DESC
		""", (date_7d_ago,), as_dict=True)
		
		# Kiểm tra CRM Guardian với portal_activated
		activated_count = frappe.db.count("CRM Guardian", {"portal_activated": 1})
		
		# Sample activated guardians
		sample_guardians = frappe.db.sql("""
			SELECT name, guardian_id, guardian_name, first_login_at, last_login_at, portal_activated
			FROM `tabCRM Guardian`
			WHERE portal_activated = 1
			LIMIT 5
		""", as_dict=True)
		
		return {
			"success": True,
			"debug": {
				"today_date": today_date,
				"total_activity_records": total_activities,
				"today_activities": today_activities,
				"week_activities_by_day": week_activities,
				"activated_guardians_count": activated_count,
				"sample_activated_guardians": sample_guardians
			}
		}
		
	except Exception as e:
		import traceback
		return {
			"success": False,
			"error": str(e),
			"traceback": traceback.format_exc()
		}


@frappe.whitelist()
def get_student_activation_stats():
	"""
	Thống kê học sinh theo parent activation.
	
	Học sinh "có parent login" là học sinh có ít nhất 1 guardian với portal_activated = 1.
	
	Returns:
		- total_students: Tổng số học sinh đang học (có trong SIS Class Student)
		- students_with_parent_login: HS có ít nhất 1 parent đã login
		- students_without_parent_login: HS chưa có parent nào login
		- activation_rate: Tỷ lệ %
		- by_class: Thống kê chi tiết theo từng lớp
	"""
	try:
		# Lấy school year hiện tại (is_enable = 1, mới nhất theo start_date)
		current_school_year = frappe.db.get_value(
			"SIS School Year", 
			{"is_enable": 1}, 
			"name",
			order_by="start_date DESC"
		)
		
		if not current_school_year:
			# Fallback: lấy school year mới nhất
			current_school_year = frappe.db.get_value(
				"SIS School Year",
				{},
				"name",
				order_by="start_date DESC"
			)
		
		# Query lấy tất cả học sinh đang học và check xem có guardian nào activated không
		# Sử dụng subquery để check MAX(portal_activated) cho mỗi student
		students_data = frappe.db.sql("""
			SELECT 
				cs.class_id,
				c.title as class_name,
				cs.student_id,
				s.student_name,
				COALESCE(MAX(g.portal_activated), 0) as has_parent_login
			FROM `tabSIS Class Student` cs
			INNER JOIN `tabSIS Class` c ON c.name = cs.class_id
			INNER JOIN `tabCRM Student` s ON s.name = cs.student_id
			LEFT JOIN `tabCRM Family Relationship` fr ON fr.student = s.name
			LEFT JOIN `tabCRM Guardian` g ON g.name = fr.parent
			WHERE cs.school_year_id = %s
			AND (c.class_type = 'regular' OR c.class_type IS NULL OR c.class_type = '')
			GROUP BY cs.class_id, c.title, cs.student_id, s.student_name
			ORDER BY c.title ASC, s.student_name ASC
		""", (current_school_year,), as_dict=True)
		
		# Tính toán thống kê tổng
		total_students = len(students_data)
		students_with_parent = sum(1 for s in students_data if s.has_parent_login == 1)
		students_without_parent = total_students - students_with_parent
		activation_rate = round((students_with_parent / total_students * 100), 1) if total_students > 0 else 0
		
		# Group theo lớp
		class_stats = {}
		for student in students_data:
			class_id = student.class_id
			if class_id not in class_stats:
				class_stats[class_id] = {
					'class_id': class_id,
					'class_name': student.class_name,
					'total_students': 0,
					'with_parent_login': 0,
					'without_parent_login': 0
				}
			
			class_stats[class_id]['total_students'] += 1
			if student.has_parent_login == 1:
				class_stats[class_id]['with_parent_login'] += 1
			else:
				class_stats[class_id]['without_parent_login'] += 1
		
		# Tính tỷ lệ cho mỗi lớp và convert sang list
		by_class = []
		for class_id, stats in class_stats.items():
			stats['activation_rate'] = round(
				(stats['with_parent_login'] / stats['total_students'] * 100), 1
			) if stats['total_students'] > 0 else 0
			by_class.append(stats)
		
		# Sort theo tên lớp
		by_class.sort(key=lambda x: x['class_name'])
		
		return {
			"success": True,
			"data": {
				"total_students": total_students,
				"students_with_parent_login": students_with_parent,
				"students_without_parent_login": students_without_parent,
				"activation_rate": activation_rate,
				"by_class": by_class
			}
		}
		
	except Exception as e:
		import traceback
		frappe.log_error(f"Error getting student activation stats: {str(e)}\n{traceback.format_exc()}", "Dashboard API Error")
		return {
			"success": False,
			"message": str(e)
		}
