import os
import re
import secrets
import html
import json
from datetime import timedelta
from functools import wraps

import psycopg
import requests
from psycopg.rows import dict_row
from openai import OpenAI
import resend
from twilio.rest import Client as TwilioClient
from flask import Flask, jsonify, render_template, request, session, g
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
AMADEUS_CLIENT_ID = os.environ.get("AMADEUS_CLIENT_ID", "").strip()
AMADEUS_CLIENT_SECRET = os.environ.get("AMADEUS_CLIENT_SECRET", "").strip()
TICKETMASTER_API_KEY = os.environ.get("TICKETMASTER_API_KEY", "").strip()
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "").strip()
WAYIN_FROM_EMAIL = os.environ.get("WAYIN_FROM_EMAIL", "onboarding@resend.dev").strip()
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER", "").strip()
AMADEUS_BASE_URL = os.environ.get("AMADEUS_BASE_URL", "https://test.api.amadeus.com").rstrip("/")

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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS trips (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title TEXT NOT NULL DEFAULT 'My trip',
                destination TEXT NOT NULL DEFAULT '',
                items_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
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


def amadeus_token():
    if not AMADEUS_CLIENT_ID or not AMADEUS_CLIENT_SECRET:
        return None
    r = requests.post(
        f"{AMADEUS_BASE_URL}/v1/security/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "client_id": AMADEUS_CLIENT_ID,
            "client_secret": AMADEUS_CLIENT_SECRET,
        },
        timeout=12,
    )
    r.raise_for_status()
    return r.json().get("access_token")

def live_flights(origin, destination, departure_date, adults=1):
    token = amadeus_token()
    if not token or not origin or not destination or not departure_date:
        return []
    r = requests.get(
        f"{AMADEUS_BASE_URL}/v2/shopping/flight-offers",
        headers={"Authorization": f"Bearer {token}"},
        params={
            "originLocationCode": origin.upper()[:3],
            "destinationLocationCode": destination.upper()[:3],
            "departureDate": departure_date,
            "adults": max(1, min(int(adults or 1), 9)),
            "max": 8,
            "currencyCode": "USD",
        },
        timeout=15,
    )
    r.raise_for_status()
    payload = r.json()
    carriers = payload.get("dictionaries", {}).get("carriers", {})
    output = []
    for offer in payload.get("data", [])[:8]:
        itin = (offer.get("itineraries") or [{}])[0]
        segs = itin.get("segments") or []
        if not segs:
            continue
        first, last = segs[0], segs[-1]
        code = first.get("carrierCode", "")
        output.append({
            "id": f"flight-{offer.get('id')}",
            "type": "Flight",
            "name": f"{carriers.get(code, code)} {first.get('number','')}".strip(),
            "location": f"{first.get('departure',{}).get('iataCode','')} → {last.get('arrival',{}).get('iataCode','')}",
            "price": f"${offer.get('price',{}).get('grandTotal','—')}",
            "summary": f"{len(segs)-1} stop(s) · depart {first.get('departure',{}).get('at','')}",
            "source": "Amadeus",
            "booking_url": None,
            "features": [],
            "fit_score": 90,
            "matched_needs": [],
            "unconfirmed_needs": [],
        })
    return output

