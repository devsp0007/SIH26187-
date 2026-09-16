import React, { useState, useEffect } from 'react';
import {
  ShieldAlert,
  ShieldCheck,
  User,
  LogOut,
  Activity,
  Radio,
  Clock,
  History,
  Info,
  Volume2,
  VolumeX,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';

export default function Header({
  isConnected,
  activeTab,
  setActiveTab,
  liveCount = 0,
  isVoiceMuted = false,
  isVoiceSpeaking = false,
  onToggleVoiceMute,
  onTestVoice,
}) {
  const { user, logout, isAdmin, authDisabled } = useAuth();
  const [timeStr, setTimeStr] = useState('');

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setTimeStr(now.toUTCString().slice(17, 25) + ' UTC');
    };
    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  return (
    <header className="top-header">
      <div className="brand-section">
        <div className="brand-logo" title="Intelligent Border Video Analytics Platform">
          <ShieldAlert size={22} />
        </div>
        <div>
          <div className="brand-title">
            IBVAP <span style={{ color: '#0ea5e9' }}>CORE</span>
          </div>
          <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)', fontWeight: 500, letterSpacing: '0.01em' }}>
            Intelligent Border Video Analytics Platform
          </div>
        </div>
      </div>

      <div className="telemetry-bar">
        {/* Voice / Audio Alert Toggle & Status */}
        <div className="voice-control-group">
          <button
            type="button"
            className={`voice-toggle-btn ${isVoiceMuted ? 'muted' : 'active'} ${isVoiceSpeaking ? 'speaking' : ''}`}
            onClick={onToggleVoiceMute}
            title={
              isVoiceMuted
                ? 'Voice Alerts are Muted — Click to enable spoken alerts for HIGH severity events'
                : isVoiceSpeaking
                ? 'Speaking tactical alert aloud — Click to mute'
                : 'Voice Alerts Enabled (Speaks HIGH severity events aloud) — Click to mute'
            }
            aria-label={isVoiceMuted ? 'Unmute voice alerts' : 'Mute voice alerts'}
          >
            {isVoiceMuted ? (
              <VolumeX size={15} className="voice-icon muted" />
            ) : isVoiceSpeaking ? (
              <div className="voice-speaking-indicator">
                <span className="voice-wave wave1" />
                <span className="voice-wave wave2" />
                <span className="voice-wave wave3" />
                <Volume2 size={15} className="voice-icon speaking" />
              </div>
            ) : (
              <Volume2 size={15} className="voice-icon active" />
            )}
            <span className="voice-label">
              {isVoiceMuted ? 'VOICE MUTED' : isVoiceSpeaking ? 'SPEAKING ALERT...' : 'VOICE ALERTS'}
            </span>
          </button>

          {!isVoiceMuted && onTestVoice && (
            <button
              type="button"
              className="voice-test-btn"
              onClick={(e) => {
                e.stopPropagation();
                onTestVoice();
              }}
              title="Test Voice Speech Synthesis"
              aria-label="Test tactical voice alert speech"
            >
              Test
            </button>
          )}
        </div>

        <div
          className="disclaimer-chip"
          title="Consented Demo Watchlist Only: Face identification evaluates strictly against a local team profile set for demonstration; NOT connected to any government or law-enforcement database."
        >
          <Activity size={13} style={{ color: '#4ade80' }} />
          <span>Demo Watchlist ID</span>
          <Info size={12} style={{ opacity: 0.7 }} />
        </div>

        <div className="live-clock" title="System Synchronized UTC Clock">
          <Clock size={13} style={{ color: '#38bdf8' }} />
          <span>{timeStr}</span>
        </div>

        <div
          className={`ws-status-beacon ${isConnected ? 'connected' : 'disconnected'}`}
          title={isConnected ? 'Live Telemetry & Event Stream Connected' : 'Attempting to reconnect WebSocket stream...'}
        >
          <span className="pulse-dot" />
          <span>{isConnected ? 'LIVE FEED ACTIVE' : 'RECONNECTING WS...'}</span>
        </div>

        {/* Authenticated User Profile & Role Indicator */}
        <div className="user-auth-section">
          {authDisabled && (
            <span className="auth-bypass-badge" title="Authentication disabled via DISABLE_AUTH=true">
              BYPASS
            </span>
          )}

          <div
            className={`user-role-card ${isAdmin ? 'role-admin-card' : 'role-operator-card'}`}
            title={`Logged in as ${user?.full_name || user?.username || 'User'} (${user?.role || 'operator'})`}
          >
            {isAdmin ? (
              <div className="role-tag admin-tag">
                <ShieldCheck size={12} />
                <span>Admin</span>
              </div>
            ) : (
              <div className="role-tag operator-tag">
                <User size={12} />
                <span>Operator</span>
              </div>
            )}
            <span className="user-display-name">{user?.username || 'operator'}</span>
          </div>

          <button
            type="button"
            className="header-logout-btn"
            onClick={logout}
            title="Log out and return to secure authentication screen"
            aria-label="Logout"
          >
            <LogOut size={14} />
            <span className="logout-text">Logout</span>
          </button>
        </div>
      </div>
    </header>
  );
}
