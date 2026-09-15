import React from 'react';
import ReactDOMServer from 'react-dom/server';
import SnapshotModal from './src/components/SnapshotModal.jsx';
import { getSnapshotUrl, getReplayVideoUrl, fetchReplayMeta } from './src/services/api.js';

console.log("=================================================");
console.log("TESTING FRONTEND SNAPSHOT MODAL & REPLAY SERVICES");
console.log("=================================================");

// Test 1: URL Generators
const testEventId = "35cc00f8-80fa-49f1-8911-b7259ad5b1b6";
const snapshotUrl = getSnapshotUrl(testEventId);
const replayUrl = getReplayVideoUrl(testEventId, 3.0);

console.log("\n[Test 1] URL Generator Validation:");
console.log(" -> Snapshot URL:", snapshotUrl);
console.log(" -> Replay Video URL:", replayUrl);
if (snapshotUrl.includes(`/api/snapshots/${testEventId}`) && replayUrl.includes(`/api/events/${testEventId}/replay?window=3`)) {
  console.log(" [+] URL Generator Test PASSED");
} else {
  throw new Error("URL generation mismatch");
}

// Test 2: SnapshotModal Static SSR Render
console.log("\n[Test 2] Component Render Validation:");
const sampleEvent = {
  event_id: testEventId,
  camera_id: "CAM_01",
  event_type: "suspicious_loitering",
  object_class: "person",
  track_id: 3,
  frame_number: 39,
  confidence: 0.89,
  severity: "high",
  tactical_summary: "Suspicious Activity Alert: Subject (Track #3) displaying prolonged stationary presence.",
  bbox: [200, 150, 350, 400],
  timestamp: "2026-08-30T10:00:00Z",
  face_detected: false,
};

const html = ReactDOMServer.renderToString(
  React.createElement(SnapshotModal, { event: sampleEvent, onClose: () => {} })
);

console.log(" -> Rendered HTML length:", html.length);
if (html.includes("replay-incident-btn") && html.includes("Replay Incident") && html.includes("modal-img-container")) {
  console.log(" [+] SnapshotModal Replay Button and DOM Elements Rendered Successfully!");
} else {
  throw new Error("SnapshotModal failed to render replay elements");
}

console.log("\n=================================================");
console.log("FRONTEND COMPONENT & SERVICE TESTS PASSED!");
console.log("=================================================");
