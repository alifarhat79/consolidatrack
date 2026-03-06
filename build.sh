#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt

# Create tables and seed admin user
python -c "
import sys
sys.path.insert(0, '.')
from app import create_app
from app.extensions import db
from app.models import User, Role

app = create_app()
with app.app_context():
    db.create_all()

    # Create default roles
    for role_name, desc in [('admin','Full access'), ('manager','Manage operations'), ('operator','Daily operations'), ('viewer','Read only')]:
        if not Role.query.filter_by(name=role_name).first():
            db.session.add(Role(name=role_name, description=desc))

    # Create admin user if none exists
    if not User.query.first():
        admin = User(email='admin@consolidatrack.com', full_name='Administrator')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.flush()
        admin_role = Role.query.filter_by(name='admin').first()
        if admin_role:
            admin.roles.append(admin_role)

    db.session.commit()
    print('Database ready!')
"
