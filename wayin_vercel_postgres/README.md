# WayIn — Vercel + Persistent Postgres

This version is configured for **Vercel + Neon Postgres**.

## What changed

The app no longer writes SQLite files into the deployment filesystem.

Persistent data now goes to Postgres through `DATABASE_URL`:

- user accounts
- password hashes
- saved searches
- party / traveler profiles

The public homepage and guest search do not require the database, so WayIn can still render even if the account database has a temporary outage.

## Vercel setup

### 1. Use this folder as the project Root Directory

`wayin_vercel_postgres` if uploaded as that folder, or the folder containing `app.py` if you rename it.

### 2. Add Neon

In the Vercel project:

**Storage / Marketplace → Neon → Create database → Connect to this project**

The Vercel Neon integration should add a `DATABASE_URL` environment variable to the project automatically.

### 3. Add these environment variables

`WAYIN_SECRET_KEY`

Use a long random value. Do not commit the real secret to GitHub.

`WAYIN_SECURE_COOKIES=1`

For the Vercel HTTPS deployment.

`DATABASE_URL`

This should normally be populated by the Neon integration.

### 4. Redeploy

After adding the database and environment variables, redeploy the latest commit.

## Database schema

The app safely creates the three required tables on the first database-backed request:

- `users`
- `saved_searches`
- `party_members`

## Health check

After deployment, visit:

`/api/health`

You should see:

```json
{"database_configured":true,"ok":true}
```

If `database_configured` is `false`, Vercel has not provided the `DATABASE_URL` to the deployment.

## Security baseline

- scrypt password hashing
- HttpOnly session cookies
- Secure cookies in production
- SameSite=Lax
- CSRF tokens
- rate limiting
- parameterized Postgres queries
- CSP and clickjacking protection
- request-size limits
- validated / allowlisted search inputs

For a larger production rollout, move rate limiting to Redis/Upstash, add email verification, password reset, MFA/passkeys, audit logging, and automated dependency/security scanning.
