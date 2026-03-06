"""Warehouse Receipts blueprint — CRUD, stock, listing with filters, photos."""
import os
import uuid
from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for, current_app, send_from_directory
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import (
    AuditLog, Customer, QtyUnitType, Warehouse, WarehouseReceipt, WRPhoto, WRStatus,
)

wr_bp = Blueprint("wr", __name__, template_folder="../../templates/wr")

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "pdf"}


def _allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _save_wr_files(wr, files, caption=None):
    """Save uploaded files for a WR. Returns count."""
    upload_dir = current_app.config.get("UPLOAD_FOLDER", "uploads/photos")
    os.makedirs(upload_dir, exist_ok=True)
    count = 0
    for f in files:
        if f and f.filename and _allowed_file(f.filename):
            ext = f.filename.rsplit(".", 1)[1].lower()
            unique_name = f"{uuid.uuid4().hex}.{ext}"
            f.save(os.path.join(upload_dir, unique_name))
            photo = WRPhoto(
                wr_id=wr.id,
                filename=unique_name,
                original_name=secure_filename(f.filename),
                caption=caption,
                uploaded_by=current_user.id,
            )
            db.session.add(photo)
            count += 1
    return count


def _next_wr_number(warehouse: Warehouse) -> str:
    """Generate next sequential WR number: SZX-2025-0001."""
    year = date.today().year
    prefix = f"{warehouse.code}-{year}-"
    last = (
        WarehouseReceipt.query
        .filter(WarehouseReceipt.wr_number.like(f"{prefix}%"))
        .order_by(WarehouseReceipt.wr_number.desc())
        .first()
    )
    if last:
        seq = int(last.wr_number.split("-")[-1]) + 1
    else:
        seq = 1
    return f"{prefix}{seq:04d}"


# ── LIST ─────────────────────────────────────────────────────────────
@wr_bp.route("/")
@login_required
def wr_list():
    query = WarehouseReceipt.query

    # Filters
    cust_id = request.args.get("customer_id", type=int)
    status = request.args.get("status")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")

    if cust_id:
        query = query.filter_by(customer_id=cust_id)
    if status:
        query = query.filter_by(status=WRStatus(status))
    if date_from:
        query = query.filter(WarehouseReceipt.date_received >= date_from)
    if date_to:
        query = query.filter(WarehouseReceipt.date_received <= date_to)

    wrs = query.order_by(WarehouseReceipt.date_received.desc()).all()
    warehouses = Warehouse.query.filter_by(is_active=True).all()
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()

    # Group by warehouse
    from collections import OrderedDict
    wrs_by_wh = OrderedDict()
    for wh in warehouses:
        wrs_by_wh[wh.code] = {
            "warehouse": wh,
            "wrs": [w for w in wrs if w.warehouse_id == wh.id],
        }

    return render_template(
        "wr/list.html",
        wrs_by_wh=wrs_by_wh,
        warehouses=warehouses,
        customers=customers,
        filters=request.args,
    )


# ── CREATE ───────────────────────────────────────────────────────────
@wr_bp.route("/create", methods=["GET", "POST"])
@login_required
def wr_create():
    warehouses = Warehouse.query.filter_by(is_active=True).all()
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()

    if request.method == "POST":
        wh = db.session.get(Warehouse, int(request.form["warehouse_id"]))
        if not wh:
            flash("Invalid warehouse.", "danger")
            return redirect(url_for("wr.wr_create"))

        wr = WarehouseReceipt(
            warehouse_id=wh.id,
            customer_id=int(request.form["customer_id"]),
            wr_number=_next_wr_number(wh),
            date_received=date.fromisoformat(request.form["date_received"]),
            commodity=request.form["commodity"].strip(),
            qty_total=int(request.form["qty_total"]),
            qty_unit_type=QtyUnitType(request.form["qty_unit_type"]),
            cbm_total=float(request.form["cbm_total"]),
            kg_total=float(request.form["kg_total"]),
            notes=request.form.get("notes", "").strip(),
            status=WRStatus.RECEIVED,
        )

        # Validation
        errors = []
        if wr.qty_total <= 0:
            errors.append("Quantity must be positive.")
        if wr.cbm_total <= 0:
            errors.append("CBM must be positive.")
        if wr.kg_total <= 0:
            errors.append("Weight must be positive.")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template(
                "wr/form.html", warehouses=warehouses, customers=customers, wr=None,
            )

        db.session.add(wr)
        db.session.flush()

        # Audit
        db.session.add(AuditLog(
            user_id=current_user.id,
            action="CREATE",
            table_name="warehouse_receipts",
            record_id=wr.id,
            new_values=f"wr_number={wr.wr_number}",
        ))

        # Handle file uploads
        files = request.files.getlist("photos")
        file_caption = request.form.get("file_caption", "").strip() or None
        fcount = _save_wr_files(wr, files, file_caption)

        db.session.commit()
        msg = f"WR {wr.wr_number} created successfully."
        if fcount:
            msg += f" {fcount} file(s) uploaded."
        flash(msg, "success")
        next_url = request.form.get("next") or url_for("wr.wr_detail", wr_id=wr.id)
        return redirect(next_url)

    return render_template("wr/form.html", warehouses=warehouses, customers=customers, wr=None)


