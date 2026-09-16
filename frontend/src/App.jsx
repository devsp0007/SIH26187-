import React, { useState, useEffect, useRef } from 'react';
import { BrowserRouter, Routes, Route, Navigate, Link, useLocation } from 'react-router-dom';
import Header from './components/Header';
import StatsRow from './components/StatsRow';
import LiveAlertFeed from './components/LiveAlertFeed';
import LiveVideoFeed from './components/LiveVideoFeed';
import CameraPanel from './components/CameraPanel';
import EventHistory from './components/EventHistory';
import SnapshotModal from './components/SnapshotModal';
import LoginPage from './components/LoginPage';
import AdminPanel from './components/AdminPanel';
import SupervisorPortal from './components/SupervisorPortal';
import { AuthProvider, useAuth } from './context/AuthContext';
import { fetchStats, fetchCameras, fetchEvents, WS_BASE } from './services/api';
import voiceAlertService from './services/voiceAlertService';
import { ShieldAlert, ShieldCheck, Map, Activity, Users } from 'lucide-react';

function ProtectedRoute({ children, allowedRoles }) {
  const { isAuthenticated, user } = useAuth();
  
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  if (allowedRoles && !allowedRoles.includes(user?.role)) {
    if (user?.role === 'admin') return <Navigate to="/admin" replace />;
    if (user?.role === 'supervisor') return <Navigate to="/supervisor" replace />;
    return <Navigate to="/" replace />;
  }
  return children;
}

function GlobalWebSocketManager({ setStats, setCameras, setLiveEvents, setLastEventTime, setIsConnected, lastStatsFetchRef }) {
  const { isAuthenticated } = useAuth();
  const wsRef = useRef(null);

  useEffect(() => {
    if (!isAuthenticated) return;
    let ws = null;
    let reconnectTimeout = null;
    let pingInterval = null;
    let isCleanedUp = false;

    const connect = () => {
      if (isCleanedUp) return;
      const wsUrl = `${WS_BASE}/ws/events`;
      ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        if (isCleanedUp) { ws.close(); return; }
        setIsConnected(true);
        if (pingInterval) clearInterval(pingInterval);
        pingInterval = setInterval(() => {
          if (ws && ws.readyState === WebSocket.OPEN) {
            try { ws.send('ping'); } catch (_) {}
          }
        }, 10000);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (['connection_established', 'pong', 'ping', 'heartbeat'].includes(data.type)) return;

          if (data.type === 'camera_heartbeat') {
            setCameras((prevCams) => {
              const idx = prevCams.findIndex((c) => c.camera_id === data.camera_id);
              if (idx >= 0) {
                const copy = [...prevCams];
                copy[idx] = { ...copy[idx], status: 'online', last_seen: data.last_seen || new Date().toISOString() };
                return copy;
              }
              return [...prevCams, { camera_id: data.camera_id, name: data.name || `Sector ${data.camera_id} Gate`, location: data.location || `Perimeter ${data.camera_id}`, status: 'online', last_seen: data.last_seen || new Date().toISOString() }];
            });
            setLastEventTime(Date.now());
            return;
          }

          setLastEventTime(Date.now());
          let isNewEvent = false;
          setLiveEvents((prev) => {
            if (prev.some((e) => e.event_id === data.event_id)) return prev;
            isNewEvent = true;
            return [data, ...prev].slice(0, 40);
          });

          if (isNewEvent) voiceAlertService.announceEvent(data);

          const now = Date.now();
          if (now - lastStatsFetchRef.current >= 3500) {
            lastStatsFetchRef.current = now;
            fetchStats().then(setStats).catch(() => {});
          }
        } catch (e) {}
      };

      ws.onclose = () => {
        if (pingInterval) clearInterval(pingInterval);
        if (!isCleanedUp) {
          setIsConnected(false);
          reconnectTimeout = setTimeout(connect, 1500);
        }
      };

      ws.onerror = (err) => ws.close();
      wsRef.current = ws;
    };

    connect();

    return () => {
      isCleanedUp = true;
      if (pingInterval) clearInterval(pingInterval);
      if (reconnectTimeout) clearTimeout(reconnectTimeout);
      if (ws) { ws.onopen = null; ws.onmessage = null; ws.onerror = null; ws.onclose = null; ws.close(); }
      wsRef.current = null;
    };
  }, [isAuthenticated, setIsConnected, setStats, setCameras, setLiveEvents, setLastEventTime, lastStatsFetchRef]);

  return null;
}

function OperatorDashboard({ stats, cameras, liveEvents, lastEventTime, isLoadingInitial, setSelectedEvent, setCameras }) {
  const [selectedCameraId, setSelectedCameraId] = useState('CAM_01');
  
  const currentCam = cameras.find((c) => c.camera_id === selectedCameraId) || cameras[0] || {
    camera_id: 'CAM_01', name: 'Sector 4 Gate', location: 'North Perimeter Fence - Sector 4', status: 'online',
  };

  return (
    <>
      <StatsRow stats={stats} />
      <div className="dashboard-grid">
        <div className="feed-column">
          <LiveVideoFeed
            cameraId={currentCam.camera_id}
            cameraName={currentCam.name}
            location={currentCam.location}
            cameras={cameras}
            onSelectCamera={setSelectedCameraId}
            lastEventTime={lastEventTime}
          />
          <LiveAlertFeed
            events={liveEvents}
            onSelectEvent={setSelectedEvent}
            isLoading={isLoadingInitial}
          />
        </div>
        <div className="sidebar-column">
          <CameraPanel
            cameras={cameras}
            selectedCameraId={currentCam.camera_id}
            onSelectCamera={setSelectedCameraId}
            onPipelineTriggered={() => {}}
          />
        </div>
      </div>
    </>
  );
}

