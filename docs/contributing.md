# Contributing Guide

> FinanceTracker -- Developer Setup & Contribution Guidelines

Thank you for your interest in contributing to FinanceTracker. This guide covers everything you need to get started.

---

## Prerequisites

| Tool | Version | Installation |
|---|---|---|
| **Python** | 3.12+ | https://python.org or `pyenv install 3.12` |
| **uv** | Latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **Node.js** | 20+ | https://nodejs.org or `nvm install 20` |
| **pnpm** | 9+ | `npm install -g pnpm` |
| **Git** | 2.30+ | https://git-scm.com |
| **Redis** | 7+ | Optional: `brew install redis` (macOS) / `apt install redis-server` (Ubuntu) |
| **Ollama** | Latest | Optional: https://ollama.ai |
| **Rust** | Latest stable | Required only for desktop app: https://rustup.rs |

---

## Development Setup

### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/financeTracking.git
cd financeTracking
```

### 2. Backend Setup

```bash
cd backend

# Install Python dependencies
uv sync

# Create environment file
cp .env.example .env
# Edit .env with your settings (SECRET_KEY is auto-generated if empty)

# Run database migrations
uv run alembic upgrade head

# Seed development data (optional)
uv run python -m app.scripts.seed

# Start the backend server
uv run uvicorn app.main:app --reload --port 8000
```

The API is now available at http://localhost:8000 and Swagger docs at http://localhost:8000/docs.

### 3. Frontend Setup

```bash
# From the project root
pnpm install

# Start the web app
pnpm --filter web dev
```

The web app is now available at http://localhost:3000.

### 4. Desktop App Setup (Optional)

```bash
# Requires Rust toolchain (https://rustup.rs)
# The backend must be running first (step 2)
cd apps/desktop
pnpm tauri dev
```

For building production installers, see [desktop-app.md](desktop-app.md) — it covers the full 7-step build process, sidecar binary compilation, and platform-specific details.

### 5. Optional Services

```bash
# Redis (for background task queue)
redis-server

# Celery worker (requires Redis)
cd backend && uv run celery -A app.tasks.celery_app worker --beat -l info

# Ollama (for AI features)
ollama serve && ollama pull llama3.2
```

---

## Project Structure Overview

```
financeTracking/
+-- backend/               # Python FastAPI backend
|   +-- app/
|   |   +-- api/v1/        # REST API route handlers
|   |   +-- api/ws/        # WebSocket handlers
|   |   +-- models/        # SQLAlchemy ORM models
|   |   +-- schemas/       # Pydantic request/response schemas
|   |   +-- services/      # Business logic layer
|   |   +-- brokers/       # Broker integration adapters
|   |   +-- ml/            # ML/AI services
|   |   +-- tasks/         # Celery background tasks
|   |   +-- utils/         # Security, constants, helpers
|   +-- tests/             # Backend test suite
+-- apps/
|   +-- web/               # Next.js 15 web application
|   +-- desktop/           # Tauri v2 desktop application
+-- packages/
|   +-- ui/                # Shared UI component library
+-- docs/                  # Documentation (you are here)
+-- scripts/               # Setup, start, stop scripts
```

---

## Code Style

### Python (Backend)

**Formatter & Linter**: [ruff](https://docs.astral.sh/ruff/) (replaces black, isort, flake8)

```bash
# Format code
cd backend && uv run ruff format .

# Lint code
cd backend && uv run ruff check .

# Fix auto-fixable lint issues
cd backend && uv run ruff check --fix .
```

**Key rules**:
- Line length: 100 characters
- Imports sorted in sections (stdlib, third-party, local)
- Double quotes for strings
- Type hints required for function signatures
- Docstrings in Google style

```python
async def calculate_rsi(
    close_prices: list[float],
    period: int = 14,
) -> float:
    """Calculate the Relative Strength Index for a price series.

    Args:
        close_prices: List of closing prices, oldest first.
        period: RSI calculation period (default 14).

    Returns:
        RSI value between 0 and 100.

    Raises:
        ValueError: If close_prices has fewer than period + 1 elements.
    """
    ...
