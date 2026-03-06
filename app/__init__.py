"""Application factory — ConsolidaTrack."""
from flask import Flask

from app.config import Config
from app.extensions import csrf, db, login_manager, migrate


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # ── Initialize extensions ──
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    # ── User loader for Flask-Login ──
    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # ── Register Blueprints ──
    from app.blueprints.auth.routes import auth_bp
    from app.blueprints.wr.routes import wr_bp
    from app.blueprints.containers.routes import containers_bp
    from app.blueprints.finance.routes import finance_bp
    from app.blueprints.tracking.routes import tracking_bp
    from app.blueprints.reports.routes import reports_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(wr_bp, url_prefix="/wr")
    app.register_blueprint(containers_bp, url_prefix="/containers")
    app.register_blueprint(finance_bp, url_prefix="/finance")
    app.register_blueprint(tracking_bp, url_prefix="/tracking")
    app.register_blueprint(reports_bp, url_prefix="/reports")

    # ── Dashboard route ──
    from app.blueprints.dashboard import register_dashboard
    register_dashboard(app)

    # ── CLI commands ──
    from app.cli import register_cli
    register_cli(app)

    # ── Context processors ──
    @app.context_processor
    def inject_enums():
        from app.models import ContainerStatus, WRStatus
        return dict(WRStatus=WRStatus, ContainerStatus=ContainerStatus)

    # ── Database setup ──
    with app.app_context():
        db_uri = app.config["SQLALCHEMY_DATABASE_URI"]
        is_sqlite = db_uri.startswith("sqlite")

        if is_sqlite:
            from sqlalchemy import event as sa_event

            @sa_event.listens_for(db.engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        # Auto-create any missing tables
        db.create_all()

    # ── Ensure uploads dir exists ──
    import os
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    return app