def live_hotels(city_code, check_in, check_out, adults=1):
    token = amadeus_token()
    if not token or not city_code:
        return []
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(
        f"{AMADEUS_BASE_URL}/v1/reference-data/locations/hotels/by-city",
        headers=headers,
        params={"cityCode": city_code.upper()[:3], "radius": 20, "radiusUnit": "KM", "hotelSource": "ALL"},
        timeout=15,
    )
    r.raise_for_status()
    hotels = r.json().get("data", [])[:10]
    ids = [h.get("hotelId") for h in hotels if h.get("hotelId")]
    offers_by_id = {}
    if ids and check_in and check_out:
        try:
            p = requests.get(
                f"{AMADEUS_BASE_URL}/v3/shopping/hotel-offers",
                headers=headers,
                params={
                    "hotelIds": ",".join(ids[:10]),
                    "adults": max(1, min(int(adults or 1), 9)),
                    "checkInDate": check_in,
                    "checkOutDate": check_out,
                    "roomQuantity": 1,
                    "currency": "USD",
                    "bestRateOnly": "true",
                },
                timeout=18,
            )
            if p.ok:
                for item in p.json().get("data", []):
                    offers_by_id[item.get("hotel", {}).get("hotelId")] = item
        except Exception:
            pass

    output = []
    for h in hotels:
        hid = h.get("hotelId")
        priced = offers_by_id.get(hid, {})
        offers = priced.get("offers") or []
        total = offers[0].get("price", {}).get("total") if offers else None
        currency = offers[0].get("price", {}).get("currency", "USD") if offers else "USD"
        output.append({
            "id": f"hotel-{hid}",
            "type": "Hotel",
            "name": h.get("name") or priced.get("hotel", {}).get("name") or "Hotel",
            "location": h.get("iataCode") or city_code.upper(),
            "price": f"{currency} {total}" if total else "Check availability",
            "summary": "Live hotel listing" + (" with current offer" if total else ""),
            "source": "Amadeus",
            "booking_url": None,
            "features": [],
            "fit_score": 88,
            "matched_needs": [],
            "unconfirmed_needs": [],
        })
    return output

def live_events(city):
    if not TICKETMASTER_API_KEY or not city:
        return []
    r = requests.get(
        "https://app.ticketmaster.com/discovery/v2/events.json",
        params={"apikey": TICKETMASTER_API_KEY, "city": city, "size": 12, "sort": "date,asc"},
        timeout=12,
    )
    r.raise_for_status()
    events = r.json().get("_embedded", {}).get("events", [])
    output = []
    for e in events:
        venue = ((e.get("_embedded") or {}).get("venues") or [{}])[0]
        date = (e.get("dates") or {}).get("start", {}).get("localDate", "")
        price_ranges = e.get("priceRanges") or []
        price = "See tickets"
        if price_ranges:
            lo, hi = price_ranges[0].get("min"), price_ranges[0].get("max")
            if lo is not None:
                price = f"${lo:g}" + (f"–${hi:g}" if hi is not None else "+")
        output.append({
            "id": f"event-{e.get('id')}",
            "type": "Event",
            "name": e.get("name", "Event"),
            "location": venue.get("name") or city,
            "price": price,
            "summary": f"{date} · {city}",
            "source": "Ticketmaster",
            "booking_url": e.get("url"),
            "features": [],
            "fit_score": 86,
            "matched_needs": [],
            "unconfirmed_needs": [],
        })
    return output

@app.post("/api/live-search")
@limiter.limit("30 per minute")
def live_search():
    payload = request.get_json(silent=True) or {}
    category = str(payload.get("category", "Everything"))
    origin = str(payload.get("origin", "")).strip()
    destination = str(payload.get("destination", "")).strip()
    city_code = str(payload.get("city_code", destination)).strip()
    departure_date = str(payload.get("departure_date", "")).strip()
    return_date = str(payload.get("return_date", "")).strip()
    adults = payload.get("adults", 1)

    results, errors = [], []
    if category in ("Everything", "Flights"):
        try:
            results.extend(live_flights(origin, city_code, departure_date, adults))
        except Exception:
            errors.append("Flight provider unavailable")
    if category in ("Everything", "Hotels"):
        try:
            results.extend(live_hotels(city_code, departure_date, return_date, adults))
        except Exception:
            errors.append("Hotel provider unavailable")
    if category in ("Everything", "Events"):
        try:
            results.extend(live_events(destination))
        except Exception:
            errors.append("Event provider unavailable")

    return jsonify({
        "results": results,
        "live": True,
        "configured": {
            "flights_hotels": bool(AMADEUS_CLIENT_ID and AMADEUS_CLIENT_SECRET),
            "events": bool(TICKETMASTER_API_KEY),
        },
        "errors": errors,
    })

