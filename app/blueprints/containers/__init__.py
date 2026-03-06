"""Containers blueprint — CRUD, loading (full/partial), events, closing, photos."""
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, request, url_for, current_app, send_from_directory
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import (
    AuditLog, Container, ContainerCheckItem, ContainerEvent, ContainerLoadLine,
    ContainerPhoto, ContainerStatus, EventType, Warehouse, WarehouseReceipt, WRStatus,
)

containers_bp = Blueprint("containers", __name__, template_folder="../../templates/containers")


def _parse_date(value):
    """Parse a date string (YYYY-MM-DD) into a Python date object, or None."""
    if not value or not value.strip():
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


# ── HELPERS ──────────────────────────────────────────────────────────
def _validate_proportional(wr, qty_loaded, cbm_loaded, kg_loaded, tolerance=None):
    """Validate that manually entered cbm/kg are proportional to qty within tolerance."""
    if tolerance is None:
        tolerance = current_app.config.get("PROPORTIONAL_TOLERANCE", 0.01)

    ratio = Decimal(str(qty_loaded)) / Decimal(str(wr.qty_total))
    expected_cbm = Decimal(str(wr.cbm_total)) * ratio
    expected_kg = Decimal(str(wr.kg_total)) * ratio

    cbm_diff = abs(Decimal(str(cbm_loaded)) - expected_cbm)
    kg_diff = abs(Decimal(str(kg_loaded)) - expected_kg)

    errors = []
    if expected_cbm > 0 and cbm_diff / expected_cbm > Decimal(str(tolerance)):
        errors.append(
            f"CBM loaded ({cbm_loaded}) differs from proportional ({expected_cbm:.4f}) "
            f"by more than {tolerance*100}%."
        )
    if expected_kg > 0 and kg_diff / expected_kg > Decimal(str(tolerance)):
        errors.append(
            f"KG loaded ({kg_loaded}) differs from proportional ({expected_kg:.2f}) "
            f"by more than {tolerance*100}%."
        )
    return errors


def _calc_proportional(wr, qty_loaded):
    """Calculate proportional cbm/kg for a given qty_loaded."""
    ratio = Decimal(str(qty_loaded)) / Decimal(str(wr.qty_total))
    cbm = (Decimal(str(wr.cbm_total)) * ratio).quantize(Decimal("0.0001"))
    kg = (Decimal(str(wr.kg_total)) * ratio).quantize(Decimal("0.01"))
    return cbm, kg


# ── LIST ─────────────────────────────────────────────────────────────
@containers_bp.route("/")
@login_required
def container_list():
    query = Container.query
    status = request.args.get("status")
    cust_filter = request.args.get("carrier")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")

    if status:
        query = query.filter_by(status=ContainerStatus(status))
    if cust_filter:
        query = query.filter(Container.carrier.ilike(f"%{cust_filter}%"))

    containers = query.order_by(Container.updated_at.desc()).all()
    warehouses = Warehouse.query.filter_by(is_active=True).all()

    # Group by warehouse
    from collections import OrderedDict
    containers_by_wh = OrderedDict()
    for wh in warehouses:
        containers_by_wh[wh.code] = {
            "warehouse": wh,
            "containers": [c for c in containers if c.warehouse_id == wh.id],
        }

    # Unique forwarders for datalist
    fwd_rows = db.session.query(Container.forwarder).filter(
        Container.forwarder.isnot(None)
    ).distinct().all()
    forwarders = sorted(set(r[0] for r in fwd_rows if r[0]))

    return render_template(
        "containers/list.html",
        containers_by_wh=containers_by_wh,
        warehouses=warehouses,
        forwarders=forwarders,
        filters=request.args,
    )


