# Diseño Funcional — ConsolidaTrack

## 1. FLUJO OPERATIVO DIARIO (Paso a Paso)

### Flujo Principal: Shenzhen → Contenedor → Destino

```
[1] RECEPCIÓN          [2] ACUMULACIÓN        [3] CARGA              [4] ENVÍO             [5] TRACKING
Cliente entrega    →   WRs acumulan stock  →  Operador arma       →  Contenedor sale   →  API SeaRates
mercadería al WH       hasta ~70 m³           contenedor              con ETD/ETA          actualiza posición
Se crea WR único       Dashboard muestra      Carga total o          Eventos:             Mapa Leaflet
con qty/cbm/kg         stock disponible       parcial de WRs         SHIPPED/ARRIVED      muestra ruta
                                              Cierra contenedor      /UNLOADED
```

### Detalle por Paso:

**Paso 1 — Recepción (WR)**
1. Operador selecciona warehouse (Shenzhen o Miami)
2. Selecciona cliente (o crea nuevo)
3. Ingresa: commodity, qty, unit_type, cbm_total, kg_total
4. Sistema genera WR number: `SZX-2025-0001` o `MIA-2025-0001`
5. Status inicial: `RECEIVED`

**Paso 2 — Dashboard de Stock**
- Vista por warehouse: lista de WRs con status RECEIVED o PARTIALLY_LOADED
- Totales de cbm/kg disponibles por warehouse y por cliente
- Alerta visual cuando stock acumulado se acerca a 70 m³

**Paso 3 — Carga de Contenedor (Container Loading)**
1. Crear contenedor: número, tipo (20/40/40HQ), booking, carrier, POL, POD
2. Pantalla de carga: lista de WRs disponibles del warehouse
3. Para cada WR: elegir carga completa o parcial
   - Completa: qty_loaded = qty_disponible
   - Parcial: ingresar qty_loaded → cbm/kg se calculan proporcionalmente
4. Sistema valida: no exceder disponible, proporción cbm/kg coherente
5. Totales del contenedor se actualizan automáticamente
6. Al finalizar: "Cerrar contenedor" → CLOSED (no editable)

**Paso 4 — Envío**
1. Ingresar ETD/ETA, confirmar POL/POD
2. Evento SHIPPED con timestamp
3. Registrar factura de flete (opcional en este paso)

**Paso 5 — Tracking**
1. Job automático consulta SeaRates cada N horas
2. Guarda puntos con lat/lon + eventos
3. Actualiza ETA si la API provee nuevo valor
4. Mapa Leaflet muestra posición actual + ruta histórica

---

## 2. MODELO DE DATOS (ERD)

### Diagrama de Relaciones
```
warehouses ─────┐
                │ 1:N
customers ──┐   ├── warehouse_receipts ──┐
            │   │                        │ N:M (via container_load_lines)
            │   │                        │
users ──────┤   │   containers ──────────┤
roles ──────┤   │       │                │
user_roles ─┘   │       │ 1:N            │
                │       ├── container_load_lines
                │       ├── container_events
                │       ├── container_tracking_points
                │       ├── freight_invoices ── freight_payments
                │       └── freight_proration
                │
                └── audit_log (genérica)
```

### Reglas de Integridad
- WR pertenece a UN warehouse fijo (no transferible)
- container_load_lines.qty_loaded ≤ WR.qty_disponible (calculado)
- Contenedor CLOSED: no INSERT/UPDATE/DELETE en load_lines ni events
- freight_payments.amount acumulado ≤ freight_invoice.amount

---

## 3. PANTALLAS (Wireframes Textuales)

### 3.1 Dashboard Principal
```
╔══════════════════════════════════════════════════════════════╗
║  ConsolidaTrack                    [Shenzhen ▼]  [User ▼]  ║
╠══════════════════════════════════════════════════════════════╣
║  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐           ║
║  │ WRs Pending │ │ CBM Disp.   │ │ Containers  │           ║
║  │    47       │ │   58.3 m³   │ │  En Tránsito│           ║
║  │             │ │  (de 70 m³) │ │     3       │           ║
║  └─────────────┘ └─────────────┘ └─────────────┘           ║
║                                                              ║
║  Contenedores Activos                                        ║
║  ┌──────────┬──────┬─────┬─────┬────────┬────────┐          ║
║  │Container │Status│ CBM │ POL │  ETD   │  ETA   │          ║
║  ├──────────┼──────┼─────┼─────┼────────┼────────┤          ║
║  │MSKU123456│SHIPPED│67.2│SHENZHEN│Jan-15│Feb-20 │          ║
║  │TRIU789012│LOADING│42.1│MIAMI  │ ---  │ ---   │          ║
║  └──────────┴──────┴─────┴─────┴────────┴────────┘          ║
╚══════════════════════════════════════════════════════════════╝
```

