"""Add container_photos table.

Run from project root:
    py add_photos_table.py
"""
import sys
sys.path.insert(0, ".")

from app import create_app
from app.extensions import db

app = create_app()

with app.app_context():
    # db.create_all() only creates tables that don't exist yet
    db.create_all()
    print("✅ All tables synced (container_photos added if missing)")
