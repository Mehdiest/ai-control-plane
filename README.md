# AI Control Plane

A lightweight control plane for registering, health-checking, and (in later
phases) routing traffic across AI services — applying control-plane /
data-plane separation, the same principle that underlies dynamic routing
protocols and service meshes, to AI infrastructure.

> **Status:** Phase 1 of 4 — Service Registry & Health Checking

## Origin

This project grew out of a real need inside the
[Enterprise AI Business Intelligence Platform](https://github.com/Mehdiest/Enterprise-AI-Business-Intelligence-Platform):
reliably knowing whether an LLM provider or downstream service was actually
reachable before routing a request to it. The BI Platform is the first
service registered with this control plane, but the control plane itself is
generic — it can register and govern any HTTP-based AI service.

## Phase 1 Scope

- **Service Registry**: register, list, fetch, and deregister downstream
  services via a REST API.
- **Background Health Checking**: an APScheduler job polls every registered
  service's health endpoint on a fixed interval and updates its status —
  conceptually the same as how a router marks a BGP neighbor up or down
  based on consecutive missed keepalives.
- **Status Model**: `UNKNOWN → HEALTHY / DEGRADED → UNHEALTHY`, based on a
  configurable consecutive-failure threshold.

## Architecture

```
┌─────────────────────────────┐
│      FastAPI Application     │
│  ┌────────────────────────┐ │
│  │  Registry API (CRUD)    │ │
│  └────────────────────────┘ │
│  ┌────────────────────────┐ │
│  │  APScheduler Job         │ │
│  │  (health check cycle)    │ │
│  └────────────────────────┘ │
└──────────────┬───────────────┘
               │
        PostgreSQL (services table)
               │
               ▼
   ┌───────────────────────────┐
   │  Registered Services        │
   │  (BI Platform, mock APIs…)  │
   └───────────────────────────┘
```

## Tech Stack

| Layer | Technology |
|---|---|
| API Framework | FastAPI |
| ORM | SQLAlchemy 2.0 (async) |
| Database | PostgreSQL |
| Scheduling | APScheduler |
| HTTP Client | httpx (async) |
| Containerization | Docker / docker-compose |

## Project Structure

```
ai-control-plane/
├── app/
│   ├── api/v1/
│   │   ├── __init__.py       # aggregates v1 routers
│   │   └── registry.py       # registry CRUD endpoints
│   ├── core/
│   │   ├── config.py         # environment-driven settings
│   │   └── database.py       # async engine + session management
│   ├── models/
│   │   └── service.py        # Service ORM model + status enum
│   ├── schemas/
│   │   └── service.py        # Pydantic request/response models
│   ├── services/
│   │   └── health_checker.py # background health-check engine
│   └── main.py                # app entrypoint + lifespan
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

## Getting Started

### Prerequisites
- Python 3.12+
- PostgreSQL 16+ (or use `docker-compose up`)

### Local setup
```bash
cp .env.example .env
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### With Docker
```bash
docker-compose up --build
```

The API docs are then available at `http://localhost:8000/docs`.

## API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/registry` | Register a new service |
| GET | `/api/v1/registry` | List all services + aggregate health summary |
| GET | `/api/v1/registry/{id}` | Fetch a single service |
| DELETE | `/api/v1/registry/{id}` | Deregister a service |
| GET | `/health` | Liveness check for the control plane itself |

## Roadmap

- **Phase 2** — Policy-Based Routing (route requests based on configurable rules)
- **Phase 3** — Rate Limiting & Quota per Tenant (Redis-backed, JWT-aware)
- **Phase 4** — Observability Dashboard (traffic distribution, error rates, latency trends)
- **Phase 5** — Canary Rollout support

## License

MIT
