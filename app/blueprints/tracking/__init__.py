"""Tracking blueprint — SeaRates API integration, map, scheduler.

IMPORTANT: The SeaRates API integration is designed as a pluggable service.
The actual API endpoints/payload structure should be verified against
SeaRates' current documentation (https://www.searates.com/reference/tracking).
The code below provides a clean interface that can be adapted.
"""
import json
import logging
from datetime import datetime, timezone

import requests
from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import db
from app.models import Container, ContainerStatus, ContainerTrackingPoint

logger = logging.getLogger(__name__)

tracking_bp = Blueprint("tracking", __name__, template_folder="../../templates/tracking")


# ══════════════════════════════════════════════════════════════════════
#  SeaRates Service (pluggable — adapt to actual API docs)
# ══════════════════════════════════════════════════════════════════════
class SeaRatesService:
    """Wrapper around SeaRates Tracking API.

    Adapt the `fetch_tracking` method to match the actual API:
      - Endpoint URL
      - Auth header/param format
      - Response JSON structure
    """

    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        })

    def fetch_tracking(self, container_number: str) -> dict | None:
        """Query SeaRates for container tracking events.

        Expected response structure (adapt as needed):
        {
            "status": "success",
            "data": {
                "eta": "2025-02-20T00:00:00Z",
                "events": [
                    {
                        "timestamp": "2025-01-15T09:00:00Z",
                        "description": "Departed from port",
                        "location": "Shenzhen, China",
                        "latitude": 22.5431,
                        "longitude": 114.0579
                    },
                    ...
                ]
            }
        }
        """
        if not self.api_key or not container_number:
            return None

        try:
            # ADAPT THIS URL to actual SeaRates endpoint
            url = f"{self.base_url}/tracking"
            params = {
                "container": container_number,
                "sealine": "auto",  # or specific SCAC code
            }
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()

        except requests.exceptions.RequestException as e:
            logger.error(f"SeaRates API error for {container_number}: {e}")
            return None


def _get_searates_service() -> SeaRatesService:
    return SeaRatesService(
        api_key=current_app.config["SEARATES_API_KEY"],
        base_url=current_app.config["SEARATES_BASE_URL"],
    )


def _process_tracking_response(container: Container, data: dict):
    """Parse SeaRates response and save tracking points + update ETA."""
    if not data or data.get("status") != "success":
        return 0

    tracking_data = data.get("data", {})

    # Update ETA if provided
    new_eta_str = tracking_data.get("eta")
    if new_eta_str:
        try:
            new_eta = datetime.fromisoformat(new_eta_str.replace("Z", "+00:00")).date()
            if container.eta != new_eta:
                container.eta = new_eta
        except (ValueError, AttributeError):
            pass

    # Process events
    events = tracking_data.get("events", [])
    saved = 0
    for event in events:
        ts_str = event.get("timestamp")
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except ValueError:
            continue

        # Check if we already have this point (avoid duplicates)
        existing = ContainerTrackingPoint.query.filter_by(
            container_id=container.id,
            timestamp=ts,
            event_description=event.get("description", ""),
        ).first()
        if existing:
            continue

        point = ContainerTrackingPoint(
            container_id=container.id,
            timestamp=ts,
            latitude=event.get("latitude"),
            longitude=event.get("longitude"),
            event_description=event.get("description", ""),
            location_name=event.get("location", ""),
            source="searates",
            raw_payload=json.dumps(event),
        )
        db.session.add(point)
        saved += 1

    return saved


# ── Update single container ──────────────────────────────────────────
def update_container_tracking(container_id: int):
    """Fetch and store tracking for one container."""
    container = db.session.get(Container, container_id)
    if not container or not container.container_number:
        return

    service = _get_searates_service()
    data = service.fetch_tracking(container.container_number)
    if data:
        saved = _process_tracking_response(container, data)
        db.session.commit()
        logger.info(f"Tracking updated for {container.container_number}: {saved} new points")


# ── Bulk update (for scheduler) ──────────────────────────────────────
def update_all_active_tracking(app=None):
    """Update tracking for all containers in transit. Called by scheduler."""
    if app is None:
        app = current_app._get_current_object()

    with app.app_context():
        containers = Container.query.filter(
            Container.status.in_([ContainerStatus.SHIPPED]),
            Container.container_number.isnot(None),
        ).all()

        logger.info(f"Updating tracking for {len(containers)} containers")
        for container in containers:
            try:
                update_container_tracking(container.id)
            except Exception as e:
                logger.error(f"Tracking update failed for {container.container_number}: {e}")
                continue


# ══════════════════════════════════════════════════════════════════════
#  ROUTES
# ══════════════════════════════════════════════════════════════════════

@tracking_bp.route("/<int:container_id>")
@login_required
def tracking_map(container_id):
    """Show tracking map with Leaflet."""
    container = db.session.get(Container, container_id)
    if not container:
        flash("Container not found.", "warning")
        return redirect(url_for("containers.container_list"))

    points = container.tracking_points.order_by(
        ContainerTrackingPoint.timestamp.asc()
    ).all()

    # Prepare data for Leaflet
    track_data = []
    for p in points:
        track_data.append({
            "timestamp": p.timestamp.isoformat() if p.timestamp else None,
            "lat": float(p.latitude) if p.latitude else None,
            "lon": float(p.longitude) if p.longitude else None,
            "description": p.event_description or "",
            "location": p.location_name or "",
        })

    return render_template(
        "tracking/map.html",
        container=container,
        track_data=json.dumps(track_data),
        points=points,
    )


@tracking_bp.route("/<int:container_id>/refresh", methods=["POST"])
@login_required
def refresh_tracking(container_id):
    """Manually trigger tracking update."""
    try:
        update_container_tracking(container_id)
        flash("Tracking updated.", "success")
    except Exception as e:
        flash(f"Error updating tracking: {e}", "danger")
    return redirect(url_for("tracking.tracking_map", container_id=container_id))