# ── CREATE ───────────────────────────────────────────────────────────
@containers_bp.route("/create", methods=["GET", "POST"])
@login_required
def container_create():
    warehouses = Warehouse.query.filter_by(is_active=True).all()
    if request.method == "POST":
        container = Container(
            warehouse_id=int(request.form["warehouse_id"]),
            container_number=request.form.get("container_number", "").strip() or None,
            container_type=request.form.get("container_type", "").strip() or None,
            booking_number=request.form.get("booking_number", "").strip() or None,
            carrier=request.form.get("carrier", "").strip() or None,
            forwarder=request.form.get("forwarder", "").strip() or None,
            pol=request.form.get("pol", "").strip() or None,
            pod=request.form.get("pod", "").strip() or None,
            notes=request.form.get("notes", "").strip() or None,
            status=ContainerStatus.PLANNED,
        )
        # ETD/ETA optional — parse string to date object
        container.etd = _parse_date(request.form.get("etd"))
        container.eta = _parse_date(request.form.get("eta"))

        db.session.add(container)
        db.session.flush()
        db.session.add(AuditLog(
            user_id=current_user.id, action="CREATE",
            table_name="containers", record_id=container.id,
        ))

        # Log PLANNED event
        db.session.add(ContainerEvent(
            container_id=container.id,
            event_type=EventType.PLANNED,
            notes="Container created",
            created_by=current_user.id,
        ))

        # Default checklist items
        default_items = [
            "Booking confirmation received",
            "Packing list prepared",
            "Commercial invoice ready",
            "Bill of Lading (BL) drafted",
            "Customs declaration filed",
            "Container seal number recorded",
            "Photos of loading taken",
            "Container closed & sealed",
            "Shipping instructions sent",
            "Original documents sent to consignee",
        ]
        for i, item in enumerate(default_items):
            db.session.add(ContainerCheckItem(
                container_id=container.id,
                item_name=item,
                sort_order=i,
            ))

        # Handle file uploads (photos + PDFs)
        upload_dir = _ensure_upload_dir()
        files = request.files.getlist("photos")
        file_caption = request.form.get("file_caption", "").strip() or None
        fcount = 0
        for f in files:
            if f and f.filename and _allowed_file(f.filename):
                ext = f.filename.rsplit(".", 1)[1].lower()
                unique_name = f"{uuid.uuid4().hex}.{ext}"
                f.save(os.path.join(upload_dir, unique_name))
                photo = ContainerPhoto(
                    container_id=container.id,
                    filename=unique_name,
                    original_name=secure_filename(f.filename),
                    caption=file_caption,
                    phase=container.status.value,
                    uploaded_by=current_user.id,
                )
                db.session.add(photo)
                fcount += 1

        db.session.commit()
        msg = "Container created."
        if fcount:
            msg += f" {fcount} file(s) uploaded."
        flash(msg, "success")

        next_url = request.form.get("next") or url_for("containers.container_detail", container_id=container.id)
        return redirect(next_url)

    return render_template("containers/form.html", warehouses=warehouses, container=None)