@app.post("/api/ai-chat")
@limiter.limit("30 per minute")
def ai_chat():
    payload = request.get_json(silent=True) or {}
    message = str(payload.get("message", "")).strip()[:3000]
    context = payload.get("trip", [])
    if not message:
        return jsonify({"error": "Message is required."}), 400

    if not OPENAI_API_KEY:
        return jsonify({
            "reply": "AI is ready in the product, but OPENAI_API_KEY is not configured in Vercel yet. I can still help you organize selected flights, hotels, and events once that key is added.",
            "configured": False,
        })

    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        trip_text = json.dumps(context[:20], ensure_ascii=False)[:12000]
        response = client.responses.create(
            model=os.environ.get("OPENAI_MODEL", "gpt-5"),
            input=[
                {
                    "role": "system",
                    "content": (
                        "You are WayIn, an inclusive travel planning assistant. "
                        "Help individuals, couples, single parents, families and groups build realistic itineraries. "
                        "Respect accessibility and safety-critical needs as hard constraints when the user marks them as required. "
                        "Never claim a booking is confirmed unless the supplied context says it is confirmed."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Selected trip items: {trip_text}\n\nUser: {message}",
                },
            ],
        )
        return jsonify({"reply": response.output_text, "configured": True})
    except Exception:
        app.logger.exception("AI request failed")
        return jsonify({"error": "WayIn AI is temporarily unavailable."}), 503

def build_trip_message(title, items):
    safe_title = html.escape(title[:120])
    lines = []
    for item in items[:20]:
        name = html.escape(str(item.get("name","Trip item"))[:180])
        typ = html.escape(str(item.get("type",""))[:40])
        location = html.escape(str(item.get("location",""))[:180])
        price = html.escape(str(item.get("price",""))[:80])
        status = html.escape(str(item.get("status","selected"))[:30])
        lines.append(f"<li><strong>{name}</strong> — {typ}<br>{location} · {price} · {status}</li>")
    return f"<h2>{safe_title}</h2><p>Shared from WayIn.</p><ul>{''.join(lines)}</ul>"

@app.post("/api/share-trip")
@require_auth
@require_csrf
@limiter.limit("6 per minute")
def share_trip():
    payload = request.get_json(silent=True) or {}
    title = str(payload.get("title", "WayIn trip")).strip()[:120]
    items = payload.get("items", [])
    emails = payload.get("emails", [])
    phones = payload.get("phones", [])
    if not isinstance(items, list) or not items:
        return jsonify({"error": "Add at least one flight, hotel, or event to the trip first."}), 400
    if not isinstance(emails, list): emails = []
    if not isinstance(phones, list): phones = []
    emails = [str(x).strip().lower() for x in emails[:10] if clean_email(x)]
    phones = [str(x).strip() for x in phones[:10] if re.fullmatch(r"\+[1-9]\d{7,14}", str(x).strip())]
    if not emails and not phones:
        return jsonify({"error": "Add at least one valid email or phone number."}), 400

    sent_email, sent_sms, failures = 0, 0, []
    html_body = build_trip_message(title, items)
    plain = f"{title}: " + " | ".join(
        f"{str(i.get('type',''))}: {str(i.get('name',''))} ({str(i.get('location',''))})"
        for i in items[:8]
    )
    plain = plain[:1400]

    if emails:
        if not RESEND_API_KEY:
            failures.append("Email is not configured")
        else:
            try:
                resend.api_key = RESEND_API_KEY
                resend.Emails.send({
                    "from": WAYIN_FROM_EMAIL,
                    "to": emails,
                    "subject": f"WayIn trip: {title}",
                    "html": html_body,
                })
                sent_email = len(emails)
            except Exception:
                app.logger.exception("Email send failed")
                failures.append("Email provider failed")

    if phones:
        if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER):
            failures.append("SMS is not configured")
        else:
            try:
                tw = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
                for phone in phones:
                    tw.messages.create(body=plain, from_=TWILIO_FROM_NUMBER, to=phone)
                    sent_sms += 1
            except Exception:
                app.logger.exception("SMS send failed")
                failures.append("SMS provider failed")

    return jsonify({
        "ok": sent_email > 0 or sent_sms > 0,
        "sent_email": sent_email,
        "sent_sms": sent_sms,
        "warnings": failures,
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "8000")), debug=False)
