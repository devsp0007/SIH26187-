import React from 'react';
import AdminPanel from './AdminPanel';
import LiveAlertFeed from './LiveAlertFeed';

export default function SupervisorPortal({ liveEvents = [] }) {
  return (
    <div className="dashboard-grid">
      <div className="feed-column" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        <div style={{ background: 'var(--bg-panel)', padding: '1rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
          <h2 style={{ fontSize: '1.2rem', fontWeight: '700', marginBottom: '1rem', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            Aggregated Cloud Alerts (All Edge Nodes)
          </h2>
          <LiveAlertFeed events={liveEvents} />
        </div>
      </div>
      
      <div className="sidebar-column" style={{ overflowY: 'auto', maxHeight: 'calc(100vh - 120px)' }}>
        <AdminPanel isSupervisorMode={true} />
      </div>
    </div>
  );
}
