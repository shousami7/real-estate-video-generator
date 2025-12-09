#!/usr/bin/env python3
"""
Quick test script for on-demand frame extraction
Run this to verify backend functionality before manual UI testing.

Usage:
    python test_frame_extraction.py <video_path>

Example:
    python test_frame_extraction.py uploads/local/session_xxx/video.mp4
"""

import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from frame_editor import FrameEditor


def test_frame_extraction(video_path: str):
    """Test frame extraction at various timestamps"""

    print("=" * 60)
    print("🧪 On-Demand Frame Extraction - Quick Test")
    print("=" * 60)

    # Check if video exists
    if not os.path.exists(video_path):
        print(f"❌ Video not found: {video_path}")
        return False

    print(f"📹 Testing video: {video_path}")

    # Create FrameEditor instance
    frames_dir = "test_frames"
    editor = FrameEditor(video_path, frames_dir)

    # Get video duration
    try:
        duration = editor.get_video_duration()
        print(f"✅ Video duration: {duration:.2f}s")
    except Exception as e:
        print(f"❌ Failed to get video duration: {e}")
        return False

    # Test timestamps
    test_timestamps = [
        0.0,                    # Start
        duration / 4,          # 25%
        duration / 2,          # 50%
        duration * 3 / 4,      # 75%
        duration - 0.5         # Near end
    ]

    print(f"\n🔍 Testing {len(test_timestamps)} timestamps...")
    print("-" * 60)

    results = []

    for i, timestamp in enumerate(test_timestamps, 1):
        print(f"\n[Test {i}/{len(test_timestamps)}] Extracting at {timestamp:.2f}s ({timestamp/duration*100:.1f}%)")

        try:
            frame = editor.extract_frame_at_timestamp(timestamp)

            # Verify frame data
            assert 'path' in frame, "Missing 'path' in frame"
            assert 'timestamp' in frame, "Missing 'timestamp' in frame"
            assert 'seconds' in frame, "Missing 'seconds' in frame"
            assert 'base64' in frame, "Missing 'base64' in frame"

            # Verify file exists
            assert os.path.exists(frame['path']), f"Frame file not found: {frame['path']}"

            # Verify file size
            file_size = os.path.getsize(frame['path'])
            assert file_size > 0, "Frame file is empty"

            print(f"  ✅ Frame extracted successfully")
            print(f"     - Timestamp: {frame['timestamp']}")
            print(f"     - Path: {frame['path']}")
            print(f"     - Size: {file_size:,} bytes ({file_size/1024:.1f} KB)")

            results.append({
                'timestamp': timestamp,
                'success': True,
                'path': frame['path'],
                'size': file_size
            })

        except Exception as e:
            print(f"  ❌ Failed: {e}")
            results.append({
                'timestamp': timestamp,
                'success': False,
                'error': str(e)
            })

    # Summary
    print("\n" + "=" * 60)
    print("📊 Test Summary")
    print("=" * 60)

    passed = sum(1 for r in results if r['success'])
    failed = len(results) - passed

    print(f"Total tests: {len(results)}")
    print(f"✅ Passed: {passed}")
    print(f"❌ Failed: {failed}")

    if failed == 0:
        print("\n🎉 All tests PASSED!")
        print("\n💡 Next steps:")
        print("   1. Start Flask server: python app.py")
        print("   2. Open browser: http://localhost:5000/editor")
        print("   3. Follow E2E_TEST_CHECKLIST.md for manual UI testing")
        return True
    else:
        print("\n⚠️  Some tests FAILED. Check errors above.")
        return False


def test_error_handling():
    """Test error handling"""
    print("\n" + "=" * 60)
    print("🧪 Error Handling Tests")
    print("=" * 60)

    # Test 1: Invalid video path
    print("\n[Test 1] Non-existent video")
    try:
        editor = FrameEditor("/nonexistent/video.mp4", "test_frames")
        editor.extract_frame_at_timestamp(1.0)
        print("  ❌ Should have raised FileNotFoundError")
        return False
    except FileNotFoundError as e:
        print(f"  ✅ Correctly raised FileNotFoundError")

    # Test 2: Negative timestamp (need valid video)
    print("\n[Test 2] Negative timestamp")
    print("  ⚠️  Skipping (requires valid video path)")

    print("\n✅ Error handling tests completed")
    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_frame_extraction.py <video_path>")
        print("\nExample:")
        print("  python test_frame_extraction.py uploads/local/session_xxx/video.mp4")
        sys.exit(1)

    video_path = sys.argv[1]

    # Run extraction tests
    extraction_ok = test_frame_extraction(video_path)

    # Run error handling tests
    error_handling_ok = test_error_handling()

    # Exit code
    if extraction_ok and error_handling_ok:
        sys.exit(0)
    else:
        sys.exit(1)
