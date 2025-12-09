# -*- coding: utf-8 -*-
# Copyright (c) 2025, Linh Nguyen and contributors
# For license information, please see license.txt

"""
Parent Portal Analytics Aggregation
Scheduled job to collect and aggregate analytics data daily
"""

from __future__ import unicode_literals
import frappe
from frappe.utils import today, add_days, now_datetime, get_datetime
import json
from datetime import datetime, timedelta
import os
import re


def aggregate_portal_analytics():
	"""
	Main scheduled job to aggregate portal analytics
	Runs daily to collect statistics about Parent Portal usage
	"""
	try:
		date = today()
		frappe.errprint(f"🔵 [Analytics] Starting portal analytics aggregation for {date}")
		
		# Check if analytics already exists for today
		existing = frappe.db.exists("SIS Portal Analytics", date)
		if existing:
			doc = frappe.get_doc("SIS Portal Analytics", date)
			frappe.errprint(f"🔵 [Analytics] Updating existing analytics for {date}")
		else:
			doc = frappe.new_doc("SIS Portal Analytics")
			doc.date = date
			frappe.errprint(f"🔵 [Analytics] Creating new analytics for {date}")
		
		# 1. Count total guardians in system
		doc.total_guardians = frappe.db.count("CRM Guardian", {
			"guardian_id": ["!=", ""]
		})
		
		# 2. Get comprehensive activity metrics from logs
		try:
			active_stats = count_active_guardians_from_logs()
			
			# New meaningful metrics:
			doc.active_guardians_today = active_stats.get('dau', 0)  # Daily Active Users (API calls)
			doc.active_guardians_7d = active_stats.get('wau', 0)     # Weekly Active Users
			doc.active_guardians_30d = active_stats.get('mau', 0)    # Monthly Active Users
			doc.new_guardians = active_stats.get('new_users_today', 0)  # First-time logins today
			
			# Store additional metrics in details (can add to doctype later)
			activated_users = active_stats.get('activated_users', 0)
			activation_rate = round((activated_users / doc.total_guardians * 100), 1) if doc.total_guardians > 0 else 0
			engagement_rate = round((active_stats.get('dau', 0) / active_stats.get('mau', 1) * 100), 1) if active_stats.get('mau', 0) > 0 else 0
			
			frappe.errprint(f"📊 [Analytics] Activated: {activated_users}/{doc.total_guardians} ({activation_rate}%), Engagement: {engagement_rate}%")
			
		except Exception as e:
			frappe.errprint(f"❌ [Analytics] Error counting active guardians: {str(e)}")
			doc.active_guardians_today = 0
			doc.active_guardians_7d = 0
			doc.active_guardians_30d = 0
			doc.new_guardians = 0
		
		# 4. Aggregate API calls by module
		try:
			module_usage = aggregate_module_usage_from_logs()
			doc.api_calls_by_module = json.dumps(module_usage, ensure_ascii=False)
		except Exception as e:
			frappe.errprint(f"❌ [Analytics] Error aggregating module usage: {str(e)}")
			doc.api_calls_by_module = json.dumps({})
		
		# Save document
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		
		frappe.errprint(f"✅ [Analytics] Successfully aggregated portal analytics for {date}")
		return {
			"success": True,
			"date": date,
			"total_guardians": doc.total_guardians,
			"active_today": doc.active_guardians_today
		}
		
	except Exception as e:
		frappe.log_error(f"Failed to aggregate portal analytics: {str(e)}", "Portal Analytics Error")
		frappe.errprint(f"❌ [Analytics] Fatal error: {str(e)}")
		import traceback
		frappe.errprint(traceback.format_exc())
		return {"success": False, "error": str(e)}


