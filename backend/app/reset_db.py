"""
IBVAP - Intelligent Border Video Analytics Platform
Reset Demo Data Script: Clears SQLite events table and wipes snapshot images.
"""

import sqlite3
from pathlib import Path


def reset_database():
    backend_dir = Path(__file__).resolve().parent.parent
    db_path = backend_dir / "ibvap.db"
    snapshots_dir = backend_dir / "snapshots"

    print("\n" + "=" * 60)
    print(" IBVAP - Reset Demo Data & Snapshots")
    print("=" * 60)

    # 1. Truncate SQLite events table
    if db_path.exists():
        try:
            with sqlite3.connect(db_path) as conn:
                conn.execute("DELETE FROM events;")
                try:
                    conn.execute("DELETE FROM cameras;")
                except Exception:
                    pass
                conn.commit()
            print(f"[+] Truncated all records in SQLite database: {db_path}")
        except Exception as e:
            print(f"[!] Warning: Could not truncate database: {e}")
    else:
        print(f"[*] Database file does not exist yet: {db_path}")

    # 2. Delete all snapshot images
    if snapshots_dir.exists():
        deleted_count = 0
        for img_file in snapshots_dir.glob("*.jpg"):
            try:
                img_file.unlink()
                deleted_count += 1
            except Exception as e:
                print(f"[!] Warning: Could not delete {img_file.name}: {e}")
        print(f"[+] Deleted {deleted_count} evidence snapshots in: {snapshots_dir}")
    else:
        print(f"[*] Snapshots directory does not exist: {snapshots_dir}")

    print("=" * 60)
    print(" Demo data successfully reset to clean slate.\n")


if __name__ == "__main__":
    reset_database()
