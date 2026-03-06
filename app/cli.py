"""CLI commands: seed-data, create-admin, etc."""
import os
from datetime import date, datetime, timezone

import click
from flask import Flask

from app.extensions import db
from app.models import (
    Customer, Role, User, Warehouse, WarehouseReceipt,
    WRStatus, QtyUnitType,
)


def register_cli(app: Flask):
    @app.cli.command("seed-data")
    def seed_data():
        """Seed initial data: warehouses, roles, admin user, sample customers & WRs."""
        _seed_warehouses()
        _seed_roles()
        _seed_admin()
        _seed_customers()
        _seed_sample_wrs()
        db.session.commit()
        click.echo("✅ Seed data loaded successfully.")

    @app.cli.command("create-admin")
    @click.argument("email")
    @click.argument("password")
    @click.argument("name")
    def create_admin(email, password, name):
        """Create an admin user: create-admin EMAIL PASSWORD NAME."""
        admin_role = Role.query.filter_by(name="admin").first()
        if not admin_role:
            admin_role = Role(name="admin", description="Full access")
            db.session.add(admin_role)
        user = User(email=email, full_name=name)
        user.set_password(password)
        user.roles.append(admin_role)
        db.session.add(user)
        db.session.commit()
        click.echo(f"✅ Admin user '{email}' created.")


def _seed_warehouses():
    if Warehouse.query.count() > 0:
        return
    db.session.add_all([
        Warehouse(code="SZX", name="Shenzhen Warehouse", city="Shenzhen", country="China"),
        Warehouse(code="MIA", name="Miami Warehouse", city="Miami", country="USA"),
    ])
    db.session.flush()
    click.echo("  → Warehouses created")


def _seed_roles():
    if Role.query.count() > 0:
        return
    for name, desc in [
        ("admin", "Full system access"),
        ("warehouse_operator", "WR and container operations"),
        ("finance", "Invoice and payment management"),
        ("readonly", "View-only access"),
    ]:
        db.session.add(Role(name=name, description=desc))
    db.session.flush()
    click.echo("  → Roles created")


def _seed_admin():
    email = os.environ.get("ADMIN_EMAIL", "admin@consolidatrack.com")
    if User.query.filter_by(email=email).first():
        return
    admin = User(email=email, full_name="System Admin")
    admin.set_password(os.environ.get("ADMIN_PASSWORD", "changeme123"))
    admin_role = Role.query.filter_by(name="admin").first()
    if admin_role:
        admin.roles.append(admin_role)
    db.session.add(admin)
    db.session.flush()
    click.echo("  → Admin user created")


def _seed_customers():
    if Customer.query.count() > 0:
        return
    db.session.add_all([
        Customer(code="ACME", name="Acme Corporation", email="ops@acme.com"),
        Customer(code="BETA", name="Beta Logistics Ltd", email="info@betalog.com"),
        Customer(code="GAMMA", name="Gamma Import/Export", email="trade@gamma.co"),
        Customer(code="DELTA", name="Delta Trading Co", email="shipping@delta.com"),
    ])
    db.session.flush()
    click.echo("  → Sample customers created")


def _seed_sample_wrs():
    if WarehouseReceipt.query.count() > 0:
        return
    szx = Warehouse.query.filter_by(code="SZX").first()
    mia = Warehouse.query.filter_by(code="MIA").first()
    acme = Customer.query.filter_by(code="ACME").first()
    beta = Customer.query.filter_by(code="BETA").first()
    gamma = Customer.query.filter_by(code="GAMMA").first()

    wrs = [
        WarehouseReceipt(
            warehouse=szx, customer=acme, wr_number="SZX-2025-0001",
            date_received=date(2025, 1, 10), commodity="Electronics - LED Panels",
            qty_total=500, qty_unit_type=QtyUnitType.CAJAS,
            cbm_total=22.5000, kg_total=4500.00, status=WRStatus.RECEIVED,
        ),
        WarehouseReceipt(
            warehouse=szx, customer=beta, wr_number="SZX-2025-0002",
            date_received=date(2025, 1, 12), commodity="Textiles - Cotton Fabric",
            qty_total=200, qty_unit_type=QtyUnitType.PALETAS,
            cbm_total=35.0000, kg_total=6800.00, status=WRStatus.RECEIVED,
        ),
        WarehouseReceipt(
            warehouse=szx, customer=gamma, wr_number="SZX-2025-0003",
            date_received=date(2025, 1, 15), commodity="Auto Parts - Brake Discs",
            qty_total=1000, qty_unit_type=QtyUnitType.UNIDADES,
            cbm_total=15.0000, kg_total=8000.00, status=WRStatus.RECEIVED,
        ),
        WarehouseReceipt(
            warehouse=mia, customer=acme, wr_number="MIA-2025-0001",
            date_received=date(2025, 1, 20), commodity="Medical Supplies",
            qty_total=300, qty_unit_type=QtyUnitType.CAJAS,
            cbm_total=18.0000, kg_total=2400.00, status=WRStatus.RECEIVED,
        ),
    ]
    db.session.add_all(wrs)
    db.session.flush()
    click.echo("  → Sample WRs created")