def get_all_log_files(base_log_file):
	"""
	Get all log files including rotated ones.
	Returns list of log files sorted by number (newest first).
	E.g., logging.log, logging.log.1, logging.log.2, ...
	"""
	log_files = []
	log_dir = os.path.dirname(base_log_file)
	base_name = os.path.basename(base_log_file)
	
	if not os.path.exists(log_dir):
		return []
	
	# Get all matching log files
	for filename in os.listdir(log_dir):
		if filename == base_name or filename.startswith(base_name + '.'):
			full_path = os.path.join(log_dir, filename)
			if os.path.isfile(full_path):
				log_files.append(full_path)
	
	# Sort: base file first, then by rotation number
	def sort_key(path):
		filename = os.path.basename(path)
		if filename == base_name:
			return -1  # Main file first
		try:
			# Extract rotation number (e.g., logging.log.1 -> 1)
			num = int(filename.split('.')[-1])
			return num
		except ValueError:
			return 999
	
	log_files.sort(key=sort_key)
	return log_files


def count_active_guardians_from_logs():
	"""
	Count guardian activity metrics from logging.log AND all rotated log files.
	Returns comprehensive analytics:
	- activated_users: Total users who ever logged in (OTP)
	- dau: Daily Active Users (OTP login OR app session OR API calls today)
	- new_users_today: First-time logins today
	- wau: Weekly Active Users (any activity in 7 days)
	- mau: Monthly Active Users (any activity in 30 days)
	
	Activity includes: OTP login, app session, or any Parent Portal API call
	
	NOTE: Reads from ALL rotated log files (logging.log, logging.log.1, etc.)
	to prevent data loss when logs are rotated.
	"""
	try:
		# Get site path
		site_path = frappe.get_site_path()
		base_log_file = os.path.join(site_path, 'logs', 'logging.log')
		
		# Get all log files including rotated ones
		log_files = get_all_log_files(base_log_file)
		
		if not log_files:
			frappe.errprint(f"⚠️ [Analytics] No log files found in: {os.path.dirname(base_log_file)}")
			return {
				'activated_users': 0,
				'dau': 0,
				'new_users_today': 0,
				'wau': 0,
				'mau': 0
			}
		
		frappe.errprint(f"📂 [Analytics] Found {len(log_files)} log files to process")
		
		# Date ranges
		today_date = datetime.now().date()
		date_7d_ago = today_date - timedelta(days=7)
		date_30d_ago = today_date - timedelta(days=30)
		
		# Sets to track different metrics
		all_logged_in_users = set()  # Ever logged in (OTP)
		users_with_first_login_today = set()  # First login today
		dau_users = set()  # Active today (OTP login OR app session OR API calls)
		wau_users = set()  # Active in 7d
		mau_users = set()  # Active in 30d
		
		# Track first login date per user
		user_first_login = {}  # {user: earliest_login_date}
		
		# Parse ALL log files
		for log_file in log_files:
			try:
				with open(log_file, 'r', encoding='utf-8') as f:
					for line in f:
						try:
							# Parse JSON log line
							log_entry = json.loads(line.strip())
							user = log_entry.get('user', '')
							timestamp_str = log_entry.get('timestamp', '')
							action = log_entry.get('action', '')
							resource = log_entry.get('resource', '')
							
							# Skip if no user or timestamp
							if not user or not timestamp_str:
								continue
							
							# Only count Parent Portal users (format: xxx@parent.wellspring.edu.vn)
							if '@parent.wellspring.edu.vn' not in user:
								continue
							
							# Parse timestamp (format: "06/12/2025 10:30:45")
							try:
								log_date = datetime.strptime(timestamp_str, "%d/%m/%Y %H:%M:%S").date()
							except ValueError:
								continue
							
							# Track OTP logins (for activated users & new users)
							if action == 'otp_login':
								all_logged_in_users.add(user)
								
								# Track first login date
								if user not in user_first_login:
									user_first_login[user] = log_date
								else:
									user_first_login[user] = min(user_first_login[user], log_date)
							
							# Track active users (OTP login OR app session OR Parent Portal API calls)
							# This gives us true DAU/WAU/MAU - anyone who interacted with the app
							is_active_user = (
								action == 'otp_login' or  # Logged in via OTP
								action == 'app_session' or  # Opened/resumed app
								('parent_portal' in resource.lower() and action not in ['otp_login', 'app_session'])  # Made API call
							)
							
							if is_active_user:
								if log_date == today_date:
									dau_users.add(user)
								if log_date >= date_7d_ago:
									wau_users.add(user)
								if log_date >= date_30d_ago:
									mau_users.add(user)
							
						except json.JSONDecodeError:
							continue
						except Exception as e:
							continue
			except Exception as e:
				frappe.errprint(f"⚠️ [Analytics] Error reading log file {log_file}: {str(e)}")
				continue
		
		# Calculate new users today (first login = today)
		for user, first_login_date in user_first_login.items():
			if first_login_date == today_date:
				users_with_first_login_today.add(user)
		
		result = {
			'activated_users': len(all_logged_in_users),
			'dau': len(dau_users),
			'new_users_today': len(users_with_first_login_today),
			'wau': len(wau_users),
			'mau': len(mau_users)
		}
		
		frappe.errprint(f"✅ [Analytics] Metrics - Activated: {result['activated_users']}, DAU: {result['dau']}, New Today: {result['new_users_today']}, WAU: {result['wau']}, MAU: {result['mau']}")
		
		return result
		
	except Exception as e:
		frappe.errprint(f"❌ [Analytics] Error reading logs: {str(e)}")
		return {
			'activated_users': 0,
			'dau': 0,
			'new_users_today': 0,
			'wau': 0,
			'mau': 0
		}


