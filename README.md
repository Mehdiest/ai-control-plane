# AI Control Plane

![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat&logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-18-336791?style=flat&logo=postgresql&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-D71F00?style=flat&logo=sqlalchemy&logoColor=white)
![Alembic](https://img.shields.io/badge/Alembic-1.18-6BA81E?style=flat&logo=alembic&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?style=flat&logo=docker&logoColor=white)
![Tests](https://img.shields.io/badge/Tests-24%20passed-brightgreen?style=flat&logo=pytest&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green?style=flat)
![Status](https://img.shields.io/badge/Status-Phase%202%20Complete-blue?style=flat)

A lightweight control plane for AI services — handling service registration, background health checking, and network-aware policy-based routing. Applies control-plane / data-plane separation, topology-aware routing, and failover mechanics from SDN and traditional networking (BGP, OSPF) to AI infrastructure.

## Origin

This project grew out of a real need inside the
[Enterprise AI Business Intelligence Platform](https://github.com/Mehdiest/Enterprise-AI-Business-Intelligence-Platform):
reliably knowing whether an LLM provider or downstream service was actually
reachable before routing a request to it. The BI Platform is the first
service registered with this control plane, but the control plane itself is
generic — it can register and govern any HTTP-based AI service.

## Phase 1 — Service Registry & Health Checking ✅

- **Service Registry**: register, list, fetch, and deregister downstream services via a REST API.
- **Background Health Checking**: an APScheduler job polls every registered service's health endpoint on a configurable interval — the same way a router marks a BGP neighbor up or down based on consecutive missed keepalives.
- **Status Model**: `UNKNOWN → HEALTHY / DEGRADED → UNHEALTHY` based on a configurable consecutive-failure threshold.
- **Admin Status Override**: manually force a service into any health state — the equivalent of `shutdown` / `no shutdown` on a network interface.

## Phase 2 — Policy-Based Routing ✅

- **Policy Engine**: evaluates active routing policies in priority order (lowest first) — mirroring route-map clause evaluation in traditional network policy-based routing.
- **Network-Aware Routing**: services carry topology metadata (region, latency zone, network tags) and policies can constrain routing to specific regions or latency classes — analogous to BGP community filtering and OSPF link-cost preference.
- **Automatic Failover**: if the primary target fails health or topology checks, the engine transparently falls back to the configured secondary. If all policies are exhausted, a typed resolution code is returned.
- **Policy Fallthrough**: when a constrained policy finds no eligible service, evaluation continues to the next policy in priority order — mirroring route-map clause fallthrough.
- **Conflict Validation**: no two active policies for the same request type may share the same priority value — enforced on both create and update.
- **FK-style Validation**: `target_service_name` and `fallback_service_name` are validated against registered services at the API layer before persistence.
- **Resolution Codes**: every routing decision returns a typed outcome (`primary`, `fallback`, `no_policy`, `no_healthy_service`) so callers can handle each case explicitly.

## Architecture

```
┌──────────────────────────────────────────────────┐
│                FastAPI Application                 │
│  ┌──────────────────┐  ┌────────────────────────┐ │
│  │  Registry API     │  │     Policies API        │ │
│  │  CRUD + override  │  │  CRUD + /route          │ │
│  └──────────────────┘  └────────────────────────┘ │
│  ┌────────────────────────────────────────────────┐│
│  │       APScheduler — Health Check Cycle          ││
│  │  ping → status update → failure threshold       ││
│  └────────────────────────────────────────────────┘│
│  ┌────────────────────────────────────────────────┐│
│  │           Policy Engine                         ││
│  │  priority sort → request match                  ││
│  │  → region/latency filter → health check         ││
│  │  → primary / fallback / fallthrough             ││
│  └────────────────────────────────────────────────┘│
└────────────────────┬─────────────────────────────-─┘
                     │
          PostgreSQL + Alembic migrations
                     │
       ┌─────────────┴──────────────┐
       ▼                            ▼
  BI Platform                 Any AI Service
  region: eu-west             region: on-premise
  latency: high               latency: low
  tags: [cloud, railway]      tags: [gpu, air-gapped]
```

## Network Topology Model

Each registered service carries three network attributes used by the policy engine to make topology-aware routing decisions:

| Attribute | Type | Analogy |
|---|---|---|
| `region` | string (e.g. `eu-west`, `on-premise`) | BGP community — restricts route advertisement to certain ASes |
| `latency_zone` | enum `low / medium / high` | OSPF link cost — lower cost paths are preferred |
| `network_tags` | list of strings (e.g. `["gpu", "air-gapped"]`) | BGP extended communities — free-form route filtering labels |

Policies can constrain routing with `match_region` and `match_latency_zone`. A service that does not satisfy these constraints is skipped, and the engine falls through to the next policy — exactly as a route-map clause with a failed match falls through to the next clause.

## Tech Stack

| Layer | Technology |
|---|---|
| API Framework | FastAPI 0.115 |
| ORM | SQLAlchemy 2.0 (async) |
| Database | PostgreSQL 18 |
| Migrations | Alembic 1.18 |
| Scheduling | APScheduler 3.x |
| HTTP Client | httpx (async) |
| Validation | Pydantic v2 |
| Testing | pytest + pytest-asyncio |
| Containerization | Docker / docker-compose |

## Project Structure

```
ai-control-plane/
├── alembic/                    # migration scripts (managed by Alembic)
│   ├── env.py                  # reads DATABASE_URL from .env, sync driver for migrations
│   └── versions/               # auto-generated migration files
├── app/
│   ├── api/v1/
│   │   ├── __init__.py         # aggregates v1 routers
│   │   ├── registry.py         # service registry CRUD + status override
│   │   └── policies.py         # policy CRUD + route resolution endpoint
│   ├── core/
│   │   ├── config.py           # environment-driven settings
│   │   └── database.py         # async engine + session management
│   ├── models/
│   │   ├── service.py          # Service ORM model + ServiceStatus + LatencyZone enums
│   │   └── policy.py           # Policy ORM model with network match conditions
│   ├── schemas/
│   │   ├── service.py          # service request/response schemas + path validator
│   │   └── policy.py           # policy schemas + RouteResult with topology fields
│   ├── services/
│   │   ├── health_checker.py   # background health-check engine
│   │   └── policy_engine.py    # two-stage routing: request match → topology filter
│   └── main.py                 # app entrypoint + lifespan (schema managed by Alembic)
├── tests/
│   ├── conftest.py             # shared fixtures (SQLite in-memory, sample services)
│   ├── test_health_checker.py  # health-check status transitions + path validation
│   ├── test_policy_conflicts.py # priority conflict validation (create + update)
│   └── test_policy_engine.py   # routing logic + network topology constraints
├── pytest.ini
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

## Getting Started

### Prerequisites
- Python 3.12+
- PostgreSQL 18+ (or use `docker-compose up`)

### Local setup
```bash
cp .env.example .env
# edit DATABASE_URL in .env with your PostgreSQL credentials
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

### With Docker
```bash
docker-compose up --build
```

API docs: `http://localhost:8000/docs`

### Run tests
```bash
pip install pytest pytest-asyncio httpx aiosqlite pytest-timeout
python -m pytest tests/ -v --timeout=15
```

> ⚠️ **Production note**: never deploy with default credentials from `.env.example`.
> Always set strong values for `DATABASE_URL` and `JWT_SECRET_KEY` in your environment.

## API Endpoints

### Registry

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/registry` | Register a new service (with region, latency_zone, network_tags) |
| `GET` | `/api/v1/registry` | List all services + aggregate health summary |
| `GET` | `/api/v1/registry/{id}` | Fetch a single service |
| `PATCH` | `/api/v1/registry/{id}/status` | Manually override a service's health status |
| `DELETE` | `/api/v1/registry/{id}` | Deregister a service |

### Policies & Routing

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/policies` | Create a routing policy (with optional region/latency constraints) |
| `GET` | `/api/v1/policies` | List all policies ordered by priority |
| `GET` | `/api/v1/policies/{id}` | Fetch a single policy |
| `PATCH` | `/api/v1/policies/{id}` | Update a policy (conflict-checked) |
| `DELETE` | `/api/v1/policies/{id}` | Delete a policy |
| `POST` | `/api/v1/route` | Resolve which service should handle a request |

### Meta

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness check for the control plane itself |

## Roadmap

- ✅ **Phase 1** — Service Registry & Health Checking
- ✅ **Phase 2** — Policy-Based Routing with Network-Aware Constraints
- 🔲 **Phase 3** — Rate Limiting & Quota per Tenant (Redis-backed, JWT-aware)
- 🔲 **Phase 4** — Observability Dashboard (traffic distribution, error rates, latency trends)
- 🔲 **Phase 5** — Canary Rollout support

## License

MIT
