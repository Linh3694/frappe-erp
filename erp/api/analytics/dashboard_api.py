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
def get_push_subscriptions(search="", page=1, page_size=50):
	"""
	Lấy danh sách Push Subscriptions của tất cả Parent
	
	Args:
		search: Tìm kiếm theo tên hoặc email
		page: Số trang
		page_size: Số records mỗi trang
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
		
		# Đếm tổng số parents có subscriptions
		count_sql = f"""
			SELECT COUNT(DISTINCT u.name)
			FROM `tabUser` u
			INNER JOIN `tabHas Role` hr ON hr.parent = u.name
			LEFT JOIN `tabPush Subscription` ps ON ps.user = u.name
			{base_where}
			{search_condition}
		"""
		total_parents = frappe.db.sql(count_sql, search_params)[0][0] or 0
		
		# Lấy danh sách parents và subscriptions
		data_sql = f"""
			SELECT 
				u.name as email,
				u.full_name,
				u.enabled,
				ps.name as subscription_name,
				ps.device_name,
				ps.created_at,
				ps.last_used,
				ps.endpoint
			FROM `tabUser` u
			INNER JOIN `tabHas Role` hr ON hr.parent = u.name
			LEFT JOIN `tabPush Subscription` ps ON ps.user = u.name
			{base_where}
			{search_condition}
			ORDER BY u.full_name ASC, ps.created_at DESC
			LIMIT %s OFFSET %s
		"""
		
		results = frappe.db.sql(data_sql, search_params + [page_size, offset], as_dict=True)
		
		# Group by parent
		parents_dict = {}
		for row in results:
			email = row['email']
			if email not in parents_dict:
				parents_dict[email] = {
					'email': email,
					'full_name': row['full_name'],
					'enabled': row['enabled'],
					'subscriptions': []
				}
			
			if row['subscription_name']:
				parents_dict[email]['subscriptions'].append({
					'name': row['subscription_name'],
					'device_name': row['device_name'] or 'Unknown',
					'created_at': str(row['created_at']) if row['created_at'] else None,
					'last_used': str(row['last_used']) if row['last_used'] else None
				})
		
		parents_list = list(parents_dict.values())
		
		# Thống kê tổng quan
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
				"total_count": total_parents,
				"page": page,
				"page_size": page_size,
				"total_pages": (total_parents + page_size - 1) // page_size if total_parents > 0 else 1,
				"stats": {
					"total_parents": stats['total_parents'],
					"parents_with_subs": stats['parents_with_subs'],
					"parents_without_subs": stats['total_parents'] - stats['parents_with_subs'],
					"total_subscriptions": stats['total_subscriptions'],
					"activation_rate": round(stats['parents_with_subs'] / stats['total_parents'] * 100, 1) if stats['total_parents'] > 0 else 0
				},
				"device_stats": device_stats
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
