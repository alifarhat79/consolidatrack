"""Finance blueprint — Freight invoices, payments, and proration."""
import os
import uuid
from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, request, url_for, current_app
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import (
    AuditLog, Container, ContainerLoadLine, ContainerPhoto, Customer,
    FreightInvoice, FreightPayment, FreightProration, InvoiceStatus,
)

finance_bp = Blueprint("finance", __name__, template_folder="../../templates/finance")


ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "pdf"}


def _allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# ── INVOICE LIST ─────────────────────────────────────────────────────
@finance_bp.route("/")
@login_required
def invoice_list():
    invoices = FreightInvoice.query.order_by(FreightInvoice.issue_date.desc()).all()
    containers = Container.query.order_by(Container.created_at.desc()).all()

    # Totals
    total_amount = sum(Decimal(str(inv.amount)) for inv in invoices)
    total_paid = sum(inv.total_paid for inv in invoices)
    total_balance = total_amount - total_paid
    overdue_count = sum(
        1 for inv in invoices
        if inv.due_date and inv.status.value in ('OPEN', 'PARTIAL')
    )

    return render_template(
        "finance/invoice_list.html",
        invoices=invoices,
        containers=containers,
        total_amount=total_amount,
        total_paid=total_paid,
        total_balance=total_balance,
        overdue_count=overdue_count,
    )


# ── CREATE INVOICE ───────────────────────────────────────────────────
@finance_bp.route("/invoices/create", methods=["GET", "POST"])
@login_required
def invoice_create():
    containers = Container.query.order_by(Container.created_at.desc()).all()
    if request.method == "POST":
        from datetime import date as dt_date
        issue_str = request.form["issue_date"]
        due_str = request.form.get("due_date")
        inv = FreightInvoice(
            container_id=int(request.form["container_id"]),
            supplier=request.form["supplier"].strip(),
            invoice_no=request.form["invoice_no"].strip(),
            amount=Decimal(request.form["amount"]),
            currency=request.form.get("currency", "USD").strip(),
            issue_date=dt_date.fromisoformat(issue_str) if issue_str else None,
            due_date=dt_date.fromisoformat(due_str) if due_str else None,
            notes=request.form.get("notes", "").strip() or None,
        )
        db.session.add(inv)
        db.session.flush()

        # Handle PDF/file uploads — attach to container
        upload_dir = current_app.config.get("UPLOAD_FOLDER", "uploads/photos")
        os.makedirs(upload_dir, exist_ok=True)
        files = request.files.getlist("documents")
        fcount = 0
        for f in files:
            if f and f.filename and _allowed_file(f.filename):
                ext = f.filename.rsplit(".", 1)[1].lower()
                unique_name = f"{uuid.uuid4().hex}.{ext}"
                f.save(os.path.join(upload_dir, unique_name))
                photo = ContainerPhoto(
                    container_id=inv.container_id,
                    filename=unique_name,
                    original_name=secure_filename(f.filename),
                    caption=f"Invoice {inv.invoice_no}",
                    phase="INVOICE",
                    uploaded_by=current_user.id,
                )
                db.session.add(photo)
                fcount += 1

        db.session.commit()
        msg = f"Invoice {inv.invoice_no} created."
        if fcount:
            msg += f" {fcount} document(s) attached."
        flash(msg, "success")

        next_url = request.form.get("next") or url_for("finance.invoice_detail", invoice_id=inv.id)
        return redirect(next_url)
    return render_template("finance/invoice_form.html", containers=containers, invoice=None)


# ── DELETE INVOICE ───────────────────────────────────────────────────
@finance_bp.route("/invoices/<int:invoice_id>/delete", methods=["POST"])
@login_required
def invoice_delete(invoice_id):
    inv = db.session.get(FreightInvoice, invoice_id)
    if not inv:
        flash("Invoice not found.", "warning")
        return redirect(url_for("finance.invoice_list"))

    if inv.total_paid > 0:
        flash(f"Cannot delete {inv.invoice_no}: has recorded payments.", "danger")
        return redirect(url_for("finance.invoice_list"))

    inv_no = inv.invoice_no
    db.session.add(AuditLog(
        user_id=current_user.id,
        action="DELETE",
        table_name="freight_invoices",
        record_id=inv.id,
        new_values=f"invoice_no={inv_no}",
    ))
    db.session.delete(inv)
    db.session.commit()
    flash(f"Invoice {inv_no} deleted.", "success")

    next_url = request.form.get("next") or url_for("finance.invoice_list")
    return redirect(next_url)


