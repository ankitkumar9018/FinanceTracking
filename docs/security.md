# Security Architecture

> FinanceTracker -- Security, Privacy & Compliance Documentation

## Overview

FinanceTracker handles sensitive financial data and broker credentials. This document describes the security measures implemented across the application.

---

## Authentication

### JWT Token System

FinanceTracker uses JSON Web Tokens (JWT) for stateless authentication.

| Token | Lifetime | Purpose |
|---|---|---|
| Access Token | 15 minutes | API request authentication |
| Refresh Token | 7 days | Renewing access tokens without re-login |

**Implementation:**

```python
from jose import jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Token creation
def create_access_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.utcnow() + timedelta(minutes=15),
        "type": "access"
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

def create_refresh_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.utcnow() + timedelta(days=7),
        "type": "refresh"
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")
```

**Token flow:**

```
1. User logs in with email + password (+ optional 2FA code)
2. Server validates credentials and returns access_token + refresh_token
3. Client stores tokens in httpOnly secure cookies (web) or secure storage (desktop)
4. Client includes access_token in Authorization header for each request
5. When access_token expires, client uses refresh_token to get a new one
6. When refresh_token expires, user must log in again
```

### Two-Factor Authentication (2FA)

Optional TOTP-based 2FA using RFC 6238.

**Setup flow:**
1. User requests 2FA setup from Settings
2. Server generates a TOTP secret and returns it as a QR code (scannable by Google Authenticator, Authy, etc.)
3. User scans the QR code and enters the current 6-digit code to confirm
4. Server stores the TOTP secret (encrypted) and enables 2FA
5. On subsequent logins, user must enter their password AND the current TOTP code

**Backup codes:** When 2FA is enabled, the server generates 5 backup codes. Each can be used once to bypass TOTP if the user loses access to their authenticator app.

---

## Encryption

### Encryption at Rest

All sensitive data is encrypted before storage using Fernet symmetric encryption (AES-128-CBC with HMAC-SHA256).

**What is encrypted:**

| Data | Where Stored | Encryption |
|---|---|---|
| Broker API keys | `broker_connections.encrypted_api_key` | Fernet |
| Broker API secrets | `broker_connections.encrypted_api_secret` | Fernet |
| Broker access tokens | `broker_connections.access_token_encrypted` | Fernet |
| TOTP secrets | `users.totp_secret` | Fernet |
| Sensitive app settings | `app_settings.value` (where `is_encrypted=true`) | Fernet |

**Key derivation:**

The Fernet encryption key is derived from the `SECRET_KEY` environment variable. This key must be:
- At least 32 characters long
- Randomly generated (not human-memorable)
- Never committed to version control
- Rotated if there is any suspicion of compromise

```python
from cryptography.fernet import Fernet
import base64
import hashlib

def get_fernet_key(secret_key: str) -> Fernet:
    # Derive a 32-byte key from SECRET_KEY using SHA-256
    key = hashlib.sha256(secret_key.encode()).digest()
    fernet_key = base64.urlsafe_b64encode(key)
    return Fernet(fernet_key)
```

### Encryption in Transit

- **HTTPS only** in production -- all HTTP traffic redirected to HTTPS
- **HSTS headers** (`Strict-Transport-Security: max-age=31536000; includeSubDomains`)
- **WebSocket over WSS** (encrypted WebSocket)
- Development uses HTTP on localhost (acceptable for local-only access)

### Password Storage

User passwords are hashed with **bcrypt** (cost factor 12). The original password is never stored or logged.

```python
# Hashing
hashed = pwd_context.hash("user_password")
# Result: $2b$12$LJ3m4y... (60 characters, irreversible)

# Verification
is_valid = pwd_context.verify("user_password", hashed)
```

---

## API Security

### CORS (Cross-Origin Resource Sharing)

Strict origin allowlist prevents unauthorized domains from accessing the API:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",       # Web dev
        "https://app.financetracker.com",  # Production web
        "tauri://localhost",           # Tauri desktop app
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
```

### Rate Limiting

Rate limiting prevents brute-force attacks and API abuse:

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

# Endpoint-specific limits
@app.post("/api/v1/auth/register")
@limiter.limit("5/minute")   # Strict limit on registration
async def register(request: Request): ...

@app.post("/api/v1/auth/login")
@limiter.limit("10/minute")  # Strict limit on login attempts
async def login(request: Request): ...

@app.post("/api/v1/auth/refresh")
@limiter.limit("20/minute")  # Token refresh
async def refresh(request: Request): ...

@app.get("/api/v1/portfolios")
@limiter.limit("100/minute")  # General API limit
async def list_portfolios(request: Request): ...

@app.post("/api/v1/import/excel")
@limiter.limit("5/minute")  # File upload limit
async def import_excel(request: Request): ...
```