# ── DETAIL ───────────────────────────────────────────────────────────
@containers_bp.route("/<int:container_id>")
@login_required
def container_detail(container_id):
    container = db.session.get(Container, container_id)
    if not container:
        flash("Container not found.", "warning")
        return redirect(url_for("containers.container_list"))

    load_lines = container.load_lines.all()
    events = container.events.order_by(ContainerEvent.event_time.asc()).all()
    checklist = container.checklist.all()
    photos = container.photos.all()

    # Alerts
    from datetime import datetime, timedelta
    alerts = []
    today = datetime.now().date()

    if container.etd and container.status.value in ('PLANNED', 'LOADING'):
        days_to_etd = (container.etd - today).days
        if days_to_etd < 0:
            alerts.append({"type": "danger", "icon": "exclamation-triangle",
                           "msg": f"ETD was {abs(days_to_etd)} days ago — container still {container.status.value}"})
        elif days_to_etd <= 3:
            alerts.append({"type": "warning", "icon": "clock",
                           "msg": f"ETD in {days_to_etd} day(s) — container still {container.status.value}"})

    if container.status.value in ('PLANNED', 'LOADING') and not container.load_lines.count():
        alerts.append({"type": "info", "icon": "inbox",
                       "msg": "No cargo loaded yet"})

    if container.status.value == 'LOADING':
        created = container.created_at.date() if container.created_at else today
        days_open = (today - created).days
        if days_open > 14:
            alerts.append({"type": "warning", "icon": "hourglass-split",
                           "msg": f"Container open for {days_open} days — consider closing"})

    # Check unchecked mandatory items
    total_checks = len(checklist)
    checked_count = sum(1 for c in checklist if c.is_checked)
    if total_checks > 0 and checked_count < total_checks:
        alerts.append({"type": "info", "icon": "list-check",
                       "msg": f"Checklist: {checked_count}/{total_checks} completed"})

    # Invoice alerts
    from app.models import FreightInvoice, InvoiceStatus
    open_invoices = FreightInvoice.query.filter_by(container_id=container.id).filter(
        FreightInvoice.status.in_([InvoiceStatus.OPEN, InvoiceStatus.PARTIAL])
    ).all()
    for inv in open_invoices:
        if inv.due_date and inv.due_date < today:
            alerts.append({"type": "danger", "icon": "cash-stack",
                           "msg": f"Invoice {inv.invoice_no} overdue ({inv.due_date})"})
        elif inv.due_date and (inv.due_date - today).days <= 7:
            alerts.append({"type": "warning", "icon": "cash-stack",
                           "msg": f"Invoice {inv.invoice_no} due in {(inv.due_date - today).days} day(s)"})

    return render_template(
        "containers/detail.html",
        container=container, load_lines=load_lines, events=events,
        checklist=checklist, photos=photos, alerts=alerts,
        checked_count=checked_count, total_checks=total_checks,
    )


# ── LOADING SCREEN ──────────────────────────────────────────────────
@containers_bp.route("/<int:container_id>/loading")
@login_required
def container_loading(container_id):
    container = db.session.get(Container, container_id)
    if not container:
        flash("Container not found.", "warning")
        return redirect(url_for("containers.container_list"))
    if not container.is_editable:
        flash("Container is not editable (closed or shipped).", "warning")
        return redirect(url_for("containers.container_detail", container_id=container.id))

    # If still PLANNED, transition to LOADING
    if container.status == ContainerStatus.PLANNED:
        container.status = ContainerStatus.LOADING
        db.session.add(ContainerEvent(
            container_id=container.id,
            event_type=EventType.LOADING,
            created_by=current_user.id,
        ))
        db.session.commit()

    # Available WRs from same warehouse, not on HOLD/CANCELLED/LOADED
    available_wrs = WarehouseReceipt.query.filter(
        WarehouseReceipt.warehouse_id == container.warehouse_id,
        WarehouseReceipt.status.in_([WRStatus.RECEIVED, WRStatus.PARTIALLY_LOADED]),
    ).order_by(WarehouseReceipt.wr_number).all()

    # Filter out those with qty_available <= 0
    available_wrs = [wr for wr in available_wrs if wr.qty_available > 0]

    load_lines = container.load_lines.all()

    return render_template(
        "containers/loading.html",
        container=container,
        available_wrs=available_wrs,
        load_lines=load_lines,
    )


