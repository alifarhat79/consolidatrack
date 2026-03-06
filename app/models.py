"""SQLAlchemy models — ConsolidaTrack.

Tables:
  warehouses, customers, roles, users, user_roles,
  warehouse_receipts, containers, container_load_lines,
  container_events, freight_invoices, freight_payments,
  freight_proration, container_tracking_points, audit_log
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone
from decimal import Decimal

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db

# ── helpers ──────────────────────────────────────────────────────────
def _utcnow():
    return datetime.now(timezone.utc)


# ── ENUMS ────────────────────────────────────────────────────────────
class QtyUnitType(enum.Enum):
    CAJAS = "CAJAS"
    UNIDADES = "UNIDADES"
    PALETAS = "PALETAS"


class WRStatus(enum.Enum):
    RECEIVED = "RECEIVED"
    PARTIALLY_LOADED = "PARTIALLY_LOADED"
    LOADED = "LOADED"
    HOLD = "HOLD"
    CANCELLED = "CANCELLED"


class ContainerStatus(enum.Enum):
    PLANNED = "PLANNED"
    LOADING = "LOADING"
    CLOSED = "CLOSED"
    SHIPPED = "SHIPPED"
    ARRIVED = "ARRIVED"
    UNLOADED = "UNLOADED"


class InvoiceStatus(enum.Enum):
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class EventType(enum.Enum):
    PLANNED = "PLANNED"
    LOADING = "LOADING"
    CLOSED = "CLOSED"
    SHIPPED = "SHIPPED"
    ARRIVED = "ARRIVED"
    UNLOADED = "UNLOADED"


# ── ASSOCIATION: user ↔ role ─────────────────────────────────────────
user_roles = db.Table(
    "user_roles",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
    db.Column("role_id", db.Integer, db.ForeignKey("roles.id"), primary_key=True),
)


# ── WAREHOUSES ───────────────────────────────────────────────────────
class Warehouse(db.Model):
    __tablename__ = "warehouses"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), unique=True, nullable=False)  # SZX, MIA
    name = db.Column(db.String(100), nullable=False)
    city = db.Column(db.String(100))
    country = db.Column(db.String(100))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=_utcnow)

    warehouse_receipts = db.relationship("WarehouseReceipt", backref="warehouse", lazy="dynamic")
    containers = db.relationship("Container", backref="warehouse", lazy="dynamic")

    def __repr__(self):
        return f"<Warehouse {self.code}>"


# ── CUSTOMERS ────────────────────────────────────────────────────────
class Customer(db.Model):
    __tablename__ = "customers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False)
    email = db.Column(db.String(200))
    phone = db.Column(db.String(50))
    address = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=_utcnow)

    warehouse_receipts = db.relationship("WarehouseReceipt", backref="customer", lazy="dynamic")

    def __repr__(self):
        return f"<Customer {self.code}>"


# ── ROLES ────────────────────────────────────────────────────────────
class Role(db.Model):
    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(200))

    def __repr__(self):
        return f"<Role {self.name}>"


# ── USERS ────────────────────────────────────────────────────────────
class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(200), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name = db.Column(db.String(200), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=_utcnow)

    roles = db.relationship("Role", secondary=user_roles, backref="users")

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def has_role(self, role_name: str) -> bool:
        return any(r.name == role_name for r in self.roles)

    def __repr__(self):
        return f"<User {self.email}>"


# ── WAREHOUSE RECEIPTS (WR) ─────────────────────────────────────────
class WarehouseReceipt(db.Model):
    __tablename__ = "warehouse_receipts"

    id = db.Column(db.Integer, primary_key=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey("warehouses.id"), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False)
    wr_number = db.Column(db.String(30), unique=True, nullable=False)
    date_received = db.Column(db.Date, nullable=False)
    commodity = db.Column(db.String(300), nullable=False)
    qty_total = db.Column(db.Integer, nullable=False)
    qty_unit_type = db.Column(db.Enum(QtyUnitType), nullable=False)
    cbm_total = db.Column(db.Numeric(10, 4), nullable=False)  # m³, 4 decimals
    kg_total = db.Column(db.Numeric(10, 2), nullable=False)   # kg, 2 decimals
    notes = db.Column(db.Text)
    status = db.Column(db.Enum(WRStatus), nullable=False, default=WRStatus.RECEIVED)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    load_lines = db.relationship("ContainerLoadLine", backref="warehouse_receipt", lazy="dynamic")
    photos = db.relationship("WRPhoto", backref="warehouse_receipt", lazy="dynamic",
                              cascade="all, delete-orphan", order_by="WRPhoto.uploaded_at.desc()")

    # ── Indices ──
    __table_args__ = (
        db.Index("ix_wr_warehouse_status", "warehouse_id", "status"),
        db.Index("ix_wr_customer", "customer_id"),
        db.Index("ix_wr_date", "date_received"),
    )

    # ── Calculated available stock ──
    @property
    def qty_loaded(self) -> int:
        """Sum of qty loaded across all container load lines."""
        result = (
            db.session.query(db.func.coalesce(db.func.sum(ContainerLoadLine.qty_loaded), 0))
            .filter(ContainerLoadLine.wr_id == self.id)
            .scalar()
        )
        return int(result)

    @property
    def qty_available(self) -> int:
        return self.qty_total - self.qty_loaded

    @property
    def cbm_loaded(self):
        result = (
            db.session.query(db.func.coalesce(db.func.sum(ContainerLoadLine.cbm_loaded), 0))
            .filter(ContainerLoadLine.wr_id == self.id)
            .scalar()
        )
        return Decimal(str(result))

    @property
    def cbm_available(self):
        return Decimal(str(self.cbm_total)) - self.cbm_loaded

    @property
    def kg_loaded(self):
        result = (
            db.session.query(db.func.coalesce(db.func.sum(ContainerLoadLine.kg_loaded), 0))
            .filter(ContainerLoadLine.wr_id == self.id)
            .scalar()
        )
        return Decimal(str(result))

    @property
    def kg_available(self):
        return Decimal(str(self.kg_total)) - self.kg_loaded

    def recalc_status(self):
        """Update status based on loaded quantities."""
        loaded = self.qty_loaded
        if loaded == 0:
            if self.status not in (WRStatus.HOLD, WRStatus.CANCELLED):
                self.status = WRStatus.RECEIVED
        elif loaded >= self.qty_total:
            self.status = WRStatus.LOADED
        else:
            self.status = WRStatus.PARTIALLY_LOADED

    def __repr__(self):
        return f"<WR {self.wr_number}>"


# ── WR PHOTOS ────────────────────────────────────────────────────────
class WRPhoto(db.Model):
    __tablename__ = "wr_photos"

    id = db.Column(db.Integer, primary_key=True)
    wr_id = db.Column(db.Integer, db.ForeignKey("warehouse_receipts.id"), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    caption = db.Column(db.String(255))
    uploaded_at = db.Column(db.DateTime, default=_utcnow)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    __table_args__ = (
        db.Index("ix_wrphoto_wr", "wr_id"),
    )

    def __repr__(self):
        return f"<WRPhoto {self.filename}>"


# ── CONTAINERS ───────────────────────────────────────────────────────
class Container(db.Model):
    __tablename__ = "containers"

    id = db.Column(db.Integer, primary_key=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey("warehouses.id"), nullable=False)
    container_number = db.Column(db.String(20))  # may be TBD at PLANNED stage
    container_type = db.Column(db.String(10))     # 20, 40, 40HQ
    booking_number = db.Column(db.String(50))
    carrier = db.Column(db.String(100))           # shipping line / naviera
    forwarder = db.Column(db.String(100))
    pol = db.Column(db.String(100))               # Port of Loading
    pod = db.Column(db.String(100))               # Port of Discharge
    etd = db.Column(db.Date)                      # Estimated Time of Departure
    eta = db.Column(db.Date)                      # Estimated Time of Arrival
    status = db.Column(db.Enum(ContainerStatus), nullable=False, default=ContainerStatus.PLANNED)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    load_lines = db.relationship("ContainerLoadLine", backref="container", lazy="dynamic",
                                  cascade="all, delete-orphan")
    events = db.relationship("ContainerEvent", backref="container", lazy="dynamic",
                              order_by="ContainerEvent.event_time")
    tracking_points = db.relationship("ContainerTrackingPoint", backref="container",
                                       lazy="dynamic", order_by="ContainerTrackingPoint.timestamp")
    freight_invoices = db.relationship("FreightInvoice", backref="container", lazy="dynamic")
    photos = db.relationship("ContainerPhoto", backref="container", lazy="dynamic",
                              cascade="all, delete-orphan", order_by="ContainerPhoto.uploaded_at.desc()")
    checklist = db.relationship("ContainerCheckItem", backref="container", lazy="dynamic",
                                 cascade="all, delete-orphan", order_by="ContainerCheckItem.sort_order")

    __table_args__ = (
        db.Index("ix_container_status", "status"),
        db.Index("ix_container_warehouse", "warehouse_id"),
    )

    @property
    def total_cbm(self):
        result = (
            db.session.query(db.func.coalesce(db.func.sum(ContainerLoadLine.cbm_loaded), 0))
            .filter(ContainerLoadLine.container_id == self.id)
            .scalar()
        )
        return Decimal(str(result))

    @property
    def total_kg(self):
        result = (
            db.session.query(db.func.coalesce(db.func.sum(ContainerLoadLine.kg_loaded), 0))
            .filter(ContainerLoadLine.container_id == self.id)
            .scalar()
        )
        return Decimal(str(result))

    @property
    def is_editable(self) -> bool:
        return self.status in (ContainerStatus.PLANNED, ContainerStatus.LOADING)

    # Valid transitions
    VALID_TRANSITIONS = {
        ContainerStatus.PLANNED: [ContainerStatus.LOADING],
        ContainerStatus.LOADING: [ContainerStatus.CLOSED],
        ContainerStatus.CLOSED: [ContainerStatus.SHIPPED],
        ContainerStatus.SHIPPED: [ContainerStatus.ARRIVED],
        ContainerStatus.ARRIVED: [ContainerStatus.UNLOADED],
    }

    def can_transition_to(self, new_status: ContainerStatus) -> bool:
        return new_status in self.VALID_TRANSITIONS.get(self.status, [])

    def __repr__(self):
        return f"<Container {self.container_number or 'TBD'}>"


# ── CONTAINER PHOTOS ─────────────────────────────────────────────────
class ContainerPhoto(db.Model):
    __tablename__ = "container_photos"

    id = db.Column(db.Integer, primary_key=True)
    container_id = db.Column(db.Integer, db.ForeignKey("containers.id"), nullable=False)
    filename = db.Column(db.String(255), nullable=False)     # stored filename (UUID)
    original_name = db.Column(db.String(255), nullable=False) # original upload name
    caption = db.Column(db.String(255))
    phase = db.Column(db.String(30))                          # LOADING, CLOSED, SHIPPED...
    uploaded_at = db.Column(db.DateTime, default=_utcnow)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    __table_args__ = (
        db.Index("ix_photo_container", "container_id"),
    )

    def __repr__(self):
        return f"<ContainerPhoto {self.filename}>"


# ── CONTAINER LOAD LINES ─────────────────────────────────────────────
class ContainerLoadLine(db.Model):
    __tablename__ = "container_load_lines"

    id = db.Column(db.Integer, primary_key=True)
    container_id = db.Column(db.Integer, db.ForeignKey("containers.id"), nullable=False)
    wr_id = db.Column(db.Integer, db.ForeignKey("warehouse_receipts.id"), nullable=False)
    qty_loaded = db.Column(db.Integer, nullable=False)
    cbm_loaded = db.Column(db.Numeric(10, 4), nullable=False)
    kg_loaded = db.Column(db.Numeric(10, 2), nullable=False)
    loaded_at = db.Column(db.DateTime, default=_utcnow)
    notes = db.Column(db.Text)

    __table_args__ = (
        db.UniqueConstraint("container_id", "wr_id", name="uq_container_wr"),
        db.Index("ix_loadline_wr", "wr_id"),
        db.CheckConstraint("qty_loaded > 0", name="ck_qty_positive"),
        db.CheckConstraint("cbm_loaded >= 0", name="ck_cbm_nonneg"),
        db.CheckConstraint("kg_loaded >= 0", name="ck_kg_nonneg"),
    )

    def __repr__(self):
        return f"<LoadLine container={self.container_id} wr={self.wr_id} qty={self.qty_loaded}>"


# ── CONTAINER EVENTS ─────────────────────────────────────────────────
class ContainerEvent(db.Model):
    __tablename__ = "container_events"

    id = db.Column(db.Integer, primary_key=True)
    container_id = db.Column(db.Integer, db.ForeignKey("containers.id"), nullable=False)
    event_type = db.Column(db.Enum(EventType), nullable=False)
    event_time = db.Column(db.DateTime, nullable=False, default=_utcnow)
    notes = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    user = db.relationship("User", foreign_keys=[created_by])

    __table_args__ = (
        db.Index("ix_event_container", "container_id"),
    )


# ── CONTAINER CHECKLIST ─────────────────────────────────────────────
class ContainerCheckItem(db.Model):
    __tablename__ = "container_checklist"

    id = db.Column(db.Integer, primary_key=True)
    container_id = db.Column(db.Integer, db.ForeignKey("containers.id"), nullable=False)
    item_name = db.Column(db.String(200), nullable=False)
    is_checked = db.Column(db.Boolean, default=False)
    checked_at = db.Column(db.DateTime)
    checked_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    notes = db.Column(db.String(300))
    sort_order = db.Column(db.Integer, default=0)

    user = db.relationship("User", foreign_keys=[checked_by])

    __table_args__ = (
        db.Index("ix_checklist_container", "container_id"),
    )


# ── FREIGHT INVOICES ─────────────────────────────────────────────────
class FreightInvoice(db.Model):
    __tablename__ = "freight_invoices"

    id = db.Column(db.Integer, primary_key=True)
    container_id = db.Column(db.Integer, db.ForeignKey("containers.id"), nullable=False)
    supplier = db.Column(db.String(200), nullable=False)  # forwarder/carrier
    invoice_no = db.Column(db.String(50), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="USD")
    issue_date = db.Column(db.Date, nullable=False)
    due_date = db.Column(db.Date)
    status = db.Column(db.Enum(InvoiceStatus), nullable=False, default=InvoiceStatus.OPEN)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)

    payments = db.relationship("FreightPayment", backref="invoice", lazy="dynamic",
                                cascade="all, delete-orphan")

    __table_args__ = (
        db.Index("ix_freight_container", "container_id"),
        db.UniqueConstraint("invoice_no", name="uq_invoice_no"),
    )

    @property
    def total_paid(self):
        result = (
            db.session.query(db.func.coalesce(db.func.sum(FreightPayment.amount), 0))
            .filter(FreightPayment.freight_invoice_id == self.id)
            .scalar()
        )
        return Decimal(str(result))

    @property
    def balance(self):
        return Decimal(str(self.amount)) - self.total_paid

    def recalc_status(self):
        paid = self.total_paid
        if paid >= Decimal(str(self.amount)):
            self.status = InvoiceStatus.PAID
        elif paid > 0:
            self.status = InvoiceStatus.PARTIAL
        else:
            if self.status != InvoiceStatus.CANCELLED:
                self.status = InvoiceStatus.OPEN


# ── FREIGHT PAYMENTS ─────────────────────────────────────────────────
class FreightPayment(db.Model):
    __tablename__ = "freight_payments"

    id = db.Column(db.Integer, primary_key=True)
    freight_invoice_id = db.Column(db.Integer, db.ForeignKey("freight_invoices.id"), nullable=False)
    payment_date = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    method = db.Column(db.String(50))  # wire, check, etc.
    reference = db.Column(db.String(100))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)

    __table_args__ = (
        db.CheckConstraint("amount > 0", name="ck_payment_positive"),
    )


# ── FREIGHT PRORATION (optional) ─────────────────────────────────────
class FreightProration(db.Model):
    """Prorated freight cost per customer within a container."""
    __tablename__ = "freight_proration"

    id = db.Column(db.Integer, primary_key=True)
    container_id = db.Column(db.Integer, db.ForeignKey("containers.id"), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False)
    method = db.Column(db.String(10), nullable=False, default="CBM")  # CBM or KG
    cbm_share = db.Column(db.Numeric(10, 4))
    kg_share = db.Column(db.Numeric(10, 2))
    percentage = db.Column(db.Numeric(7, 4))  # e.g. 33.3333%
    amount = db.Column(db.Numeric(12, 2))
    currency = db.Column(db.String(3), default="USD")

    __table_args__ = (
        db.UniqueConstraint("container_id", "customer_id", name="uq_proration_container_customer"),
    )


# ── CONTAINER TRACKING POINTS ────────────────────────────────────────
class ContainerTrackingPoint(db.Model):
    __tablename__ = "container_tracking_points"

    id = db.Column(db.Integer, primary_key=True)
    container_id = db.Column(db.Integer, db.ForeignKey("containers.id"), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False)
    latitude = db.Column(db.Numeric(9, 6))   # nullable: not all events have coords
    longitude = db.Column(db.Numeric(9, 6))
    event_description = db.Column(db.String(300))
    location_name = db.Column(db.String(200))
    source = db.Column(db.String(50), default="searates")
    raw_payload = db.Column(db.Text)  # JSON snapshot for audit
    fetched_at = db.Column(db.DateTime, default=_utcnow)

    __table_args__ = (
        db.Index("ix_tracking_container_ts", "container_id", "timestamp"),
    )


# ── AUDIT LOG ────────────────────────────────────────────────────────
class AuditLog(db.Model):
    __tablename__ = "audit_log"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    action = db.Column(db.String(50), nullable=False)  # CREATE, UPDATE, DELETE, STATUS_CHANGE
    table_name = db.Column(db.String(50), nullable=False)
    record_id = db.Column(db.Integer)
    old_values = db.Column(db.Text)  # JSON
    new_values = db.Column(db.Text)  # JSON
    ip_address = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, default=_utcnow)

    __table_args__ = (
        db.Index("ix_audit_table_record", "table_name", "record_id"),
        db.Index("ix_audit_user", "user_id"),
        db.Index("ix_audit_time", "created_at"),
    )
