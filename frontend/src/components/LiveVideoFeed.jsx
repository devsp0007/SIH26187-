import React, { useState, useRef, useEffect } from 'react';
import {
  Radio,
  Maximize2,
  Minimize2,
  RefreshCw,
  Shield,
  Activity,
  AlertTriangle,
  Layers,
  Users,
  Cpu,
  Video,
  Square,
  Play,
  Film,
  Loader2,
  Eye,
  CheckCircle,
  Clock,
} from 'lucide-react';
import {
  getLiveFeedUrl,
  fetchSystemHealth,
  startStream,
  stopStream,
  fetchStreamStatus,
  fetchAvailableVideos,
} from '../services/api';

export default function LiveVideoFeed({
  cameraId = 'CAM_01',
  cameraName = 'Sector 4 Gate',
  location = 'North Perimeter Fence - Sector 4',
  cameras = [],
  onSelectCamera,
  lastEventTime = null,
}) {
  const [streamKey, setStreamKey] = useState(Date.now());
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [hasError, setHasError] = useState(false);
  const [isLoaded, setIsLoaded] = useState(false);
  const [systemHealth, setSystemHealth] = useState(null);
  const [streamProcesses, setStreamProcesses] = useState({});
  const [availableVideos, setAvailableVideos] = useState([]);
  const [selectedVideo, setSelectedVideo] = useState('sample.mp4');
  const [isControllingStream, setIsControllingStream] = useState(false);
  const [streamMode, setStreamMode] = useState('mjpeg'); // 'mjpeg' | 'fallback_frame'
  const [showZone, setShowZone] = useState(true);
  const [activeSourceType, setActiveSourceType] = useState('test_video');
  const [manuallyStopped, setManuallyStopped] = useState(false);
  const videoContainerRef = useRef(null);
  const fallbackIntervalRef = useRef(null);

  const feedUrl = `${getLiveFeedUrl(cameraId)}?v=${streamKey}`;

  const validCameras = (cameras || []).filter(
    (c) => c?.camera_id && !c.camera_id.toUpperCase().startsWith('SYSTEM') && !c.camera_id.toUpperCase().startsWith('AUTH')
  );

  const isProcessRunning = streamProcesses[cameraId]?.running || false;
  const isCamOnline = !manuallyStopped && (isProcessRunning || (validCameras.find((c) => c.camera_id === cameraId)?.status === 'online'));

  // Load available test videos on mount
  useEffect(() => {
    fetchAvailableVideos()
      .then((data) => {
        if (data?.videos && data.videos.length > 0) {
          setAvailableVideos(data.videos);
        }
      })
      .catch(() => {});
  }, []);

  // Poll system health & process status at a reasonable, low-overhead interval (3.5s)
  useEffect(() => {
    let isMounted = true;
    const pollStatus = async () => {
      try {
        const [healthData, procStatus] = await Promise.all([
          fetchSystemHealth().catch(() => null),
          fetchStreamStatus().catch(() => ({})),
        ]);
        if (isMounted) {
          if (healthData) setSystemHealth(healthData);
          if (procStatus) setStreamProcesses(procStatus);
        }
      } catch {
        // Silently handle polling errors
      }
    };
    pollStatus();
    const interval = setInterval(pollStatus, 3500);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  const camTelemetry = systemHealth?.camera_telemetry?.[cameraId] || {
    footfall_in: 0,
    footfall_out: 0,
    occupancy: 0,
    fps: 0.0,
  };

  // Reset loading state and gracefully clear error when switching camera
  useEffect(() => {
    setIsLoaded(false);
    setHasError(false);
    setManuallyStopped(false);
    setStreamKey(Date.now());
  }, [cameraId]);

  // Gracefully transition out the loader after 700ms so MJPEG stream is never hidden behind spinner
  useEffect(() => {
    const timer = setTimeout(() => {
      setIsLoaded(true);
    }, 700);
    return () => clearTimeout(timer);
  }, [streamKey]);

  // Handle fallback polling if MJPEG fails in browser
  useEffect(() => {
    if (streamMode === 'fallback_frame' && !manuallyStopped) {
      const updateFrame = () => {
        setFallbackFrameUrl(`${getLiveFeedUrl(cameraId)}/frame?t=${Date.now()}`);
      };
      updateFrame();
      fallbackIntervalRef.current = setInterval(updateFrame, 200); // 5 FPS fallback
      return () => {
        if (fallbackIntervalRef.current) clearInterval(fallbackIntervalRef.current);
      };
    } else {
      if (fallbackIntervalRef.current) clearInterval(fallbackIntervalRef.current);
    }
  }, [streamMode, cameraId, manuallyStopped]);

  // 1-Click Launch or Switch Surveillance Video Feed (Continuous Loop)
  const handleStartVideoFeed = async (videoFilename = selectedVideo) => {
    setActiveSourceType('test_video');
    setManuallyStopped(false);
    setIsControllingStream(true);
    setHasError(false);
    setIsLoaded(false);
    setStreamMode('mjpeg');
    try {
      await startStream(cameraId, {
        source: videoFilename,
        sourceType: 'test_video',
        imgsz: 480,
        showZone: showZone,
      });
      // Short delay for pipeline initialization then refresh stream key
      setTimeout(() => {
        setStreamKey(Date.now());
      }, 1000);
    } catch (err) {
      alert(`Failed to start video feed: ${err.message}`);
    } finally {
      setIsControllingStream(false);
    }
  };

  // 1-Click Launch Live Webcam
  const handleStartWebcam = async () => {
    setActiveSourceType('webcam');
    setManuallyStopped(false);
    setIsControllingStream(true);
    setHasError(false);
    setIsLoaded(false);
    setStreamMode('mjpeg');
    try {
      await startStream(cameraId, {
        source: 'https://cilantro-glitter-gristle.ngrok-free.dev/video',
        sourceType: 'webcam',
        imgsz: 384,
        showZone: showZone,
      });
      setTimeout(() => {
        setStreamKey(Date.now());
      }, 1200);
    } catch (err) {
      alert(`Failed to start webcam: ${err.message}`);
    } finally {
      setIsControllingStream(false);
    }
  };

  // Toggle Virtual Fence Zone (Blue Box) ON / OFF
  const handleToggleZone = async () => {
    const nextZone = !showZone;
    setShowZone(nextZone);
    setManuallyStopped(false);
    setIsControllingStream(true);
    try {
      if (activeSourceType === 'webcam') {
        await startStream(cameraId, {
          source: 'https://cilantro-glitter-gristle.ngrok-free.dev/video',
          sourceType: 'webcam',
          imgsz: 384,
          showZone: nextZone,
        });
      } else {
        await startStream(cameraId, {
          source: selectedVideo,
          sourceType: 'test_video',
          imgsz: 480,
          showZone: nextZone,
        });
      }
      setTimeout(() => {
        setStreamKey(Date.now());
      }, 900);
    } catch (err) {
      console.error('Failed to toggle virtual fence:', err);
    } finally {
      setIsControllingStream(false);
    }
  };

  // 1-Click Stop Active Stream
  const handleStopStream = async () => {
    setIsControllingStream(true);
    try {
      await stopStream(cameraId);
      setManuallyStopped(true);
      setStreamProcesses((prev) => ({
        ...prev,
        [cameraId]: { running: false, pid: null },
      }));
    } catch (err) {
      alert(`Failed to stop stream: ${err.message}`);
    } finally {
      setIsControllingStream(false);
    }
  };

  const handleRefresh = () => {
    setManuallyStopped(false);
    setHasError(false);
    setIsLoaded(false);
    setStreamMode('mjpeg');
    setStreamKey(Date.now());
  };

  const toggleFullscreen = () => {
    if (!videoContainerRef.current) return;
    if (!document.fullscreenElement) {
      videoContainerRef.current.requestFullscreen().catch(() => {});
      setIsFullscreen(true);
    } else {
      document.exitFullscreen().catch(() => {});
      setIsFullscreen(false);
    }
  };

  const hasIntrusion = camTelemetry.occupancy > 0;

  return (
    <div className="card live-feed-card" role="region" aria-label="Live Video Surveillance Stream">
      {/* Multi-Camera Channel Switcher Tab Bar */}
      <div
        className="camera-switcher-bar"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '0.5rem',
          padding: '0.5rem 1.1rem',
          background: 'rgba(15, 23, 42, 0.75)',
          borderBottom: '1px solid var(--border-subtle)',
          overflowX: 'auto',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', color: '#38bdf8', fontSize: '0.74rem', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.05em', marginRight: '0.4rem' }}>
          <Video size={14} />
          <span>Switch Camera:</span>
        </div>
        {validCameras.map((cam) => {
          const isSelected = cam.camera_id === cameraId;
          const isRunning = streamProcesses[cam.camera_id]?.running ?? (isSelected ? !manuallyStopped : false);
          return (
            <button
              key={cam.camera_id}
              onClick={() => onSelectCamera?.(cam.camera_id)}
              type="button"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.45rem',
                padding: '0.35rem 0.85rem',
                borderRadius: 'var(--radius-sm)',
                border: isSelected ? '1.5px solid #0ea5e9' : '1px solid rgba(148, 163, 184, 0.2)',
                background: isSelected ? 'rgba(14, 165, 233, 0.25)' : 'rgba(15, 23, 42, 0.55)',
                color: isSelected ? '#38bdf8' : '#94a3b8',
                fontSize: '0.8rem',
                fontWeight: isSelected ? 800 : 500,
                cursor: 'pointer',
                transition: 'all 0.18s ease',
                whiteSpace: 'nowrap',
                boxShadow: isSelected ? '0 0 10px rgba(14, 165, 233, 0.3)' : 'none',
              }}
            >
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  backgroundColor: isRunning ? '#10b981' : '#64748b',
                  boxShadow: isRunning ? '0 0 6px #10b981' : 'none',
                }}
              />
              <span>{cam.name || cam.camera_id}</span>
            </button>
          );
        })}
      </div>

      {/* Feed Panel Header */}
      <div className="card-header live-feed-header" style={{ padding: '0.75rem 1.1rem' }}>
        <div className="live-feed-title-wrap" style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
          <div className={`status-indicator ${isCamOnline ? 'online' : 'standby'}`}>
            <span className="pulse-dot" />
            {isCamOnline ? 'SURVEILLANCE ACTIVE' : 'STANDBY'}
          </div>

          {/* Camera Selector Dropdown */}
          <div className="camera-selector-wrap">
            <Radio size={14} className="cam-icon" />
            <select
              className="camera-dropdown"
              value={cameraId}
              onChange={(e) => onSelectCamera?.(e.target.value)}
              aria-label="Select Monitored Camera"
              style={{
                background: '#0f172a',
                color: '#f8fafc',
                border: '1px solid var(--border-subtle)',
                borderRadius: '4px',
                padding: '0.2rem 0.5rem',
                fontSize: '0.8rem',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              {validCameras.map((cam) => (
                <option key={cam.camera_id} value={cam.camera_id} style={{ background: '#0f172a', color: '#f8fafc' }}>
                  {cam.name || cam.camera_id} ({cam.location || 'Perimeter Sector'})
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Action Controls & Feed Selector */}
        <div className="feed-actions" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
          {/* Quick Video Scenario Selector */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', background: '#0f172a', padding: '0.2rem 0.5rem', borderRadius: 'var(--radius-sm)', border: '1px solid rgba(56, 189, 248, 0.4)' }}>
            <Film size={13} style={{ color: '#38bdf8' }} />
            <select
              value={selectedVideo}
              onChange={(e) => {
                const vid = e.target.value;
                setSelectedVideo(vid);
                handleStartVideoFeed(vid);
              }}
              style={{
                background: '#0f172a',
                border: 'none',
                color: '#f8fafc',
                fontSize: '0.78rem',
                fontWeight: 600,
                outline: 'none',
                cursor: 'pointer',
                padding: '0.15rem 0.25rem',
              }}
              title="Select Video Surveillance Scenario"
            >
              <option value="sample.mp4" style={{ background: '#0f172a', color: '#f8fafc' }}>Sector 01 (Bus & Person Intrusion)</option>
              <option value="tracking_test.mp4" style={{ background: '#0f172a', color: '#f8fafc' }}>Sector 04 (Multi-Target Tracking)</option>
              <option value="dark_test.mp4" style={{ background: '#0f172a', color: '#f8fafc' }}>Night Vision (CLAHE Retinex)</option>
              <option value="foggy_test.mp4" style={{ background: '#0f172a', color: '#f8fafc' }}>Adverse Fog (DCP Dehazing)</option>
              <option value="suspicious_behavior_test.mp4" style={{ background: '#0f172a', color: '#f8fafc' }}>Perimeter (Loitering & Pacing)</option>
              <option value="real_footage_1.mp4" style={{ background: '#0f172a', color: '#f8fafc' }}>Outpost 01 (Real Surveillance)</option>
              <option value="real_footage_2.mp4" style={{ background: '#0f172a', color: '#f8fafc' }}>Outpost 02 (Real Surveillance)</option>
            </select>
          </div>

          {/* Play/Restart CCTV Loop Button */}
          <button
            className="icon-btn"
            onClick={() => handleStartVideoFeed(selectedVideo)}
            disabled={isControllingStream}
            title="Play / Restart Surveillance Video Loop"
            style={{
              background: 'rgba(14, 165, 233, 0.2)',
              border: '1px solid #0ea5e9',
              color: '#38bdf8',
              padding: '0.35rem 0.65rem',
              borderRadius: 'var(--radius-sm)',
              display: 'flex',
              alignItems: 'center',
              gap: '0.35rem',
              fontWeight: 700,
              fontSize: '0.78rem',
              cursor: 'pointer',
            }}
          >
            {isControllingStream ? <Loader2 size={13} className="spin-icon" /> : <Play size={13} fill="currentColor" />}
            <span>Play Feed</span>
          </button>

          {/* Webcam Button */}
          <button
            className="icon-btn"
            onClick={handleStartWebcam}
            disabled={isControllingStream}
            title="Activate Live Webcam Device"
            style={{
              background: 'rgba(16, 185, 129, 0.2)',
              border: '1px solid #10b981',
              color: '#34d399',
              padding: '0.35rem 0.65rem',
              borderRadius: 'var(--radius-sm)',
              display: 'flex',
              alignItems: 'center',
              gap: '0.35rem',
              fontWeight: 700,
              fontSize: '0.78rem',
              cursor: 'pointer',
            }}
          >
            <Video size={13} />
            <span>Webcam</span>
          </button>

          {/* Virtual Fence Zone (Blue Box) Toggle Button */}
          <button
            className="icon-btn"
            onClick={handleToggleZone}
            disabled={isControllingStream}
            title={showZone ? "Virtual Fence (Blue Box) is Active. Click to Remove / Hide." : "Virtual Fence (Blue Box) is Hidden. Click to Enable."}
            style={{
              background: showZone ? 'rgba(14, 165, 233, 0.2)' : 'rgba(100, 116, 139, 0.2)',
              border: `1px solid ${showZone ? '#38bdf8' : '#64748b'}`,
              color: showZone ? '#38bdf8' : '#94a3b8',
              padding: '0.35rem 0.65rem',
              borderRadius: 'var(--radius-sm)',
              display: 'flex',
              alignItems: 'center',
              gap: '0.35rem',
              fontWeight: 700,
              fontSize: '0.78rem',
              cursor: 'pointer',
              transition: 'all 0.2s ease',
            }}
          >
            <Shield size={13} />
            <span>{showZone ? 'Zone: ON' : 'Zone: OFF'}</span>
          </button>

          {/* Stop Stream Button */}
          {!manuallyStopped && (isProcessRunning || isCamOnline) && (
            <button
              className="icon-btn"
              onClick={handleStopStream}
              disabled={isControllingStream}
              title="Stop Camera Stream"
              style={{
                background: 'rgba(239, 68, 68, 0.2)',
                border: '1px solid #ef4444',
                color: '#f87171',
                padding: '0.35rem 0.65rem',
                borderRadius: 'var(--radius-sm)',
                display: 'flex',
                alignItems: 'center',
                gap: '0.35rem',
                fontWeight: 700,
                fontSize: '0.78rem',
                cursor: 'pointer',
              }}
            >
              <Square size={12} fill="currentColor" />
              <span>Stop</span>
            </button>
          )}

          <button
            className="icon-btn"
            onClick={handleRefresh}
            title="Refresh Stream Ingestion"
            aria-label="Refresh Camera Stream"
          >
            <RefreshCw size={14} />
          </button>
          <button
            className="icon-btn"
            onClick={toggleFullscreen}
            title={isFullscreen ? 'Exit Fullscreen' : 'Fullscreen View'}
            aria-label="Toggle Fullscreen Video View"
          >
            {isFullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>
        </div>
      </div>

      {/* Main Video Viewport */}
      <div
        ref={videoContainerRef}
        className={`live-viewport-container video-viewport ${isFullscreen ? 'fullscreen-mode' : ''}`}
      >
        {/* Optical HUD Crosshair & Reticles */}
        <div className="reticle top-left" />
        <div className="reticle top-right" />
        <div className="reticle bottom-left" />
        <div className="reticle bottom-right" />

        {/* Tactical Crosshair watermark in center */}
        <div className="tactical-crosshair" />

        {/* Loading Radar Overlay if stream is initializing */}
        {!manuallyStopped && !isLoaded && !hasError && (
          <div className="stream-loader-overlay">
            <div className="radar-spinner" />
            <div className="stream-loader-text">
              <Activity size={14} />
              SYNCING AI DETECTION STREAM...
            </div>
          </div>
        )}

        {/* Stopped Standby Screen OR Live MJPEG / Fallback Stream */}
        {manuallyStopped ? (
          <div
            className="stream-stopped-overlay"
            style={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              background: 'radial-gradient(ellipse at center, rgba(15, 23, 42, 0.96) 0%, rgba(2, 6, 23, 0.99) 100%)',
              color: '#94a3b8',
              zIndex: 5,
              textAlign: 'center',
              padding: '2rem',
            }}
          >
            <div
              style={{
                width: 68,
                height: 68,
                borderRadius: '50%',
                background: 'rgba(239, 68, 68, 0.12)',
                border: '1.5px solid rgba(239, 68, 68, 0.35)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                marginBottom: '1rem',
                boxShadow: '0 0 25px rgba(239, 68, 68, 0.25)',
              }}
            >
              <Square size={28} style={{ color: '#ef4444' }} />
            </div>
            <div style={{ color: '#f8fafc', fontSize: '1.3rem', fontWeight: 800, letterSpacing: '0.06em', marginBottom: '0.4rem' }}>
              CAMERA OFF // FEED STANDBY
            </div>
            <div style={{ fontSize: '0.85rem', color: '#64748b', maxWidth: 450, marginBottom: '1.6rem', lineHeight: 1.5 }}>
              Surveillance feed for <strong style={{ color: '#38bdf8' }}>{cameraName} ({cameraId})</strong> has been stopped by operator. Inference pipeline is completely paused with 0% CPU overhead.
            </div>
            <div style={{ display: 'flex', gap: '0.85rem', flexWrap: 'wrap', justifyContent: 'center' }}>
              <button
                onClick={() => handleStartVideoFeed(selectedVideo)}
                disabled={isControllingStream}
                style={{
                  background: 'linear-gradient(135deg, #0284c7, #0369a1)',
                  border: '1px solid #38bdf8',
                  color: '#ffffff',
                  padding: '0.6rem 1.4rem',
                  borderRadius: 'var(--radius-md)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.55rem',
                  fontWeight: 700,
                  fontSize: '0.85rem',
                  cursor: 'pointer',
                  boxShadow: '0 0 15px rgba(14, 165, 233, 0.4)',
                  transition: 'all 0.2s ease',
                }}
              >
                {isControllingStream ? <Loader2 size={15} className="spin-icon" /> : <Play size={15} fill="currentColor" />}
                <span>Resume Feed</span>
              </button>
              <button
                onClick={handleStartWebcam}
                disabled={isControllingStream}
                style={{
                  background: 'rgba(16, 185, 129, 0.15)',
                  border: '1px solid #10b981',
                  color: '#34d399',
                  padding: '0.6rem 1.3rem',
                  borderRadius: 'var(--radius-md)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.55rem',
                  fontWeight: 700,
                  fontSize: '0.85rem',
                  cursor: 'pointer',
                  transition: 'all 0.2s ease',
                }}
              >
                <Video size={15} />
                <span>Activate Webcam</span>
              </button>
            </div>
          </div>
        ) : streamMode === 'mjpeg' ? (
          <img
            key={streamKey}
            src={feedUrl}
            alt={`Live Security Stream - ${cameraId}`}
            className="live-stream-img loaded"
            onLoad={() => {
              setIsLoaded(true);
              setHasError(false);
            }}
            onError={() => {
              console.warn('[LiveFeed] MJPEG stream error, switching to frame polling fallback...');
              setStreamMode('fallback_frame');
              setIsLoaded(true);
              setHasError(false);
            }}
          />
        ) : (
          <img
            src={fallbackFrameUrl}
            alt={`Live Security Stream (Fast Frame Mode) - ${cameraId}`}
            className="live-stream-img loaded"
            onLoad={() => {
              setIsLoaded(true);
              setHasError(false);
            }}
            onError={() => {
              setHasError(true);
            }}
          />
        )}

        {/* Stream Overlay HUD (Top Bar) */}
        <div className="viewport-hud top" style={{ display: 'flex', alignItems: 'center', gap: '0.8rem', background: 'rgba(3, 7, 18, 0.75)', padding: '0.35rem 0.75rem', borderRadius: 'var(--radius-sm)', backdropFilter: 'blur(8px)' }}>
          <div className="hud-metric">
            <span className="rec-dot" style={manuallyStopped ? { background: '#64748b', boxShadow: 'none' } : {}} />
            <span className="hud-label" style={{ color: manuallyStopped ? '#94a3b8' : '#f87171', fontWeight: 800 }}>
              {manuallyStopped ? 'STANDBY' : 'LIVE'}
            </span>
            <span className="hud-val">{manuallyStopped ? 'STREAM PAUSED' : 'YOLOv8 + BYTETRACK'}</span>
          </div>
          <div className="hud-metric">
            <Layers size={12} style={{ color: '#06b6d4' }} />
            <span className="hud-label">ZONE:</span>
            <span className="hud-val">POLYGON α</span>
          </div>
          <div className="hud-metric">
            <Users size={12} style={{ color: manuallyStopped ? '#64748b' : (hasIntrusion ? '#f87171' : '#34d399') }} />
            <span className="hud-label">STATUS:</span>
            <span
              className="hud-val"
              style={{
                color: manuallyStopped ? '#64748b' : (hasIntrusion ? '#f87171' : '#34d399'),
                fontWeight: 800,
                letterSpacing: '0.04em',
              }}
            >
              {manuallyStopped ? 'CAMERA OFF' : (hasIntrusion ? `INTRUSION (${camTelemetry.occupancy})` : 'SECTOR CLEAR')}
            </span>
          </div>
        </div>

        {/* Stream Overlay HUD (Bottom Right FPS & Stream Info) */}
        <div
          style={{
            position: 'absolute',
            bottom: '12px',
            right: '12px',
            zIndex: 6,
            background: 'rgba(3, 7, 18, 0.75)',
            padding: '0.25rem 0.6rem',
            borderRadius: 'var(--radius-sm)',
            backdropFilter: 'blur(8px)',
            display: 'flex',
            alignItems: 'center',
            gap: '0.6rem',
            fontSize: '0.72rem',
            fontFamily: 'var(--font-mono)',
            color: '#94a3b8',
          }}
        >
          <span style={{ color: manuallyStopped ? '#64748b' : '#38bdf8', fontWeight: 700 }}>
            {manuallyStopped ? '0.0' : (camTelemetry.fps ? camTelemetry.fps.toFixed(1) : '30.0')} FPS
          </span>
          <span style={{ color: '#64748b' }}>|</span>
          <span>{manuallyStopped ? 'PAUSED' : 'LOOP ACTIVE'}</span>
        </div>

        {/* Fallback Display if stream disconnects */}
        {hasError && (
          <div className="stream-error-overlay">
            <AlertTriangle size={36} style={{ color: '#fbbf24', marginBottom: '0.5rem' }} />
            <div className="error-heading" style={{ fontSize: '1rem', fontWeight: 800, color: '#f8fafc' }}>
              CAMERA STREAM DISCONNECTED
            </div>
            <p className="error-sub" style={{ fontSize: '0.82rem', color: '#94a3b8', maxWidth: '400px', margin: '0.4rem auto' }}>
              The camera feed process is initializing or standby. Click below to launch the surveillance loop.
            </p>
            <div style={{ display: 'flex', gap: '0.6rem', marginTop: '0.6rem' }}>
              <button
                className="action-btn"
                onClick={() => handleStartVideoFeed(selectedVideo)}
                style={{
                  background: 'var(--border-accent)',
                  color: '#fff',
                  padding: '0.45rem 1rem',
                  borderRadius: 'var(--radius-sm)',
                  fontWeight: 700,
                  fontSize: '0.82rem',
                  cursor: 'pointer',
                  border: 'none',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.4rem',
                }}
              >
                <Play size={14} fill="currentColor" />
                Start Surveillance Loop
              </button>
              <button
                className="action-btn retry-btn"
                onClick={handleRefresh}
                style={{
                  background: 'rgba(148, 163, 184, 0.2)',
                  color: '#f8fafc',
                  padding: '0.45rem 1rem',
                  borderRadius: 'var(--radius-sm)',
                  fontWeight: 600,
                  fontSize: '0.82rem',
                  cursor: 'pointer',
                  border: '1px solid var(--border-subtle)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.4rem',
                }}
              >
                <RefreshCw size={14} />
                Retry Connection
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Feed Panel Footer */}
      <div className="live-feed-footer" style={{ padding: '0.75rem 1.1rem' }}>
        <div className="footer-meta-item">
          <Shield size={14} style={{ color: '#34d399' }} />
          <span>Surveillance Zone:</span>
          <strong style={{ color: '#f8fafc' }}>{location}</strong>
        </div>
        <div className="footer-meta-item">
          <Users size={14} style={{ color: '#06b6d4' }} />
          <span>Footfall:</span>
          <span style={{ color: '#38bdf8', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
            IN: +{camTelemetry.footfall_in} | OUT: -{camTelemetry.footfall_out}
          </span>
        </div>
        <div className="footer-meta-item">
          <Cpu size={14} style={{ color: '#a855f7' }} />
          <span>Vitals:</span>
          <span style={{ color: '#c084fc', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
            CPU {systemHealth?.cpu_percent ?? 0}% | {systemHealth?.active_streams ?? 1} STREAMS
          </span>
        </div>
      </div>
    </div>
  );
}
