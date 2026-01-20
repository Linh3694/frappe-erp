"""
Performance Test Script cho Attendance Buffer System

Script này giúp test performance của hệ thống attendance buffer.
Chạy bằng bench console hoặc bench execute.

Usage:
    bench --site [sitename] execute erp.api.attendance.test_performance.run_load_test --kwargs '{"num_events": 500}'
    bench --site [sitename] execute erp.api.attendance.test_performance.check_buffer_status
    bench --site [sitename] execute erp.api.attendance.test_performance.trigger_batch_process

Author: System
Created: 2026-01-20
"""

import frappe
import json
import time
import random
from datetime import datetime, timedelta

from erp.api.attendance.hikvision import (
    push_to_attendance_buffer,
    get_buffer_length,
    ATTENDANCE_BUFFER_KEY
)
from erp.api.attendance.batch_processor import (
    process_attendance_buffer,
    get_processor_stats
)


def run_load_test(num_events=500, batch_size=50):
    """
    Chạy load test bằng cách tạo nhiều attendance events.
    
    Args:
        num_events: Số lượng events để tạo (default: 500)
        batch_size: Số events mỗi batch push (default: 50)
    
    Returns:
        Dict with test results
    """
    print(f"\n{'='*60}")
    print(f"🧪 ATTENDANCE BUFFER LOAD TEST")
    print(f"{'='*60}")
    print(f"📊 Configuration:")
    print(f"   - Number of events: {num_events}")
    print(f"   - Batch size: {batch_size}")
    print(f"{'='*60}\n")
    
    # Tạo test data - giả lập học sinh tan học
    test_events = []
    base_time = datetime.now()
    
    for i in range(num_events):
        # Tạo employee_code giả (giống format thực tế)
        employee_code = f"TEST{str(i).zfill(5)}"
        
        # Random timestamp trong 5 phút (giả lập tan học đồng loạt)
        timestamp_offset = random.randint(0, 300)  # 0-5 phút
        event_time = base_time - timedelta(seconds=timestamp_offset)
        
        event = {
            "employee_code": employee_code,
            "employee_name": f"Test Student {i}",
            "timestamp": event_time.isoformat(),
            "device_id": f"192.168.1.{random.randint(1, 10)}",
            "device_name": f"Gate {random.randint(1, 5)} - Test",
            "event_type": "faceSnapMatch",
            "similarity": random.randint(85, 99),
            "received_at": datetime.now().isoformat()
        }
        test_events.append(event)
    
    # Phase 1: Push events vào buffer
    print("📥 Phase 1: Pushing events to buffer...")
    start_push = time.time()
    
    push_count = 0
    for i in range(0, num_events, batch_size):
        batch = test_events[i:i+batch_size]
        for event in batch:
            push_to_attendance_buffer(event)
            push_count += 1
        
        # Progress update
        progress = (i + batch_size) / num_events * 100
        print(f"   Progress: {min(progress, 100):.1f}% ({push_count}/{num_events})")
    
    push_duration = time.time() - start_push
    push_rate = num_events / push_duration if push_duration > 0 else 0
    
    print(f"\n✅ Push completed:")
    print(f"   - Duration: {push_duration:.2f}s")
    print(f"   - Rate: {push_rate:.0f} events/second")
    print(f"   - Buffer size: {get_buffer_length()}")
    
    # Phase 2: Process buffer
    print(f"\n📤 Phase 2: Processing buffer...")
    start_process = time.time()
    
    total_processed = 0
    batch_count = 0
    
    while get_buffer_length() > 0:
        result = process_attendance_buffer()
        processed = result.get("records_processed", 0) + result.get("records_updated", 0)
        total_processed += processed
        batch_count += 1
        
        remaining = result.get("remaining_in_buffer", 0)
        print(f"   Batch {batch_count}: processed {processed}, remaining {remaining}")
        
        if processed == 0 and remaining == 0:
            break
    
    process_duration = time.time() - start_process
    process_rate = total_processed / process_duration if process_duration > 0 else 0
    
    print(f"\n✅ Processing completed:")
    print(f"   - Duration: {process_duration:.2f}s")
    print(f"   - Rate: {process_rate:.0f} records/second")
    print(f"   - Total processed: {total_processed}")
    print(f"   - Batches: {batch_count}")
    
    # Summary
    total_duration = push_duration + process_duration
    print(f"\n{'='*60}")
    print(f"📊 TEST SUMMARY")
    print(f"{'='*60}")
    print(f"   Total events: {num_events}")
    print(f"   Total duration: {total_duration:.2f}s")
    print(f"   Average latency: {total_duration / num_events * 1000:.1f}ms per event")
    print(f"   Push rate: {push_rate:.0f} events/s")
    print(f"   Process rate: {process_rate:.0f} records/s")
    print(f"{'='*60}\n")
    
    return {
        "num_events": num_events,
        "push_duration_seconds": round(push_duration, 2),
        "push_rate_per_second": round(push_rate),
        "process_duration_seconds": round(process_duration, 2),
        "process_rate_per_second": round(process_rate),
        "total_duration_seconds": round(total_duration, 2),
        "batches_processed": batch_count,
        "total_records_processed": total_processed
    }


