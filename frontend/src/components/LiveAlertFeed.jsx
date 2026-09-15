import React from 'react';
import {
  ShieldAlert,
  AlertTriangle,
  ArrowRightCircle,
  ArrowLeftCircle,
  Camera,
  User,
  Bus,
  Car,
  Truck,
  Clock,
  Sparkles,
  Terminal,
  ShieldCheck,
  CheckCircle2,
} from 'lucide-react';
import { getSnapshotUrl } from '../services/api';

export default function LiveAlertFeed({ events = [], onSelectEvent, isLoading = false }) {
  const getClassIcon = (cls) => {
    switch (cls?.toLowerCase()) {
      case 'person': return <User size={15} />;
      case 'bus': return <Bus size={15} />;
      case 'car': return <Car size={15} />;
      case 'truck': return <Truck size={15} />;
      default: return <AlertTriangle size={15} />;
    }
  };

  const getSeverityIcon = (sev) => {
    switch (sev?.toLowerCase()) {
      case 'high': return <ShieldAlert size={14} />;
      case 'medium': return <AlertTriangle size={14} />;
      case 'low': return <CheckCircle2 size={14} />;
      default: return <ShieldCheck size={14} />;
    }
  };

  const renderEventTypeBadge = (ev) => {
    const eventType = typeof ev === 'string' ? ev : ev?.event_type;
    const isAuthorizedEntry = (
      eventType === 'zone_entry' &&
      ev?.object_class === 'person' &&
      ev?.identified_as &&
      ev?.identified_as !== 'UNKNOWN'
    );

    if (isAuthorizedEntry) {
      return (
        <span style={{
          display: 'inline-flex', alignItems: 'center', gap: '4px',
          fontSize: '0.74rem', fontWeight: 800, color: '#34d399',
          background: 'rgba(16, 185, 129, 0.18)', border: '1px solid rgba(16, 185, 129, 0.45)',
          padding: '0.15rem 0.5rem', borderRadius: 'var(--radius-sm)'
        }}>
          <ShieldCheck size={13} /> AUTHORIZED ACCESS
        </span>
      );
    }

    switch (eventType) {
      case 'zone_entry':
        return (
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: '4px',
            fontSize: '0.74rem', fontWeight: 800, color: '#f87171',
            background: 'rgba(239, 68, 68, 0.18)', border: '1px solid rgba(239, 68, 68, 0.45)',
            padding: '0.15rem 0.5rem', borderRadius: 'var(--radius-sm)'
          }}>
            <ArrowRightCircle size={13} /> ZONE INTRUSION
          </span>
        );
      case 'zone_exit':
        return (
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: '4px',
            fontSize: '0.74rem', fontWeight: 800, color: '#34d399',
            background: 'rgba(16, 185, 129, 0.18)', border: '1px solid rgba(16, 185, 129, 0.4)',
            padding: '0.15rem 0.5rem', borderRadius: 'var(--radius-sm)'
          }}>
            <ArrowLeftCircle size={13} /> ZONE EXIT
          </span>
        );
      case 'suspicious_loitering':
        return (
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: '4px',
            fontSize: '0.74rem', fontWeight: 800, color: '#fbbf24',
            background: 'rgba(245, 158, 11, 0.20)', border: '1px solid rgba(245, 158, 11, 0.5)',
            padding: '0.15rem 0.5rem', borderRadius: 'var(--radius-sm)'
          }}>
            <Clock size={13} /> SUSPICIOUS LOITERING
          </span>
        );
      case 'suspicious_pacing':
        return (
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: '4px',
            fontSize: '0.74rem', fontWeight: 800, color: '#fb923c',
            background: 'rgba(251, 146, 60, 0.20)', border: '1px solid rgba(251, 146, 60, 0.5)',
            padding: '0.15rem 0.5rem', borderRadius: 'var(--radius-sm)'
          }}>
            <AlertTriangle size={13} /> SUSPICIOUS PACING
          </span>
        );
      case 'auth_login_success':
        return (
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: '4px',
            fontSize: '0.74rem', fontWeight: 800, color: '#38bdf8',
            background: 'rgba(14, 165, 233, 0.18)', border: '1px solid rgba(14, 165, 233, 0.45)',
            padding: '0.15rem 0.5rem', borderRadius: 'var(--radius-sm)'
          }}>
            <ShieldCheck size={13} /> AUTH LOGIN
          </span>
        );
      case 'auth_login_failed':
        return (
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: '4px',
            fontSize: '0.74rem', fontWeight: 800, color: '#ef4444',
            background: 'rgba(239, 68, 68, 0.22)', border: '1px solid rgba(239, 68, 68, 0.5)',
            padding: '0.15rem 0.5rem', borderRadius: 'var(--radius-sm)'
          }}>
            <ShieldAlert size={13} /> AUTH FAILED
          </span>
        );
      default:
        return (
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: '4px',
            fontSize: '0.74rem', fontWeight: 700, color: '#94a3b8',
            background: 'rgba(148, 163, 184, 0.15)', padding: '0.15rem 0.5rem', borderRadius: 'var(--radius-sm)'
          }}>
            {eventType?.toUpperCase()}
          </span>
        );
    }
  };

  const formatTimestamp = (isoStr) => {
    if (!isoStr) return '';
    try {
      const date = new Date(isoStr);
      return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch {
      return isoStr;
    }
  };

  return (
    <div className="panel-card" role="region" aria-label="Perimeter Threat Alert Feed">
      <div className="panel-header">
        <div className="panel-title">
          <ShieldAlert size={18} style={{ color: '#f87171' }} />
          Live Perimeter Threat Feed
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
          <Sparkles size={14} style={{ color: '#0ea5e9' }} />
          <span>Real-Time Stream ({events.length} Events)</span>
        </div>
      </div>

      <div className="alerts-list">
        {isLoading ? (
          // Skeleton Loading state
          [1, 2, 3].map((n) => (
            <div key={n} className="skeleton-card">
              <div className="skeleton skeleton-thumb" />
              <div className="skeleton-content">
                <div className="skeleton" style={{ height: 16, width: '60%' }} />
                <div className="skeleton" style={{ height: 14, width: '90%' }} />
                <div className="skeleton" style={{ height: 12, width: '40%' }} />
              </div>
            </div>
          ))
        ) : events.length === 0 ? (
          <div className="empty-state">
            <div className="empty-radar-circle">
              <ShieldCheck size={36} />
            </div>
            <div>
              <p style={{ fontWeight: 700, fontSize: '1rem', color: 'var(--text-primary)' }}>
                Perimeter Secure — Zero Intrusions Detected
              </p>
              <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginTop: '4px' }}>
                AI perimeter guard is actively monitoring Sector 4 Gate video telemetry...
              </p>
            </div>
          </div>
        ) : (
          events.map((ev) => {
            const sev = ev.severity || 'low';

            return (
              <div
                key={ev.event_id || Math.random()}
                className={`alert-card ${sev}`}
                tabIndex={0}
                role="article"
                aria-label={`Alert: ${ev.object_class} ${ev.event_type}`}
              >
                <div className="alert-main">
                  {/* Forensic Snapshot Thumbnail */}
                  <div
                    className="alert-thumbnail-container"
                    onClick={() => onSelectEvent(ev)}
                    title="Click to view full forensic snapshot & evidence modal"
                  >
                    <img
                      src={getSnapshotUrl(ev.event_id)}
                      alt={`Snapshot ${ev.object_class}`}
                      onError={(e) => {
                        e.target.onerror = null;
                        e.target.src =
                          'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="76" height="56" fill="%230d152a"><rect width="100%" height="100%"/><text x="50%" y="50%" fill="%2364748b" dominant-baseline="middle" text-anchor="middle" font-size="9" font-family="monospace">SNAPSHOT</text></svg>';
                      }}
                    />
                  </div>

                  {/* Threat Details */}
                  <div className="alert-details">
                    {/* Primary Classification Row */}
                    <div className="alert-primary-row">
                      <span className={`badge-sev ${sev}`}>
                        {getSeverityIcon(sev)}
                        {sev.toUpperCase()}
                      </span>

                      {renderEventTypeBadge(ev)}

                      <span className="badge-class">
                        {getClassIcon(ev.object_class)}
                        {ev.object_class?.toUpperCase()}
                      </span>

                      <span className="badge-track">
                        Track #{ev.track_id}
                      </span>

                      {ev.identified_as && ev.identified_as !== 'UNKNOWN' ? (
                        <span className="badge-chip identity" title="Consented Demo Watchlist Profile Match">
                          ID: {ev.identified_as}
                        </span>
                      ) : (
                        ev.face_detected && (
                          <span className="badge-chip neutral" title="Face detected — not in demo watchlist">
                            FACE: UNLISTED
                          </span>
                        )
                      )}

                      {ev.plate_number ? (
                        <span className="badge-chip plate" title="ANPR License Plate Recognized">
                          PLATE: {ev.plate_number}
                        </span>
                      ) : (
                        ['car', 'bus', 'truck', 'motorcycle'].includes(ev.object_class?.toLowerCase()) && (
                          <span className="badge-chip neutral" title="License plate unreadable">
                            PLATE: UNREADABLE
                          </span>
                        )
                      )}
                    </div>

                    {/* Plain-English Tactical Summary */}
                    {ev.tactical_summary && (
                      <div className="alert-tactical-summary">
                        <Terminal size={14} className="tactical-icon" />
                        <span>{ev.tactical_summary}</span>
                      </div>
                    )}

                    {/* Metadata Telemetry */}
                    <div className="alert-meta">
                      <span>
                        <Camera size={13} style={{ color: 'var(--color-cyan)' }} />
                        Sector 4 Gate (CAM_01)
                      </span>
                      <span>
                        <Clock size={13} />
                        {formatTimestamp(ev.timestamp)}
                      </span>
                      <span style={{ fontFamily: 'var(--font-mono)' }}>
                        Frame {ev.frame_number}
                      </span>
                      <span style={{ fontFamily: 'var(--font-mono)', color: '#38bdf8', fontWeight: 600 }}>
                        Conf: {(ev.confidence * 100).toFixed(0)}%
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
