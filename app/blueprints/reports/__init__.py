"""Reports blueprint — PDF/CSV exports for manifests, stock, finance, tracking."""
import csv
import io
from datetime import datetime
from decimal import Decimal

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for
from flask_login import login_required
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet

from app.extensions import db
from app.models import (
    Container, ContainerLoadLine, ContainerStatus, ContainerTrackingPoint,
    Customer, FreightInvoice, InvoiceStatus, Warehouse, WarehouseReceipt, WRStatus,
)

reports_bp = Blueprint("reports", __name__, template_folder="../../templates/reports")


# ── REPORT INDEX ─────────────────────────────────────────────────────
@reports_bp.route("/")
@login_required
def report_index():
    containers = Container.query.order_by(Container.created_at.desc()).all()
    warehouses = Warehouse.query.filter_by(is_active=True).all()
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
    return render_template(
        "reports/index.html",
        containers=containers, warehouses=warehouses, customers=customers,
    )


# ══════════════════════════════════════════════════════════════════════
#  1. CONTAINER MANIFEST
# ══════════════════════════════════════════════════════════════════════

@reports_bp.route("/manifest/<int:container_id>/csv")
@login_required
def manifest_csv(container_id):
    container = db.session.get(Container, container_id)
    if not container:
        flash("Container not found.", "warning")
        return redirect(url_for("reports.report_index"))

    lines = container.load_lines.all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Container", container.container_number or "TBD"])
    writer.writerow(["POL", container.pol or "", "POD", container.pod or ""])
    writer.writerow(["ETD", str(container.etd or ""), "ETA", str(container.eta or "")])
    writer.writerow([])
    writer.writerow(["WR#", "Customer", "Commodity", "Qty", "Unit", "CBM", "KG"])

    total_cbm = Decimal("0")
    total_kg = Decimal("0")
    for line in lines:
        wr = line.warehouse_receipt
        writer.writerow([
            wr.wr_number, wr.customer.name, wr.commodity,
            line.qty_loaded, wr.qty_unit_type.value,
            f"{line.cbm_loaded:.4f}", f"{line.kg_loaded:.2f}",
        ])
        total_cbm += Decimal(str(line.cbm_loaded))
        total_kg += Decimal(str(line.kg_loaded))

    writer.writerow([])
    writer.writerow(["TOTALS", "", "", "", "", f"{total_cbm:.4f}", f"{total_kg:.2f}"])

    filename = f"manifest_{container.container_number or container.id}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@reports_bp.route("/manifest/<int:container_id>/pdf")
