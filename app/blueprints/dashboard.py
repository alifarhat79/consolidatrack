"""Dashboard / home page."""
from datetime import date

from flask import Flask, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Container, ContainerStatus, Customer, Warehouse, WarehouseReceipt, WRStatus


def register_dashboard(app: Flask):
    @app.route("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        return redirect(url_for("auth.login"))

    @app.route("/dashboard")
    @login_required
    def dashboard():
        warehouses = Warehouse.query.filter_by(is_active=True).all()
        stats = {}
        for wh in warehouses:
            # Pending WRs (RECEIVED or PARTIALLY_LOADED)
            pending_wrs_list = WarehouseReceipt.query.filter(
                WarehouseReceipt.warehouse_id == wh.id,
                WarehouseReceipt.status.in_([WRStatus.RECEIVED, WRStatus.PARTIALLY_LOADED]),
            ).order_by(WarehouseReceipt.created_at.desc()).all()

            # All WRs in this warehouse (for full view)
            all_wrs = WarehouseReceipt.query.filter(
                WarehouseReceipt.warehouse_id == wh.id,
            ).order_by(WarehouseReceipt.created_at.desc()).all()

            # Available CBM (not yet loaded)
            avail_cbm = db.session.execute(
                db.text("""
                    SELECT COALESCE(SUM(wr.cbm_total - COALESCE(loaded.cbm, 0)), 0)
                    FROM warehouse_receipts wr
                    LEFT JOIN (
                        SELECT wr_id, SUM(cbm_loaded) AS cbm
                        FROM container_load_lines GROUP BY wr_id
                    ) loaded ON loaded.wr_id = wr.id
                    WHERE wr.warehouse_id = :wid
                      AND wr.status IN ('RECEIVED', 'PARTIALLY_LOADED')
                """),
                {"wid": wh.id},
            ).scalar()

            # Available KG
            avail_kg = db.session.execute(
                db.text("""
                    SELECT COALESCE(SUM(wr.kg_total - COALESCE(loaded.kg, 0)), 0)
                    FROM warehouse_receipts wr
                    LEFT JOIN (
                        SELECT wr_id, SUM(kg_loaded) AS kg
                        FROM container_load_lines GROUP BY wr_id
                    ) loaded ON loaded.wr_id = wr.id
                    WHERE wr.warehouse_id = :wid
                      AND wr.status IN ('RECEIVED', 'PARTIALLY_LOADED')
                """),
                {"wid": wh.id},
            ).scalar()

            # Total units available
            avail_units = sum(wr.qty_available for wr in pending_wrs_list)

            # Containers in this warehouse
            wh_containers = Container.query.filter(
                Container.warehouse_id == wh.id,
                Container.status.in_([
                    ContainerStatus.PLANNED,
                    ContainerStatus.LOADING,
                    ContainerStatus.CLOSED,
                    ContainerStatus.SHIPPED,
                ]),
            ).order_by(Container.updated_at.desc()).all()

            stats[wh.code] = {
                "warehouse": wh,
                "pending_wrs": len(pending_wrs_list),
                "pending_wrs_list": pending_wrs_list,
                "all_wrs": all_wrs,
                "available_cbm": float(avail_cbm or 0),
                "available_kg": float(avail_kg or 0),
                "available_units": avail_units,
                "active_containers": len(wh_containers),
                "containers": wh_containers,
            }

        active_containers = Container.query.filter(
            Container.status.in_([
                ContainerStatus.LOADING,
                ContainerStatus.CLOSED,
                ContainerStatus.SHIPPED,
            ])
        ).order_by(Container.updated_at.desc()).limit(10).all()

        customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()

        return render_template(
            "dashboard.html",
            stats=stats,
            active_containers=active_containers,
            customers=customers,
            today=date.today().isoformat(),
        )
