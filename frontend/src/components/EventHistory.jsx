import React, { useState, useEffect } from 'react';
import {
  History,
  Search,
  Filter,
  RefreshCw,
  Eye,
  User,
  Bus,
  Car,
  Truck,
  ShieldCheck,
  ShieldAlert,
  Lock,
  CheckCircle2,
  AlertTriangle,
  Clock,
  Check,
  FileText,
  Copy,
  X,
} from 'lucide-react';
import { fetchEvents, getSnapshotUrl, fetchAuditVerification, fetchAuditCertificate } from '../services/api';

export default function EventHistory({ onSelectEvent }) {
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [severityFilter, setSeverityFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [classFilter, setClassFilter] = useState('');

  // Tamper-evident audit verification state
  const [verifyingAudit, setVerifyingAudit] = useState(false);
  const [auditResult, setAuditResult] = useState(null);
  const [certificateData, setCertificateData] = useState(null);
  const [copiedCert, setCopiedCert] = useState(false);

  const loadHistory = async () => {
    setLoading(true);
    try {
      const data = await fetchEvents({
        limit: 100,
        severity: severityFilter || undefined,
        event_type: typeFilter || undefined,
        object_class: classFilter || undefined,
      });
      setEvents(data.events || []);
    } catch (err) {
      console.error('Error fetching history:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleVerifyAudit = async () => {
    setVerifyingAudit(true);
    try {
      const res = await fetchAuditVerification();
      setAuditResult(res);
    } catch (err) {
      setAuditResult({
        valid: false,
        reason: 'Failed to contact audit verification endpoint',
        error: err.message,
      });
    } finally {
      setVerifyingAudit(false);
    }
  };

  const handleOpenCertificate = async () => {
    try {
      const cert = await fetchAuditCertificate();
      setCertificateData(cert);
    } catch (err) {
      alert('Failed to generate audit certificate: ' + err.message);
    }
  };

  const handleCopyCertificate = () => {
    if (!certificateData) return;
    navigator.clipboard.writeText(JSON.stringify(certificateData, null, 2));
    setCopiedCert(true);
    setTimeout(() => setCopiedCert(false), 2000);
  };

  useEffect(() => {
    loadHistory();
  }, [severityFilter, typeFilter, classFilter]);

  const filteredEvents = events.filter((ev) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      ev.object_class?.toLowerCase().includes(q) ||
      String(ev.track_id).includes(q) ||
      ev.event_id?.toLowerCase().includes(q) ||
      ev.event_type?.toLowerCase().includes(q) ||
      ev.event_hash?.toLowerCase().includes(q) ||
      ev.identified_as?.toLowerCase().includes(q) ||
      ev.plate_number?.toLowerCase().includes(q)
    );
  });

  return (
    <div className="panel-card" role="region" aria-label="Event Forensics and Audit Log">
      <div className="panel-header">
        <div className="panel-title">
          <History size={18} style={{ color: '#0ea5e9' }} />
          Perimeter Event Forensics & Audit Log
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
          {/* Cryptographic SHA-256 Audit Trail Verification Trigger */}
          <button
            onClick={handleVerifyAudit}
            disabled={verifyingAudit}
            style={{
              background: 'rgba(14, 165, 233, 0.14)',
              border: '1px solid rgba(14, 165, 233, 0.45)',
              color: '#38bdf8',
              padding: '0.4rem 0.9rem',
              borderRadius: 'var(--radius-sm)',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '0.45rem',
              fontSize: '0.8rem',
              fontWeight: 700,
              transition: 'all 0.2s ease',
            }}
            title="Cryptographically verify SHA-256 blockchain-style hash chain integrity across all events"
          >
            <ShieldCheck size={15} className={verifyingAudit ? 'pulse-dot' : ''} />
            <span>{verifyingAudit ? 'Verifying Chain...' : 'Verify Audit Trail'}</span>
          </button>

          <button
            onClick={loadHistory}
            style={{
              background: 'rgba(255, 255, 255, 0.04)',
              border: '1px solid var(--border-subtle)',
              color: 'var(--text-secondary)',
              padding: '0.4rem 0.85rem',
              borderRadius: 'var(--radius-sm)',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '0.4rem',
              fontSize: '0.8rem',
              fontWeight: 600,
              transition: 'all 0.2s ease',
            }}
          >
            <RefreshCw size={14} className={loading ? 'pulse-dot' : ''} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* Cryptographic Audit Verification Banner */}
      {auditResult && (
        <div
          style={{
            padding: '0.85rem 1.25rem',
            margin: '0.85rem 1.25rem 0.25rem',
            borderRadius: 'var(--radius-md)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: auditResult.valid ? 'rgba(16, 185, 129, 0.12)' : 'rgba(239, 68, 68, 0.15)',
            border: `1px solid ${auditResult.valid ? 'rgba(16, 185, 129, 0.45)' : 'rgba(239, 68, 68, 0.5)'}`,
            color: auditResult.valid ? '#34d399' : '#f87171',
            boxShadow: `0 4px 16px ${auditResult.valid ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.2)'}`,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem', fontSize: '0.85rem' }}>
            {auditResult.valid ? <CheckCircle2 size={22} /> : <AlertTriangle size={22} />}
            <div>
              <div style={{ fontWeight: 700, fontSize: '0.92rem' }}>
                {auditResult.valid
                  ? 'Cryptographic Audit Trail Verified — No Tampering Detected'
                  : 'SECURITY ALERT: Tampering Detected in Audit Log!'}
              </div>
              <div
                style={{
                  fontSize: '0.78rem',
                  color: auditResult.valid ? '#a7f3d0' : '#fca5a5',
                  marginTop: '3px',
                  fontFamily: 'var(--font-mono)',
                }}
              >
                {auditResult.valid ? (
                  <>
                    ✓ Validated {auditResult.total_events_checked} chained security event blocks via SHA-256 hash sequence.
                    {auditResult.latest_block_hash && ` (Latest Block: ${auditResult.latest_block_hash.slice(0, 16)}...)`}
                  </>
                ) : (
                  <>
                    ⚠ Compromised at Block #{auditResult.tampered_at_position} (UUID: {auditResult.first_tampered_event_id}) — {auditResult.reason}
                  </>
                )}
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            {auditResult.valid && (
              <button
                onClick={handleOpenCertificate}
                style={{
                  background: 'rgba(16, 185, 129, 0.25)',
                  border: '1px solid #10b981',
                  color: '#fff',
                  cursor: 'pointer',
                  fontSize: '0.78rem',
                  fontWeight: 700,
                  padding: '0.35rem 0.75rem',
                  borderRadius: 'var(--radius-sm)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.35rem',
                }}
              >
                <FileText size={14} />
                <span>View Official Certificate</span>
              </button>
            )}

            <button
              onClick={() => setAuditResult(null)}
              style={{
                background: 'rgba(255, 255, 255, 0.1)',
                border: 'none',
                color: 'inherit',
                cursor: 'pointer',
                fontSize: '0.78rem',
                fontWeight: 600,
                padding: '0.35rem 0.6rem',
                borderRadius: 'var(--radius-sm)',
              }}
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      <div className="history-controls">
        <input
          type="text"
          className="search-input"
          placeholder="Search by Track ID, Class, UUID, Identity or SHA-256 Hash..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />

        <select
          className="filter-select"
          value={severityFilter}
          onChange={(e) => setSeverityFilter(e.target.value)}
          aria-label="Filter by Severity"
        >
          <option value="">All Severities</option>
          <option value="high">High Severity (Intrusion / Alert)</option>
          <option value="medium">Medium Severity (Vehicle)</option>
          <option value="low">Low Severity (Authorized / Exit)</option>
        </select>

        <select
          className="filter-select"
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          aria-label="Filter by Event Type"
        >
          <option value="">All Event Types</option>
          <option value="zone_entry">Zone Entry / Intrusion</option>
          <option value="zone_exit">Zone Exit</option>
          <option value="suspicious_loitering">Suspicious Loitering</option>
          <option value="suspicious_pacing">Suspicious Pacing</option>
        </select>

        <select
          className="filter-select"
          value={classFilter}
          onChange={(e) => setClassFilter(e.target.value)}
          aria-label="Filter by Target Class"
        >
          <option value="">All Classes</option>
          <option value="person">Person</option>
          <option value="bus">Bus</option>
          <option value="car">Car</option>
          <option value="truck">Truck</option>
        </select>
      </div>

      <div className="events-table-wrapper">
        <table className="events-table">
          <thead>
            <tr>
              <th>Preview</th>
              <th>Frame</th>
              <th>Severity</th>
              <th>Event Type</th>
              <th>Target</th>
              <th>Confidence</th>
              <th>Timestamp (UTC)</th>
              <th>SHA-256 Block Hash</th>
              <th>Event UUID</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              // Table Skeleton Rows
              [1, 2, 3, 4, 5].map((n) => (
                <tr key={n}>
                  <td>
                    <div className="skeleton" style={{ width: 44, height: 32, borderRadius: 4 }} />
                  </td>
                  <td>
                    <div className="skeleton" style={{ width: 50, height: 14 }} />
                  </td>
                  <td>
                    <div className="skeleton" style={{ width: 60, height: 16 }} />
                  </td>
                  <td>
                    <div className="skeleton" style={{ width: 90, height: 14 }} />
                  </td>
                  <td>
                    <div className="skeleton" style={{ width: 110, height: 14 }} />
                  </td>
                  <td>
                    <div className="skeleton" style={{ width: 45, height: 14 }} />
                  </td>
                  <td>
                    <div className="skeleton" style={{ width: 120, height: 14 }} />
                  </td>
                  <td>
                    <div className="skeleton" style={{ width: 80, height: 14 }} />
                  </td>
                  <td>
                    <div className="skeleton" style={{ width: 70, height: 14 }} />
                  </td>
                </tr>
              ))
            ) : filteredEvents.length === 0 ? (
              <tr>
                <td colSpan={9} style={{ textAlign: 'center', padding: '3rem 1.5rem', color: 'var(--text-muted)' }}>
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.5rem' }}>
                    <History size={32} style={{ opacity: 0.5 }} />
                    <span style={{ fontWeight: 600, fontSize: '0.95rem', color: 'var(--text-secondary)' }}>
                      No Forensic Events Found
                    </span>
                    <span style={{ fontSize: '0.8rem' }}>Try adjusting your search query or filter options.</span>
                  </div>
                </td>
              </tr>
            ) : (
              filteredEvents.map((ev) => (
                <tr key={ev.event_id} onClick={() => onSelectEvent(ev)}>
                  <td>
                    <div
                      style={{
                        width: '46px',
                        height: '32px',
                        borderRadius: '4px',
                        overflow: 'hidden',
                        background: '#000',
                        border: '1px solid var(--border-subtle)',
                      }}
                    >
                      <img
                        src={getSnapshotUrl(ev.event_id)}
                        alt="thumb"
                        style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                        onError={(e) => {
                          e.target.onerror = null;
                          e.target.src =
                            'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="46" height="32" fill="%230d152a"/>';
                        }}
                      />
                    </div>
                  </td>
                  <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: '#f8fafc' }}>
                    #{ev.frame_number}
                  </td>
                  <td>
                    <span className={`badge-sev ${ev.severity}`}>
                      {ev.severity?.toUpperCase()}
                    </span>
                  </td>
                  <td>
                    <span
                      style={{
                        fontWeight: 700,
                        color:
                          ev.event_type === 'zone_entry'
                            ? (ev.object_class === 'person' && ev.identified_as && ev.identified_as !== 'UNKNOWN' ? '#34d399' : '#f87171')
                            : ev.event_type === 'suspicious_loitering'
                            ? '#fbbf24'
                            : ev.event_type === 'suspicious_pacing'
                            ? '#fb923c'
                            : ev.event_type === 'auth_login_success'
                            ? '#38bdf8'
                            : ev.event_type === 'auth_login_failed'
                            ? '#ef4444'
                            : '#34d399',
                      }}
                    >
                      {ev.event_type === 'zone_entry'
                        ? (ev.object_class === 'person' && ev.identified_as && ev.identified_as !== 'UNKNOWN' ? 'AUTHORIZED ACCESS' : 'ZONE INTRUSION')
                        : ev.event_type === 'suspicious_loitering'
                        ? 'LOITERING'
                        : ev.event_type === 'suspicious_pacing'
                        ? 'PACING'
                        : ev.event_type === 'auth_login_success'
                        ? 'AUTH LOGIN'
                        : ev.event_type === 'auth_login_failed'
                        ? 'AUTH FAILED'
                        : 'ZONE EXIT'}
                    </span>
                  </td>
                  <td>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '5px', flexWrap: 'wrap' }}>
                      <span style={{ fontWeight: 700, color: '#fff' }}>
                        {ev.camera_id === 'SYSTEM_AUTH' ? 'OPERATOR AUTH' : `${ev.object_class?.toUpperCase()} #${ev.track_id}`}
                      </span>
                      {ev.identified_as && ev.identified_as !== 'UNKNOWN' && (
                        <span className="badge-chip identity" style={{ fontSize: '0.68rem', padding: '0.1rem 0.35rem' }}>
                          {ev.identified_as}
                        </span>
                      )}
                      {ev.plate_number && (
                        <span className="badge-chip plate" style={{ fontSize: '0.68rem', padding: '0.1rem 0.35rem' }}>
                          {ev.plate_number}
                        </span>
                      )}
                    </div>
                  </td>
                  <td style={{ fontFamily: 'var(--font-mono)', color: '#0ea5e9', fontWeight: 600 }}>
                    {(ev.confidence * 100).toFixed(1)}%
                  </td>
                  <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }}>
                    {ev.timestamp ? ev.timestamp.replace('T', ' ').slice(0, 19) : ''}
                  </td>
                  <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.76rem', color: '#38bdf8' }} title={ev.event_hash || 'Genesis Block'}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                      <Lock size={12} style={{ color: '#38bdf8', opacity: 0.75 }} />
                      <span>{ev.event_hash ? `${ev.event_hash.slice(0, 8)}...` : 'GENESIS'}</span>
                    </div>
                  </td>
                  <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.74rem', color: 'var(--text-muted)' }} title={ev.event_id}>
                    {ev.event_id.slice(0, 8)}...
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Official Forensic Digital Certificate Modal */}
      {certificateData && (
        <div
          className="modal-backdrop"
          onClick={() => setCertificateData(null)}
          role="dialog"
          aria-modal="true"
        >
          <div
            className="modal-content"
            onClick={(e) => e.stopPropagation()}
            style={{ maxWidth: '680px', border: '1px solid #10b981', background: '#0a1018' }}
          >
            <div className="modal-header" style={{ borderBottom: '1px solid rgba(16, 185, 129, 0.3)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
                <ShieldCheck size={22} style={{ color: '#10b981' }} />
                <span style={{ fontFamily: 'var(--font-heading)', fontWeight: 700, fontSize: '1.05rem', color: '#fff' }}>
                  {certificateData.title}
                </span>
              </div>
              <button
                className="close-btn"
                onClick={() => setCertificateData(null)}
                aria-label="Close Certificate Modal"
              >
                <X size={20} />
              </button>
            </div>

            <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div
                style={{
                  background: 'rgba(16, 185, 129, 0.08)',
                  border: '1px solid rgba(16, 185, 129, 0.25)',
                  padding: '1rem',
                  borderRadius: 'var(--radius-md)',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.6rem' }}>
                  <span style={{ fontSize: '0.76rem', color: '#6ee7b7', fontFamily: 'var(--font-mono)' }}>
                    CERTIFICATE ID: {certificateData.certificate_id}
                  </span>
                  <span
                    style={{
                      background: certificateData.is_valid ? '#10b981' : '#ef4444',
                      color: '#000',
                      fontWeight: 800,
                      fontSize: '0.72rem',
                      padding: '0.15rem 0.5rem',
                      borderRadius: '4px',
                      fontFamily: 'var(--font-mono)',
                    }}
                  >
                    {certificateData.integrity_status}
                  </span>
                </div>

                <div style={{ fontSize: '0.84rem', color: '#e2e8f0', lineHeight: 1.5, marginBottom: '0.75rem' }}>
                  {certificateData.compliance_statement}
                </div>

                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
                    gap: '0.6rem',
                    fontSize: '0.78rem',
                    fontFamily: 'var(--font-mono)',
                    color: '#94a3b8',
                    borderTop: '1px solid rgba(255, 255, 255, 0.08)',
                    paddingTop: '0.75rem',
                  }}
                >
                  <div>
                    <strong style={{ color: '#cbd5e1' }}>Verified Blocks:</strong> {certificateData.cryptographic_specification?.total_blocks_verified} Events
                  </div>
                  <div>
                    <strong style={{ color: '#cbd5e1' }}>Algorithm:</strong> SHA-256 Hash Chain
                  </div>
                  <div>
                    <strong style={{ color: '#cbd5e1' }}>Genesis Hash:</strong> {certificateData.cryptographic_specification?.genesis_block_hash?.slice(0, 12)}...
                  </div>
                  <div>
                    <strong style={{ color: '#cbd5e1' }}>Latest Block:</strong> {certificateData.cryptographic_specification?.latest_block_hash?.slice(0, 12)}...
                  </div>
                </div>
              </div>

              {/* Action Buttons */}
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem' }}>
                <button
                  onClick={handleCopyCertificate}
                  style={{
                    background: copiedCert ? '#10b981' : 'rgba(255, 255, 255, 0.08)',
                    border: '1px solid rgba(255, 255, 255, 0.2)',
                    color: copiedCert ? '#000' : '#fff',
                    padding: '0.5rem 1rem',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: '0.82rem',
                    fontWeight: 700,
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.4rem',
                  }}
                >
                  {copiedCert ? <Check size={15} /> : <Copy size={15} />}
                  <span>{copiedCert ? 'Copied Certificate JSON!' : 'Copy Certificate (JSON)'}</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