def aggregate_module_usage_from_logs():
	"""
	Aggregate API calls by module from logging.log AND all rotated log files.
	Returns dict with module names and call counts
	
	Only tracks MAIN modules matching Parent Portal folder pages:
	- Announcement, Attendance, Bus, Calendar, Communication, Dashboard,
	- Feedback, Leave, Menu, News, ReportCard, Students, Timetable
	
	Excluded: Profile, Landing, Documentation, Notifications, Login
	
	NOTE: Reads from ALL rotated log files (logging.log, logging.log.1, etc.)
	to prevent data loss when logs are rotated.
	"""
	try:
		# Get site path
		site_path = frappe.get_site_path()
		base_log_file = os.path.join(site_path, 'logs', 'logging.log')
		
		# Get all log files including rotated ones
		log_files = get_all_log_files(base_log_file)
		
		if not log_files:
			return {}
		
		# Date range (last 30 days)
		today_date = datetime.now().date()
		date_30d_ago = today_date - timedelta(days=30)
		
		# Module patterns - ONLY modules matching Parent Portal folder pages
		# Excluded: Profile, Landing, Documentation, Notifications, Login
		module_patterns = {
			'Announcements': r'/api/method/erp\.api\.parent_portal\.announcements',
			'Attendance': r'/api/method/erp\.api\.parent_portal\.attendance',
			'Bus': r'/api/method/erp\.api\.parent_portal\.bus',
			'Calendar': r'/api/method/erp\.api\.parent_portal\.calendar',
			'Communication': r'/api/method/erp\.api\.parent_portal\.contact_log',
			'Feedback': r'/api/method/erp\.api\.parent_portal\.feedback',
			'Leave': r'/api/method/erp\.api\.parent_portal\.leave',
			'Menu': r'/api/method/erp\.api\.parent_portal\.daily_menu',
			'News': r'/api/method/erp\.api\.parent_portal\.news',
			'Report Card': r'/api/method/erp\.api\.parent_portal\.report_card',
			'Timetable': r'/api/method/erp\.api\.parent_portal\.timetable',
		}
		
		# Initialize counters
		module_counts = {module: 0 for module in module_patterns.keys()}
		
		# Parse ALL log files
		for log_file in log_files:
			try:
				with open(log_file, 'r', encoding='utf-8') as f:
					for line in f:
						try:
							log_entry = json.loads(line.strip())
							
							# Check timestamp
							timestamp_str = log_entry.get('timestamp', '')
							if timestamp_str:
								try:
									log_date = datetime.strptime(timestamp_str, "%d/%m/%Y %H:%M:%S").date()
									if log_date < date_30d_ago:
										continue
								except ValueError:
									continue
							
							# Check resource (endpoint)
							resource = log_entry.get('resource', '')
							if resource:
								for module, pattern in module_patterns.items():
									if re.search(pattern, resource):
										module_counts[module] += 1
										break
									
						except json.JSONDecodeError:
							continue
						except Exception:
							continue
			except Exception as e:
				frappe.errprint(f"⚠️ [Analytics] Error reading log file {log_file}: {str(e)}")
				continue
		
		return module_counts
		
	except Exception as e:
		frappe.errprint(f"❌ [Analytics] Error aggregating module usage: {str(e)}")
		return {}