```

### TypeScript / JavaScript (Frontend)

**Formatter**: [Prettier](https://prettier.io/)
**Linter**: [ESLint](https://eslint.org/) with Next.js and TypeScript rules

```bash
# Format all frontend code
pnpm format

# Lint all frontend code
pnpm lint

# Type check
pnpm typecheck
```

**Key rules**:
- Line length: 100 characters
- Semicolons: required
- Quotes: double
- Trailing commas: all
- Imports sorted alphabetically
- React components use function declarations, not arrow functions
- Props interfaces named `{ComponentName}Props`

```tsx
interface PortfolioTableProps {
  portfolioId: string;
  onHoldingClick: (holdingId: string) => void;
}

export function PortfolioTable({ portfolioId, onHoldingClick }: PortfolioTableProps) {
  // ...
}
```

---

## Testing

### Backend Tests (pytest)

```bash
cd backend

# Run all tests
uv run pytest -v

# Run with coverage
uv run pytest -v --cov=app --cov-report=html

# Run specific test file
uv run pytest tests/test_portfolio.py -v

# Run tests matching a pattern
uv run pytest -k "test_alert" -v
```

**Test structure**:
```
backend/tests/
+-- conftest.py              # Shared fixtures (test database, test client, test user)
+-- test_portfolio.py        # Portfolio CRUD tests
+-- test_holdings.py         # Holdings and transactions tests
+-- test_market_data.py      # Market data service tests
+-- test_alerts.py           # Alert engine tests
+-- test_tax.py              # Tax calculation tests
+-- test_brokers/            # Broker integration tests (mocked)
```

**Test conventions**:
- Test files: `test_*.py`
- Test functions: `test_*`
- Use `pytest.mark.asyncio` for async tests
- Use `httpx.AsyncClient` for API endpoint tests
- Mock external services (yfinance, broker APIs)
- Minimum coverage target: 80%

```python
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_create_holding(client: AsyncClient, auth_headers: dict):
    response = await client.post(
        "/api/v1/holdings",
        json={
            "portfolio_id": "test-portfolio-id",
            "stock_symbol": "TCS.NS",
            "stock_name": "Tata Consultancy Services",
            "exchange": "NSE",
            "base_level": 3400.00,
            "top_level": 4600.00,
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["stock_symbol"] == "TCS.NS"
    assert data["cumulative_quantity"] == 0
```

### Frontend Tests (vitest)

```bash
# Run all frontend tests
pnpm --filter web test

# Run in watch mode
pnpm --filter web test:watch

# Run with coverage
pnpm --filter web test:coverage
```

**Test conventions**:
- Test files: `*.test.ts` or `*.test.tsx` (colocated with source files)
- Use `@testing-library/react` for component tests
- Mock API calls with `msw` (Mock Service Worker)

### End-to-End Tests (Playwright)

```bash
# Install Playwright browsers (first time)
pnpm --filter web exec playwright install

# Run E2E tests
pnpm --filter web test:e2e

# Run with UI mode
pnpm --filter web exec playwright test --ui
```

**Critical E2E flows**:
1. Register -> Login -> See empty dashboard
2. Import Excel -> Verify holdings appear with correct quantities
3. View dashboard -> Click Action cell -> See price chart
4. Click RSI cell -> See RSI chart
5. Create alert -> Verify notification appears
6. Connect broker (mocked) -> See synced holdings
7. AI chat -> Get a meaningful response

### Running All Tests

```bash
# From project root
pnpm test           # Runs all tests via Turborepo
```

---

## Git Workflow

### Branch Naming

```
feature/add-mutual-fund-import
fix/alert-engine-boundary-check
refactor/reorganize-services
docs/update-api-reference
test/add-tax-calculation-tests
chore/update-dependencies
```

### Commit Message Format

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short description>

<optional body>

<optional footer>
```

**Types**: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `perf`, `ci`

**Examples**:
```
feat(alerts): add RSI-based alert triggers
fix(tax): correct LTCG exemption calculation for FY 2025-26
docs(api): add WebSocket channel documentation
test(broker): add mock tests for Zerodha adapter
refactor(services): extract forex conversion to dedicated service
chore(deps): update SQLAlchemy to 2.0.35
```

### Branching Strategy

```
main (production-ready)
  |
  +-- develop (integration branch)
       |
       +-- feature/xyz (your work)
```

1. Create a feature branch from `develop`
2. Make your changes with descriptive commits
3. Push and open a Pull Request to `develop`
4. After review and CI passes, merge
5. `develop` is periodically merged to `main` for releases

---

## Pull Request Process

### Before Opening a PR

1. **Run all tests locally** and make sure they pass
2. **Run linters** (`ruff check`, `pnpm lint`) and fix any issues
3. **Run formatters** (`ruff format`, `pnpm format`)
4. **Update documentation** if your change affects API, schema, or user-facing features
5. **Add/update tests** for new or modified functionality

### PR Template

When you open a PR, fill in:

```markdown
## Summary
Brief description of what this PR does and why.

## Changes
- List of specific changes made

## Testing
- How was this tested?
- What tests were added?

## Screenshots
(If applicable -- especially for UI changes)

## Checklist
- [ ] Tests pass locally
- [ ] Linting passes
- [ ] Documentation updated (if applicable)
- [ ] No breaking changes (or clearly documented)
```

### Review Process

1. At least one review is required before merging
2. CI must pass (tests, lint, type check)
3. PR description must explain the "why" not just the "what"
4. Large PRs should be broken into smaller, reviewable chunks

---

## Database Migrations

When you change a SQLAlchemy model:

```bash
cd backend

# 1. Generate migration
uv run alembic revision --autogenerate -m "describe your change"

# 2. Review the generated file in alembic/versions/
# 3. Test the migration
uv run alembic upgrade head

# 4. Test rollback
uv run alembic downgrade -1
uv run alembic upgrade head

# 5. Commit the migration file with your PR
```

**Rules**:
- Always review auto-generated migrations -- they are not always correct
- One migration per logical change
- Include both `upgrade()` and `downgrade()` functions
- Test both upgrade and downgrade paths

---

## Adding a New Feature

Typical steps for a new feature:

1. **Model**: Add/modify SQLAlchemy model in `backend/app/models/`
2. **Migration**: Generate Alembic migration
3. **Schema**: Add Pydantic schemas in `backend/app/schemas/`
4. **Service**: Add business logic in `backend/app/services/`
5. **API Route**: Add endpoint in `backend/app/api/v1/`
6. **Tests**: Write backend tests
7. **Frontend**: Add UI components and pages
8. **Frontend Tests**: Write component tests
9. **Documentation**: Update relevant docs

---

## Getting Help

- Open an issue for bugs or feature requests
- Start a discussion for questions or ideas
- Tag `@maintainers` in your PR for review

---

## Code of Conduct

Be respectful, constructive, and inclusive. We are building something useful together.

---

## Windows Development

All scripts have Windows PowerShell equivalents:

| Unix | Windows |
|---|---|
| `./scripts/setup.sh` | `.\scripts\setup.ps1` |
| `./scripts/start.sh` | `.\scripts\start.ps1` |
| `./scripts/stop.sh` | `.\scripts\stop.ps1` |
| `./scripts/health-check.sh` | `.\scripts\health-check.ps1` |
| `./run.sh` | `.\run.ps1` |
| `./build-installer.sh` | `build-installer.bat` |
| `backend/build_sidecar.sh` | `backend\build_sidecar.bat` |

The PowerShell scripts use `Get-NetTCPConnection` for port detection (instead of `lsof`), `Stop-Process` (instead of `kill`), and `Invoke-WebRequest` (instead of `curl`).

---

## Related Documentation

- [Architecture](architecture.md) -- System design for understanding the codebase
- [API Reference](api-reference.md) -- Endpoint details for backend work
- [Database Schema](database-schema.md) -- Table structure for model changes
- [Desktop App](desktop-app.md) -- Desktop build guide and architecture
