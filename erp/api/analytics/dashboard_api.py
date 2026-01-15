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
	Get summary statistics for today compared to yesterday
	Returns: dict with today's stats and comparison with yesterday
	
	Response includes:
	- total_guardians: Tổng số guardians có thể đăng nhập (có phone + có student)
	- eligible_guardians: Số guardians có thể đăng nhập (alias của total_guardians)
	- activated_guardians: Số guardians đã đăng nhập ít nhất 1 lần
	- activation_rate: Tỷ lệ kích hoạt (%)
	- active_guardians_today: DAU
	- active_guardians_7d: WAU
	- active_guardians_30d: MAU
	- new_guardians: Số người login lần đầu hôm nay
	"""
	try:
		today_date = today()
		yesterday_date = add_days(today_date, -1)
		
		# Get today's analytics from SIS Portal Analytics
		today_analytics = frappe.db.get_value(
			"SIS Portal Analytics",
			today_date,
			["total_guardians", "active_guardians_today", "active_guardians_7d", "active_guardians_30d", "new_guardians"],
			as_dict=True
		)
		
		# Get yesterday's analytics for comparison
		yesterday_analytics = frappe.db.get_value(
			"SIS Portal Analytics",
			yesterday_date,
			["total_guardians", "active_guardians_today", "new_guardians"],
			as_dict=True
		)
		
		# If no data exists for today, try to aggregate now
		if not today_analytics:
			from erp.api.analytics.portal_analytics import aggregate_portal_analytics
			aggregate_portal_analytics()
			today_analytics = frappe.db.get_value(
				"SIS Portal Analytics",
				today_date,
				["total_guardians", "active_guardians_today", "active_guardians_7d", "active_guardians_30d", "new_guardians"],
				as_dict=True
			)
		
		# Bổ sung thêm metrics từ database
		from erp.api.analytics.portal_analytics import get_eligible_guardians_count
		
		# Số guardians đã activate (có first_login_at)
		activated_guardians = frappe.db.count("CRM Guardian", {"portal_activated": 1})
		
		# Số guardians eligible (có phone + có student)
		eligible_guardians = get_eligible_guardians_count()
		
		# Tính activation rate
		activation_rate = round((activated_guardians / eligible_guardians * 100), 1) if eligible_guardians > 0 else 0
		
		# Calculate changes
		changes = {}
		if yesterday_analytics:
			if yesterday_analytics.get('active_guardians_today', 0) > 0:
				changes['active_today'] = round(
					((today_analytics.get('active_guardians_today', 0) - yesterday_analytics.get('active_guardians_today', 0)) / 
					 yesterday_analytics.get('active_guardians_today', 1)) * 100, 1
				)
			else:
				changes['active_today'] = 0
			
			if yesterday_analytics.get('total_guardians', 0) > 0:
				changes['total'] = round(
					((today_analytics.get('total_guardians', 0) - yesterday_analytics.get('total_guardians', 0)) / 
					 yesterday_analytics.get('total_guardians', 1)) * 100, 1
				)
			else:
				changes['total'] = 0
		else:
			changes['active_today'] = 0
			changes['total'] = 0
		
		# Merge data
		response_data = today_analytics or {}
		response_data['eligible_guardians'] = eligible_guardians
		response_data['activated_guardians'] = activated_guardians
		response_data['activation_rate'] = activation_rate
		
		return {
			"success": True,
			"data": {
				"today": response_data,
				"changes": changes,
				"date": today_date
			}
		}
		
	except Exception as e:
		frappe.log_error(f"Error getting dashboard summary: {str(e)}", "Dashboard API Error")
		return {
			"success": False,
			"message": str(e)
		}


@frappe.whitelist()
def get_user_trends(period="30d"):
	"""
	Get user activity trends over time
	Args:
		period: "7d" or "30d"
	Returns: list of daily active user counts
	"""
	try:
		# Calculate date range
		days = 7 if period == "7d" else 30
		end_date = today()
		start_date = add_days(end_date, -days)
		
		# Get analytics data for the period
		analytics_list = frappe.get_all(
			"SIS Portal Analytics",
			filters={
				"date": ["between", [start_date, end_date]]
			},
			fields=["date", "active_guardians_today", "total_guardians"],
			order_by="date asc"
		)
		
		# Format data for chart
		trend_data = []
		for item in analytics_list:
			trend_data.append({
				"date": str(item.date),
				"active_users": item.active_guardians_today or 0,
				"total_users": item.total_guardians or 0
			})
		
		return {
			"success": True,
			"data": trend_data,
			"period": period
		}
		
	except Exception as e:
		frappe.log_error(f"Error getting user trends: {str(e)}", "Dashboard API Error")
		return {
			"success": False,
			"message": str(e)
		}


@frappe.whitelist()
def get_module_usage(period="30d"):
	"""
	Get module usage statistics
	Args:
		period: "7d" or "30d"
	Returns: dict with module names and usage counts
	"""
	try:
		# Get latest analytics with module usage
		latest_analytics = frappe.get_last_doc(
			"SIS Portal Analytics",
			filters={},
			order_by="date desc"
		)
		
		if not latest_analytics or not latest_analytics.api_calls_by_module:
			return {
				"success": True,
				"data": {}
			}
		
		# Parse JSON data
		module_usage = json.loads(latest_analytics.api_calls_by_module)
		
		# Sort by usage count
		sorted_modules = sorted(
			module_usage.items(),
			key=lambda x: x[1],
			reverse=True
		)
		
		# Calculate total
		total_calls = sum(count for _, count in sorted_modules)
		
		# Format data with percentages
		formatted_data = []
		for module, count in sorted_modules:
			if count > 0:
				percentage = round((count / total_calls) * 100, 1) if total_calls > 0 else 0
				formatted_data.append({
					"module": module,
					"count": count,
					"percentage": percentage
				})
		
		return {
			"success": True,
			"data": formatted_data,
			"total_calls": total_calls
		}
		
	except Exception as e:
		frappe.log_error(f"Error getting module usage: {str(e)}", "Dashboard API Error")
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
