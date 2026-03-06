import sqlite3
conn = sqlite3.connect("consolidatrack.db")
conn.execute("CREATE TABLE IF NOT EXISTS container_photos (id INTEGER PRIMARY KEY AUTOINCREMENT, container_id INTEGER NOT NULL, filename VARCHAR(255) NOT NULL, original_name VARCHAR(255) NOT NULL, caption VARCHAR(255), phase VARCHAR(30), uploaded_at DATETIME, uploaded_by INTEGER)")
conn.execute("CREATE INDEX IF NOT EXISTS ix_photo_container ON container_photos(container_id)")
conn.commit()
conn.close()
print("Done - container_photos table created!")