# ── ADD LOAD LINE ───────────────────────────────────────────────────
@containers_bp.route("/<int:container_id>/load", methods=["POST"])
@login_required
def add_load_line(container_id):
    container = db.session.get(Container, container_id)
    if not container or not container.is_editable:
        flash("Cannot modify this container.", "danger")
        return redirect(url_for("containers.container_list"))

    wr_id = int(request.form["wr_id"])
    wr = db.session.get(WarehouseReceipt, wr_id)
    if not wr:
        flash("WR not found.", "danger")
        return redirect(url_for("containers.container_loading", container_id=container.id))

    # Check same warehouse
    if wr.warehouse_id != container.warehouse_id:
        flash("WR belongs to a different warehouse.", "danger")
        return redirect(url_for("containers.container_loading", container_id=container.id))

    # Check not already loaded in this container
    existing = ContainerLoadLine.query.filter_by(
        container_id=container.id, wr_id=wr.id
    ).first()
    if existing:
        flash(f"WR {wr.wr_number} is already loaded in this container.", "warning")
        return redirect(url_for("containers.container_loading", container_id=container.id))

    qty_loaded = int(request.form["qty_loaded"])

    # Validate qty doesn't exceed available
    if qty_loaded <= 0:
        flash("Quantity must be positive.", "danger")
        return redirect(url_for("containers.container_loading", container_id=container.id))
    if qty_loaded > wr.qty_available:
        flash(f"Cannot load {qty_loaded}. Available: {wr.qty_available}.", "danger")
        return redirect(url_for("containers.container_loading", container_id=container.id))

    # Calculate or validate cbm/kg
    manual_cbm = request.form.get("cbm_loaded")
    manual_kg = request.form.get("kg_loaded")

    if manual_cbm and manual_kg:
        cbm_loaded = Decimal(manual_cbm)
        kg_loaded = Decimal(manual_kg)
        # Validate proportionality
        prop_errors = _validate_proportional(wr, qty_loaded, cbm_loaded, kg_loaded)
        if prop_errors:
            for e in prop_errors:
                flash(e, "warning")
            # Still allow but warn — use calculated values instead
            cbm_loaded, kg_loaded = _calc_proportional(wr, qty_loaded)
            flash("Using proportional values instead.", "info")
    else:
        cbm_loaded, kg_loaded = _calc_proportional(wr, qty_loaded)

    line = ContainerLoadLine(
        container_id=container.id,
        wr_id=wr.id,
        qty_loaded=qty_loaded,
        cbm_loaded=cbm_loaded,
        kg_loaded=kg_loaded,
        notes=request.form.get("notes", "").strip() or None,
    )
    db.session.add(line)

    # Update WR status
    wr.recalc_status()

    db.session.add(AuditLog(
        user_id=current_user.id, action="LOAD",
        table_name="container_load_lines", record_id=container.id,
        new_values=f"wr={wr.wr_number}, qty={qty_loaded}",
    ))
    db.session.commit()

    flash(f"Loaded {qty_loaded} {wr.qty_unit_type.value} from {wr.wr_number}.", "success")
    return redirect(url_for("containers.container_loading", container_id=container.id))


# ── REMOVE LOAD LINE ────────────────────────────────────────────────
@containers_bp.route("/<int:container_id>/unload/<int:line_id>", methods=["POST"])
@login_required
def remove_load_line(container_id, line_id):
    container = db.session.get(Container, container_id)
    if not container or container.status.value in ("ARRIVED", "UNLOADED"):
        flash("Cannot modify this container.", "danger")
        return redirect(url_for("containers.container_list"))

    line = db.session.get(ContainerLoadLine, line_id)
    if not line or line.container_id != container.id:
        flash("Load line not found.", "warning")
        return redirect(url_for("containers.container_loading", container_id=container.id))

    wr = line.warehouse_receipt
    db.session.add(AuditLog(
        user_id=current_user.id, action="UNLOAD",
        table_name="container_load_lines", record_id=container.id,
        new_values=f"wr={wr.wr_number}, qty={line.qty_loaded}",
    ))
    db.session.delete(line)
    db.session.flush()
    wr.recalc_status()
    db.session.commit()

    flash(f"Removed {wr.wr_number} from container.", "info")
    # Redirect back to dashboard (from modal) or loading page
    next_url = request.form.get("next") or url_for("containers.container_loading", container_id=container.id)
    return redirect(next_url)