@login_required
def manifest_pdf(container_id):
    container = db.session.get(Container, container_id)
    if not container:
        flash("Container not found.", "warning")
        return redirect(url_for("reports.report_index"))

    lines = container.load_lines.all()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.5 * inch)
    styles = getSampleStyleSheet()
    elements = []

    # Title
    elements.append(Paragraph(
        f'Container Manifest — <font color="#3b82f6"><b>{container.container_number or "TBD"}</b></font>',
        styles["Title"],
    ))
    elements.append(Spacer(1, 12))

    # Header info
    info_text = (
        f"POL: {container.pol or 'N/A'} | POD: {container.pod or 'N/A'} | "
        f"ETD: {container.etd or 'N/A'} | ETA: {container.eta or 'N/A'} | "
        f"Carrier: {container.carrier or 'N/A'}"
    )
    elements.append(Paragraph(info_text, styles["Normal"]))
    elements.append(Spacer(1, 12))

    # Table
    data = [["WR#", "Customer", "Commodity", "Qty", "CBM", "KG"]]
    total_cbm = Decimal("0")
    total_kg = Decimal("0")

    for line in lines:
        wr = line.warehouse_receipt
        data.append([
            wr.wr_number, wr.customer.name, wr.commodity[:30],
            str(line.qty_loaded),
            f"{line.cbm_loaded:.4f}",
            f"{line.kg_loaded:.2f}",
        ])
        total_cbm += Decimal(str(line.cbm_loaded))
        total_kg += Decimal(str(line.kg_loaded))

    data.append(["TOTAL", "", "", "", f"{total_cbm:.4f}", f"{total_kg:.2f}"])

    table = Table(data, colWidths=[1.1*inch, 1.3*inch, 1.5*inch, 0.6*inch, 0.8*inch, 0.8*inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#ecf0f1")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
    ]))
    elements.append(table)

    doc.build(elements)
    buf.seek(0)

    filename = f"manifest_{container.container_number or container.id}.pdf"
    return Response(
        buf.getvalue(),
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ══════════════════════════════════════════════════════════════════════
#  2. CUSTOMER STATUS
# ══════════════════════════════════════════════════════════════════════

@reports_bp.route("/customer-status/<int:customer_id>/csv")
@login_required
def customer_status_csv(customer_id):
    customer = db.session.get(Customer, customer_id)
    if not customer:
        flash("Customer not found.", "warning")
        return redirect(url_for("reports.report_index"))

    wrs = WarehouseReceipt.query.filter_by(customer_id=customer.id).order_by(
        WarehouseReceipt.date_received.desc()
    ).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([f"Customer Status Report — {customer.name}"])
    writer.writerow([])
    writer.writerow(["WR#", "Warehouse", "Date", "Commodity", "Qty Total", "Qty Available",
                      "CBM Total", "CBM Avail", "KG Total", "KG Avail", "Status"])

    for wr in wrs:
        writer.writerow([
            wr.wr_number, wr.warehouse.code, str(wr.date_received), wr.commodity,
            wr.qty_total, wr.qty_available,
            f"{wr.cbm_total:.4f}", f"{wr.cbm_available:.4f}",
            f"{wr.kg_total:.2f}", f"{wr.kg_available:.2f}",
            wr.status.value,
        ])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=customer_{customer.code}_status.csv"},
    )


# ══════════════════════════════════════════════════════════════════════
#  3. WAREHOUSE STOCK
# ══════════════════════════════════════════════════════════════════════

@reports_bp.route("/stock/csv")
@login_required
def stock_csv():
    wh_id = request.args.get("warehouse_id", type=int)
    query = WarehouseReceipt.query.filter(
        WarehouseReceipt.status.in_([WRStatus.RECEIVED, WRStatus.PARTIALLY_LOADED])
    )
    if wh_id:
        query = query.filter_by(warehouse_id=wh_id)

    wrs = query.order_by(WarehouseReceipt.warehouse_id, WarehouseReceipt.customer_id).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Warehouse Stock Report"])
    writer.writerow([])
    writer.writerow(["Warehouse", "Customer", "WR#", "Commodity", "Qty Avail", "CBM Avail", "KG Avail"])

    for wr in wrs:
        writer.writerow([
            wr.warehouse.code, wr.customer.name, wr.wr_number, wr.commodity,
            wr.qty_available, f"{wr.cbm_available:.4f}", f"{wr.kg_available:.2f}",
        ])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=warehouse_stock.csv"},
    )


# ══════════════════════════════════════════════════════════════════════
#  4. FINANCE REPORT
# ══════════════════════════════════════════════════════════════════════

@reports_bp.route("/finance/csv")
@login_required
def finance_csv():
    invoices = FreightInvoice.query.order_by(FreightInvoice.issue_date.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Finance Report — Freight Invoices"])
    writer.writerow([])
    writer.writerow(["Container", "Invoice#", "Supplier", "Amount", "Currency",
                      "Paid", "Balance", "Status", "Issue Date", "Due Date"])

    for inv in invoices:
        writer.writerow([
            inv.container.container_number or inv.container_id,
            inv.invoice_no, inv.supplier,
            f"{inv.amount:.2f}", inv.currency,
            f"{inv.total_paid:.2f}", f"{inv.balance:.2f}",
            inv.status.value, str(inv.issue_date), str(inv.due_date or ""),
        ])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=finance_report.csv"},
    )


# ══════════════════════════════════════════════════════════════════════
#  5. TRACKING REPORT
# ══════════════════════════════════════════════════════════════════════

