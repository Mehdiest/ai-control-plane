# AI Control Plane

![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat&logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16+-336791?style=flat&logo=postgresql&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-D71F00?style=flat&logo=sqlalchemy&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?style=flat&logo=docker&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green?style=flat)
![Status](https://img.shields.io/badge/Status-Phase%202%20of%204-orange?style=flat)

A lightweight control plane for AI services — handling service registration, background health checking, and policy-based routing. Applies the control-plane / data-plane separation principle from SDN and service mesh architecture to AI infrastructure.

## Origin

This project grew out of a real need inside the
[Enterprise AI Business Intelligence Platform](https://github.com/Mehdiest/Enterprise-AI-Business-Intelligence-Platform):
reliably knowing whether an LLM provider or downstream service was actually
reachable before routing a request to it. The BI Platform is the first
service registered with this control plane, but the control plane itself is
generic — it can register and govern any HTTP-based AI service.

## Phase 1 Scope — Service Registry & Health Checking

- **Service Registry**: register, list, fetch, and deregister downstream services via a REST API.
- **Background Health Checking**: an APScheduler job polls every registered service's health endpoint on a fixed interval and updates its status — conceptually the same as how a router marks a BGP neighbor up or down based on consecutive missed keepalives.
- **Status Model**: `UNKNOWN → HEALTHY / DEGRADED → UNHEALTHY`, based on a configurable consecutive-failure threshold.

## Phase 2 Scope — Policy-Based Routing

- **Policy Engine**: evaluates active routing policies in priority order (lowest first) — mirroring route-map clause evaluation in traditional network policy-based routing.
- **Automatic Failover**: if the primary target is unhealthy, the engine transparently falls back to the configured secondary without any change to the caller.
- **Admin Status Override**: manually force a service into any health state for controlled failover testing — the equivalent of `shutdown` / `no shutdown` on a network interface.
- **Resolution Codes**: every routing decision returns a typed outcome (`primary`, `fallback`, `no_policy`, `no_healthy_service`) so callers can handle each case explicitly.

## Architecture

```
┌──────────────────────────────────────────────┐
│              FastAPI Application               │
│  ┌─────────────────┐  ┌────────────────────┐ │
│  │  Registry API    │  │   Policies API     │ │
│  │  (CRUD + status  │  │  (CRUD + /route)   │ │
│  │   override)      │  │                    │ │
│  └─────────────────┘  └────────────────────┘ │
│  ┌──────────────────────────────────────────┐ │
│  │     APScheduler — Health Check Cycle      │ │
│  └──────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────┐ │
│  │          Policy Engine                    │ │
│  │  priority sort → health check → failover  │ │
│  └──────────────────────────────────────────┘ │
└───────────────────┬──────────────────────────-┘
                    │
         PostgreSQL (services + policies)
                    │
        ┌───────────┴────────────┐
        ▼                        ▼
  BI Platform             Any AI Service
  (primary)               (fallback / secondary)
```

## Tech Stack

| Layer | Technology |
|---|---|
| API Framework | FastAPI 0.115 |
| ORM | SQLAlchemy 2.0 (async) |
| Database | PostgreSQL 16+ |
| Scheduling | APScheduler 3.x |
| HTTP Client | httpx (async) |
| Validation | Pydantic v2 |
| Containerization | Docker / docker-compose |

## Project Structure

```
ai-control-plane/
├── app/
│   ├── api/v1/
│   │   ├── __init__.py         # aggregates v1 routers
│   │   ├── registry.py         # service registry CRUD + status override
│   │   └── policies.py         # policy CRUD + route resolution endpoint
│   ├── core/
│   │   ├── config.py           # environment-driven settings
│   │   └── database.py         # async engine + session management
│   ├── models/
│   │   ├── service.py          # Service ORM model + status enum
│   │   └── policy.py           # Policy ORM model
│   ├── schemas/
│   │   ├── service.py          # service request/response schemas
│   │   └── policy.py           # policy + route resolution schemas
│   ├── services/
│   │   ├── health_checker.py   # background health-check engine
│   │   └── policy_engine.py    # routing decision logic
│   └── main.py                 # app entrypoint + lifespan
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
# edit DATABASE_URL in .env to match your PostgreSQL credentials
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### With Docker
```bash
docker-compose up --build
```

API docs available at `http://localhost:8000/docs`.

## API Endpoints

### Registry

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/registry` | Register a new service |
| `GET` | `/api/v1/registry` | List all services + aggregate health summary |
| `GET` | `/api/v1/registry/{id}` | Fetch a single service |
| `PATCH` | `/api/v1/registry/{id}/status` | Manually override a service's health status |
| `DELETE` | `/api/v1/registry/{id}` | Deregister a service |

### Policies & Routing

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/policies` | Create a routing policy |
| `GET` | `/api/v1/policies` | List all policies |
| `GET` | `/api/v1/policies/{id}` | Fetch a single policy |
| `PATCH` | `/api/v1/policies/{id}` | Update a policy (partial) |
| `DELETE` | `/api/v1/policies/{id}` | Delete a policy |
| `POST` | `/api/v1/route` | Resolve which service should handle a request |

### Meta

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness check for the control plane itself |

## Roadmap

- ✅ **Phase 1** — Service Registry & Health Checking
- ✅ **Phase 2** — Policy-Based Routing with Failover
- 🔲 **Phase 3** — Rate Limiting & Quota per Tenant (Redis-backed, JWT-aware)
- 🔲 **Phase 4** — Observability Dashboard (traffic distribution, error rates, latency trends)
- 🔲 **Phase 5** — Canary Rollout support

## License

MIT