# ── EDIT LOAD LINE ─────────────────────────────────────────────────
@containers_bp.route("/<int:container_id>/load-line/<int:line_id>/edit", methods=["POST"])
@login_required
def edit_load_line(container_id, line_id):
    container = db.session.get(Container, container_id)
    if not container or container.status.value in ("ARRIVED", "UNLOADED"):
        flash("Cannot modify this container.", "danger")
        return redirect(url_for("containers.container_list"))

    line = db.session.get(ContainerLoadLine, line_id)
    if not line or line.container_id != container.id:
        flash("Load line not found.", "warning")
        return redirect(url_for("containers.container_detail", container_id=container.id))

    wr = line.warehouse_receipt

    new_qty = int(request.form.get("qty_loaded", line.qty_loaded))
    new_cbm = Decimal(request.form.get("cbm_loaded", str(line.cbm_loaded)))
    new_kg = Decimal(request.form.get("kg_loaded", str(line.kg_loaded)))

    # Validate: new_qty can't exceed what's available + what was already loaded
    max_available = wr.qty_available + line.qty_loaded
    if new_qty <= 0:
        flash("Quantity must be positive.", "danger")
    elif new_qty > max_available:
        flash(f"Cannot load {new_qty}. Max available: {max_available}.", "danger")
    elif new_cbm <= 0 or new_kg <= 0:
        flash("CBM and KG must be positive.", "danger")
    else:
        old_vals = f"qty={line.qty_loaded}, cbm={line.cbm_loaded}, kg={line.kg_loaded}"
        line.qty_loaded = new_qty
        line.cbm_loaded = new_cbm
        line.kg_loaded = new_kg

        db.session.add(AuditLog(
            user_id=current_user.id, action="EDIT_LOAD",
            table_name="container_load_lines", record_id=line.id,
            new_values=f"wr={wr.wr_number}, qty={new_qty}, cbm={new_cbm}, kg={new_kg} (was {old_vals})",
        ))
        db.session.flush()
        wr.recalc_status()
        db.session.commit()
        flash(f"Updated {wr.wr_number}: {new_qty} units, {new_cbm} m³, {new_kg} kg.", "success")

    next_url = request.form.get("next") or url_for("containers.container_detail", container_id=container.id)
    return redirect(next_url)


# ── CLOSE CONTAINER ──────────────────────────────────────────────────
@containers_bp.route("/<int:container_id>/close", methods=["POST"])
@login_required
def close_container(container_id):
    container = db.session.get(Container, container_id)
    if not container:
        flash("Container not found.", "warning")
        return redirect(url_for("containers.container_list"))
    if container.status != ContainerStatus.LOADING:
        flash("Container can only be closed from LOADING status.", "warning")
        return redirect(url_for("containers.container_detail", container_id=container.id))
    if container.load_lines.count() == 0:
        flash("Cannot close an empty container.", "danger")
        return redirect(url_for("containers.container_loading", container_id=container.id))

    container.status = ContainerStatus.CLOSED
    db.session.add(ContainerEvent(
        container_id=container.id,
        event_type=EventType.CLOSED,
        created_by=current_user.id,
        notes=request.form.get("notes", ""),
    ))
    db.session.commit()
    flash(f"Container {container.container_number or container.id} closed.", "success")
    return redirect(url_for("containers.container_detail", container_id=container.id))


# ── TRANSITION EVENTS (SHIPPED / ARRIVED / UNLOADED) ────────────────
@containers_bp.route("/<int:container_id>/event", methods=["POST"])
@login_required
def add_event(container_id):
    container = db.session.get(Container, container_id)
    if not container:
        flash("Container not found.", "warning")
        return redirect(url_for("containers.container_list"))

    new_status_str = request.form.get("new_status")
    try:
        new_status = ContainerStatus(new_status_str)
    except ValueError:
        flash("Invalid status.", "danger")
        return redirect(url_for("containers.container_detail", container_id=container.id))

    if not container.can_transition_to(new_status):
        flash(f"Cannot transition from {container.status.value} to {new_status.value}.", "danger")
        return redirect(url_for("containers.container_detail", container_id=container.id))

    old_status = container.status.value
    container.status = new_status

    # Update ETD/ETA if provided — parse string to date object
    etd = _parse_date(request.form.get("etd"))
    eta = _parse_date(request.form.get("eta"))
    if etd:
        container.etd = etd
    if eta:
        container.eta = eta

    event_type = EventType(new_status.value)
    db.session.add(ContainerEvent(
        container_id=container.id,
        event_type=event_type,
        notes=f"{old_status} → {new_status.value}. " + (request.form.get("notes", "") or ""),
        created_by=current_user.id,
    ))
    db.session.commit()

    flash(f"Container marked as {new_status.value}.", "success")
    return redirect(url_for("containers.container_detail", container_id=container.id))