def check_buffer_status():
    """
    Kiểm tra status của attendance buffer.
    """
    print(f"\n{'='*60}")
    print(f"📊 ATTENDANCE BUFFER STATUS")
    print(f"{'='*60}")
    
    stats = get_processor_stats()
    
    if stats.get("status") == "success":
        buffer_stats = stats.get("stats", {})
        print(f"   Buffer key: {buffer_stats.get('buffer_key')}")
        print(f"   Pending events: {buffer_stats.get('pending_events')}")
        print(f"   Batch size: {buffer_stats.get('batch_size')}")
        print(f"   Processing interval: {buffer_stats.get('processing_interval')}")
    else:
        print(f"   Error: {stats.get('message')}")
    
    print(f"   Timestamp: {stats.get('timestamp')}")
    print(f"{'='*60}\n")
    
    return stats


def trigger_batch_process():
    """
    Trigger batch processing thủ công.
    """
    print(f"\n{'='*60}")
    print(f"🚀 TRIGGERING BATCH PROCESS")
    print(f"{'='*60}")
    
    before_length = get_buffer_length()
    print(f"   Buffer before: {before_length} events")
    
    result = process_attendance_buffer()
    
    after_length = get_buffer_length()
    print(f"   Buffer after: {after_length} events")
    print(f"   Processed: {result.get('records_processed', 0)} new")
    print(f"   Updated: {result.get('records_updated', 0)} existing")
    print(f"   Notifications: {result.get('notifications_sent', 0)}")
    print(f"   Errors: {result.get('total_errors', 0)}")
    print(f"   Status: {result.get('status')}")
    print(f"{'='*60}\n")
    
    return result


def cleanup_test_data():
    """
    Xóa dữ liệu test (các records có employee_code bắt đầu bằng 'TEST').
    CHỈ DÙNG TRONG MÔI TRƯỜNG DEVELOPMENT/TESTING.
    """
    print(f"\n{'='*60}")
    print(f"🧹 CLEANING UP TEST DATA")
    print(f"{'='*60}")
    
    # Cảnh báo
    print("⚠️  WARNING: This will delete all attendance records with employee_code starting with 'TEST'")
    
    # Count records
    count = frappe.db.count("ERP Time Attendance", filters={
        "employee_code": ["like", "TEST%"]
    })
    
    print(f"   Found {count} test records")
    
    if count > 0:
        # Delete
        frappe.db.delete("ERP Time Attendance", filters={
            "employee_code": ["like", "TEST%"]
        })
        frappe.db.commit()
        print(f"   ✅ Deleted {count} test records")
    else:
        print(f"   No test records to delete")
    
    print(f"{'='*60}\n")
    
    return {"deleted": count}


def benchmark_single_vs_buffer():
    """
    So sánh performance giữa xử lý single event vs buffer.
    """
    print(f"\n{'='*60}")
    print(f"🏃 BENCHMARK: SINGLE vs BUFFER")
    print(f"{'='*60}")
    
    num_test_events = 100
    
    # Test buffer approach (new)
    print(f"\n📥 Testing BUFFER approach ({num_test_events} events)...")
    
    base_time = datetime.now()
    start_buffer = time.time()
    
    for i in range(num_test_events):
        event = {
            "employee_code": f"BENCH{str(i).zfill(5)}",
            "employee_name": f"Benchmark Student {i}",
            "timestamp": base_time.isoformat(),
            "device_id": "192.168.1.1",
            "device_name": "Gate 1 - Benchmark",
            "event_type": "faceSnapMatch",
            "received_at": datetime.now().isoformat()
        }
        push_to_attendance_buffer(event)
    
    buffer_push_time = time.time() - start_buffer
    
    # Process the buffer
    start_process = time.time()
    while get_buffer_length() > 0:
        process_attendance_buffer()
    buffer_process_time = time.time() - start_process
    
    buffer_total = buffer_push_time + buffer_process_time
    
    print(f"   Push time: {buffer_push_time*1000:.1f}ms")
    print(f"   Process time: {buffer_process_time*1000:.1f}ms")
    print(f"   Total: {buffer_total*1000:.1f}ms")
    print(f"   Per event: {buffer_total/num_test_events*1000:.2f}ms")
    
    # Cleanup
    frappe.db.delete("ERP Time Attendance", filters={
        "employee_code": ["like", "BENCH%"]
    })
    frappe.db.commit()
    
    print(f"\n{'='*60}")
    print(f"📊 RESULTS")
    print(f"{'='*60}")
    print(f"   Buffer approach: {buffer_total*1000:.1f}ms total ({buffer_total/num_test_events*1000:.2f}ms per event)")
    print(f"   API response time (push only): {buffer_push_time/num_test_events*1000:.2f}ms")
    print(f"{'='*60}\n")
    
    return {
        "num_events": num_test_events,
        "buffer_push_ms": round(buffer_push_time * 1000, 1),
        "buffer_process_ms": round(buffer_process_time * 1000, 1),
        "buffer_total_ms": round(buffer_total * 1000, 1),
        "buffer_per_event_ms": round(buffer_total / num_test_events * 1000, 2),
        "api_response_ms": round(buffer_push_time / num_test_events * 1000, 2)
    }
