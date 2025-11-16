# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Cache Management Utilities

Centralized cache clearing functions để đảm bảo consistency và dễ maintain.
Tất cả cache clearing operations nên sử dụng các hàm trong module này.
"""

import frappe


def clear_teacher_dashboard_cache():
	"""
	Clear ALL caches related to teacher dashboard and timetable.
	
	Gọi hàm này sau khi:
	- Tạo/cập nhật/xóa SIS Class
	- Thay đổi homeroom_teacher hoặc vice_homeroom_teacher
	- Tạo/cập nhật/xóa Subject Assignment
	- Import/cập nhật Timetable
	- Tạo/cập nhật/xóa Timetable Override
	- Sync Teacher Timetable
	
	Cache patterns bị xóa:
	- teacher_classes:* (legacy endpoint)
	- teacher_classes_v2:* (optimized endpoint)
	- teacher_week:* (legacy endpoint)
	- teacher_week_v2:* (optimized endpoint)
	- class_week:* (class timetable)
	
	Returns:
		dict: {
			"success": bool,
			"total_deleted": int,
			"details": list[str],  # Chi tiết từng pattern
			"error": str (nếu có lỗi)
		}
	"""
	logs = []
	try:
		cache = frappe.cache()
		logs.append("🗑️ Starting cache clear for teacher dashboard")
		
		cache_patterns = [
			"teacher_classes:*",
			"teacher_classes_v2:*",
			"teacher_week:*",
			"teacher_week_v2:*",
			"class_week:*"
		]
		
		total_deleted = 0
		pattern_results = []
		
		for pattern in cache_patterns:
			try:
				# Get Redis connection from frappe cache
				redis_conn = cache.redis_cache if hasattr(cache, 'redis_cache') else cache
				
				# Use SCAN to find and delete keys matching pattern
				if hasattr(redis_conn, 'scan_iter'):
					keys_to_delete = list(redis_conn.scan_iter(match=pattern, count=100))
					if keys_to_delete:
						deleted_count = redis_conn.delete(*keys_to_delete)
						total_deleted += deleted_count
						msg = f"✅ Deleted {deleted_count} keys matching '{pattern}'"
						logs.append(msg)
						pattern_results.append({"pattern": pattern, "deleted": deleted_count})
					else:
						msg = f"ℹ️ No keys found for pattern '{pattern}'"
						logs.append(msg)
						pattern_results.append({"pattern": pattern, "deleted": 0})
				else:
					# Fallback: Try direct delete (may not work with wildcard)
					try:
						cache.delete_key(pattern)
						total_deleted += 1
						msg = f"✅ Deleted key '{pattern}' (fallback method)"
						logs.append(msg)
						pattern_results.append({"pattern": pattern, "deleted": 1, "method": "fallback"})
					except Exception as fallback_error:
						msg = f"⚠️ Fallback delete failed for '{pattern}': {str(fallback_error)}"
						logs.append(msg)
						pattern_results.append({"pattern": pattern, "deleted": 0, "error": str(fallback_error)})
						
			except Exception as pattern_error:
				msg = f"⚠️ Failed to clear pattern '{pattern}': {str(pattern_error)}"
				logs.append(msg)
				pattern_results.append({"pattern": pattern, "error": str(pattern_error)})
		
		if total_deleted > 0:
			summary = f"✅ Successfully cleared {total_deleted} cache keys for teacher dashboard"
		else:
			summary = "ℹ️ No cache keys found to clear (might be empty or already cleared)"
		
		logs.append(summary)
		
		# Also log to frappe logger for server-side debugging
		frappe.logger().info(f"Cache Clear: {summary}")
		
		return {
			"success": True,
			"total_deleted": total_deleted,
			"details": logs,
			"patterns": pattern_results,
			"summary": summary
		}
		
	except Exception as e:
		error_msg = f"❌ Failed to clear teacher dashboard cache: {str(e)}"
		logs.append(error_msg)
		frappe.logger().error(error_msg)
		
		return {
			"success": False,
			"total_deleted": 0,
			"details": logs,
			"error": str(e)
		}


def clear_class_cache(class_id):
	"""
	Clear cache for a specific class.
	
	Args:
		class_id: SIS Class ID
	"""
	try:
		cache = frappe.cache()
		redis_conn = cache.redis_cache if hasattr(cache, 'redis_cache') else cache
		
		# Clear class-specific cache
		pattern = f"class_week:{class_id}:*"
		
		if hasattr(redis_conn, 'scan_iter'):
			keys_to_delete = list(redis_conn.scan_iter(match=pattern, count=100))
			if keys_to_delete:
				redis_conn.delete(*keys_to_delete)
				frappe.logger().info(f"✅ Cleared cache for class {class_id}: {len(keys_to_delete)} keys")
		
	except Exception as e:
		frappe.logger().warning(f"Failed to clear cache for class {class_id}: {str(e)}")


def clear_teacher_cache(teacher_user_id):
	"""
	Clear cache for a specific teacher.
	
	Args:
		teacher_user_id: User ID of teacher
	"""
	try:
		cache = frappe.cache()
		redis_conn = cache.redis_cache if hasattr(cache, 'redis_cache') else cache
		
		# Clear teacher-specific cache
		patterns = [
			f"teacher_classes:{teacher_user_id}:*",
			f"teacher_classes_v2:{teacher_user_id}:*",
			f"teacher_week:*:{teacher_user_id}:*",
			f"teacher_week_v2:*:{teacher_user_id}:*"
		]
		
		total_deleted = 0
		for pattern in patterns:
			if hasattr(redis_conn, 'scan_iter'):
				keys_to_delete = list(redis_conn.scan_iter(match=pattern, count=100))
				if keys_to_delete:
					redis_conn.delete(*keys_to_delete)
					total_deleted += len(keys_to_delete)
		
		if total_deleted > 0:
			frappe.logger().info(f"✅ Cleared cache for teacher {teacher_user_id}: {total_deleted} keys")
		
	except Exception as e:
		frappe.logger().warning(f"Failed to clear cache for teacher {teacher_user_id}: {str(e)}")


def clear_all_assignment_cache():
	"""
	Clear ALL assignment-related caches.
	Sử dụng sau khi batch operations hoặc mass updates.
	"""
	try:
		# Clear teacher dashboard cache
		result = clear_teacher_dashboard_cache()
		
		# Also clear assignment cache from assignment_cache.py
		try:
			from .assignment_cache import invalidate_all_caches
			invalidate_all_caches()
		except Exception as e:
			frappe.logger().warning(f"Failed to invalidate assignment cache: {str(e)}")
		
		return result
		
	except Exception as e:
		frappe.logger().error(f"Failed to clear all assignment cache: {str(e)}")
		return {"success": False, "error": str(e)}


# Backward compatibility aliases
_clear_teacher_classes_cache = clear_teacher_dashboard_cache
clear_teacher_classes_cache = clear_teacher_dashboard_cache