# ── EDIT (only PLANNED/LOADING) ─────────────────────────────────────
@containers_bp.route("/<int:container_id>/edit", methods=["GET", "POST"])
@login_required
def container_edit(container_id):
    container = db.session.get(Container, container_id)
    if not container:
        flash("Container not found.", "warning")
        return redirect(url_for("containers.container_list"))

    warehouses = Warehouse.query.filter_by(is_active=True).all()

    if request.method == "POST":
        container.container_number = request.form.get("container_number", "").strip() or None
        container.container_type = request.form.get("container_type", "").strip() or None
        container.booking_number = request.form.get("booking_number", "").strip() or None
        container.carrier = request.form.get("carrier", "").strip() or None
        container.forwarder = request.form.get("forwarder", "").strip() or None
        container.pol = request.form.get("pol", "").strip() or None
        container.pod = request.form.get("pod", "").strip() or None
        container.notes = request.form.get("notes", "").strip() or None
        # ETD/ETA — parse string to date object
        container.etd = _parse_date(request.form.get("etd"))
        container.eta = _parse_date(request.form.get("eta"))

        db.session.commit()
        flash("Container updated.", "success")
        return redirect(url_for("containers.container_detail", container_id=container.id))

    return render_template("containers/form.html", warehouses=warehouses, container=container)


# ── PHOTO HELPERS ────────────────────────────────────────────────────
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "pdf"}


def _allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _ensure_upload_dir():
    upload_dir = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir


# ── UPLOAD PHOTOS ────────────────────────────────────────────────────
@containers_bp.route("/<int:container_id>/photos/upload", methods=["POST"])
@login_required
def upload_photos(container_id):
    container = db.session.get(Container, container_id)
    if not container:
        flash("Container not found.", "warning")
        return redirect(url_for("containers.container_list"))

    upload_dir = _ensure_upload_dir()
    files = request.files.getlist("photos")
    caption = request.form.get("caption", "").strip() or None
    count = 0

    for f in files:
        if f and f.filename and _allowed_file(f.filename):
            ext = f.filename.rsplit(".", 1)[1].lower()
            unique_name = f"{uuid.uuid4().hex}.{ext}"
            f.save(os.path.join(upload_dir, unique_name))

            photo = ContainerPhoto(
                container_id=container.id,
                filename=unique_name,
                original_name=secure_filename(f.filename),
                caption=caption,
                phase=container.status.value,
                uploaded_by=current_user.id,
            )
            db.session.add(photo)
            count += 1

    if count:
        db.session.commit()
        flash(f"{count} file(s) uploaded.", "success")
    else:
        flash("No valid files selected. Allowed: JPG, PNG, GIF, WEBP, PDF.", "warning")

    next_url = request.form.get("next") or url_for("containers.container_gallery", container_id=container.id)
    return redirect(next_url)


