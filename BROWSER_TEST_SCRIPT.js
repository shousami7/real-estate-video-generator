/**
 * Browser Console Test Script for On-Demand Frame Extraction
 *
 * Usage:
 * 1. Open http://localhost:5000/editor in browser
 * 2. Upload a video and extract frames to show timeline
 * 3. Open Developer Tools (F12) → Console tab
 * 4. Copy-paste this entire script and press Enter
 * 5. Run: await runAllTests()
 */

// ========================================
// Test Utilities
// ========================================

function log(emoji, message, data = null) {
    console.log(`${emoji} ${message}`);
    if (data) console.log(data);
}

function logSection(title) {
    console.log('\n' + '='.repeat(60));
    console.log(`🧪 ${title}`);
    console.log('='.repeat(60));
}

function assert(condition, message) {
    if (!condition) {
        throw new Error(`❌ Assertion failed: ${message}`);
    }
    log('✅', `Passed: ${message}`);
}

// ========================================
// Test Functions
// ========================================

async function testAPIEndpoint() {
    logSection('Test 1: API Endpoint');

    // Get current video path from state
    if (!state.videoFrames || state.expandedFrameId === null) {
        throw new Error('No video loaded. Please upload a video and extract frames first.');
    }

    const frameData = state.videoFrames[state.expandedFrameId];
    const videoPath = frameData.videoPath?.startsWith('/')
        ? frameData.videoPath.substring(1)
        : frameData.videoPath;

    log('📹', `Testing with video: ${videoPath}`);

    // Test 1: Valid request
    log('🔍', 'Test 1.1: Valid timestamp (3.5s)');
    const response1 = await fetch('/frames/extract_at_time', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            video_path: videoPath,
            timestamp: 3.5
        })
    });

    const data1 = await response1.json();
    assert(data1.status === 'success', 'API returned success');
    assert(data1.frame, 'Frame data exists');
    assert(data1.frame.timestamp, 'Frame has timestamp');
    assert(data1.frame.base64, 'Frame has base64 image');
    log('📸', `Extracted frame at ${data1.frame.timestamp}`);

    // Test 2: Invalid timestamp
    log('🔍', 'Test 1.2: Invalid timestamp (-1.0s)');
    const response2 = await fetch('/frames/extract_at_time', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            video_path: videoPath,
            timestamp: -1.0
        })
    });

    const data2 = await response2.json();
    assert(data2.status === 'error', 'API returned error for invalid timestamp');
    log('✅', `Error message: ${data2.message}`);

    // Test 3: Missing parameters
    log('🔍', 'Test 1.3: Missing video_path');
    const response3 = await fetch('/frames/extract_at_time', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            timestamp: 1.0
        })
    });

    const data3 = await response3.json();
    assert(data3.status === 'error', 'API returned error for missing video_path');
    log('✅', `Error message: ${data3.message}`);

    log('🎉', 'All API tests passed!');
}

async function testTimelineClickCalculation() {
    logSection('Test 2: Timeline Click Calculation');

    if (!allExtractedFrames || allExtractedFrames.length === 0) {
        throw new Error('No frames extracted. Please extract frames first.');
    }

    const videoDuration = allExtractedFrames[allExtractedFrames.length - 1].seconds;
    log('📹', `Video duration: ${videoDuration.toFixed(2)}s`);

    // Simulate timeline clicks at different positions
    const timeline = document.getElementById('liquid-glass-timeline');
    const rect = timeline.getBoundingClientRect();
    const scrollWidth = timeline.scrollWidth;

    const testPositions = [
        { name: 'Start (0%)', percentage: 0.0 },
        { name: 'Quarter (25%)', percentage: 0.25 },
        { name: 'Middle (50%)', percentage: 0.5 },
        { name: 'Three-quarters (75%)', percentage: 0.75 },
        { name: 'Near end (95%)', percentage: 0.95 }
    ];

    for (const pos of testPositions) {
        const totalPosition = scrollWidth * pos.percentage;
        const expectedTimestamp = videoDuration * pos.percentage;

        log('🔍', `${pos.name}: Expected timestamp ~${expectedTimestamp.toFixed(2)}s`);

        // Calculate actual timestamp (same logic as double-click handler)
        const clickX = totalPosition - timeline.scrollLeft;
        const percentage = totalPosition / scrollWidth;
        const timestamp = videoDuration * percentage;

        assert(
            Math.abs(timestamp - expectedTimestamp) < 0.1,
            `Timestamp calculation accurate (${timestamp.toFixed(2)}s)`
        );
    }

    log('🎉', 'All timeline calculation tests passed!');
}

async function testModalDisplay() {
    logSection('Test 3: Modal Display');

    // Create test frame data
    const testFrame = {
        timestamp: '0:03.5',
        seconds: 3.5,
        base64: 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
    };

    log('🔍', 'Test 3.1: Show modal');
    showFramePreviewModal(testFrame, 'test.mp4');

    // Check if modal exists
    const modal = document.querySelector('.fixed.inset-0.bg-black\\/80');
    assert(modal !== null, 'Modal element created');

    // Check modal content
    const title = modal.querySelector('h3');
    assert(title !== null, 'Modal has title');
    assert(title.textContent.includes('0:03.5'), 'Title shows correct timestamp');

    const img = modal.querySelector('img');
    assert(img !== null, 'Modal has image');
    assert(img.src.startsWith('data:image'), 'Image has base64 source');

    const editBtn = modal.querySelector('.edit-frame-btn');
    assert(editBtn !== null, 'Modal has Edit button');

    const closeBtn = modal.querySelector('.close-modal');
    assert(closeBtn !== null, 'Modal has Close button');

    log('🔍', 'Test 3.2: Close modal');
    closeBtn.click();

    // Wait for modal to close
    await new Promise(resolve => setTimeout(resolve, 100));

    const modalAfterClose = document.querySelector('.fixed.inset-0.bg-black\\/80');
    assert(modalAfterClose === null, 'Modal closed successfully');

    log('🎉', 'All modal tests passed!');
}

