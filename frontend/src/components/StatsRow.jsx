import React from 'react';
import { ShieldAlert, AlertTriangle, CheckCircle, Video, Activity, Users, ArrowDownRight, ArrowUpRight } from 'lucide-react';

export default function StatsRow({ stats }) {
  // If stats are currently loading on initial fetch, render skeleton shimmer cards
  if (!stats) {
    return (
      <div className="stats-grid" aria-label="Loading Metrics">
        {[1, 2, 3, 4, 5, 6].map((idx) => (
          <div key={idx} className="stat-card">
            <div className="stat-icon-wrapper skeleton" style={{ width: 46, height: 46 }} />
            <div className="stat-info" style={{ flex: 1, gap: '6px' }}>
              <div className="skeleton" style={{ height: 12, width: '70%' }} />
              <div className="skeleton" style={{ height: 26, width: '45%', marginTop: '4px' }} />
            </div>
          </div>
        ))}
      </div>
    );
  }

  const highCount = stats?.by_severity?.high ?? 0;
  const medCount = stats?.by_severity?.medium ?? 0;
  const lowCount = stats?.by_severity?.low ?? 0;
  const totalEvents = stats?.total_events ?? 0;
  const activeCameras = stats?.active_cameras ?? 1;
  const totalCameras = stats?.total_cameras ?? activeCameras;

  const footfall = stats?.footfall || { total_in: 0, total_out: 0, current_occupancy: 0 };
  const totalIn = footfall.total_in ?? 0;
  const totalOut = footfall.total_out ?? 0;
  const occupancy = footfall.current_occupancy ?? 0;

  return (
    <div className="stats-grid" role="region" aria-label="Real-Time Analytics Metrics" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))' }}>
      {/* Critical Intrusions */}
      <div className="stat-card" style={{ '--stat-accent': 'var(--color-high)' }}>
        <div
          className="stat-icon-wrapper"
          style={{ color: 'var(--color-high)', background: 'var(--color-high-bg)', borderColor: 'var(--color-high-border)' }}
        >
          <ShieldAlert size={22} />
        </div>
        <div className="stat-info">
          <span className="stat-label">Critical Alerts</span>
          <span className="stat-value" style={{ color: 'var(--color-high)' }}>
            {highCount}
          </span>
        </div>
      </div>

      {/* Total Detections */}
      <div className="stat-card" style={{ '--stat-accent': 'var(--border-accent)' }}>
        <div className="stat-icon-wrapper">
          <Activity size={22} />
        </div>
        <div className="stat-info">
          <span className="stat-label">Total Events</span>
          <span className="stat-value">{totalEvents}</span>
        </div>
      </div>

      {/* Sector Occupancy & Footfall */}
      <div className="stat-card" style={{ '--stat-accent': '#06b6d4' }}>
        <div
          className="stat-icon-wrapper"
          style={{ color: '#06b6d4', background: 'rgba(6, 182, 212, 0.12)', borderColor: 'rgba(6, 182, 212, 0.35)' }}
        >
          <Users size={22} />
        </div>
        <div className="stat-info">
          <span className="stat-label">Sector Occupancy</span>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.6rem', flexWrap: 'wrap' }}>
            <span className="stat-value" style={{ color: '#38bdf8' }}>
              {occupancy}
            </span>
            <span style={{ fontSize: '0.78rem', color: '#94a3b8', fontWeight: 600 }}>
              [+{totalIn} in / -{totalOut} out]
            </span>
          </div>
        </div>
      </div>

      {/* Active Surveillance Sectors */}
      <div className="stat-card" style={{ '--stat-accent': '#10b981' }}>
        <div
          className="stat-icon-wrapper"
          style={{ color: '#10b981', background: 'rgba(16, 185, 129, 0.14)', borderColor: 'rgba(16, 185, 129, 0.35)' }}
        >
          <Video size={22} />
        </div>
        <div className="stat-info">
          <span className="stat-label">Active Sectors</span>
          <span className="stat-value" style={{ fontSize: '1.35rem' }}>
            {activeCameras} / {totalCameras}{' '}
            <span style={{ fontSize: '0.8rem', color: '#34d399', fontWeight: 700, marginLeft: '0.35rem' }}>
              ONLINE
            </span>
          </span>
        </div>
      </div>
    </div>
  );
}