# ── INVOICE DETAIL ───────────────────────────────────────────────────
@finance_bp.route("/invoices/<int:invoice_id>")
@login_required
def invoice_detail(invoice_id):
    inv = db.session.get(FreightInvoice, invoice_id)
    if not inv:
        flash("Invoice not found.", "warning")
        return redirect(url_for("finance.invoice_list"))
    payments = inv.payments.order_by(FreightPayment.payment_date).all()
    return render_template("finance/invoice_detail.html", invoice=inv, payments=payments)


# ── ADD PAYMENT ──────────────────────────────────────────────────────
@finance_bp.route("/invoices/<int:invoice_id>/pay", methods=["POST"])
@login_required
def add_payment(invoice_id):
    inv = db.session.get(FreightInvoice, invoice_id)
    if not inv:
        flash("Invoice not found.", "warning")
        return redirect(url_for("finance.invoice_list"))
    if inv.status == InvoiceStatus.PAID:
        flash("Invoice is already fully paid.", "info")
        return redirect(url_for("finance.invoice_detail", invoice_id=inv.id))

    amount = Decimal(request.form["amount"])
    if amount <= 0:
        flash("Amount must be positive.", "danger")
        return redirect(url_for("finance.invoice_detail", invoice_id=inv.id))
    if amount > inv.balance:
        flash(f"Amount exceeds balance ({inv.balance}).", "danger")
        return redirect(url_for("finance.invoice_detail", invoice_id=inv.id))

    payment = FreightPayment(
        freight_invoice_id=inv.id,
        payment_date=request.form["payment_date"],
        amount=amount,
        method=request.form.get("method", "").strip() or None,
        reference=request.form.get("reference", "").strip() or None,
        notes=request.form.get("notes", "").strip() or None,
    )
    db.session.add(payment)
    db.session.flush()
    inv.recalc_status()
    db.session.commit()

    flash(f"Payment of {amount} recorded.", "success")
    return redirect(url_for("finance.invoice_detail", invoice_id=inv.id))


# ── PRORATION ────────────────────────────────────────────────────────
@finance_bp.route("/proration/<int:container_id>")
@login_required
def proration(container_id):
    """Calculate freight proration by CBM or KG for a container."""
    container = db.session.get(Container, container_id)
    if not container:
        flash("Container not found.", "warning")
        return redirect(url_for("finance.invoice_list"))

    method = request.args.get("method", "CBM").upper()

    # Get total freight for this container
    total_freight = sum(
        Decimal(str(inv.amount)) for inv in container.freight_invoices
        if inv.status != InvoiceStatus.CANCELLED
    )

    # Get load lines grouped by customer
    lines = (
        db.session.query(
            ContainerLoadLine.wr_id,
            ContainerLoadLine.cbm_loaded,
            ContainerLoadLine.kg_loaded,
        )
        .filter(ContainerLoadLine.container_id == container_id)
        .all()
    )

    # Build customer shares
    from app.models import WarehouseReceipt
    customer_data = {}
    for line in lines:
        wr = db.session.get(WarehouseReceipt, line.wr_id)
        cid = wr.customer_id
        if cid not in customer_data:
            customer_data[cid] = {"cbm": Decimal("0"), "kg": Decimal("0"), "customer": wr.customer}
        customer_data[cid]["cbm"] += Decimal(str(line.cbm_loaded))
        customer_data[cid]["kg"] += Decimal(str(line.kg_loaded))

    total_cbm = container.total_cbm
    total_kg = container.total_kg

    prorations = []
    for cid, data in customer_data.items():
        if method == "KG":
            pct = (data["kg"] / total_kg * 100) if total_kg > 0 else Decimal("0")
        else:
            pct = (data["cbm"] / total_cbm * 100) if total_cbm > 0 else Decimal("0")

        amt = (total_freight * pct / 100).quantize(Decimal("0.01"))
        prorations.append({
            "customer": data["customer"],
            "cbm": data["cbm"],
            "kg": data["kg"],
            "percentage": pct.quantize(Decimal("0.01")),
            "amount": amt,
        })

    return render_template(
        "finance/proration.html",
        container=container,
        prorations=prorations,
        total_freight=total_freight,
        method=method,
    )
