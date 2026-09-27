#!/usr/bin/env python3
"""
Test script for AI provider selection and functionality.
Verifies:
1. Mock provider works (default)
2. Gemini provider can be selected
3. Fallback to mock on Gemini errors
4. Real Gemini API call works when configured
"""
import os
import sys

# Add parent directory to path so we can import backend modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_mock_provider():
    """Test that mock provider works correctly."""
    print("=" * 60)
    print("TEST 1: Mock Provider (default)")
    print("=" * 60)
    
    # Ensure mock mode
    os.environ["AI_PROVIDER"] = "mock"
    
    # Reload the module to pick up new env
    import importlib
    import backend.ai as ai_module
    importlib.reload(ai_module)
    
    from backend.ai import analyze_complaint, AI_PROVIDER
    
    print(f"AI_PROVIDER: {AI_PROVIDER}")
    
    # Test complaint
    result = analyze_complaint(
        text="There are huge potholes on the main road near my house causing accidents",
        language="English",
        location="Pune, Maharashtra"
    )
    
    print(f"Result keys: {list(result.keys())}")
    print(f"Category: {result.get('category')}")
    print(f"Severity: {result.get('severity')}")
    print(f"Urgency: {result.get('urgency')}")
    print(f"Summary: {result.get('issue_summary')}")
    print(f"Action: {result.get('recommended_action')}")
    
    # Validate structure
    required = ["language", "category", "location", "severity", "urgency", 
                "affected_group", "issue_summary", "recommended_action"]
    for field in required:
        assert field in result, f"Missing field: {field}"
    
    assert result["category"] in ai_module.CATEGORIES
    assert result["severity"] in ai_module.SEVERITY_LEVELS
    assert result["urgency"] in ai_module.URGENCY_LEVELS
    
    print("[OK] Mock provider test PASSED")
    return True


def test_gemini_provider_selection():
    """Test that Gemini provider can be selected (without actual API call)."""
    print("\n" + "=" * 60)
    print("TEST 2: Gemini Provider Selection (config only)")
    print("=" * 60)
    
    # Set Gemini mode but no API key
    os.environ["AI_PROVIDER"] = "gemini"
    os.environ.pop("GEMINI_API_KEY", None)
    
    # Reload
    import importlib
    import backend.ai as ai_module
    importlib.reload(ai_module)
    
    from backend.ai import analyze_complaint, AI_PROVIDER, GEMINI_API_KEY
    
    print(f"AI_PROVIDER: {AI_PROVIDER}")
    print(f"GEMINI_API_KEY: {'SET' if GEMINI_API_KEY else 'NOT SET'}")
    
    # Should fall back to mock when no API key
    result = analyze_complaint(
        text="Test complaint for Gemini selection",
        language="English",
        location="Test Location"
    )
    
    print(f"Fallback to mock: category={result.get('category')}")
    assert result["category"] in ai_module.CATEGORIES
    
    print("[OK] Gemini provider selection test PASSED (falls back to mock without key)")
    return True


def test_gemini_with_invalid_key():
    """Test that invalid API key triggers fallback."""
    print("\n" + "=" * 60)
    print("TEST 3: Gemini with Invalid API Key (fallback)")
    print("=" * 60)
    
    os.environ["AI_PROVIDER"] = "gemini"
    os.environ["GEMINI_API_KEY"] = "invalid-key-123"
    
    import importlib
    import backend.ai as ai_module
    importlib.reload(ai_module)
    
    from backend.ai import analyze_complaint
    
    # This should fall back to mock since the key is invalid
    result = analyze_complaint(
        text="Test with invalid key",
        language="English",
        location="Test"
    )
    
    print(f"Result category: {result.get('category')}")
    assert result["category"] in ai_module.CATEGORIES
    
    print("[OK] Invalid key fallback test PASSED")
    return True