| Endpoint Group | Rate Limit |
|---|---|
| Register | 5 requests/minute |
| Login | 10 requests/minute |
| Token Refresh | 20 requests/minute |
| General API | 100 requests/minute |
| Import/Export | 5 requests/minute |
| AI/Chat | 30 requests/minute |
| WebSocket connections | 5 per user |

### Input Validation

All request data is validated through Pydantic schemas:

```python
from pydantic import BaseModel, EmailStr, Field

class RegisterRequest(BaseModel):
    email: EmailStr                    # Validates email format
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=100)
    preferred_currency: str = Field(pattern="^(INR|EUR|USD)$")
```

- All string inputs are length-bounded
- Numeric inputs have range constraints
- Enum values are validated against allowed values
- File uploads are type-checked and size-limited

### SQL Injection Prevention

SQLAlchemy ORM is used exclusively. No raw SQL queries exist in the codebase.

```python
# SAFE: SQLAlchemy ORM (parameterized)
result = await db.execute(
    select(Holding).where(Holding.stock_symbol == user_input)
)

# NEVER USED: Raw SQL with string interpolation
# cursor.execute(f"SELECT * FROM holdings WHERE symbol = '{user_input}'")
```

### XSS Prevention

- React automatically escapes all rendered content
- Content Security Policy (CSP) headers restrict script sources
- No use of `dangerouslySetInnerHTML` except for sanitized MDX help content
- All user-generated content (notes, custom field values) is escaped on display
- Server-side HTML export uses `html.escape()` on all user-generated content (`export_service.py`) to prevent stored XSS in generated reports

### CSRF Protection

- JWT tokens are sent via `Authorization` header (not cookies for API)
- The web app uses `SameSite=Strict` cookie attributes
- Tauri desktop app uses a custom protocol that is not susceptible to CSRF

---

## Data Privacy

### What Data Is Stored

| Data Category | Where | Encrypted? |
|---|---|---|
| Email, password hash | `users` table | Password is hashed (bcrypt) |
| Portfolio holdings | `holdings` table | No (needed for queries) |
| Transaction history | `transactions` table | No (needed for calculations) |
| Broker API credentials | `broker_connections` table | Yes (Fernet) |
| Notification config | `app_settings` table | API keys are encrypted |
| Chat history | `chat_sessions` table | No |
| Price data | `price_history` table | No (public market data) |

### What Is NOT Stored

- Plain-text passwords (only bcrypt hashes)
- Full credit card or bank account numbers
- Aadhaar, PAN, or tax ID numbers (these are never collected)
- Browser history or tracking data

### Data Retention

- **Chat sessions**: Kept for 90 days, then auto-deleted
- **Notification logs**: Kept for 30 days
- **Price history**: Kept indefinitely (public market data)
- **User data**: Kept until account deletion

### Account Deletion

Users can request full account deletion from Settings -> Advanced. This:
1. Deletes all portfolios, holdings, transactions
2. Deletes all alerts and notification history
3. Deletes all broker connections (credentials are destroyed)
4. Deletes all chat sessions
5. Deletes all settings and preferences
6. Removes the user record

This is a hard delete with no recovery possible.

---

## Secrets Management

### Environment Variables

All secrets are stored in environment variables, never in code:

```bash
# backend/.env (NEVER committed to git)
SECRET_KEY=a-random-32-plus-character-string
DATABASE_URL=postgresql+asyncpg://user:pass@host/db
SENDGRID_API_KEY=SG.xxx
TWILIO_ACCOUNT_SID=ACxxx
TWILIO_AUTH_TOKEN=xxx
TELEGRAM_BOT_TOKEN=123:xxx
OPENAI_API_KEY=sk-xxx
ANTHROPIC_API_KEY=sk-ant-xxx
```

### .gitignore Rules

The following patterns are in `.gitignore`:

```
.env
.env.*
!.env.example
*.key
*.pem
*.p12
finance.db
*.sqlite3
```

