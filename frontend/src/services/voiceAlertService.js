/**
 * IBVAP - Voice & Audio Alert Service
 * 
 * Provides client-side tactical text-to-speech using the native Web Speech API
 * (window.speechSynthesis).
 * 
 * Features:
 * - High-severity event filter (only speaks for severity: 'high')
 * - Anti-stacking sequential queue (each utterance finishes before next starts)
 * - Rate limiting & queue capacity cap (max 2 queued; drops stale backlog)
 * - Tactical concise phrasing formatter (removes awkward confidence % & track numbers)
 * - Mute/Unmute state toggle (default: unmuted)
 * - User gesture auto-unlocking for browser autoplay policies
 * - Status listeners for reactive UI indicators (isSpeaking, isMuted)
 */

class VoiceAlertService {
  constructor() {
    this.muted = false;
    this.speechQueue = [];
    this.isCurrentlySpeaking = false;
    this.lastSpokenTimestamp = 0;
    this.minIntervalMs = 2600; // Minimum interval between alert starts
    this.maxQueueDepth = 2;    // Drop excess alerts beyond this to prevent lag
    this.listeners = new Set();
    this.watchdogTimer = null;
    this.isUnlocked = false;

    // Load persisted mute preference from localStorage if available
    try {
      const savedMute = localStorage.getItem('ibvap_voice_muted');
      if (savedMute !== null) {
        this.muted = savedMute === 'true';
      }
    } catch (_) {
      this.muted = false;
    }

    // Auto-unlock speech synthesis on first user interaction
    this.setupUserGestureUnlock();
  }

  /**
   * Set up one-time document listeners to unlock Web Speech API on user interaction.
   */
  setupUserGestureUnlock() {
    if (typeof window === 'undefined') return;

    const unlock = () => {
      if (this.isUnlocked) return;
      this.isUnlocked = true;

      // Prime the speech synthesis engine with an empty utterance
      if ('speechSynthesis' in window) {
        try {
          const primer = new SpeechSynthesisUtterance('');
          primer.volume = 0;
          window.speechSynthesis.speak(primer);
        } catch (_) {}
      }

      window.removeEventListener('click', unlock);
      window.removeEventListener('keydown', unlock);
      window.removeEventListener('touchstart', unlock);
    };

    window.addEventListener('click', unlock, { once: true, passive: true });
    window.addEventListener('keydown', unlock, { once: true, passive: true });
    window.addEventListener('touchstart', unlock, { once: true, passive: true });
  }

  /**
   * Register a subscriber callback for state changes (isMuted, isSpeaking).
   */
  subscribe(callback) {
    this.listeners.add(callback);
    // Initial notification
    callback({
      isMuted: this.muted,
      isSpeaking: this.isCurrentlySpeaking,
    });
    return () => this.listeners.delete(callback);
  }

  /**
   * Notify all registered UI subscribers.
   */
  notifySubscribers() {
    const state = {
      isMuted: this.muted,
      isSpeaking: this.isCurrentlySpeaking,
    };
    this.listeners.forEach((cb) => {
      try {
        cb(state);
      } catch (err) {
        console.error('[VoiceAlertService] Subscriber error:', err);
      }
    });
  }

  /**
   * Check if speech synthesis is currently muted.
   */
  isMuted() {
    return this.muted;
  }

  /**
   * Toggle or set mute state.
   */
  setMuted(muted) {
    this.muted = Boolean(muted);
    try {
      localStorage.setItem('ibvap_voice_muted', String(this.muted));
    } catch (_) {}

    if (this.muted) {
      this.cancelAll();
    }
    this.notifySubscribers();
  }

  /**
   * Toggle between muted and unmuted.
   */
  toggleMute() {
    this.setMuted(!this.muted);
    return this.muted;
  }

