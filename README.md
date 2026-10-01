# Field Service Management (FSM) - Backend

An enterprise-grade, distributed backend system for managing the end-to-end field service lifecycle:
`Service Request -> Dispatcher Review -> Work Order -> Technician Scheduling -> Field Service Execution -> Automated Billing -> Payment -> Closure`

---

## Architecture Overview

- **Modular Domain Architecture**: Domain-specific apps organized under the `apps/` directory (`apps.core`, `apps.accounts`, `apps.customers`, `apps.work_orders`, etc.).
- **Split Settings Pattern**:
  - `config/settings/base.py`: Common framework and DRF configurations.
  - `config/settings/local.py`: Local developer environment with SQLite/Postgres flexibility.
  - `config/settings/production.py`: Production-hardened settings with strict security headers.
- **Core Base Models (`apps.core.models`)**:
  - `UUIDModel`: Security-focused UUIDv4 primary keys.
  - `TimeStampedModel`: Automatic `created_at` and `updated_at` indexing.
  - `SoftDeletableModel`: Custom manager preventing accidental hard deletion of business records.

---

## Local Development Setup

### 1. Prerequisites
- Python 3.11+ (Python 3.13 recommended)

### 2. Setup Virtual Environment
```bash
python -m venv .venv
# On Windows:
.\.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements/local.txt
```

### 4. Configure Environment
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

### 5. Run Tests
```bash
pytest
```

### 6. Start Development Server
```bash
python manage.py runserver
```

Health Check Endpoint: `http://localhost:8000/api/v1/health/`
