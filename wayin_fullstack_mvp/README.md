# WayIn Full-Stack MVP

**Travel that fits everyone.**

This is a working full-stack MVP with:

- Guest search without sign-in
- Traveler modes:
  - Individual
  - Couple
  - Single parent + kids
  - Family
  - Friends / group
- Destination, category, and needs-based search
- Server-side fit scoring
- Account registration and login
- Saved searches for signed-in users
- SQLite persistence
- Party-member backend endpoints
- Responsive frontend
- Security-focused defaults

## Security included

- Passwords hashed with Werkzeug `scrypt`
- Session-based authentication; auth tokens are not stored in browser localStorage
- `HttpOnly` and `SameSite=Lax` session cookies
- Optional `Secure` cookie mode for HTTPS production deployments
- CSRF token required for authenticated state-changing requests
- Rate limiting on login, register, search, and writes
- Parameterized SQL queries
- Generic login failure messages
- Request size limits
- Security headers including CSP, frame blocking, referrer policy, and MIME sniffing protection
- Input validation and allowlists for search filters

## Important production upgrades

This is a strong portfolio/MVP baseline, not a complete enterprise security program. Before handling real customers, add:

- TLS/HTTPS at the hosting layer and set `WAYIN_SECURE_COOKIES=1`
- Managed database (Postgres) with encrypted backups
- Email verification and secure password-reset flow
- MFA / passkeys
- Redis-backed rate limiting instead of in-memory limits
- Centralized logging, alerting, and audit events
- Secrets manager rather than plain environment files
- Dependency scanning and automated tests
- WAF/CDN protections
- Privacy policy, consent, retention controls, and data deletion
- A third-party identity provider if scaling authentication

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate       # macOS/Linux
# .venv\Scripts\activate        # Windows

pip install -r requirements.txt
export WAYIN_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
python app.py
```

Open:

```text
http://127.0.0.1:8000
```

### Local development note

`Secure` cookies are off by default so login works over local HTTP.

For HTTPS production:

```bash
export WAYIN_SECURE_COOKIES=1
```

## Example API

Guest search:

```http
POST /api/search
Content-Type: application/json

{
  "destination": "Chicago",
  "traveler_type": "single_parent",
  "category": "Everything",
  "needs": ["Stroller", "Nap schedule", "Family restroom"]
}
```

## Next product integrations

Replace the demo inventory with live providers for:

- Hotels
- Events and attractions
- Maps/transit
- Flights/rail
- Accessibility verification
- AI itinerary generation

Keep the WayIn fit-ranking layer above those providers so the differentiator remains the group's actual needs rather than generic travel ranking.
