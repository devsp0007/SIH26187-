/**
 * Automated Verification Script for Voice Alert Subsystem
 * Tests:
 * 1. Severity filter (HIGH vs MEDIUM/LOW)
 * 2. Mute/Unmute state & cancellations
 * 3. Tactical concise text formatter
 * 4. Queue anti-stacking and rate-limiting
 * 5. Event burst handling (no garbling/overlap)
 */

// Mock browser window and SpeechSynthesis
class MockSpeechSynthesisUtterance {
  constructor(text) {
    this.text = text;
    this.lang = 'en-US';
    this.rate = 1.0;
    this.pitch = 1.0;
    this.volume = 1.0;
    this.onend = null;
    this.onerror = null;
  }
}

class MockSpeechSynthesis {
  constructor() {
    this.speaking = false;
    this.pending = false;
    this.paused = false;
    this.spokenLog = [];
    this.currentUtterance = null;
  }

  getVoices() {
    return [
      { name: 'Google US English', lang: 'en-US' },
      { name: 'Microsoft David', lang: 'en-US' },
    ];
  }

  speak(utterance) {
    this.spokenLog.push({
      text: utterance.text,
      timestamp: Date.now(),
    });
    this.speaking = true;
    this.currentUtterance = utterance;

    // Simulate speech finishing asynchronously
    setTimeout(() => {
      this.speaking = false;
      this.currentUtterance = null;
      if (typeof utterance.onend === 'function') {
        utterance.onend({ type: 'end' });
      }
    }, 100);
  }

  cancel() {
    this.speaking = false;
    this.currentUtterance = null;
  }
}

// Set up global environment
global.window = {
  speechSynthesis: new MockSpeechSynthesis(),
  addEventListener: () => {},
  removeEventListener: () => {},
};
global.SpeechSynthesisUtterance = MockSpeechSynthesisUtterance;
global.localStorage = {
  _store: {},
  getItem(key) { return this._store[key] ?? null; },
  setItem(key, val) { this._store[key] = String(val); },
};