@frappe.whitelist()
def get_guardian_login_history(days=30, limit=100):
	"""
	Get list of guardian login and app activity history from logs
	
	Tracks:
	- OTP logins (when guardian logs in with OTP)
	- App sessions (when guardian opens/resumes the app)
	
	Args:
		days: Number of days to look back (default 30)
		limit: Maximum number of records to return (default 100)
		
	Returns:
		dict: List of login records with guardian info and timestamps
	
	NOTE: Reads from ALL rotated log files (logging.log, logging.log.1, etc.)
	to prevent data loss when logs are rotated.
	"""
	try:
		# Get site path
		site_path = frappe.get_site_path()
		base_log_file = os.path.join(site_path, 'logs', 'logging.log')
		
		# Get all log files including rotated ones
		log_files = get_all_log_files(base_log_file)
		
		if not log_files:
			return {
				"success": False,
				"message": "No log files found",
				"data": []
			}
		
		frappe.errprint(f"📂 [Analytics] Reading login history from {len(log_files)} log files")
		
		# Date range
		today_date = datetime.now().date()
		date_cutoff = today_date - timedelta(days=int(days))
		
		# Collect login records
		login_records = []
		
		# Parse ALL log files
		for log_file in log_files:
			try:
				with open(log_file, 'r', encoding='utf-8') as f:
					for line in f:
						try:
							log_entry = json.loads(line.strip())
							
							action = log_entry.get('action', '')
							
							# Process both OTP logins and app sessions
							if action not in ['otp_login', 'app_session']:
								continue
							
							user = log_entry.get('user', '')
							timestamp_str = log_entry.get('timestamp', '')
							details = log_entry.get('details', {})
							
							# Only count Parent Portal users
							if '@parent.wellspring.edu.vn' not in user:
								continue
							
							# Parse timestamp
							try:
								log_datetime = datetime.strptime(timestamp_str, "%d/%m/%Y %H:%M:%S")
								log_date = log_datetime.date()
								
								# Skip if older than cutoff
								if log_date < date_cutoff:
									continue
							except ValueError:
								continue
							
							# Extract guardian info from details or parse from user email
							guardian_id = user.split('@')[0] if '@' in user else user
							
							# Determine activity type for display
							activity_type = "OTP Login" if action == 'otp_login' else "Mở App"
							
							login_records.append({
								"user": user,
								"guardian_id": guardian_id,
								"guardian_name": details.get('fullname', guardian_id),
								"phone_number": details.get('phone_number', ''),
								"ip": log_entry.get('ip', 'unknown'),
								"login_time": timestamp_str,
								"login_datetime": log_datetime.isoformat(),
								"date": log_date.strftime("%Y-%m-%d"),
								"activity_type": activity_type,  # NEW: Show what type of activity
								"action": action  # Raw action for filtering if needed
							})
							
						except json.JSONDecodeError:
							continue
						except Exception:
							continue
			except Exception as e:
				frappe.errprint(f"⚠️ [Analytics] Error reading log file {log_file}: {str(e)}")
				continue
		
		# Sort by login time (most recent first)
		login_records.sort(key=lambda x: x['login_datetime'], reverse=True)
		
		# Limit results
		login_records = login_records[:int(limit)]
		
		# Group by date for summary
		logins_by_date = {}
		for record in login_records:
			date = record['date']
			if date not in logins_by_date:
				logins_by_date[date] = 0
			logins_by_date[date] += 1
		
		# Count unique guardians
		unique_guardians = set(r['guardian_id'] for r in login_records)
		
		return {
			"success": True,
			"data": {
				"logins": login_records,
				"summary": {
					"total_logins": len(login_records),
					"unique_guardians": len(unique_guardians),
					"days_queried": int(days),
					"logins_by_date": logins_by_date
				}
			}
		}
		
	except Exception as e:
		frappe.errprint(f"❌ [Analytics] Error getting login history: {str(e)}")
		import traceback
		frappe.errprint(traceback.format_exc())
		return {
			"success": False,
			"message": str(e),
			"data": []
		}
