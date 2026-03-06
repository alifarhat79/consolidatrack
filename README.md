# ConsolidaTrack — Sistema de Consolidación y Tracking Marítimo

## Visión General
Sistema web interno (Python/Flask/SQLite) para gestionar:
- 2 warehouses: **Shenzhen (China)** y **Miami (USA)**
- Recepción de cargas consolidadas (WR – Warehouse Receipts)
- Carga de contenedores (completa o parcial)
- Tracking marítimo vía SeaRates API con mapa Leaflet
- Gestión financiera de fletes

## Stack Tecnológico
| Capa | Tecnología |
|------|-----------|
| Backend | Python 3.11+, Flask 3.x |
| ORM | SQLAlchemy + Flask-Migrate (Alembic) |
| DB | SQLite 3 (WAL mode) |
| Auth | Flask-Login + Werkzeug |
| Templates | Jinja2 + Bootstrap 5 |
| Mapas | Leaflet.js |
| Reportes | ReportLab (PDF), csv stdlib |
| Scheduler | APScheduler |
| Server | Gunicorn (producción) |

## Instalación Rápida
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
cp .env.example .env      # Editar credenciales
flask db upgrade
flask seed-data            # Datos de prueba
flask run --debug
```

## Estructura del Proyecto
```
consolidation-system/
├── app/
│   ├── __init__.py          # App factory
│   ├── models.py            # SQLAlchemy models
│   ├── extensions.py        # db, migrate, login_manager, scheduler
│   ├── config.py            # Config por entorno
│   ├── blueprints/
│   │   ├── auth/            # Login, roles, usuarios
│   │   ├── wr/              # Warehouse Receipts
│   │   ├── containers/      # Contenedores + loading
│   │   ├── finance/         # Facturas + pagos flete
│   │   ├── tracking/        # SeaRates API + mapa
│   │   └── reports/         # PDF/CSV exports
│   ├── templates/
│   └── static/
├── migrations/
├── tests/
├── seeds/
├── docs/
│   └── DESIGN.md            # Diseño funcional completo
├── requirements.txt
├── .env.example
├── wsgi.py
└── run.py
```