async function runTests() {
  console.log('====================================================');
  console.log('IBVAP Voice Alert Subsystem Automated Verification');
  console.log('====================================================\n');

  const { voiceAlertService } = await import('./src/services/voiceAlertService.js');

  let passedTests = 0;
  let totalTests = 0;

  function assert(condition, testName) {
    totalTests++;
    if (condition) {
      console.log(`[PASS] ${testName}`);
      passedTests++;
    } else {
      console.error(`[FAIL] ${testName}`);
    }
  }

  // --- Test 1: Tactical Concise Text Formatter ---
  console.log('--- Test Group 1: Tactical Phrasing Formatter ---');
  {
    const eventPerson = {
      event_type: 'zone_entry',
      object_class: 'person',
      camera_id: 'CAM_01',
      camera_name: 'Sector 4 Gate',
      severity: 'high',
      confidence: 0.94,
    };
    const textPerson = voiceAlertService.formatSpokenAlert(eventPerson);
    assert(
      textPerson.includes('Person detected entering Sector 4 Gate') && !textPerson.includes('94%'),
      'Person intrusion formats concisely without percentages'
    );

    const eventWatchlist = {
      event_type: 'zone_entry',
      object_class: 'person',
      camera_id: 'CAM_01',
      camera_name: 'Sector 4 Gate',
      identified_as: 'Alex Smith',
      identification_confidence: 0.92,
      severity: 'high',
    };
    const textWatchlist = voiceAlertService.formatSpokenAlert(eventWatchlist);
    assert(
      textWatchlist.includes('Watchlist alert: Alex Smith detected at Sector 4 Gate'),
      'Watchlist detection formats concise alert with matched profile identity'
    );

    const eventLoiter = {
      event_type: 'suspicious_loitering',
      object_class: 'person',
      camera_id: 'CAM_01',
      camera_name: 'Sector 4 Gate',
      severity: 'high',
    };
    const textLoiter = voiceAlertService.formatSpokenAlert(eventLoiter);
    assert(
      textLoiter.includes('Suspicious loitering detected near Sector 4 Gate'),
      'Suspicious loitering anomaly formats tactical warning'
    );

    const eventPacing = {
      event_type: 'suspicious_pacing',
      object_class: 'person',
      camera_id: 'CAM_01',
      camera_name: 'Sector 4 Gate',
      severity: 'high',
    };
    const textPacing = voiceAlertService.formatSpokenAlert(eventPacing);
    assert(
      textPacing.includes('Suspicious pacing behavior detected near Sector 4 Gate'),
      'Suspicious pacing anomaly formats tactical warning'
    );
  }

  // --- Test 2: Severity Filtering ---
  console.log('\n--- Test Group 2: Severity Filtering (HIGH only) ---');
  {
    window.speechSynthesis.spokenLog = [];
    voiceAlertService.setMuted(false);

    // LOW severity event (Zone Exit)
    voiceAlertService.announceEvent({
      event_id: 'ev-low-1',
      event_type: 'zone_exit',
      object_class: 'person',
      severity: 'low',
      camera_id: 'CAM_01',
    });
    assert(window.speechSynthesis.spokenLog.length === 0, 'LOW severity event does NOT trigger speech');

    // MEDIUM severity event (Vehicle Entry)
    voiceAlertService.announceEvent({
      event_id: 'ev-med-1',
      event_type: 'zone_entry',
      object_class: 'car',
      severity: 'medium',
      camera_id: 'CAM_01',
    });
    assert(window.speechSynthesis.spokenLog.length === 0, 'MEDIUM severity event does NOT trigger speech');

    // HIGH severity event (Person Intrusion)
    voiceAlertService.announceEvent({
      event_id: 'ev-high-1',
      event_type: 'zone_entry',
      object_class: 'person',
      severity: 'high',
      camera_id: 'CAM_01',
      camera_name: 'Sector 4 Gate',
    });
    assert(window.speechSynthesis.spokenLog.length === 1, 'HIGH severity event triggers speech announcement');
  }

  // --- Test 3: Mute & Unmute Toggle ---
  console.log('\n--- Test Group 3: Mute & Unmute Controls ---');
  {
    window.speechSynthesis.spokenLog = [];
    voiceAlertService.setMuted(true);
    assert(voiceAlertService.isMuted() === true, 'Mute state is active');

    // Attempt announcing high severity while muted
    voiceAlertService.announceEvent({
      event_id: 'ev-high-muted',
      event_type: 'zone_entry',
      object_class: 'person',
      severity: 'high',
      camera_id: 'CAM_01',
    });
    assert(window.speechSynthesis.spokenLog.length === 0, 'No speech occurs while muted');

    // Unmute
    voiceAlertService.setMuted(false);
    assert(voiceAlertService.isMuted() === false, 'Unmute restores audio alerts');

    voiceAlertService.lastSpokenTimestamp = 0; // Reset rate-limit timer for immediate test assertion
    voiceAlertService.announceEvent({
      event_id: 'ev-high-unmuted',
      event_type: 'zone_entry',
      object_class: 'person',
      severity: 'high',
      camera_id: 'CAM_01',
      camera_name: 'Sector 4 Gate',
    });
    assert(window.speechSynthesis.spokenLog.length === 1, 'Speech triggers immediately after unmuting');
  }

  // --- Test 4: Anti-Stacking & Rapid Burst Protection ---
  console.log('\n--- Test Group 4: Anti-Stacking & Queue Burst Safeguards ---');
  {
    window.speechSynthesis.spokenLog = [];
    voiceAlertService.cancelAll();
    voiceAlertService.minIntervalMs = 0; // Test queue capacity for test run

    // Send 10 rapid events simultaneously
    for (let i = 1; i <= 10; i++) {
      voiceAlertService.announceEvent({
        event_id: `ev-burst-${i}`,
        event_type: 'zone_entry',
        object_class: 'person',
        severity: 'high',
        camera_id: 'CAM_01',
        camera_name: `Sector 4 Gate - Track #${i}`,
      });
    }

    // Queue depth should be capped at maxQueueDepth (2)
    assert(
      voiceAlertService.speechQueue.length <= 2,
      `Queue size (${voiceAlertService.speechQueue.length}) is capped at <= 2 to prevent audio lag`
    );
  }

  console.log('\n====================================================');
  console.log(`Results: ${passedTests}/${totalTests} Tests Passed successfully.`);
  console.log('====================================================\n');

  if (passedTests === totalTests) {
    process.exit(0);
  } else {
    process.exit(1);
  }
}

runTests().catch((err) => {
  console.error('Test execution failed:', err);
  process.exit(1);
});