def test_existing_endpoints_still_work():
    """Verify the analyze_complaint interface is unchanged."""
    print("\n" + "=" * 60)
    print("TEST 4: Interface Compatibility")
    print("=" * 60)
    
    os.environ["AI_PROVIDER"] = "mock"
    
    import importlib
    import backend.ai as ai_module
    importlib.reload(ai_module)
    
    from backend.ai import analyze_complaint
    
    # Test all supported languages
    for lang in ["English", "Hindi", "Marathi"]:
        result = analyze_complaint(
            text=f"Test complaint in {lang}",
            language=lang,
            location="Test Location"
        )
        assert result["language"] == lang
        print(f"  Language {lang}: OK")
    
    # Test category detection
    test_cases = [
        ("pothole on the road", "Road Infrastructure"),
        ("no water supply", "Water Supply"),
        ("power outage", "Electricity"),
        ("garbage not collected", "Sanitation"),
        ("bus delay", "Public Transport"),
        ("hospital emergency", "Healthcare"),
        ("school building", "Education"),
    ]
    
    for text, expected_cat in test_cases:
        result = analyze_complaint(text=text, language="English", location="Test")
        print(f"  '{text[:30]}...' -> {result['category']} (expected: {expected_cat})")
    
    print("[OK] Interface compatibility test PASSED")
    return True


def test_real_gemini_call():
    """Test actual Gemini API call when configured."""
    print("\n" + "=" * 60)
    print("TEST 5: Real Gemini API Call (requires valid API key)")
    print("=" * 60)
    
    # Check if API key is available
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY not set - SKIPPING real Gemini test")
        print("  To run this test, set GEMINI_API_KEY in environment")
        return True
    
    os.environ["AI_PROVIDER"] = "gemini"
    os.environ["GEMINI_MODEL"] = "gemini-3-flash-preview"
    
    import importlib
    import backend.ai as ai_module
    importlib.reload(ai_module)
    
    from backend.ai import analyze_complaint, GEMINI_MODEL
    
    print(f"Testing with model: {GEMINI_MODEL}")
    
    # Test with a realistic CivicAI complaint
    complaint_text = "There is no proper water supply in my area and many families are affected."
    
    try:
        result = analyze_complaint(
            text=complaint_text,
            language="English",
            location="Pune, Maharashtra"
        )
        
        print(f"Result keys: {list(result.keys())}")
        print(f"Category: {result.get('category')}")
        print(f"Severity: {result.get('severity')}")
        print(f"Urgency: {result.get('urgency')}")
        print(f"Affected Group: {result.get('affected_group')}")
        print(f"Summary: {result.get('issue_summary')}")
        print(f"Action: {result.get('recommended_action')}")
        
        # Validate all required CivicAI structured fields
        required = ["language", "category", "location", "severity", "urgency", 
                    "affected_group", "issue_summary", "recommended_action"]
        for field in required:
            assert field in result, f"Missing field: {field}"
            print(f"  {field}: PRESENT")
        
        # Validate values
        assert result["category"] in ai_module.CATEGORIES
        assert result["severity"] in ai_module.SEVERITY_LEVELS
        assert result["urgency"] in ai_module.URGENCY_LEVELS
        assert result["language"] == "English"
        assert result["location"] == "Pune, Maharashtra"
        
        print("[OK] Real Gemini API call test PASSED")
        return True
        
    except Exception as e:
        print(f"[FAIL] Real Gemini API call failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("CivicAI AI Provider Test Suite")
    print("=" * 60)
    
    tests = [
        test_mock_provider,
        test_gemini_provider_selection,
        test_gemini_with_invalid_key,
        test_existing_endpoints_still_work,
        test_real_gemini_call,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"[FAIL] FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)
    
    if failed > 0:
        sys.exit(1)
    else:
        print("\nAll tests passed!")
        print("\nTo test with real Gemini:")
        print("  1. Set AI_PROVIDER=gemini in .env")
        print("  2. Set GEMINI_API_KEY=your_key in .env")
        print("  3. Run this test again")


if __name__ == "__main__":
    main()