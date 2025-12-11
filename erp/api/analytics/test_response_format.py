"""
Test script to verify API response format matches frontend expectations
Run in bench console:
>>> from erp.api.analytics.test_response_format import test_all_endpoints
>>> test_all_endpoints()
"""

import frappe
import json


def test_dashboard_summary():
    """Test dashboard summary endpoint"""
    print("\n" + "="*60)
    print("Testing: get_dashboard_summary()")
    print("="*60)
    
    from erp.api.analytics.dashboard_api import get_dashboard_summary
    result = get_dashboard_summary()
    
    print("\n✅ Response:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    # Verify structure
    assert result.get('success') == True, "success field missing or false"
    assert 'data' in result, "data field missing"
    assert 'today' in result['data'], "data.today field missing"
    assert 'changes' in result['data'], "data.changes field missing"
    
    today = result['data']['today']
    expected_fields = ['total_guardians', 'active_guardians_today', 'active_guardians_7d', 'active_guardians_30d', 'new_guardians']
    
    for field in expected_fields:
        assert field in today, f"Missing field in today: {field}"
        print(f"  ✓ {field}: {today[field]}")
    
    print("\n✅ Dashboard Summary structure is CORRECT!")
    return result


def test_user_trends():
    """Test user trends endpoint"""
    print("\n" + "="*60)
    print("Testing: get_user_trends()")
    print("="*60)
    
    from erp.api.analytics.dashboard_api import get_user_trends
    result = get_user_trends("30d")
    
    print("\n✅ Response:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    # Verify structure
    assert result.get('success') == True, "success field missing or false"
    assert 'data' in result, "data field missing"
    assert isinstance(result['data'], list), "data should be a list"
    
    if result['data']:
        item = result['data'][0]
        expected_fields = ['date', 'active_users', 'total_users']
        for field in expected_fields:
            assert field in item, f"Missing field in trend data: {field}"
    
    print(f"\n✅ User Trends structure is CORRECT! ({len(result['data'])} items)")
    return result


def test_module_usage():
    """Test module usage endpoint"""
    print("\n" + "="*60)
    print("Testing: get_module_usage()")
    print("="*60)
    
    from erp.api.analytics.dashboard_api import get_module_usage
    result = get_module_usage("30d")
    
    print("\n✅ Response:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    # Verify structure
    assert result.get('success') == True, "success field missing or false"
    assert 'data' in result, "data field missing"
    assert isinstance(result['data'], list), "data should be a list"
    assert 'total_calls' in result, "total_calls field missing"
    
    if result['data']:
        item = result['data'][0]
        expected_fields = ['module', 'count', 'percentage']
        for field in expected_fields:
            assert field in item, f"Missing field in module data: {field}"
    
    print(f"\n✅ Module Usage structure is CORRECT! ({len(result['data'])} modules, {result['total_calls']} total calls)")
    return result


def test_feedback_ratings():
    """Test feedback ratings endpoint"""
    print("\n" + "="*60)
    print("Testing: get_feedback_ratings()")
    print("="*60)
    
    from erp.api.analytics.dashboard_api import get_feedback_ratings
    result = get_feedback_ratings(1, 20)
    
    print("\n✅ Response:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    # Verify structure
    assert result.get('success') == True, "success field missing or false"
    assert 'data' in result, "data field missing"
    assert 'feedbacks' in result['data'], "data.feedbacks field missing"
    assert 'average_rating' in result['data'], "data.average_rating field missing"
    assert 'rating_count' in result['data'], "data.rating_count field missing"
    
    print(f"\n✅ Feedback Ratings structure is CORRECT! ({len(result['data']['feedbacks'])} feedbacks, avg: {result['data']['average_rating']})")
    return result


def test_all_endpoints():
    """Run all tests"""
    print("\n" + "🧪"*30)
    print("TESTING ALL ANALYTICS ENDPOINTS")
    print("🧪"*30)
    
    try:
        summary = test_dashboard_summary()
        trends = test_user_trends()
        modules = test_module_usage()
        feedback = test_feedback_ratings()
        
        print("\n" + "✅"*30)
        print("ALL TESTS PASSED!")
        print("✅"*30)
        
        print("\n📊 SUMMARY:")
        print(f"  Total Guardians: {summary['data']['today']['total_guardians']}")
        print(f"  DAU: {summary['data']['today']['active_guardians_today']}")
        print(f"  MAU: {summary['data']['today']['active_guardians_30d']}")
        print(f"  Trend Data Points: {len(trends['data'])}")
        print(f"  Module Usage: {len(modules['data'])} modules, {modules['total_calls']} calls")
        print(f"  Feedback Ratings: {len(feedback['data']['feedbacks'])} ratings")
        
        print("\n💡 If frontend is still blank, check:")
        print("   1. Browser console for errors")
        print("   2. Network tab - verify API calls")
        print("   3. Hard refresh: Cmd/Ctrl + Shift + R")
        
        return True
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {str(e)}")
        return False
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    test_all_endpoints()