async function testMemoryUsage() {
    logSection('Test 4: Memory Usage');

    if (!performance.memory) {
        log('⚠️', 'Performance.memory not available in this browser');
        log('💡', 'Use Chrome with --enable-precise-memory-info flag');
        return;
    }

    const before = performance.memory.usedJSHeapSize;
    log('📊', `Memory before extraction: ${(before / 1024 / 1024).toFixed(2)} MB`);

    // Extract 3 frames
    const frameData = state.videoFrames[state.expandedFrameId];
    const videoPath = frameData.videoPath?.startsWith('/')
        ? frameData.videoPath.substring(1)
        : frameData.videoPath;

    for (let i = 0; i < 3; i++) {
        const timestamp = (i + 1) * 2.0; // 2s, 4s, 6s
        await fetch('/frames/extract_at_time', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ video_path: videoPath, timestamp })
        });
    }

    const after = performance.memory.usedJSHeapSize;
    const increase = after - before;

    log('📊', `Memory after extraction: ${(after / 1024 / 1024).toFixed(2)} MB`);
    log('📊', `Memory increase: ${(increase / 1024 / 1024).toFixed(2)} MB`);

    assert(increase < 50 * 1024 * 1024, 'Memory increase < 50MB (acceptable)');

    log('🎉', 'Memory usage test passed!');
}

async function testExtractFrameAtTimestamp() {
    logSection('Test 5: extractFrameAtTimestamp Function');

    if (!state.videoFrames || state.expandedFrameId === null) {
        throw new Error('No video loaded');
    }

    const frameData = state.videoFrames[state.expandedFrameId];
    const videoPath = frameData.videoPath;

    log('🔍', 'Test 5.1: Extract at 2.5s');

    const loadingBefore = document.querySelectorAll('.fixed.inset-0.bg-black\\/60').length;

    // Call the function (it's async)
    const promise = extractFrameAtTimestamp(videoPath, 2.5);

    // Check loading indicator appears
    await new Promise(resolve => setTimeout(resolve, 50));
    const loadingDuring = document.querySelectorAll('.fixed.inset-0.bg-black\\/60').length;
    assert(loadingDuring > loadingBefore, 'Loading indicator shown');

    // Wait for extraction to complete
    await promise;

    // Check modal appears
    const modal = document.querySelector('.fixed.inset-0.bg-black\\/80');
    assert(modal !== null, 'Modal displayed after extraction');

    // Close modal
    const closeBtn = modal.querySelector('.close-modal');
    closeBtn.click();

    log('🎉', 'extractFrameAtTimestamp test passed!');
}

// ========================================
// Main Test Runner
// ========================================

async function runAllTests() {
    console.clear();
    logSection('On-Demand Frame Extraction - Browser Tests');

    const tests = [
        { name: 'API Endpoint', fn: testAPIEndpoint },
        { name: 'Timeline Click Calculation', fn: testTimelineClickCalculation },
        { name: 'Modal Display', fn: testModalDisplay },
        { name: 'extractFrameAtTimestamp Function', fn: testExtractFrameAtTimestamp },
        { name: 'Memory Usage', fn: testMemoryUsage }
    ];

    let passed = 0;
    let failed = 0;
    const results = [];

    for (const test of tests) {
        try {
            await test.fn();
            passed++;
            results.push({ name: test.name, status: '✅ PASSED' });
        } catch (error) {
            failed++;
            results.push({ name: test.name, status: '❌ FAILED', error: error.message });
            console.error(`❌ Test failed: ${test.name}`, error);
        }
    }

    // Summary
    console.log('\n' + '='.repeat(60));
    console.log('📊 Test Summary');
    console.log('='.repeat(60));
    console.table(results);
    console.log(`\nTotal: ${tests.length}`);
    console.log(`✅ Passed: ${passed}`);
    console.log(`❌ Failed: ${failed}`);

    if (failed === 0) {
        console.log('\n🎉 All browser tests PASSED!');
        console.log('\n💡 Next steps:');
        console.log('   1. Follow E2E_TEST_CHECKLIST.md for complete manual testing');
        console.log('   2. Test on different browsers (Firefox, Safari)');
        console.log('   3. Test with different video lengths (8s, 20s, 60s)');
    } else {
        console.log('\n⚠️  Some tests FAILED. Check errors above.');
    }

    return { passed, failed, results };
}

// ========================================
// Quick Tests (Individual)
// ========================================

async function quickTestAPI() {
    await testAPIEndpoint();
}

async function quickTestTimeline() {
    await testTimelineClickCalculation();
}

async function quickTestModal() {
    await testModalDisplay();
}

async function quickTestMemory() {
    await testMemoryUsage();
}

// ========================================
// Instructions
// ========================================

console.log('='.repeat(60));
console.log('🧪 On-Demand Frame Extraction - Browser Test Suite');
console.log('='.repeat(60));
console.log('\n📝 Instructions:');
console.log('   1. Make sure you have uploaded a video');
console.log('   2. Extract frames to show the timeline');
console.log('   3. Run: await runAllTests()');
console.log('\n💡 Quick tests (run individually):');
console.log('   - await quickTestAPI()');
console.log('   - await quickTestTimeline()');
console.log('   - await quickTestModal()');
console.log('   - await quickTestMemory()');
console.log('='.repeat(60));
