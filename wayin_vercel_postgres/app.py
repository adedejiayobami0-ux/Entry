import os
import re
import secrets
from datetime import timedelta
from functools import wraps

import psycopg
from psycopg.rows import dict_row
from flask import Flask, jsonify, render_template, request, session, g
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("WAYIN_SECRET_KEY", secrets.token_hex(32)),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("WAYIN_SECURE_COOKIES", "1") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    MAX_CONTENT_LENGTH=32 * 1024,
)

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["240 per minute"],
    storage_uri="memory://",
)

INVENTORY = [
    {
        "id": "hotel-sea-1", "type": "Hotels", "name": "Harbor View Hotel",
        "location": "Seattle, WA", "base_score": 92, "price": "$$",
        "features": ["Step-free access","Accessible restroom","Limited walking","Service animal","Elevator","Family restroom"],
        "summary": "Downtown hotel close to light rail with step-free entry and elevator access."
    },
    {
        "id": "hotel-chi-1", "type": "Hotels", "name": "Cityline Family Suites",
        "location": "Chicago, IL", "base_score": 91, "price": "$$",
        "features": ["Stroller","Family restroom","Nap schedule","Limited walking","Elevator","High chairs"],
        "summary": "Family-oriented suites near transit with elevator access and room for strollers."
    },
    {
        "id": "event-sea-1", "type": "Events", "name": "Sounders Night Match",
        "location": "Seattle, WA", "base_score": 88, "price": "$$",
        "features": ["Step-free access","Accessible restroom","Captions / ASL","Service animal","Family restroom"],
        "summary": "Large venue with accessible seating zones, step-free entry, and family facilities."
    },
    {
        "id": "event-chi-1", "type": "Events", "name": "Museum Family Afternoon",
        "location": "Chicago, IL", "base_score": 95, "price": "$",
        "features": ["Stroller","Family restroom","Low sensory","Limited walking","Elevator","Nap schedule"],
        "summary": "Indoor family activity with elevators, rest areas, and flexible timing."
    },
    {
        "id": "trip-sea-1", "type": "Trips", "name": "Seattle Easy-Pace Weekend",
        "location": "Seattle, WA", "base_score": 93, "price": "$$",
        "features": ["Step-free access","Limited walking","Low sensory","Family restroom","Stroller","Elevator"],
        "summary": "A relaxed two-day itinerary designed around short transfers and accessible stops."
    },
    {
        "id": "trip-chi-1", "type": "Trips", "name": "Chicago Family Arts Escape",
        "location": "Chicago, IL", "base_score": 94, "price": "$$",
        "features": ["Stroller","Nap schedule","Family restroom","Limited walking","High chairs","Elevator"],
        "summary": "Family itinerary that protects nap time and keeps walking segments short."
    },
    {
        "id": "event-sd-1", "type": "Events", "name": "Coastal Discovery Center",
        "location": "San Diego, CA", "base_score": 90, "price": "$",
        "features": ["Stroller","Accessible restroom","Low sensory","Step-free access","Family restroom"],
        "summary": "Low-pressure indoor/outdoor attraction with wide routes and family facilities."
    },
    {
        "id": "hotel-sd-1", "type": "Hotels", "name": "Pacific Courtyard",
        "location": "San Diego, CA", "base_score": 90, "price": "$$",
        "features": ["Step-free access","Accessible restroom","Service animal","Low sensory","Elevator"],
        "summary": "Quiet hotel with accessible parking, elevators, and service-animal support."
    },
]

TRAVELER_TYPES = {
    "individual": "Individual",
    "couple": "Couple",
    "single_parent": "Single parent + kids",
    "family": "Family",
    "group": "Friends / group",
}

NEEDS = [
    "Step-free access", "Accessible restroom", "Low sensory", "Captions / ASL",
    "Limited walking", "Service animal", "Stroller", "Nap schedule",
    "Family restroom", "High chairs", "Elevator"
]

_schema_ready = False

def get_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured.")
    if "db" not in g:
        g.db = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    ensure_schema(g.db)
    return g.db

