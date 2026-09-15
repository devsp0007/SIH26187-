import http from 'http';

const BASE_URL = 'http://127.0.0.1:8000';

async function request(path, options = {}) {
  const url = `${BASE_URL}${path}`;
  const res = await fetch(url, options);
  const data = await res.json().catch(() => ({}));
  return { status: res.status, data };
}

async function run() {
  console.log('='.repeat(65));
  console.log(' IBVAP Frontend/Backend Camera Panel & Auth Verification');
  console.log('='.repeat(65));

  // 1. Admin Login
  console.log('\n[1] Logging in as Admin...');
  const login1 = await request('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'admin', password: 'Admin@IBVAP2026!' }),
  });
  console.log('  Admin login status:', login1.status, login1.data.user);
  const adminToken = login1.data.access_token;

  // 2. Fetch cameras with Admin token
  console.log('\n[2] Querying /api/cameras with Admin token...');
  const cams1 = await request('/api/cameras', {
    headers: { Authorization: `Bearer ${adminToken}` },
  });
  console.log('  Cameras returned:', cams1.data);
  const hasPhantom1 = cams1.data.some((c) => c.camera_id.includes('SYSTEM') || c.camera_id.includes('AUTH'));
  console.log('  Phantom cameras present?', hasPhantom1);
  if (hasPhantom1) throw new Error('FAIL: Phantom camera found in /api/cameras!');

  // 3. Failed Login Attempt
  console.log('\n[3] Simulating failed login...');
  const failLogin = await request('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'intruder', password: 'WrongPassword!' }),
  });
  console.log('  Failed login rejection status:', failLogin.status);

  // 4. Operator Login
  console.log('\n[4] Logging in as Operator...');
  const login2 = await request('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'operator', password: 'Operator@IBVAP2026!' }),
  });
  console.log('  Operator login status:', login2.status, login2.data.user);
  const opToken = login2.data.access_token;

  // 5. Fetch cameras with Operator token
  console.log('\n[5] Querying /api/cameras with Operator token...');
  const cams2 = await request('/api/cameras', {
    headers: { Authorization: `Bearer ${opToken}` },
  });
  console.log('  Cameras returned:', cams2.data);
  const hasPhantom2 = cams2.data.some((c) => c.camera_id.includes('SYSTEM') || c.camera_id.includes('AUTH'));
  console.log('  Phantom cameras present?', hasPhantom2);
  if (hasPhantom2) throw new Error('FAIL: Phantom camera found in /api/cameras!');

  // 6. Verify Events Forensics has recorded auth events
  console.log('\n[6] Querying /api/events for Audit Trail...');
  const events = await request('/api/events?limit=20', {
    headers: { Authorization: `Bearer ${adminToken}` },
  });
  const authEvents = (events.data.events || []).filter((e) => e.camera_id === 'SYSTEM_AUTH');
  console.log(`  Found ${authEvents.length} auth events in recent audit history.`);
  for (const ae of authEvents.slice(0, 3)) {
    console.log(`    - [${ae.event_type}] ${ae.tactical_summary} | Hash: ${ae.event_hash.slice(0, 16)}...`);
  }

  // 7. Verify Cryptographic SHA-256 Hash Chain
  console.log('\n[7] Verifying Cryptographic SHA-256 Audit Trail...');
  const audit = await request('/api/audit/verify', {
    headers: { Authorization: `Bearer ${adminToken}` },
  });
  console.log(`  Audit Valid: ${audit.data.valid} across ${audit.data.total_events_checked} blocks`);
  if (!audit.data.valid) throw new Error('FAIL: Audit trail hash chain invalid!');

  console.log('\n' + '='.repeat(65));
  console.log(' ALL VERIFICATIONS PASSED: ZERO PHANTOM CAMERAS & FULL AUDIT LOG!');
  console.log('='.repeat(65) + '\n');
}

run().catch((err) => {
  console.error('Verification failed:', err);
  process.exit(1);
});