@reports_bp.route("/tracking/<int:container_id>/csv")
@login_required
def tracking_csv(container_id):
    container = db.session.get(Container, container_id)
    if not container:
        flash("Container not found.", "warning")
        return redirect(url_for("reports.report_index"))

    points = container.tracking_points.order_by(ContainerTrackingPoint.timestamp.asc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([f"Tracking Report — {container.container_number or 'TBD'}"])
    writer.writerow(["Status", container.status.value, "ETA", str(container.eta or "")])
    writer.writerow([])
    writer.writerow(["Timestamp", "Location", "Description", "Lat", "Lon", "Source"])

    for p in points:
        writer.writerow([
            p.timestamp.isoformat() if p.timestamp else "",
            p.location_name or "",
            p.event_description or "",
            str(p.latitude or ""),
            str(p.longitude or ""),
            p.source or "",
        ])

    filename = f"tracking_{container.container_number or container.id}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ── PDF HELPERS ──────────────────────────────────────────────────────
def _pdf_header(elements, styles, title, subtitle=""):
    """Add branded header to PDF."""
    from reportlab.platypus import Table, TableStyle, Paragraph
    from reportlab.lib import colors

    elements.append(Paragraph(
        f'<font size="16" color="#1e293b"><b>ConsolidaTrack</b></font> &nbsp;&nbsp;'
        f'<font size="7" color="#94a3b8">Maritime Logistics</font>',
        styles["Normal"],
    ))
    elements.append(Spacer(1, 6))
    elements.append(Paragraph(
        f'<font size="13" color="#334155"><b>{title}</b></font>',
        styles["Normal"],
    ))
    elements.append(Spacer(1, 3))
    elements.append(Paragraph(
        f'<font size="7.5" color="#94a3b8">Generated: {datetime.now().strftime("%d/%m/%Y %H:%M")} &nbsp;|&nbsp; {subtitle}</font>',
        styles["Normal"],
    ))
    elements.append(Spacer(1, 4))

    # Separator line
    line_table = Table([[""]], colWidths=[7.3*inch])
    line_table.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), 2, colors.HexColor("#3b82f6")),
    ]))
    elements.append(line_table)
    elements.append(Spacer(1, 12))


def _styled_table(data, col_widths, has_total=True):
    """Create a consistently styled table."""
    from reportlab.platypus import Table, TableStyle
    from reportlab.lib import colors

    table = Table(data, colWidths=col_widths)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTSIZE", (0, 1), (-1, -1), 7.5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1 if not has_total else -2), [colors.white, colors.HexColor("#f8fafc")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if has_total and len(data) > 2:
        style_cmds += [
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f1f5f9")),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#3b82f6")),
        ]
    table.setStyle(TableStyle(style_cmds))
    return table


# ══════════════════════════════════════════════════════════════════════
#  6. CONTAINER PACKING LIST (enhanced PDF)
# ══════════════════════════════════════════════════════════════════════

