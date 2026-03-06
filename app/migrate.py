import sqlite3
conn = sqlite3.connect("consolidatrack.db")

# Force checkpoint
conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

# Backup existing events
rows = conn.execute("SELECT id, container_id, event_type, event_time, notes, created_by FROM container_events").fetchall()
print(f"Backing up {len(rows)} events...")

# Drop and recreate
conn.execute("DROP TABLE IF EXISTS container_events")
conn.execute("""CREATE TABLE container_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    container_id INTEGER NOT NULL REFERENCES containers(id),
    event_type VARCHAR(10) NOT NULL,
    old_status VARCHAR(20),
    new_status VARCHAR(20),
    event_time DATETIME NOT NULL,
    notes TEXT,
    created_by INTEGER REFERENCES users(id)
)""")
conn.execute("CREATE INDEX IF NOT EXISTS ix_event_container ON container_events(container_id)")

# Restore data
for r in rows:
    conn.execute("INSERT INTO container_events (id, container_id, event_type, old_status, new_status, event_time, notes, created_by) VALUES (?,?,?,NULL,?,?,?,?)",
                 (r[0], r[1], r[2], r[2], r[3], r[4], r[5]))
print(f"Restored {len(rows)} events")

# Create checklist table
conn.execute("""CREATE TABLE IF NOT EXISTS container_checklist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    container_id INTEGER NOT NULL REFERENCES containers(id),
    item_name VARCHAR(200) NOT NULL,
    is_checked BOOLEAN DEFAULT 0,
    checked_at DATETIME,
    checked_by INTEGER REFERENCES users(id),
    notes VARCHAR(300),
    sort_order INTEGER DEFAULT 0
)""")
conn.execute("CREATE INDEX IF NOT EXISTS ix_checklist_container ON container_checklist(container_id)")
print("container_checklist ready")

# Create wr_photos table
conn.execute("""CREATE TABLE IF NOT EXISTS wr_photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wr_id INTEGER NOT NULL REFERENCES warehouse_receipts(id),
    filename VARCHAR(255) NOT NULL,
    original_name VARCHAR(255) NOT NULL,
    caption VARCHAR(255),
    uploaded_at DATETIME,
    uploaded_by INTEGER REFERENCES users(id)
)""")
conn.execute("CREATE INDEX IF NOT EXISTS ix_wrphoto_wr ON wr_photos(wr_id)")
print("wr_photos ready")

# Final checkpoint
conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
conn.commit()
conn.close()
print("Done! Restart Flask now.")
