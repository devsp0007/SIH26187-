"""
IBVAP - WebSocket Test Client (Step 4 Verification)

Connects to the FastAPI WebSocket server at ws://127.0.0.1:8000/ws/events,
listens for live security events emitted by the detection pipeline, and prints them formatted.
"""

import argparse
import asyncio
import json
from datetime import datetime
import websockets


async def listen_events(ws_url: str, max_events: int = 0):
    print(f"[*] Connecting to IBVAP WebSocket at: {ws_url}")
    try:
        async with websockets.connect(ws_url) as websocket:
            print("[+] Successfully connected to IBVAP Event Stream.")
            print("[*] Waiting for live security events (run detection_tracking.py to trigger events)...\n")

            event_count = 0
            while True:
                message = await websocket.recv()
                data = json.loads(message)

                if data.get("type") == "connection_established":
                    print(f"[HANDSHAKE] {data.get('message')} at {data.get('timestamp')}\n")
                    continue

                event_count += 1
                now = datetime.now().strftime("%H:%M:%S.%f")[:-3]

                event_type = data.get("event_type", "UNKNOWN")
                obj_cls = data.get("object_class", "unknown")
                track_id = data.get("track_id", "?")
                severity = data.get("severity", "info").upper()
                frame = data.get("frame_number", "?")
                event_id = data.get("event_id", "N/A")

                print(f"[{now}] [WS EVENT #{event_count}] [{severity}] {event_type.upper()} -> ID #{track_id} ({obj_cls}) @ Frame {frame}")
                print(f"    Event UUID : {event_id}")
                print(f"    BBox       : {data.get('bbox')}")
                print(f"    Snapshot   : {data.get('snapshot_path')}\n")

                if 0 < max_events <= event_count:
                    print(f"[+] Reached target count of {max_events} events. Closing connection.")
                    break

    except ConnectionRefusedError:
        print(f"[!] Error: Could not connect to {ws_url}. Is the FastAPI server running?")
    except Exception as e:
        print(f"[*] WebSocket connection ended: {e}")


def main():
    parser = argparse.ArgumentParser(description="IBVAP WebSocket Event Listener Client")
    parser.add_argument(
        "--url",
        "-u",
        type=str,
        default="ws://127.0.0.1:8000/ws/events",
        help="WebSocket URL (default: ws://127.0.0.1:8000/ws/events)",
    )
    parser.add_argument(
        "--max-events",
        "-n",
        type=int,
        default=0,
        help="Exit after receiving N events (0 for continuous listening)",
    )
    args = parser.parse_args()

    asyncio.run(listen_events(args.url, args.max_events))


if __name__ == "__main__":
    main()