@reports_bp.route("/packing-list/<int:container_id>/pdf")
@login_required
def packing_list_pdf(container_id):
    container = db.session.get(Container, container_id)
    if not container:
        flash("Container not found.", "warning")
        return redirect(url_for("reports.report_index"))

    lines = container.load_lines.all()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.4*inch, bottomMargin=0.4*inch, leftMargin=0.5*inch, rightMargin=0.5*inch)
    styles = getSampleStyleSheet()
    elements = []

    max_cbm = 33 if container.container_type == '20' else (76 if container.container_type == '40HQ' else 67)

    _pdf_header(elements, styles, "PACKING LIST",
                f"Container: {container.container_number or 'TBD'}")

    # Container info box
    cnt_num = Paragraph(
        f'<font size="11" color="#3b82f6"><b>{container.container_number or "TBD"}</b></font>',
        styles["Normal"],
    )
    info_data = [
        ["Container #", cnt_num, "Type", container.container_type or "-"],
        ["Carrier", container.carrier or "-", "Booking", container.booking_number or "-"],
        ["POL", container.pol or "-", "POD", container.pod or "-"],
        ["ETD", str(container.etd or "-"), "ETA", str(container.eta or "-")],
        ["Forwarder", container.forwarder or "-", "Status", container.status.value],
    ]
    info_table = Table(info_data, colWidths=[0.9*inch, 2.8*inch, 0.8*inch, 2.8*inch])
    info_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#64748b")),
        ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor("#64748b")),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 14))

    # Cargo table
    elements.append(Paragraph('<font size="10" color="#1e293b"><b>Cargo Detail</b></font>', styles["Normal"]))
    elements.append(Spacer(1, 6))

    data = [["#", "WR#", "Customer", "Commodity", "Qty", "Unit", "CBM", "KG"]]
    total_cbm = Decimal("0")
    total_kg = Decimal("0")
    total_qty = 0

    for i, line in enumerate(lines, 1):
        wr = line.warehouse_receipt
        data.append([
            str(i), wr.wr_number, wr.customer.name[:22], wr.commodity[:28],
            str(line.qty_loaded), wr.qty_unit_type.value,
            f"{line.cbm_loaded:.4f}", f"{line.kg_loaded:.2f}",
        ])
        total_cbm += Decimal(str(line.cbm_loaded))
        total_kg += Decimal(str(line.kg_loaded))
        total_qty += line.qty_loaded

    data.append(["", "TOTAL", f"{len(lines)} lines", "", str(total_qty), "",
                 f"{total_cbm:.4f}", f"{total_kg:.2f}"])

    table = _styled_table(data, [0.3*inch, 1*inch, 1.3*inch, 1.7*inch, 0.5*inch, 0.6*inch, 0.9*inch, 0.9*inch])
    for col in range(4, 8):
        table.setStyle(TableStyle([("ALIGN", (col, 0), (col, -1), "RIGHT")]))
    elements.append(table)

    elements.append(Spacer(1, 12))
    pct = (float(total_cbm) / max_cbm * 100) if max_cbm > 0 else 0
    elements.append(Paragraph(
        f'<font size="8" color="#64748b">Capacity: {total_cbm:.2f} / {max_cbm} m' + u'\u00B3'
        + f' ({pct:.1f}%) | Free: {max_cbm - float(total_cbm):.2f} m' + u'\u00B3' + '</font>',
        styles["Normal"],
    ))

    # Footer
    elements.append(Spacer(1, 24))
    elements.append(Paragraph(
        '<font size="7" color="#94a3b8">This document is system-generated by ConsolidaTrack. '
        'For questions contact your logistics coordinator.</font>',
        styles["Normal"],
    ))

    doc.build(elements)
    buf.seek(0)

    filename = f"packing_list_{container.container_number or container.id}.pdf"
    return Response(
        buf.getvalue(), mimetype="application/pdf",
        headers={"Content-Disposition": f"inline; filename={filename}"},
    )


# ══════════════════════════════════════════════════════════════════════
#  7. WAREHOUSE STOCK PDF
# ══════════════════════════════════════════════════════════════════════