  /**
   * Format structured event or tactical summary into concise, natural tactical speech.
   */
  formatSpokenAlert(event) {
    if (!event) return 'Security alert detected.';

    const location =
      event.camera_name ||
      (event.camera_id === 'CAM_01'
        ? 'Sector 4 Gate'
        : event.camera_id === 'CAM_02'
        ? 'Sector 2 East Fence'
        : event.camera_id === 'CAM_03'
        ? 'Sector 7 Outpost'
        : event.camera_id || 'monitored perimeter');

    const eventType = (event.event_type || '').toLowerCase();
    const objectClass = (event.object_class || 'target').toLowerCase();
    const identifiedAs = event.identified_as && event.identified_as !== 'UNKNOWN' ? event.identified_as : null;

    // 1. Behavioral Anomalies (Checked first: flags loitering/pacing even for authorized personnel)
    if (eventType === 'suspicious_loitering') {
      const subject = identifiedAs ? `Subject ${identifiedAs}` : '';
      return subject
        ? `Security warning: ${subject} loitering detected near ${location}.`
        : `Suspicious loitering detected near ${location}.`;
    }
    if (eventType === 'suspicious_pacing') {
      const subject = identifiedAs ? ` by Subject ${identifiedAs}` : '';
      return `Suspicious pacing behavior${subject} detected near ${location}.`;
    }

    // 2. Watchlist Alert (if identified personnel on high alert / entry)
    if (identifiedAs) {
      if (eventType === 'zone_entry' && (event.severity === 'high' || event.severity === 'HIGH')) {
        return `Watchlist alert: ${identifiedAs} detected at ${location}.`;
      }
      return `Routine access: ${identifiedAs} entered ${location}.`;
    }

    // 3. Zone Intrusions / Access
    if (eventType === 'zone_entry') {
      if (objectClass === 'person') {
        return `Person detected entering ${location}.`;
      }
      return `High alert: Vehicle ${objectClass} entered ${location}.`;
    }

    // 4. Fallback: Clean existing tactical summary
    if (event.tactical_summary) {
      let clean = event.tactical_summary
        .replace(/\s*\(\s*\d+%\s*(confidence|match)?\s*\)/gi, '')
        .replace(/\s*\(Track\s*#\d+\)/gi, '')
        .replace(/Track\s*#\d+/gi, 'subject')
        .replace(/—\s*patrol dispatch advised/gi, '')
        .replace(/—\s*visual verification recommended/gi, '')
        .replace(/\s*-\s*requires verification/gi, '')
        .trim();
      return clean;
    }

    return `High alert: Security event detected at ${location}.`;
  }

  /**
   * Announce an incoming security event.
   * Only processes events with severity: 'high'.
   */
  announceEvent(event) {
    if (!event) return;

    const severity = (event.severity || '').toLowerCase();
    // Requirement 1: Only speak for severity: high events
    if (severity !== 'high') {
      return;
    }

    if (this.muted) {
      return;
    }

    const spokenText = this.formatSpokenAlert(event);
    this.enqueue(spokenText);
  }

  /**
   * Speak a direct custom message (e.g. for testing).
   */
  speak(text) {
    if (this.muted || !text) return;
    this.enqueue(text);
  }

  /**
   * Test audio synthesis immediately.
   */
  testVoice() {
    const wasMuted = this.muted;
    if (wasMuted) {
      this.setMuted(false);
    }
    this.cancelAll();
    this.enqueue('IBVAP tactical audio alert system active and operational.');
  }

  /**
   * Add text to speech queue with anti-stacking and rate-limit safeguards.
   */
  enqueue(text) {
    if (!text || typeof window === 'undefined' || !('speechSynthesis' in window)) {
      return;
    }

    // Anti-stacking cap: If queue already has max items, drop older pending alerts
    if (this.speechQueue.length >= this.maxQueueDepth) {
      console.warn('[VoiceAlertService] Speech queue full, dropping oldest alert to maintain real-time telemetry.');
      this.speechQueue.shift();
    }

    this.speechQueue.push(text);
    this.processQueue();
  }

  /**
   * Process the next item in the speech queue.
   */
  processQueue() {
    if (this.muted) {
      this.speechQueue = [];
      this.isCurrentlySpeaking = false;
      this.notifySubscribers();
      return;
    }

    if (this.isCurrentlySpeaking || this.speechQueue.length === 0) {
      return;
    }

    const now = Date.now();
    const timeSinceLastSpoken = now - this.lastSpokenTimestamp;
    if (timeSinceLastSpoken < this.minIntervalMs) {
      const delay = this.minIntervalMs - timeSinceLastSpoken;
      setTimeout(() => this.processQueue(), delay);
      return;
    }

    const textToSpeak = this.speechQueue.shift();
    if (!textToSpeak) return;

    this.isCurrentlySpeaking = true;
    this.lastSpokenTimestamp = Date.now();
    this.notifySubscribers();

    try {
      // Create utterance
      const utterance = new SpeechSynthesisUtterance(textToSpeak);
      utterance.lang = 'en-US';
      utterance.rate = 1.02;  // Crisp, professional tactical pace
      utterance.pitch = 1.0;
      utterance.volume = 1.0;

      // Select natural English voice if available
      const voices = window.speechSynthesis.getVoices();
      const preferredVoice = voices.find(
        (v) =>
          v.lang.startsWith('en') &&
          (v.name.includes('Google') ||
           v.name.includes('Natural') ||
           v.name.includes('Samantha') ||
           v.name.includes('David') ||
           v.name.includes('Zira') ||
           v.name.includes('Microsoft'))
      ) || voices.find((v) => v.lang.startsWith('en'));

      if (preferredVoice) {
        utterance.voice = preferredVoice;
      }

      // Chromium stall watchdog (in case onend never fires due to background throttling)
      if (this.watchdogTimer) clearTimeout(this.watchdogTimer);
      this.watchdogTimer = setTimeout(() => {
        if (this.isCurrentlySpeaking) {
          console.warn('[VoiceAlertService] Speech watchdog triggered.');
          this.onSpeechFinished();
        }
      }, 7000);

      utterance.onend = () => {
        this.onSpeechFinished();
      };

      utterance.onerror = (e) => {
        // 'interrupted' or 'canceled' are normal during mute/reset
        if (e.error !== 'interrupted' && e.error !== 'canceled') {
          console.warn('[VoiceAlertService] Speech synthesis error:', e.error);
        }
        this.onSpeechFinished();
      };

      window.speechSynthesis.speak(utterance);
    } catch (err) {
      console.error('[VoiceAlertService] Failed to invoke speech synthesis:', err);
      this.onSpeechFinished();
    }
  }

  /**
   * Handle completion of an utterance and schedule next queue item.
   */
  onSpeechFinished() {
    if (this.watchdogTimer) {
      clearTimeout(this.watchdogTimer);
      this.watchdogTimer = null;
    }

    this.isCurrentlySpeaking = false;
    this.notifySubscribers();

    // Small pause between alerts for natural acoustics
    setTimeout(() => {
      this.processQueue();
    }, 350);
  }

  /**
   * Cancel any active and pending speech synthesis.
   */
  cancelAll() {
    this.speechQueue = [];
    if (this.watchdogTimer) {
      clearTimeout(this.watchdogTimer);
      this.watchdogTimer = null;
    }
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      try {
        window.speechSynthesis.cancel();
      } catch (_) {}
    }
    this.isCurrentlySpeaking = false;
    this.notifySubscribers();
  }
}

// Export singleton instance
export const voiceAlertService = new VoiceAlertService();
export default voiceAlertService;