def ensure_schema(conn):
    global _schema_ready
    if _schema_ready:
        return
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id BIGSERIAL PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS saved_searches (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                destination TEXT NOT NULL,
                traveler_type TEXT NOT NULL,
                category TEXT NOT NULL,
                needs_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS party_members (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                needs_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
    conn.commit()
    _schema_ready = True

@app.teardown_appcontext
def close_db(_err):
    conn = g.pop("db", None)
    if conn:
        conn.close()

def user_id():
    return session.get("user_id")

def csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token

def require_csrf(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        supplied = request.headers.get("X-CSRF-Token", "")
        if not supplied or not secrets.compare_digest(supplied, csrf_token()):
            return jsonify({"error": "Invalid request token."}), 403
        return fn(*args, **kwargs)
    return wrapper

def require_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not user_id():
            return jsonify({"error": "Sign in required."}), 401
        return fn(*args, **kwargs)
    return wrapper

def clean_email(value):
    value = (value or "").strip().lower()
    if len(value) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
        return None
    return value

def validate_password(value):
    if not isinstance(value, str) or len(value) < 10 or len(value) > 128:
        return False
    return any(c.isalpha() for c in value) and any(c.isdigit() for c in value)

def normalize_search(payload):
    destination = str(payload.get("destination", "")).strip()[:80]
    traveler_type = str(payload.get("traveler_type", "individual"))
    category = str(payload.get("category", "Everything"))
    raw_needs = payload.get("needs", [])
    if traveler_type not in TRAVELER_TYPES:
        traveler_type = "individual"
    if category not in ("Everything", "Hotels", "Trips", "Events"):
        category = "Everything"
    needs = []
    if isinstance(raw_needs, list):
        for item in raw_needs:
            if item in NEEDS and item not in needs:
                needs.append(item)
    return destination, traveler_type, category, needs

def score_item(item, needs, traveler_type):
    if not needs:
        fit = item["base_score"]
        matched, missing = [], []
    else:
        matched = [n for n in needs if n in item["features"]]
        missing = [n for n in needs if n not in item["features"]]
        fit = round(item["base_score"] * 0.50 + (len(matched) / len(needs)) * 50)
    if traveler_type in ("single_parent", "family") and any(
        f in item["features"] for f in ("Stroller","Family restroom","High chairs","Nap schedule")
    ):
        fit = min(100, fit + 3)
    return fit, matched, missing

def db_unavailable_response(exc):
    app.logger.exception("Database operation failed")
    return jsonify({"error":"WayIn could not reach the account database. Please try again."}), 503

@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
        "base-uri 'self'; form-action 'self'"
    )
    return response

@app.get("/")
def home():
    # Intentionally no database access: public search page should load even if
    # the account database is temporarily unavailable.
    return render_template(
        "index.html",
        csrf_token=csrf_token(),
        traveler_types=TRAVELER_TYPES,
        needs=NEEDS,
    )

@app.get("/api/health")
def health():
    return jsonify({
        "ok": True,
        "database_configured": bool(DATABASE_URL),
    })

@app.get("/api/session")
def api_session():
    uid = user_id()
    email = None
    if uid:
        try:
            conn = get_db()
            with conn.cursor() as cur:
                cur.execute("SELECT email FROM users WHERE id=%s", (uid,))
                row = cur.fetchone()
            email = row["email"] if row else None
        except Exception:
            # Keep public UI functional if account DB is unavailable.
            session.pop("user_id", None)
    return jsonify({"authenticated": bool(email), "email": email, "csrf_token": csrf_token()})

@app.post("/api/search")
@limiter.limit("60 per minute")
def search():
    payload = request.get_json(silent=True) or {}
    destination, traveler_type, category, needs = normalize_search(payload)
    candidates = INVENTORY

    if destination:
        words = [w.lower() for w in re.findall(r"[A-Za-z]+", destination) if len(w) > 1]
        location_matches = [i for i in candidates if any(w in i["location"].lower() for w in words)]
        if location_matches:
            candidates = location_matches

    if category != "Everything":
        candidates = [i for i in candidates if i["type"] == category]

    results = []
    for item in candidates:
        fit, matched, missing = score_item(item, needs, traveler_type)
        results.append({
            **item,
            "fit_score": fit,
            "matched_needs": matched,
            "unconfirmed_needs": missing,
            "traveler_label": TRAVELER_TYPES[traveler_type],
        })
    results.sort(key=lambda x: (-x["fit_score"], x["name"]))
    return jsonify({
        "results": results,
        "query": {
            "destination": destination,
            "traveler_type": traveler_type,
            "traveler_label": TRAVELER_TYPES[traveler_type],
            "category": category,
            "needs": needs,
        }
    })

@app.post("/api/register")
@limiter.limit("5 per minute")
@require_csrf
def register():
    payload = request.get_json(silent=True) or {}
    email = clean_email(payload.get("email"))
    password = payload.get("password", "")
    if not email or not validate_password(password):
        return jsonify({"error":"Use a valid email and a password of at least 10 characters with letters and numbers."}), 400
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users(email,password_hash) VALUES(%s,%s) RETURNING id",
                (email, generate_password_hash(password, method="scrypt"))
            )
            new_id = cur.fetchone()["id"]
        conn.commit()
    except psycopg.errors.UniqueViolation:
        try: g.db.rollback()
        except Exception: pass
        return jsonify({"error":"Unable to create account with those details."}), 409
    except Exception as exc:
        return db_unavailable_response(exc)

    session.clear()
    session["user_id"] = new_id
    session["csrf_token"] = secrets.token_urlsafe(32)
    session.permanent = True
    return jsonify({"ok":True,"email":email,"csrf_token":session["csrf_token"]})

@app.post("/api/login")
@limiter.limit("8 per minute")
@require_csrf
def login():
    payload = request.get_json(silent=True) or {}
    email = clean_email(payload.get("email"))
    password = payload.get("password", "")
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("SELECT id,email,password_hash FROM users WHERE email=%s", (email or "",))
            row = cur.fetchone()
    except Exception as exc:
        return db_unavailable_response(exc)

    if not row or not check_password_hash(row["password_hash"], password):
        return jsonify({"error":"Email or password is incorrect."}), 401

    session.clear()
    session["user_id"] = row["id"]
    session["csrf_token"] = secrets.token_urlsafe(32)
    session.permanent = True
    return jsonify({"ok":True,"email":row["email"],"csrf_token":session["csrf_token"]})

@app.post("/api/logout")
@require_csrf
def logout():
    session.clear()
    return jsonify({"ok":True})

@app.post("/api/save-search")
@require_auth
@require_csrf
@limiter.limit("30 per minute")
def save_search():
    payload = request.get_json(silent=True) or {}
    destination, traveler_type, category, needs = normalize_search(payload)
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO saved_searches
                   (user_id,destination,traveler_type,category,needs_json)
                   VALUES(%s,%s,%s,%s,%s::jsonb)""",
                (user_id(), destination, traveler_type, category, json_dumps(needs))
            )
        conn.commit()
        return jsonify({"ok":True})
    except Exception as exc:
        return db_unavailable_response(exc)

@app.get("/api/saved-searches")
@require_auth
def saved_searches():
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id,destination,traveler_type,category,needs_json,created_at
                   FROM saved_searches WHERE user_id=%s ORDER BY id DESC LIMIT 20""",
                (user_id(),)
            )
            rows = cur.fetchall()
        return jsonify({"items":[
            {
                "id":r["id"],
                "destination":r["destination"],
                "traveler_type":r["traveler_type"],
                "category":r["category"],
                "needs":r["needs_json"],
                "created_at":r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]})
    except Exception as exc:
        return db_unavailable_response(exc)

@app.post("/api/party-members")
@require_auth
@require_csrf
@limiter.limit("30 per minute")
def add_party_member():
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name","")).strip()[:50]
    role = str(payload.get("role","Adult")).strip()[:30]
    needs = payload.get("needs", [])
    if not name:
        return jsonify({"error":"Name is required."}), 400
    needs = [n for n in needs if n in NEEDS][:20] if isinstance(needs, list) else []
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO party_members(user_id,name,role,needs_json)
                   VALUES(%s,%s,%s,%s::jsonb)""",
                (user_id(), name, role, json_dumps(needs))
            )
        conn.commit()
        return jsonify({"ok":True})
    except Exception as exc:
        return db_unavailable_response(exc)

@app.get("/api/party-members")
@require_auth
def list_party_members():
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id,name,role,needs_json FROM party_members WHERE user_id=%s ORDER BY id ASC",
                (user_id(),)
            )
            rows = cur.fetchall()
        return jsonify({"items":[
            {"id":r["id"],"name":r["name"],"role":r["role"],"needs":r["needs_json"]}
            for r in rows
        ]})
    except Exception as exc:
        return db_unavailable_response(exc)

def json_dumps(value):
    import json
    return json.dumps(value, separators=(",", ":"))

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "8000")), debug=False)