@reports_bp.route("/stock/pdf")
@login_required
def stock_pdf():
    wh_id = request.args.get("warehouse_id", type=int)
    query = WarehouseReceipt.query.filter(
        WarehouseReceipt.status.in_([WRStatus.RECEIVED, WRStatus.PARTIALLY_LOADED])
    )
    if wh_id:
        query = query.filter_by(warehouse_id=wh_id)

    wrs = query.order_by(WarehouseReceipt.warehouse_id, WarehouseReceipt.customer_id).all()
    warehouses = Warehouse.query.filter_by(is_active=True).all()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.4*inch, bottomMargin=0.4*inch, leftMargin=0.5*inch, rightMargin=0.5*inch)
    styles = getSampleStyleSheet()
    elements = []

    wh_name = "All Warehouses"
    if wh_id:
        wh = db.session.get(Warehouse, wh_id)
        if wh:
            wh_name = f"{wh.name} ({wh.code})"

    _pdf_header(elements, styles, "WAREHOUSE STOCK REPORT", wh_name)

    data = [["WR#", "Warehouse", "Customer", "Commodity", "Qty Avail", "CBM Avail", "KG Avail", "Status"]]
    total_cbm = Decimal("0")
    total_kg = Decimal("0")

    for wr in wrs:
        data.append([
            wr.wr_number, wr.warehouse.code, wr.customer.name[:18], wr.commodity[:20],
            str(wr.qty_available), f"{wr.cbm_available:.4f}", f"{wr.kg_available:.2f}",
            wr.status.value,
        ])
        total_cbm += wr.cbm_available
        total_kg += wr.kg_available

    data.append(["TOTAL", "", f"{len(wrs)} WRs", "", "", f"{total_cbm:.4f}", f"{total_kg:.2f}", ""])

    table = _styled_table(data, [0.9*inch, 0.7*inch, 1.2*inch, 1.3*inch, 0.7*inch, 0.9*inch, 0.8*inch, 0.9*inch])
    for col in range(4, 7):
        table.setStyle(TableStyle([("ALIGN", (col, 0), (col, -1), "RIGHT")]))
    elements.append(table)

    elements.append(Spacer(1, 20))
    elements.append(Paragraph(
        '<font size="7" color="#94a3b8">ConsolidaTrack — Warehouse Stock Report</font>',
        styles["Normal"],
    ))

    doc.build(elements)
    buf.seek(0)

    return Response(
        buf.getvalue(), mimetype="application/pdf",
        headers={"Content-Disposition": "inline; filename=warehouse_stock.pdf"},
    )


# ══════════════════════════════════════════════════════════════════════
#  8. FINANCIAL SUMMARY PDF
# ══════════════════════════════════════════════════════════════════════