### 3.2 WR — Crear Nuevo
```
╔══════════════════════════════════════════════════════════════╗
║  Nuevo Warehouse Receipt                                     ║
╠══════════════════════════════════════════════════════════════╣
║  Warehouse:  [Shenzhen ▼]                                    ║
║  Cliente:    [Acme Corp ▼]     [+ Nuevo Cliente]            ║
║  ───────────────────────────────────────                     ║
║  Commodity:  [Electrónicos varios_________]                  ║
║  Cantidad:   [500___]  Unidad: [CAJAS ▼]                    ║
║  CBM Total:  [12.500_]  m³                                   ║
║  Peso Total: [2500.00] kg                                    ║
║  Notas:      [________________________]                      ║
║                                                              ║
║           [Cancelar]  [Guardar WR]                           ║
╚══════════════════════════════════════════════════════════════╝
```

### 3.3 Container Loading
```
╔══════════════════════════════════════════════════════════════╗
║  Container Loading — MSKU1234567                             ║
║  Tipo: 40HQ | Carrier: MSC | POL: Shenzhen                  ║
║  Cargado: 42.1 m³ / 8,230 kg                                ║
╠══════════════════════════════════════════════════════════════╣
║  Líneas Cargadas:                                            ║
║  ┌────────────┬──────────┬─────┬──────┬──────┬─────┐        ║
║  │ WR#        │ Cliente  │ Qty │ CBM  │  KG  │ [X] │        ║
║  ├────────────┼──────────┼─────┼──────┼──────┼─────┤        ║
║  │SZX-25-0012│Acme Corp │ 500 │22.50 │4500  │ 🗑  │        ║
║  │SZX-25-0015│Beta Ltd  │ 200 │19.60 │3730  │ 🗑  │        ║
║  └────────────┴──────────┴─────┴──────┴──────┴─────┘        ║
║                                                              ║
║  + Agregar Carga:                                            ║
║  WR: [SZX-25-0020 - Gamma Inc - Textiles ▼]                 ║
║  Disponible: 300 cajas | 15.0 m³ | 3000 kg                  ║
║  Cargar: ○ Completo  ● Parcial                               ║
║  Qty a cargar: [150__]  → CBM: 7.500  KG: 1500.00           ║
║                          [Agregar al Contenedor]             ║
║  ─────────────────────────────────────────────               ║
║  [Cerrar Contenedor]  [Generar Manifest]                     ║
╚══════════════════════════════════════════════════════════════╝
```

### 3.4 Tracking / Mapa
```
╔══════════════════════════════════════════════════════════════╗
║  Tracking — MSKU1234567                                      ║
║  Status: IN TRANSIT | ETA: Feb-20-2025                       ║
╠══════════════════════════════════════════════════════════════╣
║  ┌──────────────────────────────────────────────────┐        ║
║  │                                                    │       ║
║  │            🗺  MAPA LEAFLET                        │       ║
║  │                                                    │       ║
║  │     ● Shenzhen (POL)                               │       ║
║  │      ╲                                             │       ║
║  │       ╲___●___●___📍 (posición actual)            │       ║
║  │                         ╲                          │       ║
║  │                          ○ Miami (POD)             │       ║
║  │                                                    │       ║
║  └──────────────────────────────────────────────────┘        ║
║                                                              ║
║  Timeline de Eventos:                                        ║
║  ● Feb-01 09:00  Departed Shenzhen                           ║
║  ● Feb-05 14:30  Passed Singapore Strait                     ║
║  ● Feb-10 08:00  Last position: Indian Ocean (5.2°N, 73°E)  ║
╚══════════════════════════════════════════════════════════════╝
```

---

## 4. ESTADOS Y TRANSICIONES

### WR Status
```
RECEIVED → PARTIALLY_LOADED → LOADED
    │              │              │
    └──→ HOLD ←────┘              │
    └──→ CANCELLED               │
         HOLD → RECEIVED (reactivar)
```

### Container Status
```
PLANNED → LOADING → CLOSED → SHIPPED → ARRIVED → UNLOADED
              │                  ↑
              └── (cerrar) ──────┘
```

### Freight Invoice Status
```
OPEN → PARTIAL → PAID
  │
  └→ CANCELLED
```

---

## 5. DECISIÓN ARQUITECTÓNICA: Server-Side Rendering (Jinja2)

**Justificación:**
- Sistema interno con pocos usuarios concurrentes (<20)
- Simplicidad de despliegue (un solo servidor)
- Bootstrap 5 + Jinja2 ofrece UI funcional sin complejidad SPA
- Leaflet.js se integra como componente JS aislado
- Menor costo de mantenimiento que una SPA separada
- HTMX para interacciones dinámicas sin framework JS pesado
