# Microservicio Caja Menor

API REST para gestión de **Legalización de Gastos, Anticipos y Caja Menor**, construido con Django 5 + Django REST Framework + PostgreSQL.

## Estructura

```
CajaMenor/
├── manage.py
├── requirements.txt
├── .env.example
├── cajamenor/              # Proyecto Django
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
└── legalizaciones/         # App principal
    ├── models.py           # Legalizacion (Maestro) + Gasto (Detalle)
    ├── serializers.py      # Anidamiento + bulk
    ├── views.py            # ModelViewSet CRUD + endpoint masivo
    ├── signals.py          # Recálculo automático del saldo
    ├── urls.py
    └── admin.py
```

## Setup rápido

```bash
python -m venv .venv
.venv\Scripts\activate              # Windows
pip install -r requirements.txt
copy .env.example .env              # ajustar credenciales Postgres
python manage.py makemigrations legalizaciones
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Endpoints principales (prefijo `/api/v1/`)

| Método | URL | Descripción |
|--------|-----|-------------|
| GET    | `/legalizaciones/`                          | Lista de legalizaciones (con gastos anidados). |
| POST   | `/legalizaciones/`                          | Crea cabecera + gastos en un solo payload. |
| GET    | `/legalizaciones/{numero}/`                 | Detalle con gastos anidados. |
| PUT/PATCH | `/legalizaciones/{numero}/`              | Actualiza cabecera y gastos (sync por id). |
| DELETE | `/legalizaciones/{numero}/`                 | Elimina cascada. |
| POST   | `/legalizaciones/bulk/`                     | Alias semántico para inserción masiva. |
| POST   | `/legalizaciones/{numero}/agregar-gastos/`  | Agrega gastos a una legalización existente. |
| POST   | `/legalizaciones/{numero}/aprobar/`         | Marca como APROBADO. |
| POST   | `/legalizaciones/{numero}/rechazar/`        | Marca como RECHAZADO. |
| GET/POST/... | `/gastos/`                            | CRUD individual de gastos. |

Documentación interactiva:
- Swagger UI: `/api/docs/`
- ReDoc: `/api/redoc/`
- Schema OpenAPI: `/api/schema/`

## Lógica de saldo

El campo `saldo` se recalcula automáticamente vía `signals.post_save` y `signals.post_delete` sobre `Gasto`:

```
saldo = monto_aprobado - sum(gastos.valor)
```

- **Saldo positivo** → a favor de la empresa (sobrante por reintegrar).
- **Saldo negativo** → a favor del empleado (la empresa debe reembolsar).

## Ejemplo: creación masiva

```http
POST /api/v1/legalizaciones/
Content-Type: application/json

{
  "monto_aprobado": "500000.00",
  "fecha_solicitud": "2026-04-27",
  "elaboro": 1,
  "estado": "BORRADOR",
  "gastos": [
    {
      "fecha": "2026-04-25",
      "cliente_proveedor": "Papelería La Esquina",
      "cedula_nit": "900123456-7",
      "numero_factura": "F-001-2025",
      "centro_costos": "ADM-01",
      "valor": "120000.00",
      "observaciones": "Útiles de oficina"
    },
    {
      "fecha": "2026-04-26",
      "cliente_proveedor": "Taxi Express",
      "cedula_nit": "1020304050",
      "numero_factura": "T-887",
      "centro_costos": "ADM-01",
      "valor": "35000.00"
    }
  ]
}
```

Respuesta `201 Created` incluye `saldo` ya calculado y los gastos persistidos con su `id`.
