"""
Debug script for Parent Portal Analytics
Run in bench console:
>>> from erp.api.analytics.debug_analytics import *
>>> debug_logs()
>>> debug_aggregation()
"""

import frappe
import os
import json
from datetime import datetime, timedelta


def debug_logs():
	"""Check if logging.log exists and has data"""
	print("\n" + "="*60)
	print("🔍 DEBUG: Checking Logging File")
	print("="*60)
	
	site_path = frappe.get_site_path()
	log_file = os.path.join(site_path, 'logs', 'logging.log')
	
	print(f"📁 Site path: {site_path}")
	print(f"📄 Log file: {log_file}")
	
	if not os.path.exists(log_file):
		print("❌ Log file does NOT exist!")
		print("\n💡 Solution: Trigger some OTP logins or API calls first")
		return False
	
	print("✅ Log file exists")
	
	# Get file size
	file_size = os.path.getsize(log_file)
	print(f"📊 File size: {file_size:,} bytes ({file_size/1024:.2f} KB)")
	
	if file_size == 0:
		print("⚠️ Log file is EMPTY!")
		print("\n💡 Solution: Trigger some OTP logins or API calls first")
		return False
	
	# Count lines
	with open(log_file, 'r', encoding='utf-8') as f:
		lines = f.readlines()
		total_lines = len(lines)
	
	print(f"📝 Total lines: {total_lines:,}")
	
	# Show last 5 lines
	print("\n📋 Last 5 log entries:")
	print("-" * 60)
	for line in lines[-5:]:
		try:
			log_entry = json.loads(line.strip())
			timestamp = log_entry.get('timestamp', 'N/A')
			user = log_entry.get('user', 'N/A')
			action = log_entry.get('action', 'N/A')
			print(f"[{timestamp}] {user} - {action}")
		except:
			print(line.strip()[:100])
	print("-" * 60)
	
	# Count Parent Portal activities
	parent_portal_count = 0
	otp_login_count = 0
	parent_portal_users = set()
	
	print("\n🔍 Analyzing logs...")
	for line in lines:
		try:
			log_entry = json.loads(line.strip())
			user = log_entry.get('user', '')
			action = log_entry.get('action', '')
			resource = log_entry.get('resource', '')
			
			if '@parent.wellspring.edu.vn' in user:
				parent_portal_users.add(user)
				
				if action == 'otp_login':
					otp_login_count += 1
				
				if 'parent_portal' in resource.lower():
					parent_portal_count += 1
		except:
			continue
	
	print(f"\n📊 Analysis Results:")
	print(f"   Total Parent Portal users: {len(parent_portal_users)}")
	print(f"   OTP logins: {otp_login_count}")
	print(f"   Parent Portal API calls: {parent_portal_count}")
	
	if len(parent_portal_users) == 0:
		print("\n⚠️ NO Parent Portal activity found!")
		print("💡 Solution: Test by:")
		print("   1. Login via OTP in Parent Portal")
		print("   2. Make some API calls (browse menus, timetable, etc)")
		print("   3. Run this debug again")
		return False
	
	print("\n✅ Logs look good!")
	return True


def debug_aggregation():
	"""Test aggregation logic"""
	print("\n" + "="*60)
	print("🔍 DEBUG: Testing Aggregation")
	print("="*60)
	
	from erp.api.analytics.portal_analytics import count_active_guardians_from_logs
	
	print("\n⏳ Running count_active_guardians_from_logs()...")
	result = count_active_guardians_from_logs()
	
	print(f"\n📊 Results:")
	print(f"   Activated Users (ever logged in): {result.get('activated_users', 0)}")
	print(f"   DAU (API calls today): {result.get('dau', 0)}")
	print(f"   New Users Today: {result.get('new_users_today', 0)}")
	print(f"   WAU (7 days): {result.get('wau', 0)}")
	print(f"   MAU (30 days): {result.get('mau', 0)}")
	
	if result.get('activated_users', 0) == 0:
		print("\n❌ No activated users found!")
		print("💡 This means no OTP logins in logs")
	
	if result.get('dau', 0) == 0:
		print("\n⚠️ DAU = 0")
		print("💡 This means no Parent Portal API calls TODAY")
	
	return result


def test_full_aggregation():
	"""Run full aggregation"""
	print("\n" + "="*60)
	print("🔍 DEBUG: Running Full Aggregation")
	print("="*60)
	
	from erp.api.analytics.portal_analytics import aggregate_portal_analytics
	
	print("\n⏳ Running aggregate_portal_analytics()...")
	result = aggregate_portal_analytics()
	
	print(f"\n📊 Result:")
	print(json.dumps(result, indent=2, ensure_ascii=False))
	
	if result.get('success'):
		print("\n✅ Aggregation successful!")
		
		# Show the saved data
		from frappe.utils import today
		doc = frappe.get_doc("SIS Portal Analytics", today())
		
		print(f"\n📄 Saved Analytics for {today()}:")
		print(f"   Total Guardians: {doc.total_guardians}")
		print(f"   DAU: {doc.active_guardians_today}")
		print(f"   WAU: {doc.active_guardians_7d}")
		print(f"   MAU: {doc.active_guardians_30d}")
		print(f"   New Users: {doc.new_guardians}")
	else:
		print(f"\n❌ Aggregation failed: {result.get('error', 'Unknown error')}")
	
	return result


def check_guardians():
	"""Check Guardian table"""
	print("\n" + "="*60)
	print("🔍 DEBUG: Checking Guardians")
	print("="*60)
	
	total = frappe.db.count("CRM Guardian", {"guardian_id": ["!=", ""]})
	print(f"📊 Total CRM Guardians with guardian_id: {total}")
	
	if total == 0:
		print("⚠️ No guardians in system!")
		return
	
	# Show sample guardians
	guardians = frappe.get_all(
		"CRM Guardian",
		filters={"guardian_id": ["!=", ""]},
		fields=["name", "guardian_name", "guardian_id", "phone_number"],
		limit=5
	)
	
	print(f"\n📋 Sample Guardians:")
	for g in guardians:
		user_email = f"{g.guardian_id}@parent.wellspring.edu.vn"
		print(f"   {g.guardian_name} ({g.guardian_id}) -> {user_email}")


def quick_debug():
	"""Run all debug checks"""
	print("\n" + "🔧"*30)
	print("PARENT PORTAL ANALYTICS - QUICK DEBUG")
	print("🔧"*30)
	
	# 1. Check logs
	logs_ok = debug_logs()
	
	# 2. Check guardians
	check_guardians()
	
	# 3. Test aggregation
	if logs_ok:
		debug_aggregation()
	
	print("\n" + "✅"*30)
	print("DEBUG COMPLETE")
	print("✅"*30 + "\n")


if __name__ == "__main__":
	quick_debug()