# ── DELETE PHOTO ─────────────────────────────────────────────────────
@containers_bp.route("/<int:container_id>/photos/<int:photo_id>/delete", methods=["POST"])
@login_required
def delete_photo(container_id, photo_id):
    photo = db.session.get(ContainerPhoto, photo_id)
    if not photo or photo.container_id != container_id:
        flash("Photo not found.", "warning")
        return redirect(url_for("containers.container_gallery", container_id=container_id))

    # Delete file from disk
    upload_dir = current_app.config["UPLOAD_FOLDER"]
    filepath = os.path.join(upload_dir, photo.filename)
    if os.path.exists(filepath):
        os.remove(filepath)

    db.session.delete(photo)
    db.session.commit()
    flash("Photo deleted.", "info")

    next_url = request.form.get("next") or url_for("containers.container_gallery", container_id=container_id)
    return redirect(next_url)


# ── SERVE PHOTO FILE ─────────────────────────────────────────────────
@containers_bp.route("/photos/<filename>")
@login_required
def serve_photo(filename):
    upload_dir = current_app.config["UPLOAD_FOLDER"]
    return send_from_directory(upload_dir, filename)


# ── GALLERY ──────────────────────────────────────────────────────────
@containers_bp.route("/<int:container_id>/gallery")
@login_required
def container_gallery(container_id):
    container = db.session.get(Container, container_id)
    if not container:
        flash("Container not found.", "warning")
        return redirect(url_for("containers.container_list"))

    photos = container.photos.all()

    # Group by phase
    from collections import OrderedDict
    by_phase = OrderedDict()
    for p in photos:
        phase = p.phase or "OTHER"
        if phase not in by_phase:
            by_phase[phase] = []
        by_phase[phase].append(p)

    return render_template(
        "containers/gallery.html",
        container=container,
        photos=photos,
        by_phase=by_phase,
    )


# ── CHECKLIST: TOGGLE ITEM ──────────────────────────────────────────
@containers_bp.route("/<int:container_id>/checklist/<int:item_id>/toggle", methods=["POST"])
@login_required
def toggle_checklist(container_id, item_id):
    item = db.session.get(ContainerCheckItem, item_id)
    if not item or item.container_id != container_id:
        flash("Item not found.", "warning")
        return redirect(url_for("containers.container_detail", container_id=container_id))

    from datetime import datetime
    item.is_checked = not item.is_checked
    item.checked_at = datetime.utcnow() if item.is_checked else None
    item.checked_by = current_user.id if item.is_checked else None
    db.session.commit()

    next_url = request.form.get("next") or url_for("containers.container_detail", container_id=container_id)
    return redirect(next_url)


# ── CHECKLIST: ADD CUSTOM ITEM ──────────────────────────────────────
@containers_bp.route("/<int:container_id>/checklist/add", methods=["POST"])
@login_required
def add_checklist_item(container_id):
    container = db.session.get(Container, container_id)
    if not container:
        flash("Container not found.", "warning")
        return redirect(url_for("containers.container_list"))

    name = request.form.get("item_name", "").strip()
    if not name:
        flash("Item name required.", "warning")
        return redirect(url_for("containers.container_detail", container_id=container_id))

    max_order = db.session.query(db.func.max(ContainerCheckItem.sort_order)).filter_by(
        container_id=container_id
    ).scalar() or 0

    db.session.add(ContainerCheckItem(
        container_id=container_id,
        item_name=name,
        sort_order=max_order + 1,
    ))
    db.session.commit()
    flash(f"Checklist item added.", "success")

    next_url = request.form.get("next") or url_for("containers.container_detail", container_id=container_id)
    return redirect(next_url)


# ── CHECKLIST: DELETE ITEM ──────────────────────────────────────────
@containers_bp.route("/<int:container_id>/checklist/<int:item_id>/delete", methods=["POST"])
@login_required
def delete_checklist_item(container_id, item_id):
    item = db.session.get(ContainerCheckItem, item_id)
    if not item or item.container_id != container_id:
        flash("Item not found.", "warning")
        return redirect(url_for("containers.container_detail", container_id=container_id))

    db.session.delete(item)
    db.session.commit()
    flash("Checklist item removed.", "info")

    next_url = request.form.get("next") or url_for("containers.container_detail", container_id=container_id)
    return redirect(next_url)