# ── DETAIL ───────────────────────────────────────────────────────────
@wr_bp.route("/<int:wr_id>")
@login_required
def wr_detail(wr_id):
    wr = db.session.get(WarehouseReceipt, wr_id)
    if not wr:
        flash("WR not found.", "warning")
        return redirect(url_for("wr.wr_list"))
    load_lines = wr.load_lines.all()
    return render_template("wr/detail.html", wr=wr, load_lines=load_lines)


# ── EDIT ─────────────────────────────────────────────────────────────
@wr_bp.route("/<int:wr_id>/edit", methods=["GET", "POST"])
@login_required
def wr_edit(wr_id):
    wr = db.session.get(WarehouseReceipt, wr_id)
    if not wr:
        flash("WR not found.", "warning")
        return redirect(url_for("wr.wr_list"))
    if wr.status == WRStatus.LOADED:
        flash("Cannot edit a fully loaded WR.", "warning")
        return redirect(url_for("wr.wr_detail", wr_id=wr.id))

    warehouses = Warehouse.query.filter_by(is_active=True).all()
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()

    if request.method == "POST":
        wr.commodity = request.form["commodity"].strip()
        new_qty = int(request.form["qty_total"])

        # Don't allow reducing below already loaded
        if new_qty < wr.qty_loaded:
            flash(f"Cannot set qty below already loaded ({wr.qty_loaded}).", "danger")
            return render_template("wr/form.html", warehouses=warehouses, customers=customers, wr=wr)

        wr.qty_total = new_qty
        wr.qty_unit_type = QtyUnitType(request.form["qty_unit_type"])
        wr.cbm_total = float(request.form["cbm_total"])
        wr.kg_total = float(request.form["kg_total"])
        wr.notes = request.form.get("notes", "").strip()
        wr.recalc_status()

        db.session.add(AuditLog(
            user_id=current_user.id,
            action="UPDATE",
            table_name="warehouse_receipts",
            record_id=wr.id,
        ))
        db.session.commit()
        flash(f"WR {wr.wr_number} updated.", "success")
        return redirect(url_for("wr.wr_detail", wr_id=wr.id))

    return render_template("wr/form.html", warehouses=warehouses, customers=customers, wr=wr)


# ── HOLD / UNHOLD ────────────────────────────────────────────────────
@wr_bp.route("/<int:wr_id>/hold", methods=["POST"])
@login_required
def wr_hold(wr_id):
    wr = db.session.get(WarehouseReceipt, wr_id)
    if not wr:
        flash("WR not found.", "warning")
        return redirect(url_for("wr.wr_list"))
    if wr.status in (WRStatus.RECEIVED, WRStatus.PARTIALLY_LOADED):
        wr.status = WRStatus.HOLD
        db.session.commit()
        flash(f"WR {wr.wr_number} placed on HOLD.", "info")
    elif wr.status == WRStatus.HOLD:
        wr.recalc_status()
        db.session.commit()
        flash(f"WR {wr.wr_number} released from HOLD.", "info")
    return redirect(url_for("wr.wr_detail", wr_id=wr.id))


