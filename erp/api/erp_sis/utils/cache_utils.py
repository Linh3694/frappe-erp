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
	"""
	try:
		cache = frappe.cache()
		
		cache_patterns = [
			"teacher_classes:*",
			"teacher_classes_v2:*",
			"teacher_week:*",
			"teacher_week_v2:*",
			"class_week:*"
		]
		
		total_deleted = 0
		
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
						frappe.logger().info(
							f"✅ Cache Clear: Deleted {deleted_count} keys matching '{pattern}'"
						)
				else:
					# Fallback: Try direct delete (may not work with wildcard)
					try:
						cache.delete_key(pattern)
						total_deleted += 1
						frappe.logger().info(f"✅ Cache Clear: Deleted key '{pattern}' (fallback method)")
					except:
						pass
						
			except Exception as pattern_error:
				frappe.logger().warning(
					f"⚠️ Cache Clear: Failed to clear pattern '{pattern}': {pattern_error}"
				)
		
		if total_deleted > 0:
			frappe.logger().info(
				f"✅ Cache Clear: Successfully cleared {total_deleted} cache keys for teacher dashboard"
			)
		else:
			frappe.logger().info(
				"ℹ️ Cache Clear: No cache keys found to clear (might be empty or already cleared)"
			)
		
		return {
			"success": True,
			"total_deleted": total_deleted
		}
		
	except Exception as e:
		frappe.logger().error(f"❌ Cache Clear: Failed to clear teacher dashboard cache: {str(e)}")
		return {
			"success": False,
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

