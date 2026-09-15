import React, { useEffect, useState } from 'react';
import {
  X,
  ShieldAlert,
  Camera,
  Clock,
  Crosshair,
  Terminal,
  Eye,
  Lock,
  ShieldCheck,
  Play,
  Film,
  RotateCcw,
  AlertCircle,
  Loader2,
  Tv,
  ZoomIn,
  Image as ImageIcon,
} from 'lucide-react';
import { getSnapshotUrl, getEventCropUrl, getReplayVideoUrl, fetchReplayMeta } from '../services/api';

export default function SnapshotModal({ event, onClose }) {
  const [activeTab, setActiveTab] = useState('snapshot'); // 'snapshot' | 'crop' | 'replay'
  const [replayMeta, setReplayMeta] = useState(null);
  const [isLoadingReplay, setIsLoadingReplay] = useState(false);
  const [replayError, setReplayError] = useState(null);

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  if (!event) return null;

  const snapshotSrc = getSnapshotUrl(event.event_id);
  const cropSrc = getEventCropUrl(event.event_id);
  const replayVideoSrc = getReplayVideoUrl(event.event_id);

  const handleSelectReplayTab = async () => {
    if (activeTab === 'replay') {
      setActiveTab('snapshot');
      return;
    }

    setIsLoadingReplay(true);
    setReplayError(null);

    try {
      const meta = await fetchReplayMeta(event.event_id, 3.0);
      setReplayMeta(meta);
      setActiveTab('replay');
    } catch (err) {
      console.warn('Incident replay unavailable:', err);
      setReplayError(
        err.message ||
          'Incident replay is unavailable for live-only camera sessions where continuous video recording was not retained.'
      );
      setActiveTab('snapshot');
    } finally {
      setIsLoadingReplay(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose} role="dialog" aria-modal="true">
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', flexWrap: 'wrap' }}>
            <ShieldAlert size={20} style={{ color: event.severity === 'high' ? '#f87171' : event.severity === 'medium' ? '#fbbf24' : '#34d399' }} />
            <span style={{ fontFamily: 'var(--font-heading)', fontWeight: 700, fontSize: '1.1rem', color: '#fff' }}>
              Forensic Evidence Snapshot #{event.track_id} ({event.object_class?.toUpperCase()})
            </span>
            <span className={`badge-sev ${event.severity}`}>
              {event.severity?.toUpperCase()}
            </span>
          </div>

          <button className="close-btn" onClick={onClose} aria-label="Close Forensic Modal">
            <X size={20} />
          </button>
        </div>

        <div className="modal-body">
          {/* Tactical Plain-English Intelligence Summary */}
          {event.tactical_summary && (
            <div className="alert-tactical-summary" style={{ fontSize: '0.88rem', padding: '0.55rem 0.85rem' }}>
              <Terminal size={16} className="tactical-icon" />
              <span>{event.tactical_summary}</span>
            </div>
          )}

          {/* Incident Forensic View Switcher Toolbar */}
          <div className="modal-replay-toolbar" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.75rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
              {/* Tab 1: Full Scene Snapshot */}
              <button
                type="button"
                className={`replay-trigger-btn ${activeTab === 'snapshot' ? 'active-playing' : ''}`}
                onClick={() => setActiveTab('snapshot')}
                style={{ padding: '0.45rem 0.8rem', fontSize: '0.82rem' }}
              >
                <ImageIcon size={15} />
                <span>Full Scene View</span>
              </button>

              {/* Tab 2: Target Crop Zoom */}
              <button
                type="button"
                className={`replay-trigger-btn ${activeTab === 'crop' ? 'active-playing' : ''}`}
                onClick={() => setActiveTab('crop')}
                style={{ padding: '0.45rem 0.8rem', fontSize: '0.82rem' }}
              >
                <ZoomIn size={15} />
                <span>Target Crop Zoom</span>
              </button>

              {/* Tab 3: 6-Second Incident Replay */}
              <button
                type="button"
                className={`replay-trigger-btn ${activeTab === 'replay' ? 'active-playing' : ''}`}
                onClick={handleSelectReplayTab}
                disabled={isLoadingReplay}
                style={{ padding: '0.45rem 0.8rem', fontSize: '0.82rem' }}
                id="replay-incident-btn"
                aria-label="Replay Incident"
              >
                {isLoadingReplay ? (
                  <>
                    <Loader2 size={15} className="spin-icon" />
                    <span>Extracting Clip...</span>
                  </>
                ) : (
                  <>
                    <Play size={15} fill="currentColor" />
                    <span>Replay (T-3s to T+3s)</span>
                  </>
                )}
              </button>

              {activeTab === 'replay' && replayMeta && (
                <div className="replay-status-pill">
                  <Film size={14} />
                  <span>
                    {replayMeta.total_clip_frames || 180} Frames &bull; {replayMeta.duration_seconds || 6.0}s Clip
                  </span>
                </div>
              )}
            </div>

            <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
              Target Frame #{event.frame_number}
            </div>
          </div>

          {/* Graceful Fallback Notice for Live Sessions or Missing Clips */}
          {replayError && (
            <div className="replay-fallback-alert" role="alert" id="replay-fallback-banner">
              <AlertCircle size={18} className="fallback-icon" />
              <div>
                <strong style={{ color: '#fff', display: 'block', marginBottom: '2px' }}>
                  Incident Replay Notice
                </strong>
                <span>{replayError}</span>
              </div>
            </div>
          )}

          {/* Ethical & Legal Scoping Notice */}
          <div
            style={{
              fontSize: '0.76rem',
              color: '#a5f3fc',
              background: 'rgba(6, 182, 212, 0.10)',
              border: '1px solid rgba(6, 182, 212, 0.3)',
              padding: '0.5rem 0.85rem',
              borderRadius: 'var(--radius-sm)',
              display: 'flex',
              alignItems: 'center',
              gap: '0.6rem',
              lineHeight: 1.4,
            }}
          >
            <Eye size={16} style={{ color: '#22d3ee', flexShrink: 0 }} />
            <span>
              <strong>Ethical Demo Disclaimer:</strong> Facial identification evaluates strictly against a local, consented demo watchlist of authorized team members for SIH demonstration. It is <em>not connected</em> to any external government database.
            </span>
          </div>

          {/* High-Resolution Forensic Image or Synchronized Video Clip */}
          <div className="modal-img-container" id="modal-evidence-media-container" style={{ position: 'relative', minHeight: '280px', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#080d18' }}>
            {activeTab === 'replay' ? (
              <video
                key={replayVideoSrc}
                src={replayVideoSrc}
                controls
                autoPlay
                loop
                playsInline
                className="modal-replay-video"
                id="incident-replay-video-player"
                onError={() => {
                  setReplayError(
                    'Failed to stream incident video clip from server. Displaying preserved static evidence snapshot.'
                  );
                  setActiveTab('snapshot');
                }}
              />
            ) : activeTab === 'crop' ? (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px', padding: '12px' }}>
                <img
                  src={cropSrc}
                  alt={`High-res target crop of ${event.object_class} track #${event.track_id}`}
                  style={{ maxHeight: '340px', maxWidth: '100%', objectFit: 'contain', border: '2px solid #06b6d4', borderRadius: '6px', boxShadow: '0 0 20px rgba(6, 182, 212, 0.3)' }}
                  onError={(e) => {
                    e.target.onerror = null;
                    e.target.src = snapshotSrc;
                  }}
                />
                <span style={{ fontSize: '0.74rem', color: '#38bdf8', fontFamily: 'var(--font-mono)' }}>
                  [TARGET ROI CROPPED &amp; ENHANCED AT HIGH RESOLUTION]
                </span>
              </div>
            ) : (
              <img
                src={snapshotSrc}
                alt={`Forensic evidence of ${event.object_class} track #${event.track_id}`}
                style={{ maxHeight: '380px', maxWidth: '100%', objectFit: 'contain' }}
                onError={(e) => {
                  e.target.onerror = null;
                  e.target.src =
                    'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="600" height="340" fill="%230d152a"><rect width="100%" height="100%"/><text x="50%" y="50%" fill="%2364748b" dominant-baseline="middle" text-anchor="middle" font-size="14" font-family="monospace">FORENSIC SNAPSHOT NOT AVAILABLE</text></svg>';
                }}
              />
            )}
          </div>

          {/* Forensic Metadata Grid */}
          <div className="modal-metadata">
            <div>
              <span style={{ color: 'var(--text-muted)', display: 'block', fontSize: '0.68rem', fontWeight: 600 }}>
                EVENT TYPE
              </span>
              <span
                style={{
                  fontWeight: 700,
                  fontSize: '0.86rem',
                  color:
                    event.event_type === 'zone_entry'
                      ? (event.object_class === 'person' && event.identified_as && event.identified_as !== 'UNKNOWN' ? '#34d399' : '#f87171')
                      : event.event_type === 'suspicious_loitering'
                      ? '#fbbf24'
                      : event.event_type === 'suspicious_pacing'
                      ? '#fb923c'
                      : '#34d399',
                }}
              >
                {event.event_type === 'zone_entry'
                  ? (event.object_class === 'person' && event.identified_as && event.identified_as !== 'UNKNOWN' ? 'AUTHORIZED ACCESS' : 'ZONE INTRUSION')
                  : event.event_type === 'suspicious_loitering'
                  ? 'SUSPICIOUS LOITERING'
                  : event.event_type === 'suspicious_pacing'
                  ? 'SUSPICIOUS PACING'
                  : 'ZONE EXIT'}
              </span>
            </div>

            <div>
              <span style={{ color: 'var(--text-muted)', display: 'block', fontSize: '0.68rem', fontWeight: 600 }}>
                WATCHLIST IDENTITY
              </span>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontWeight: 700,
                  fontSize: '0.86rem',
                  color: event.identified_as && event.identified_as !== 'UNKNOWN' ? '#4ade80' : '#22d3ee',
                }}
              >
                {event.identified_as && event.identified_as !== 'UNKNOWN'
                  ? `${event.identified_as} (${((event.identification_confidence || 0.84) * 100).toFixed(0)}% Match)`
                  : event.face_detected
                  ? 'UNLISTED / UNKNOWN'
                  : 'NO FACE (OCCLUDED)'}
              </span>
            </div>

            <div>
              <span style={{ color: 'var(--text-muted)', display: 'block', fontSize: '0.68rem', fontWeight: 600 }}>
                TRACK ID & CLASS
              </span>
              <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: '#fff', fontSize: '0.86rem' }}>
                {event.object_class?.toUpperCase()} (ID #{event.track_id})
              </span>
            </div>

            <div>
              <span style={{ color: 'var(--text-muted)', display: 'block', fontSize: '0.68rem', fontWeight: 600 }}>
                DETECTION CONFIDENCE
              </span>
              <span style={{ fontFamily: 'var(--font-mono)', color: '#0ea5e9', fontWeight: 700, fontSize: '0.86rem' }}>
                {(event.confidence * 100).toFixed(1)}%
              </span>
            </div>

            <div>
              <span style={{ color: 'var(--text-muted)', display: 'block', fontSize: '0.68rem', fontWeight: 600 }}>
                ANPR LICENSE PLATE
              </span>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontWeight: 700,
                  fontSize: '0.86rem',
                  color: event.plate_number ? '#facc15' : '#94a3b8',
                }}
              >
                {event.plate_number
                  ? `${event.plate_number} (${((event.plate_confidence || 0.82) * 100).toFixed(0)}%)`
                  : ['car', 'bus', 'truck', 'motorcycle'].includes(event.object_class?.toLowerCase())
                  ? 'UNREADABLE / OBLIQUE'
                  : 'N/A (NON-VEHICLE)'}
              </span>
            </div>

            <div>
              <span style={{ color: 'var(--text-muted)', display: 'block', fontSize: '0.68rem', fontWeight: 600 }}>
                CAMERA SECTOR
              </span>
              <span style={{ color: 'var(--text-primary)', fontWeight: 600, fontSize: '0.86rem' }}>
                {event.camera_id} (Sector 4 Gate)
              </span>
            </div>

            <div>
              <span style={{ color: 'var(--text-muted)', display: 'block', fontSize: '0.68rem', fontWeight: 600 }}>
                FRAME NUMBER
              </span>
              <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-primary)', fontWeight: 600, fontSize: '0.86rem' }}>
                Frame #{event.frame_number}
              </span>
            </div>

            <div style={{ gridColumn: 'span 2' }}>
              <span style={{ color: 'var(--text-muted)', display: 'block', fontSize: '0.68rem', fontWeight: 600 }}>
                BOUNDING BOX COORDINATES [X1, Y1, X2, Y2]
              </span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem', color: '#cbd5e1' }}>
                {JSON.stringify(event.bbox)}
              </span>
            </div>
          </div>

          {/* Cryptographic Hash Chain Footer */}
          <div
            style={{
              fontSize: '0.76rem',
              fontFamily: 'var(--font-mono)',
              color: 'var(--text-muted)',
              wordBreak: 'break-all',
              padding: '0.75rem 0.9rem',
              background: 'rgba(0, 0, 0, 0.45)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-sm)',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.35rem',
            }}
          >
            <div>
              <span style={{ color: 'var(--text-secondary)' }}>Event UUID:</span> {event.event_id} &bull;{' '}
              <span style={{ color: 'var(--text-secondary)' }}>Timestamp:</span> {event.timestamp}
            </div>
            {event.event_hash && (
              <div style={{ color: '#38bdf8' }}>
                <span style={{ color: 'var(--text-secondary)' }}>SHA-256 Block Hash:</span> {event.event_hash}
              </div>
            )}
            {event.prev_hash && (
              <div style={{ color: '#94a3b8' }}>
                <span style={{ color: 'var(--text-secondary)' }}>Prev Block Hash:</span> {event.prev_hash}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
