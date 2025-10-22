# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import now_datetime
import json
from datetime import datetime, timedelta


class OfflineQueue:
    """
    Offline queue for mobile app actions
    Handles queuing and syncing of actions when offline
    """

    def __init__(self):
        self.queue_doctype = "Bus Offline Queue"

    def add_action(self, action_data):
        """
        Add an action to the offline queue

        Args:
            action_data (dict): Action data with type, payload, and metadata
        """
        try:
            # Create queue entry
            queue_entry = frappe.get_doc({
                "doctype": "Bus Offline Queue",
                "monitor_id": action_data.get("monitor_id"),
                "action_type": action_data.get("action_type"),
                "action_payload": json.dumps(action_data.get("payload", {})),
                "status": "pending",
                "created_at": now_datetime(),
                "retry_count": 0,
                "max_retries": 3,
                "priority": action_data.get("priority", "normal"),  # high, normal, low
                "trip_id": action_data.get("trip_id"),
                "student_id": action_data.get("student_id")
            })

            queue_entry.insert(ignore_permissions=True)
            frappe.db.commit()

            return {
                "success": True,
                "queue_id": queue_entry.name,
                "message": "Action added to offline queue"
            }

        except Exception as e:
            frappe.log_error(f"Error adding action to queue: {str(e)}")
            return {
                "success": False,
                "message": f"Failed to queue action: {str(e)}"
            }

    def process_queue(self, monitor_id=None, max_actions=10):
        """
        Process pending actions in the queue

        Args:
            monitor_id (str): Optional monitor ID to process specific queue
            max_actions (int): Maximum actions to process in this batch
        """
        try:
            # Get pending actions
            filters = {"status": "pending"}
            if monitor_id:
                filters["monitor_id"] = monitor_id

            # Order by priority and creation time
            pending_actions = frappe.get_all(
                "Bus Offline Queue",
                filters=filters,
                fields=["name", "action_type", "action_payload", "retry_count", "max_retries"],
                order_by="priority desc, creation asc",
                limit_page_length=max_actions
            )

            processed = 0
            successful = 0
            failed = 0

            for action in pending_actions:
                result = self._execute_action(action)
                processed += 1

                if result["success"]:
                    successful += 1
                    # Mark as completed
                    frappe.db.set_value("Bus Offline Queue", action.name, {
                        "status": "completed",
                        "processed_at": now_datetime(),
                        "result": json.dumps(result)
                    })
                else:
                    failed += 1
                    retry_count = action.retry_count + 1

                    if retry_count >= action.max_retries:
                        # Mark as failed
                        frappe.db.set_value("Bus Offline Queue", action.name, {
                            "status": "failed",
                            "processed_at": now_datetime(),
                            "error_message": result.get("message", "Unknown error"),
                            "retry_count": retry_count
                        })
                    else:
                        # Increment retry count
                        frappe.db.set_value("Bus Offline Queue", action.name, {
                            "retry_count": retry_count,
                            "last_retry_at": now_datetime(),
                            "error_message": result.get("message", "Unknown error")
                        })

            frappe.db.commit()

            return {
                "success": True,
                "processed": processed,
                "successful": successful,
                "failed": failed,
                "message": f"Processed {processed} actions: {successful} successful, {failed} failed"
            }

        except Exception as e:
            frappe.log_error(f"Error processing queue: {str(e)}")
            return {
                "success": False,
                "message": f"Queue processing failed: {str(e)}"
            }

    def _execute_action(self, action):
        """
        Execute a single queued action

        Args:
            action (dict): Action data from queue

        Returns:
            dict: Execution result
        """
        try:
            action_type = action["action_type"]
            payload = json.loads(action["action_payload"])

            if action_type == "check_in_student":
                return self._execute_check_in(payload)
            elif action_type == "mark_student_absent":
                return self._execute_mark_absent(payload)
            elif action_type == "start_trip":
                return self._execute_start_trip(payload)
            elif action_type == "complete_trip":
                return self._execute_complete_trip(payload)
            else:
                return {
                    "success": False,
                    "message": f"Unknown action type: {action_type}"
                }

        except Exception as e:
            return {
                "success": False,
                "message": f"Action execution failed: {str(e)}"
            }

    def _execute_check_in(self, payload):
        """Execute check-in action"""
        from .face_recognition import check_student_in_trip

        # Simulate the check_student_in_trip call
        try:
            result = check_student_in_trip(
                student_id=payload["student_id"],
                trip_id=payload["trip_id"],
                method=payload.get("method", "manual")
            )
            return result
        except Exception as e:
            return {"success": False, "message": str(e)}

    def _execute_mark_absent(self, payload):
        """Execute mark absent action"""
        from .face_recognition import mark_student_absent

        try:
            result = mark_student_absent(
                student_id=payload["student_id"],
                trip_id=payload["trip_id"],
                reason=payload.get("reason", "Other")
            )
            return result
        except Exception as e:
            return {"success": False, "message": str(e)}

    def _execute_start_trip(self, payload):
        """Execute start trip action"""
        from .daily_trip import start_daily_trip

        try:
            result = start_daily_trip(payload["trip_id"])
            return result
        except Exception as e:
            return {"success": False, "message": str(e)}

    def _execute_complete_trip(self, payload):
        """Execute complete trip action"""
        from .daily_trip import complete_daily_trip

        try:
            result = complete_daily_trip(
                trip_id=payload["trip_id"],
                force=payload.get("force", False)
            )
            return result
        except Exception as e:
            return {"success": False, "message": str(e)}

    def get_queue_status(self, monitor_id=None):
        """
        Get queue status for monitoring

        Args:
            monitor_id (str): Optional monitor ID filter

        Returns:
            dict: Queue statistics
        """
        try:
            filters = {}
            if monitor_id:
                filters["monitor_id"] = monitor_id

            # Count by status
            status_counts = frappe.db.get_all(
                "Bus Offline Queue",
                filters=filters,
                fields=["status", "count(*) as count"],
                group_by="status"
            )

            stats = {row["status"]: row["count"] for row in status_counts}

            # Get recent failed actions
            failed_actions = frappe.get_all(
                "Bus Offline Queue",
                filters={**filters, "status": "failed"},
                fields=["name", "action_type", "error_message", "created_at", "retry_count"],
                order_by="modified desc",
                limit_page_length=5
            )

            return {
                "success": True,
                "stats": stats,
                "failed_actions": failed_actions,
                "total_pending": stats.get("pending", 0),
                "total_failed": stats.get("failed", 0)
            }

        except Exception as e:
            return {
                "success": False,
                "message": f"Failed to get queue status: {str(e)}"
            }

    def cleanup_old_entries(self, days_old=30):
        """
        Clean up old completed and failed entries

        Args:
            days_old (int): Remove entries older than this many days
        """
        try:
            cutoff_date = datetime.now() - timedelta(days=days_old)

            # Delete old completed entries
            frappe.db.delete(
                "Bus Offline Queue",
                filters={
                    "status": ["in", ["completed", "failed"]],
                    "creation": ["<", cutoff_date]
                }
            )

            frappe.db.commit()

            return {
                "success": True,
                "message": f"Cleaned up entries older than {days_old} days"
            }

        except Exception as e:
            return {
                "success": False,
                "message": f"Cleanup failed: {str(e)}"
            }