@reports_bp.route("/finance/pdf")
@login_required
def finance_pdf():
    invoices = FreightInvoice.query.order_by(FreightInvoice.issue_date.desc()).all()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.4*inch, bottomMargin=0.4*inch, leftMargin=0.5*inch, rightMargin=0.5*inch)
    styles = getSampleStyleSheet()
    elements = []

    total_amount = sum(Decimal(str(inv.amount)) for inv in invoices)
    total_paid = sum(inv.total_paid for inv in invoices)
    total_balance = total_amount - total_paid

    _pdf_header(elements, styles, "FINANCIAL SUMMARY", f"{len(invoices)} Invoices")

    # KPI row
    kpi_data = [
        ["Total Amount", "Total Paid", "Total Balance", "Open Invoices"],
        [f"${total_amount:,.2f}", f"${total_paid:,.2f}", f"${total_balance:,.2f}",
         str(sum(1 for i in invoices if i.status.value in ('OPEN', 'PARTIAL')))],
    ]
    kpi_table = Table(kpi_data, colWidths=[1.85*inch, 1.85*inch, 1.85*inch, 1.85*inch])
    kpi_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 7),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#64748b")),
        ("FONTSIZE", (0, 1), (-1, 1), 12),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 1), (0, 1), colors.HexColor("#3b82f6")),
        ("TEXTCOLOR", (1, 1), (1, 1), colors.HexColor("#10b981")),
        ("TEXTCOLOR", (2, 1), (2, 1), colors.HexColor("#ef4444")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(kpi_table)
    elements.append(Spacer(1, 14))

    # Invoice table
    data = [["Invoice #", "Container", "Origin", "Supplier", "Amount", "Paid", "Balance", "Status", "Due"]]
    for inv in invoices:
        data.append([
            inv.invoice_no, inv.container.container_number or "TBD",
            (inv.container.pol or "?")[:12], inv.supplier[:15],
            f"{inv.amount:.2f}", f"{inv.total_paid:.2f}", f"{inv.balance:.2f}",
            inv.status.value, str(inv.due_date or "-"),
        ])

    data.append(["TOTAL", "", "", f"{len(invoices)} inv.",
                 f"{total_amount:.2f}", f"{total_paid:.2f}", f"{total_balance:.2f}", "", ""])

    table = _styled_table(data, [0.9*inch, 0.8*inch, 0.7*inch, 1*inch, 0.8*inch, 0.7*inch, 0.8*inch, 0.7*inch, 0.8*inch])
    for col in range(4, 7):
        table.setStyle(TableStyle([("ALIGN", (col, 0), (col, -1), "RIGHT")]))
    elements.append(table)

    elements.append(Spacer(1, 20))
    elements.append(Paragraph(
        '<font size="7" color="#94a3b8">ConsolidaTrack — Financial Summary Report</font>',
        styles["Normal"],
    ))

    doc.build(elements)
    buf.seek(0)

    return Response(
        buf.getvalue(), mimetype="application/pdf",
        headers={"Content-Disposition": "inline; filename=financial_summary.pdf"},
    )


# ══════════════════════════════════════════════════════════════════════
#  9. CUSTOMER STATEMENT PDF
# ══════════════════════════════════════════════════════════════════════

@reports_bp.route("/customer-statement/<int:customer_id>/pdf")
@login_required
def customer_statement_pdf(customer_id):
    customer = db.session.get(Customer, customer_id)
    if not customer:
        flash("Customer not found.", "warning")
        return redirect(url_for("reports.report_index"))

    wrs = WarehouseReceipt.query.filter_by(customer_id=customer.id).order_by(
        WarehouseReceipt.date_received.desc()
    ).all()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.4*inch, bottomMargin=0.4*inch, leftMargin=0.5*inch, rightMargin=0.5*inch)
    styles = getSampleStyleSheet()
    elements = []

    _pdf_header(elements, styles, "CUSTOMER STATEMENT",
                f"{customer.name} ({customer.code})")

    # Summary
    total_wrs = len(wrs)
    received = sum(1 for w in wrs if w.status.value == 'RECEIVED')
    partial = sum(1 for w in wrs if w.status.value == 'PARTIALLY_LOADED')
    loaded = sum(1 for w in wrs if w.status.value == 'LOADED')
    total_cbm = sum(w.cbm_total for w in wrs)
    avail_cbm = sum(w.cbm_available for w in wrs)

    sum_data = [
        ["Total WRs", "Received", "Partially Loaded", "Fully Loaded", "Total CBM", "Available CBM"],
        [str(total_wrs), str(received), str(partial), str(loaded), f"{total_cbm:.2f}", f"{avail_cbm:.2f}"],
    ]
    sum_table = Table(sum_data, colWidths=[1.2*inch]*6)
    sum_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 7),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#64748b")),
        ("FONTSIZE", (0, 1), (-1, 1), 11),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(sum_table)
    elements.append(Spacer(1, 14))

    # WR detail table
    data = [["WR#", "Warehouse", "Date", "Commodity", "Qty Total", "Qty Avail", "CBM", "KG", "Status"]]
    for wr in wrs:
        data.append([
            wr.wr_number, wr.warehouse.code, str(wr.date_received),
            wr.commodity[:20], str(wr.qty_total), str(wr.qty_available),
            f"{wr.cbm_total:.2f}", f"{wr.kg_total:.0f}", wr.status.value,
        ])

    table = _styled_table(data, [0.8*inch, 0.6*inch, 0.8*inch, 1.3*inch, 0.6*inch, 0.6*inch, 0.7*inch, 0.6*inch, 0.9*inch], has_total=False)
    elements.append(table)

    elements.append(Spacer(1, 20))
    elements.append(Paragraph(
        '<font size="7" color="#94a3b8">ConsolidaTrack — Customer Statement</font>',
        styles["Normal"],
    ))

    doc.build(elements)
    buf.seek(0)

    filename = f"statement_{customer.code}.pdf"
    return Response(
        buf.getvalue(), mimetype="application/pdf",
        headers={"Content-Disposition": f"inline; filename={filename}"},
    )


# ══════════════════════════════════════════════════════════════════════
#  10. SHIPPING INSTRUCTIONS PDF
# ══════════════════════════════════════════════════════════════════════

