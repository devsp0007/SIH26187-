/**
 * IBVAP Frontend API Service
 * Connects to FastAPI backend REST and WebSocket endpoints.
 * Maintains in-memory JWT session token and role authorization headers.
 */

// In browser, using relative path '' routes through Vite reverse proxy on same origin, avoiding CORB and CORS issues
export const API_BASE = typeof window !== 'undefined' ? '' : 'http://127.0.0.1:8000';
export const WS_BASE = typeof window !== 'undefined'
  ? `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`
  : 'ws://127.0.0.1:8000';

// In-memory token storage (strictly not stored in localStorage to prevent XSS token theft)
let _authToken = null;

export function setAuthToken(token) {
  _authToken = token;
}

export function getAuthToken() {
  return _authToken;
}

export function authHeaders(extraHeaders = {}) {
  const headers = { ...extraHeaders };
  if (_authToken) {
    headers['Authorization'] = `Bearer ${_authToken}`;
  }
  return headers;
}

/**
 * Validate user credentials and obtain signed JWT token.
 */
export async function loginUser(username, password) {
  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Invalid username or password');
  }

  const data = await res.json();
  if (data.access_token) {
    setAuthToken(data.access_token);
  }
  return data;
}

/**
 * Fetch profile of the currently authenticated user.
 */
export async function fetchCurrentUser() {
  const res = await fetch(`${API_BASE}/api/auth/me`, {
    headers: authHeaders(),
  });
  if (!res.ok) {
    throw new Error('Authentication session expired or invalid');
  }
  return res.json();
}

/**
 * Query backend authentication configuration (e.g. DISABLE_AUTH demo bypass status).
 */
export async function fetchAuthConfig() {
  const res = await fetch(`${API_BASE}/api/auth/config`);
  if (!res.ok) throw new Error('Failed to fetch authentication status');
  return res.json();
}

export function getLiveFeedUrl(cameraId = 'CAM_01') {
  return `${API_BASE}/api/live-feed/${cameraId}`;
}