# Global offline queue instance
offline_queue = OfflineQueue()


@frappe.whitelist()
def add_offline_action():
    """
    API endpoint to add action to offline queue
    Expected parameters (JSON):
    - monitor_id: Monitor ID
    - action_type: Type of action (check_in_student, mark_student_absent, etc.)
    - payload: Action payload data
    - priority: Action priority (optional)
    """
    try:
        user_email = frappe.session.user

        if not user_email or user_email == 'Guest':
            return {
                "success": False,
                "message": "Authentication required"
            }

        # Get request data
        data = {}

        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
            except (json.JSONDecodeError, TypeError):
                data = frappe.local.form_dict
        else:
            data = frappe.local.form_dict

        # Extract monitor_id from email
        if "@busmonitor.wellspring.edu.vn" not in user_email:
            return {
                "success": False,
                "message": "Invalid user account format"
            }

        monitor_code = user_email.split("@")[0]
        monitors = frappe.get_all(
            "SIS Bus Monitor",
            filters={"monitor_code": monitor_code, "status": "Active"},
            fields=["name"]
        )

        if not monitors:
            return {
                "success": False,
                "message": "Bus monitor not found"
            }

        # Prepare action data
        action_data = {
            "monitor_id": monitors[0].name,
            "action_type": data.get("action_type"),
            "payload": data.get("payload", {}),
            "priority": data.get("priority", "normal"),
            "trip_id": data.get("trip_id"),
            "student_id": data.get("student_id")
        }

        result = offline_queue.add_action(action_data)
        return result

    except Exception as e:
        frappe.log_error(f"Error adding offline action: {str(e)}")
        return {
            "success": False,
            "message": f"Failed to add offline action: {str(e)}"
        }