@reports_bp.route("/shipping-instructions/<int:container_id>/pdf")
@login_required
def shipping_instructions_pdf(container_id):
    container = db.session.get(Container, container_id)
    if not container:
        flash("Container not found.", "warning")
        return redirect(url_for("reports.report_index"))

    lines = container.load_lines.all()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.4*inch, bottomMargin=0.4*inch, leftMargin=0.5*inch, rightMargin=0.5*inch)
    styles = getSampleStyleSheet()
    elements = []

    _pdf_header(elements, styles, "SHIPPING INSTRUCTIONS",
                f"Container: {container.container_number or 'TBD'}")

    # Shipper / Consignee section
    ship_data = [
        ["SHIPPER / EXPORTER", "", "CONSIGNEE / NOTIFY PARTY", ""],
        ["Carrier:", container.carrier or "_____________", "Forwarder:", container.forwarder or "_____________"],
        ["Booking:", container.booking_number or "_____________", "", ""],
    ]
    ship_table = Table(ship_data, colWidths=[1.1*inch, 2.7*inch, 1.3*inch, 2.4*inch])
    ship_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, 0), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (1, 0), colors.HexColor("#dbeafe")),
        ("BACKGROUND", (2, 0), (3, 0), colors.HexColor("#dcfce7")),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 1), (2, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 1), (0, -1), colors.HexColor("#64748b")),
        ("TEXTCOLOR", (2, 1), (2, -1), colors.HexColor("#64748b")),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(ship_table)
    elements.append(Spacer(1, 10))

    # Voyage details
    voyage_data = [
        ["PORT OF LOADING", "PORT OF DISCHARGE", "ETD", "ETA"],
        [container.pol or "-", container.pod or "-", str(container.etd or "-"), str(container.eta or "-")],
    ]
    voyage_table = Table(voyage_data, colWidths=[2.3*inch, 2.3*inch, 1.5*inch, 1.4*inch])
    voyage_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#fef3c7")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(voyage_table)
    elements.append(Spacer(1, 14))

    # Container + Cargo
    elements.append(Paragraph(
        f'<font size="10" color="#1e293b"><b>Container: </b></font>'
        f'<font size="12" color="#3b82f6"><b>{container.container_number or "TBD"}</b></font>'
        f'<font size="10" color="#1e293b"><b> &nbsp;|&nbsp; Type: {container.container_type or "-"}</b></font>', styles["Normal"]))
    elements.append(Spacer(1, 8))

    data = [["#", "WR#", "Customer", "Description", "Qty", "Unit", "CBM", "KG"]]
    total_cbm = Decimal("0")
    total_kg = Decimal("0")

    for i, line in enumerate(lines, 1):
        wr = line.warehouse_receipt
        data.append([
            str(i), wr.wr_number, wr.customer.name[:22], wr.commodity[:28],
            str(line.qty_loaded), wr.qty_unit_type.value,
            f"{line.cbm_loaded:.4f}", f"{line.kg_loaded:.2f}",
        ])
        total_cbm += Decimal(str(line.cbm_loaded))
        total_kg += Decimal(str(line.kg_loaded))

    data.append(["", "TOTAL", "", "", str(sum(l.qty_loaded for l in lines)),
                 "", f"{total_cbm:.4f}", f"{total_kg:.2f}"])

    table = _styled_table(data, [0.3*inch, 1*inch, 1.3*inch, 1.7*inch, 0.5*inch, 0.6*inch, 0.9*inch, 0.9*inch])
    for col in range(4, 8):
        table.setStyle(TableStyle([("ALIGN", (col, 0), (col, -1), "RIGHT")]))
    elements.append(table)

    # Signatures
    elements.append(Spacer(1, 40))
    sig_data = [
        ["_________________________", "", "_________________________"],
        ["Shipper Signature", "", "Carrier Signature"],
    ]
    sig_table = Table(sig_data, colWidths=[2.8*inch, 1.9*inch, 2.8*inch])
    sig_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TEXTCOLOR", (0, 1), (-1, 1), colors.HexColor("#94a3b8")),
    ]))
    elements.append(sig_table)

    doc.build(elements)
    buf.seek(0)

    filename = f"shipping_instructions_{container.container_number or container.id}.pdf"
    return Response(
        buf.getvalue(), mimetype="application/pdf",
        headers={"Content-Disposition": f"inline; filename={filename}"},
    )
