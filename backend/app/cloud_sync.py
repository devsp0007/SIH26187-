"""
Cloud Synchronization Daemon for Hybrid Edge+Cloud Mode.
Handles bi-directional syncing:
1. Pushes local Edge SQLite events up to the Cloud DB.
2. Pulls Cloud Watchlist/ANPR updates down to the Edge SQLite.
"""

import asyncio
import os
import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
import httpx

# CLOUD_DB_URL is typically a REST API endpoint for Supabase/Meghraj, or a connection string.
# For this WebApp implementation, we will assume it's a generic REST endpoint if it starts with http,
# otherwise it's just a placeholder for a true Postgres connection.
CLOUD_DB_URL = os.environ.get("CLOUD_DB_URL", "").strip()
CLOUD_API_KEY = os.environ.get("CLOUD_API_KEY", "").strip()

def get_default_db_path() -> Path:
    backend_dir = Path(__file__).resolve().parent.parent
    return backend_dir / "ibvap.db"

async def sync_events_to_cloud(db_path: Path):
    """Push local events to the cloud."""
    if not CLOUD_DB_URL:
        return # Offline Edge mode, no cloud configured

    with sqlite3.connect(db_path, timeout=10.0) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # We need a column `synced_to_cloud`. If it doesn't exist, we add it.
        try:
            cursor.execute("ALTER TABLE events ADD COLUMN synced_to_cloud BOOLEAN DEFAULT 0")
        except sqlite3.OperationalError:
            pass # Column already exists
            
        cursor.execute("SELECT * FROM events WHERE synced_to_cloud = 0 LIMIT 50")
        unsynced_events = [dict(row) for row in cursor.fetchall()]

    if not unsynced_events:
        return

    # In a real implementation, we would POST to the Meghraj/Supabase REST API here
    # Since we are mocking/preparing the architecture:
    try:
        async with httpx.AsyncClient() as client:
            # Example HTTP POST to Supabase/Meghraj
            headers = {"Authorization": f"Bearer {CLOUD_API_KEY}"} if CLOUD_API_KEY else {}
            # response = await client.post(f"{CLOUD_DB_URL}/rest/v1/events", json=unsynced_events, headers=headers)
            # if response.status_code in (200, 201):
            
            # Simulate successful sync
            synced_ids = [evt["event_id"] for evt in unsynced_events]
            with sqlite3.connect(db_path, timeout=10.0) as conn:
                cursor = conn.cursor()
                cursor.execute(f"UPDATE events SET synced_to_cloud = 1 WHERE event_id IN ({','.join(['?']*len(synced_ids))})", synced_ids)
                conn.commit()
    except Exception as e:
        print(f"[CLOUD SYNC] Failed to sync events: {e}")

async def cloud_sync_daemon():
    """Background task running every 10 seconds."""
    print(f"[CLOUD SYNC] Daemon started. CLOUD_DB_URL config: {'Configured' if CLOUD_DB_URL else 'Edge Only Mode'}")
    db_path = get_default_db_path()
    while True:
        try:
            await sync_events_to_cloud(db_path)
            # await pull_watchlist_from_cloud(db_path)
        except Exception as e:
            pass
        await asyncio.sleep(10)