@frappe.whitelist()
def sync_offline_actions():
    """
    API endpoint to sync/process offline actions
    Expected parameters (JSON):
    - max_actions: Maximum actions to process (optional, default: 10)
    """
    try:
        user_email = frappe.session.user

        if not user_email or user_email == 'Guest':
            return {
                "success": False,
                "message": "Authentication required"
            }

        # Get request data
        data = {}

        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
            except (json.JSONDecodeError, TypeError):
                data = frappe.local.form_dict
        else:
            data = frappe.local.form_dict

        # Extract monitor_id from email
        if "@busmonitor.wellspring.edu.vn" not in user_email:
            return {
                "success": False,
                "message": "Invalid user account format"
            }

        monitor_code = user_email.split("@")[0]
        monitors = frappe.get_all(
            "SIS Bus Monitor",
            filters={"monitor_code": monitor_code, "status": "Active"},
            fields=["name"]
        )

        if not monitors:
            return {
                "success": False,
                "message": "Bus monitor not found"
            }

        max_actions = data.get("max_actions", 10)

        result = offline_queue.process_queue(
            monitor_id=monitors[0].name,
            max_actions=max_actions
        )

        return result

    except Exception as e:
        frappe.log_error(f"Error syncing offline actions: {str(e)}")
        return {
            "success": False,
            "message": f"Failed to sync offline actions: {str(e)}"
        }


@frappe.whitelist()
def get_offline_queue_status():
    """
    API endpoint to get offline queue status
    """
    try:
        user_email = frappe.session.user

        if not user_email or user_email == 'Guest':
            return {
                "success": False,
                "message": "Authentication required"
            }

        # Extract monitor_id from email
        if "@busmonitor.wellspring.edu.vn" not in user_email:
            return {
                "success": False,
                "message": "Invalid user account format"
            }

        monitor_code = user_email.split("@")[0]
        monitors = frappe.get_all(
            "SIS Bus Monitor",
            filters={"monitor_code": monitor_code, "status": "Active"},
            fields=["name"]
        )

        if not monitors:
            return {
                "success": False,
                "message": "Bus monitor not found"
            }

        result = offline_queue.get_queue_status(monitor_id=monitors[0].name)
        return result

    except Exception as e:
        return {
            "success": False,
            "message": f"Failed to get queue status: {str(e)}"
        }


@frappe.whitelist()
def cleanup_offline_queue():
    """
    API endpoint to cleanup old offline queue entries
    Requires admin privileges
    """
    try:
        # Check if user has admin role
        user_roles = frappe.get_roles(frappe.session.user)
        if "Administrator" not in user_roles and "System Manager" not in user_roles:
            return {
                "success": False,
                "message": "Admin privileges required"
            }

        result = offline_queue.cleanup_old_entries(days_old=30)
        return result

    except Exception as e:
        return {
            "success": False,
            "message": f"Cleanup failed: {str(e)}"
        }