### Secret Rotation

If `SECRET_KEY` needs to be rotated:
1. All existing JWT tokens will be invalidated (users must re-login)
2. All Fernet-encrypted data must be re-encrypted with the new key
3. A migration script handles the re-encryption process

---

## Compliance Readiness

### SEBI/RBI Compliance (India)

FinanceTracker is a personal portfolio tracking tool and does **not**:
- Execute trades on behalf of users (read-only broker access)
- Provide investment advice (AI responses include disclaimer)
- Store PAN or Aadhaar numbers
- Handle payment processing

If the app evolves to include advisory features, the following would be needed:
- SEBI RIA (Registered Investment Advisor) registration
- RBI compliance for handling financial data
- Data localization requirements (Indian user data stored in India)

### GDPR Compliance (Germany)

For German users, the app follows GDPR principles:

| GDPR Principle | Implementation |
|---|---|
| **Lawful basis** | Consent-based (user explicitly creates account) |
| **Data minimization** | Only essential data collected (email, portfolio data) |
| **Purpose limitation** | Data used only for portfolio tracking |
| **Storage limitation** | Auto-deletion of old notification logs and chat sessions |
| **Right to access** | Users can export all their data (Settings -> Export) |
| **Right to erasure** | Full account deletion available (Settings -> Delete Account) |
| **Right to portability** | Data export in standard formats (Excel, JSON) |
| **Data protection** | Encryption at rest and in transit |
| **Breach notification** | Logging infrastructure to detect and report breaches |

### Data Residency

- By default, all data is stored locally (SQLite on user's machine)
- In production (PostgreSQL), the database should be hosted in a jurisdiction appropriate for the user base
- For German users: host in EU (AWS Frankfurt, Hetzner, etc.)
- For Indian users: host in India (AWS Mumbai, etc.)

---

## Audit Logging

All sensitive actions are logged with timestamp, user ID, and details:

| Action | Logged Data |
|---|---|
| Login success/failure | User email, IP, timestamp, failure reason |
| 2FA enable/disable | User ID, timestamp |
| Broker connect/disconnect | User ID, broker name, timestamp |
| Settings change | User ID, setting key, timestamp (not the value for sensitive keys) |
| Data export | User ID, export type, timestamp |
| Account deletion | User ID, timestamp |
| Import execution | User ID, file size, row count, timestamp |

Audit logs are written to Python's structured logging system (`app/utils/audit.py`) with `[AUDIT]` prefix, including user ID, action, resource type/ID, IP address, and timestamp. These can be shipped to any log aggregation system (ELK, CloudWatch, etc.).

---

## Security Headers

The following HTTP headers are set on all responses:

```
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 0
Referrer-Policy: strict-origin-when-cross-origin
Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'
Permissions-Policy: camera=(), microphone=(self), geolocation=()
```

---

## Dependency Security

### Python (Backend)

- Dependencies specified in `pyproject.toml` with version constraints
- `uv.lock` ensures deterministic, reproducible installs
- Vulnerability scanning via `pip-audit` or `safety` in CI

### JavaScript (Frontend)

- Dependencies locked via `pnpm-lock.yaml`
- `pnpm audit` runs in CI to detect known vulnerabilities
- Dependabot or Renovate bot for automated dependency updates

### Security Review Checklist

Before each release:

- [ ] No secrets in committed code (scanned with `gitleaks` or `trufflehog`)
- [ ] All dependencies audited for known vulnerabilities
- [ ] Fernet encryption verified for all sensitive fields
- [ ] Rate limiting tested on auth endpoints
- [ ] CORS configuration verified (no wildcard origins)
- [ ] SQL injection tests passed (no raw SQL)
- [ ] XSS tests passed (all user input escaped)
- [ ] JWT token expiry verified
- [ ] File upload size limits enforced
- [ ] Error messages do not leak internal details

---

## Incident Response

If a security incident is suspected:

1. **Rotate** `SECRET_KEY` immediately (invalidates all sessions)
2. **Rotate** all broker API credentials for affected users
3. **Review** audit logs for unauthorized access
4. **Notify** affected users
5. **Patch** the vulnerability
6. **Document** the incident and response

---

## Related Documentation

- [Architecture](architecture.md) -- System design overview
- [Deployment](deployment.md) -- Production security configuration
- [Broker Integration](broker-integration.md) -- Credential management details