function NavigationTabs() {
  const location = useLocation();
  const { user } = useAuth();
  const role = user?.role;
  
  return (
    <div className="header-tabs" style={{ display: 'flex', gap: '1rem', padding: '0.5rem 1rem' }}>
      <Link to="/" className={`tab-btn ${location.pathname === '/' ? 'active' : ''}`}>
        <Activity size={16} /> Live Feeds
      </Link>
      <Link to="/history" className={`tab-btn ${location.pathname === '/history' ? 'active' : ''}`}>
        <Map size={16} /> Event History
      </Link>
      
      {(role === 'supervisor' || role === 'admin') && (
        <Link to="/supervisor" className={`tab-btn ${location.pathname === '/supervisor' ? 'active' : ''}`}>
          <ShieldCheck size={16} /> Supervisor Portal
        </Link>
      )}
      
      {role === 'admin' && (
        <Link to="/admin" className={`tab-btn ${location.pathname === '/admin' ? 'active' : ''}`}>
          <Users size={16} /> System Admin
        </Link>
      )}
    </div>
  );
}

function MainLayout() {
  const { isAuthenticated, isAuthLoading } = useAuth();
  const [stats, setStats] = useState(null);
  const [cameras, setCameras] = useState([]);
  const [liveEvents, setLiveEvents] = useState([]);
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [isConnected, setIsConnected] = useState(false);
  const [isLoadingInitial, setIsLoadingInitial] = useState(true);
  const [isVoiceMuted, setIsVoiceMuted] = useState(voiceAlertService.isMuted());
  const [isVoiceSpeaking, setIsVoiceSpeaking] = useState(false);
  const [lastEventTime, setLastEventTime] = useState(null);
  const lastStatsFetchRef = useRef(0);

  useEffect(() => {
    const unsubscribe = voiceAlertService.subscribe(({ isMuted, isSpeaking }) => {
      setIsVoiceMuted(isMuted);
      setIsVoiceSpeaking(isSpeaking);
    });
    return unsubscribe;
  }, []);

  useEffect(() => {
    if (!isAuthenticated) return;
    const loadData = async () => {
      try {
        const [statsData, camerasData, eventsData] = await Promise.all([
          fetchStats(), fetchCameras(), fetchEvents({ limit: 50 }),
        ]);
        const validCams = (camerasData || []).filter(
          (c) => c?.camera_id && !c.camera_id.toUpperCase().startsWith('SYSTEM') && !c.camera_id.toUpperCase().startsWith('AUTH')
        );
        setStats(statsData);
        setCameras(validCams);
        setLiveEvents(eventsData.events || []);
      } catch (err) {
      } finally {
        setIsLoadingInitial(false);
      }
    };
    loadData();
    const interval = setInterval(() => {
      fetchStats().then(setStats).catch(() => {});
      fetchCameras().then((d) => setCameras(d?.filter(c => c?.camera_id && !c.camera_id.toUpperCase().startsWith('SYSTEM') && !c.camera_id.toUpperCase().startsWith('AUTH')) || [])).catch(() => {});
    }, 2500);
    return () => clearInterval(interval);
  }, [isAuthenticated]);

  if (isAuthLoading) {
    return (
      <div className="login-loading-screen">
        <div className="login-loading-card">
          <ShieldAlert size={36} className="login-spinner-icon" />
          <div className="loading-title">Initializing IBVAP Command Core...</div>
          <div className="loading-sub">Connecting to perimeter security telemetry</div>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <LoginPage />;
  }

  return (
    <div className="app-container">
      <GlobalWebSocketManager 
        setStats={setStats} 
        setCameras={setCameras} 
        setLiveEvents={setLiveEvents} 
        setLastEventTime={setLastEventTime} 
        setIsConnected={setIsConnected} 
        lastStatsFetchRef={lastStatsFetchRef} 
      />
      <Header
        isConnected={isConnected}
        activeTab="custom" // Used to hide legacy tabs in Header component
        setActiveTab={() => {}} // Legacy
        liveCount={liveEvents.length}
        isVoiceMuted={isVoiceMuted}
        isVoiceSpeaking={isVoiceSpeaking}
        onToggleVoiceMute={() => voiceAlertService.toggleMute()}
        onTestVoice={() => voiceAlertService.testVoice()}
      />
      <div style={{ padding: '0 1rem', background: '#0f172a', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
        <NavigationTabs />
      </div>

      <main className="main-content">
        <Routes>
          <Route path="/" element={
            <ProtectedRoute>
              <OperatorDashboard 
                stats={stats} cameras={cameras} liveEvents={liveEvents} 
                lastEventTime={lastEventTime} isLoadingInitial={isLoadingInitial} 
                setSelectedEvent={setSelectedEvent} setCameras={setCameras}
              />
            </ProtectedRoute>
          } />
          
          <Route path="/history" element={
            <ProtectedRoute>
              <EventHistory onSelectEvent={setSelectedEvent} />
            </ProtectedRoute>
          } />

          <Route path="/supervisor" element={
            <ProtectedRoute allowedRoles={['supervisor', 'admin']}>
              <SupervisorPortal liveEvents={liveEvents} />
            </ProtectedRoute>
          } />

          <Route path="/admin" element={
            <ProtectedRoute allowedRoles={['admin']}>
              <AdminPanel />
            </ProtectedRoute>
          } />
          
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>

      <SnapshotModal event={selectedEvent} onClose={() => setSelectedEvent(null)} />
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <MainLayout />
      </AuthProvider>
    </BrowserRouter>
  );
}