# ── STOCK REPORT ─────────────────────────────────────────────────────
@wr_bp.route("/stock")
@login_required
def stock_report():
    """Available stock by warehouse and customer."""
    wh_id = request.args.get("warehouse_id", type=int)
    query = WarehouseReceipt.query.filter(
        WarehouseReceipt.status.in_([WRStatus.RECEIVED, WRStatus.PARTIALLY_LOADED])
    )
    if wh_id:
        query = query.filter_by(warehouse_id=wh_id)

    wrs = query.order_by(WarehouseReceipt.warehouse_id, WarehouseReceipt.customer_id).all()
    warehouses = Warehouse.query.filter_by(is_active=True).all()
    return render_template("wr/stock.html", wrs=wrs, warehouses=warehouses, filters=request.args)


# ── CANCEL / RETURN WR ──────────────────────────────────────────────
@wr_bp.route("/<int:wr_id>/cancel", methods=["POST"])
@login_required
def wr_cancel(wr_id):
    """Cancel a WR and remove from warehouse. Only if no cargo is loaded."""
    wr = db.session.get(WarehouseReceipt, wr_id)
    if not wr:
        flash("WR not found.", "warning")
        return redirect(url_for("wr.wr_list"))

    # Check if any cargo is loaded in containers
    if wr.load_lines.count() > 0:
        flash(f"Cannot cancel {wr.wr_number}: cargo is loaded in containers. "
              f"Remove load lines first.", "danger")
        return redirect(url_for("wr.wr_detail", wr_id=wr.id))

    wr_number = wr.wr_number
    db.session.add(AuditLog(
        user_id=current_user.id,
        action="CANCEL",
        table_name="warehouse_receipts",
        record_id=wr.id,
        new_values=f"wr_number={wr_number}, status={wr.status.value}",
    ))
    db.session.delete(wr)
    db.session.commit()

    flash(f"WR {wr_number} cancelled and removed from warehouse.", "success")
    next_url = request.form.get("next") or url_for("wr.wr_list")
    return redirect(next_url)


# ── UPLOAD WR PHOTOS ─────────────────────────────────────────────────
@wr_bp.route("/<int:wr_id>/photos/upload", methods=["POST"])
@login_required
def upload_wr_photos(wr_id):
    wr = db.session.get(WarehouseReceipt, wr_id)
    if not wr:
        flash("WR not found.", "warning")
        return redirect(url_for("wr.wr_list"))

    files = request.files.getlist("photos")
    caption = request.form.get("caption", "").strip() or None
    fcount = _save_wr_files(wr, files, caption)

    if fcount:
        db.session.commit()
        flash(f"{fcount} file(s) uploaded.", "success")
    else:
        flash("No valid files. Allowed: JPG, PNG, GIF, WEBP, PDF.", "warning")

    next_url = request.form.get("next") or url_for("wr.wr_list")
    return redirect(next_url)


# ── DELETE WR PHOTO ──────────────────────────────────────────────────
@wr_bp.route("/<int:wr_id>/photos/<int:photo_id>/delete", methods=["POST"])
@login_required
def delete_wr_photo(wr_id, photo_id):
    photo = db.session.get(WRPhoto, photo_id)
    if not photo or photo.wr_id != wr_id:
        flash("Photo not found.", "warning")
        return redirect(url_for("wr.wr_list"))

    upload_dir = current_app.config.get("UPLOAD_FOLDER", "uploads/photos")
    filepath = os.path.join(upload_dir, photo.filename)
    if os.path.exists(filepath):
        os.remove(filepath)

    db.session.delete(photo)
    db.session.commit()
    flash("File deleted.", "info")

    next_url = request.form.get("next") or url_for("wr.wr_list")
    return redirect(next_url)


# ── SERVE WR PHOTO FILE ─────────────────────────────────────────────
@wr_bp.route("/photos/<filename>")
@login_required
def serve_wr_photo(filename):
    upload_dir = current_app.config.get("UPLOAD_FOLDER", "uploads/photos")
    return send_from_directory(upload_dir, filename)