export async function fetchStats() {
  const res = await fetch(`${API_BASE}/api/stats`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('Failed to fetch stats');
  return res.json();
}

export async function fetchSystemHealth() {
  const res = await fetch(`${API_BASE}/api/system/health`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('Failed to fetch system health');
  return res.json();
}

export async function fetchCameras() {
  const res = await fetch(`${API_BASE}/api/cameras`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('Failed to fetch cameras');
  return res.json();
}

export async function fetchEvents(params = {}) {
  const query = new URLSearchParams();
  if (params.limit) query.append('limit', params.limit);
  if (params.event_type) query.append('event_type', params.event_type);
  if (params.object_class) query.append('object_class', params.object_class);
  if (params.severity) query.append('severity', params.severity);
  if (params.camera_id) query.append('camera_id', params.camera_id);

  const res = await fetch(`${API_BASE}/api/events?${query.toString()}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('Failed to fetch events');
  return res.json();
}

export function getEventSnapshotUrl(eventId) {
  return `${API_BASE}/api/events/${eventId}/snapshot`;
}

export function getEventCropUrl(eventId) {
  return `${API_BASE}/api/events/${eventId}/crop`;
}

export function getEventReplayUrl(eventId) {
  return `${API_BASE}/api/events/${eventId}/replay`;
}

export async function fetchAuditVerification() {
  const res = await fetch(`${API_BASE}/api/audit/verify`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('Failed to verify audit chain');
  return res.json();
}

export async function fetchAuditCertificate() {
  const res = await fetch(`${API_BASE}/api/audit/certificate`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('Failed to generate audit certificate');
  return res.json();
}

export async function fetchEventById(eventId) {
  const res = await fetch(`${API_BASE}/api/events/${eventId}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Failed to fetch event ${eventId}`);
  return res.json();
}

export function getSnapshotUrl(eventId) {
  return `${API_BASE}/api/snapshots/${eventId}`;
}

export function getReplayVideoUrl(eventId, windowSeconds = 3.0) {
  return `${API_BASE}/api/events/${eventId}/replay?window=${windowSeconds}`;
}

export async function fetchReplayMeta(eventId, windowSeconds = 3.0) {
  const res = await fetch(`${API_BASE}/api/events/${eventId}/replay?format=json&window=${windowSeconds}`, {
    headers: authHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || err.message || 'Incident replay is unavailable for this session.');
  }
  return res.json();
}

export async function triggerPipeline() {
  const res = await fetch(`${API_BASE}/api/pipeline/run`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
  });
  if (!res.ok) throw new Error('Failed to trigger pipeline run');
  return res.json();
}

export async function startStream(cameraId = 'CAM_01', options = {}) {
  const res = await fetch(`${API_BASE}/api/stream/start`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({
      camera_id: cameraId,
      source: options.source !== undefined ? String(options.source) : '0',
      source_type: options.sourceType || 'webcam',
      imgsz: options.imgsz || (options.sourceType === 'webcam' ? 384 : 480),
      show_zone: options.showZone !== undefined ? options.showZone : true,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || err.message || 'Failed to start camera stream');
  }
  return res.json();
}

export async function stopStream(cameraId = 'CAM_01') {
  const res = await fetch(`${API_BASE}/api/stream/stop?camera_id=${encodeURIComponent(cameraId)}`, {
    method: 'POST',
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('Failed to stop camera stream');
  return res.json();
}

export async function fetchStreamStatus() {
  const res = await fetch(`${API_BASE}/api/stream/status`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('Failed to fetch stream status');
  return res.json();
}

export async function fetchAvailableVideos() {
  const res = await fetch(`${API_BASE}/api/stream/videos`, {
    headers: authHeaders(),
  });
  if (!res.ok) return { videos: [] };
  return res.json();
}

export async function verifyAuditTrail() {
  const res = await fetch(`${API_BASE}/api/audit/verify`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('Failed to verify cryptographic audit trail');
  return res.json();
}

// =====================================================================
// Admin Panel Management API (Admin Role Only)
// =====================================================================

export function getWatchlistPhotoUrl(filename) {
  if (!filename) return '';
  return `${API_BASE}/api/admin/watchlist/photo/${encodeURIComponent(filename)}`;
}

export async function fetchWatchlist() {
  const res = await fetch(`${API_BASE}/api/admin/watchlist`, {
    headers: authHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Failed to fetch watchlist profiles');
  }
  return res.json();
}

export async function addWatchlistPerson(formData) {
  const res = await fetch(`${API_BASE}/api/admin/watchlist`, {
    method: 'POST',
    headers: authHeaders(), // Browser automatically sets multipart boundary with FormData
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Failed to save watchlist profile');
  }
  return res.json();
}

export async function deleteWatchlistPerson(name) {
  const res = await fetch(`${API_BASE}/api/admin/watchlist/${encodeURIComponent(name)}`, {
    method: 'DELETE',
    headers: authHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to delete person '${name}'`);
  }
  return res.json();
}

export async function rescanWatchlist() {
  const res = await fetch(`${API_BASE}/api/admin/watchlist/rescan`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Failed to rescan watchlist');
  }
  return res.json();
}

export async function fetchVehicles() {
  const res = await fetch(`${API_BASE}/api/admin/vehicles`, {
    headers: authHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Failed to fetch authorized vehicles');
  }
  return res.json();
}

export async function addVehicle(vehicleData) {
  const res = await fetch(`${API_BASE}/api/admin/vehicles`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(vehicleData),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Failed to add vehicle to whitelist');
  }
  return res.json();
}

export async function deleteVehicle(plateNumber) {
  const res = await fetch(`${API_BASE}/api/admin/vehicles/${encodeURIComponent(plateNumber)}`, {
    method: 'DELETE',
    headers: authHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to delete vehicle '${plateNumber}'`);
  }
  return res.json();
}
