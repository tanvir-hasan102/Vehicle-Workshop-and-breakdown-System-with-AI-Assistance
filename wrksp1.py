"""
=============================================================
 RoadsideRescue BD — Full Backend
 Stack : Flask + SQLite + Anthropic Claude API
 Author: Generated for Hackathon
=============================================================
 Endpoints summary
 -----------------
 AUTH
   POST /api/register          — customer/mechanic signup
   POST /api/login             — returns JWT token

 SERVICE REQUESTS
   POST /api/service-request   — create a roadside request
   GET  /api/service-request/<id>  — get request details
   PUT  /api/service-request/<id>/status — update status

 MECHANICS
   GET  /api/mechanics/nearby  — find mechanics near GPS coords
   POST /api/mechanics/invite  — AI-powered country-wide scout + invite

 AI ASSISTANT
   POST /api/ai/diagnose       — text chat: describe problem → suggestions
   POST /api/ai/diagnose-image — image upload: detect damage from photo
   POST /api/ai/find-mechanic  — AI finds & recommends nearest mechanic

 PARTS
   GET  /api/parts             — list parts (filter by brand/model)
   POST /api/parts             — add a part (admin)

 BILLING
   POST /api/billing/create    — create a bill for a service request
   POST /api/billing/pay       — process payment (bKash/Nagad/card)
   GET  /api/billing/<id>      — get bill details

 GPS (txt-file based for now)
   POST /api/gps/update        — mechanic updates their location
   GET  /api/gps/<mechanic_id> — get mechanic's last known location
=============================================================
"""

import os
import json
import math
import uuid
import base64
import sqlite3
import datetime
import functools
from pathlib import Path

import anthropic
from flask import Flask, request, jsonify, g
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import jwt

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DB_PATH  = BASE_DIR / "rescue.db"
GPS_FILE = BASE_DIR / "gps_locations.txt"   # simple txt store
SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")   # set in env

app = Flask(__name__)
CORS(app)

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ─────────────────────────────────────────────
# DATABASE SETUP
# ─────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    phone       TEXT UNIQUE NOT NULL,
    email       TEXT,
    password    TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'customer',   -- customer | mechanic | admin
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vehicles (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    brand       TEXT NOT NULL,
    model       TEXT NOT NULL,
    year        INTEGER,
    type        TEXT NOT NULL,   -- car | bike | truck
    reg_number  TEXT,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS mechanic_profiles (
    id              TEXT PRIMARY KEY,
    user_id         TEXT UNIQUE NOT NULL,
    specialization  TEXT NOT NULL,   -- engine | tire | fuel | electrical | general
    experience_yrs  INTEGER DEFAULT 0,
    rating          REAL DEFAULT 5.0,
    available       INTEGER DEFAULT 1,   -- 1=yes 0=no
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS service_requests (
    id              TEXT PRIMARY KEY,
    customer_id     TEXT NOT NULL,
    vehicle_id      TEXT NOT NULL,
    problem_type    TEXT NOT NULL,   -- engine | tire | fuel | electrical | other
    description     TEXT,
    latitude        REAL NOT NULL,
    longitude       REAL NOT NULL,
    address_hint    TEXT,
    status          TEXT DEFAULT 'pending',   -- pending|assigned|in_progress|completed|cancelled
    mechanic_id     TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    FOREIGN KEY(customer_id) REFERENCES users(id),
    FOREIGN KEY(vehicle_id)  REFERENCES vehicles(id)
);

CREATE TABLE IF NOT EXISTS parts (
    id          TEXT PRIMARY KEY,
    brand       TEXT NOT NULL,
    model       TEXT NOT NULL,
    part_name   TEXT NOT NULL,
    category    TEXT NOT NULL,   -- engine | tire | fuel | electrical | body
    price       REAL NOT NULL,
    in_stock    INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS bills (
    id              TEXT PRIMARY KEY,
    request_id      TEXT UNIQUE NOT NULL,
    customer_id     TEXT NOT NULL,
    labour_cost     REAL DEFAULT 0,
    parts_cost      REAL DEFAULT 0,
    travel_cost     REAL DEFAULT 0,
    total           REAL DEFAULT 0,
    payment_method  TEXT,   -- bkash | nagad | visa | mastercard | cash
    payment_status  TEXT DEFAULT 'unpaid',   -- unpaid | paid | partial
    paid_at         TEXT,
    txn_ref         TEXT,
    FOREIGN KEY(request_id)  REFERENCES service_requests(id),
    FOREIGN KEY(customer_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS mechanic_invitations (
    id          TEXT PRIMARY KEY,
    phone       TEXT,
    email       TEXT,
    area        TEXT,
    status      TEXT DEFAULT 'sent',   -- sent | accepted | declined
    sent_at     TEXT NOT NULL
);
"""

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        db.executescript(SCHEMA)
        db.commit()
        _seed_parts(db)
        print("✅ Database initialised")

def _seed_parts(db):
    existing = db.execute("SELECT COUNT(*) FROM parts").fetchone()[0]
    if existing > 0:
        return
    sample_parts = [
        (str(uuid.uuid4()), "Toyota", "Corolla", "Engine Oil Filter", "engine", 350.0, 1),
        (str(uuid.uuid4()), "Toyota", "Corolla", "Spark Plug Set", "engine", 800.0, 1),
        (str(uuid.uuid4()), "Honda",  "CB150R",  "Chain Sprocket Kit", "engine", 1200.0, 1),
        (str(uuid.uuid4()), "Toyota", "Corolla", "Front Tyre 195/65R15", "tire", 3500.0, 1),
        (str(uuid.uuid4()), "Honda",  "CB150R",  "Rear Tyre 130/70-17", "tire", 2200.0, 1),
        (str(uuid.uuid4()), "Suzuki", "Alto",    "Fuel Pump", "fuel", 2800.0, 1),
        (str(uuid.uuid4()), "Toyota", "Corolla", "Alternator Belt", "electrical", 650.0, 1),
        (str(uuid.uuid4()), "Honda",  "Civic",   "Battery 12V 40Ah", "electrical", 4500.0, 1),
        (str(uuid.uuid4()), "Bajaj",  "Pulsar",  "Brake Pad Set", "body", 450.0, 1),
        (str(uuid.uuid4()), "Suzuki", "Alto",    "Radiator Coolant 1L", "engine", 280.0, 1),
    ]
    db.executemany(
        "INSERT INTO parts VALUES (?,?,?,?,?,?,?)", sample_parts
    )
    db.commit()
    print("✅ Sample parts seeded")


# ─────────────────────────────────────────────
# AUTH HELPERS
# ─────────────────────────────────────────────
def create_token(user_id: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=7),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

def token_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not token:
            return jsonify({"error": "Token missing"}), 401
        try:
            data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            g.user_id = data["sub"]
            g.user_role = data["role"]
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────
# GPS HELPERS  (txt-file based)
# ─────────────────────────────────────────────
def update_gps_file(mechanic_id: str, lat: float, lon: float):
    """Read txt file, update or insert mechanic location, write back."""
    locations: dict = {}
    if GPS_FILE.exists():
        for line in GPS_FILE.read_text().splitlines():
            parts = line.split(",")
            if len(parts) == 3:
                locations[parts[0]] = (float(parts[1]), float(parts[2]))
    locations[mechanic_id] = (lat, lon)
    GPS_FILE.write_text(
        "\n".join(f"{mid},{loc[0]},{loc[1]}" for mid, loc in locations.items())
    )

def read_gps_file() -> dict:
    locations = {}
    if GPS_FILE.exists():
        for line in GPS_FILE.read_text().splitlines():
            parts = line.strip().split(",")
            if len(parts) == 3:
                try:
                    locations[parts[0]] = (float(parts[1]), float(parts[2]))
                except ValueError:
                    pass
    return locations

def haversine_km(lat1, lon1, lat2, lon2) -> float:
    """Distance between two GPS coordinates in km."""
    R = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi  = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ─────────────────────────────────────────────
# UTILITY
# ─────────────────────────────────────────────
def now_iso():
    return datetime.datetime.utcnow().isoformat()

def row_to_dict(row):
    return dict(row) if row else None

def rows_to_list(rows):
    return [dict(r) for r in rows]


# ═════════════════════════════════════════════
# AUTH ROUTES
# ═════════════════════════════════════════════
@app.route("/api/register", methods=["POST"])
def register():
    """
    Register a customer or mechanic.
    Body JSON:
      name, phone, email, password, role (customer|mechanic),
      # If role=mechanic: specialization, experience_yrs
      # Vehicle (optional for customer): brand, model, year, type, reg_number
    """
    d = request.json or {}
    required = ["name", "phone", "password", "role"]
    missing = [f for f in required if not d.get(f)]
    if missing:
        return jsonify({"error": f"Missing fields: {missing}"}), 400

    db = get_db()
    existing = db.execute("SELECT id FROM users WHERE phone=?", (d["phone"],)).fetchone()
    if existing:
        return jsonify({"error": "Phone already registered"}), 409

    user_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO users VALUES (?,?,?,?,?,?,?)",
        (user_id, d["name"], d["phone"], d.get("email"), generate_password_hash(d["password"]), d["role"], now_iso())
    )

    if d["role"] == "mechanic":
        mech_id = str(uuid.uuid4())
        db.execute(
            "INSERT INTO mechanic_profiles VALUES (?,?,?,?,?,?)",
            (mech_id, user_id, d.get("specialization", "general"), d.get("experience_yrs", 0), 5.0, 1)
        )

    if d.get("brand"):
        veh_id = str(uuid.uuid4())
        db.execute(
            "INSERT INTO vehicles VALUES (?,?,?,?,?,?,?)",
            (veh_id, user_id, d["brand"], d["model"], d.get("year"), d.get("type", "car"), d.get("reg_number"))
        )

    db.commit()
    token = create_token(user_id, d["role"])
    return jsonify({"message": "Registered successfully", "token": token, "user_id": user_id}), 201


@app.route("/api/login", methods=["POST"])
def login():
    d = request.json or {}
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE phone=?", (d.get("phone", ""),)).fetchone()
    if not user or not check_password_hash(user["password"], d.get("password", "")):
        return jsonify({"error": "Invalid credentials"}), 401
    token = create_token(user["id"], user["role"])
    return jsonify({"token": token, "user_id": user["id"], "role": user["role"], "name": user["name"]})


# ═════════════════════════════════════════════
# SERVICE REQUEST ROUTES
# ═════════════════════════════════════════════
@app.route("/api/service-request", methods=["POST"])
@token_required
def create_service_request():
    """
    Customer creates a roadside service request.
    Body: vehicle_id, problem_type, description, latitude, longitude, address_hint
    """
    d = request.json or {}
    required = ["vehicle_id", "problem_type", "latitude", "longitude"]
    missing = [f for f in required if d.get(f) is None]
    if missing:
        return jsonify({"error": f"Missing: {missing}"}), 400

    db = get_db()
    # verify vehicle belongs to customer
    veh = db.execute(
        "SELECT * FROM vehicles WHERE id=? AND user_id=?", (d["vehicle_id"], g.user_id)
    ).fetchone()
    if not veh:
        return jsonify({"error": "Vehicle not found or not yours"}), 404

    req_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO service_requests VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (req_id, g.user_id, d["vehicle_id"], d["problem_type"],
         d.get("description"), d["latitude"], d["longitude"],
         d.get("address_hint"), "pending", None, now_iso(), now_iso())
    )
    db.commit()

    # Auto-find nearest available mechanic
    nearby = _find_nearby_mechanics(d["latitude"], d["longitude"], d["problem_type"], db, radius_km=50)

    return jsonify({
        "request_id": req_id,
        "status": "pending",
        "nearby_mechanics": nearby[:3],
        "message": "Service request created. Nearby mechanics shown above. You can assign one or wait for auto-dispatch."
    }), 201


@app.route("/api/service-request/<req_id>", methods=["GET"])
@token_required
def get_service_request(req_id):
    db = get_db()
    row = db.execute("SELECT * FROM service_requests WHERE id=?", (req_id,)).fetchone()
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row_to_dict(row))


@app.route("/api/service-request/<req_id>/status", methods=["PUT"])
@token_required
def update_request_status(req_id):
    d = request.json or {}
    db = get_db()
    valid_statuses = {"pending", "assigned", "in_progress", "completed", "cancelled"}
    if d.get("status") not in valid_statuses:
        return jsonify({"error": f"Status must be one of {valid_statuses}"}), 400

    db.execute(
        "UPDATE service_requests SET status=?, mechanic_id=COALESCE(?,mechanic_id), updated_at=? WHERE id=?",
        (d["status"], d.get("mechanic_id"), now_iso(), req_id)
    )
    db.commit()
    return jsonify({"message": "Status updated"})


# ═════════════════════════════════════════════
# MECHANIC ROUTES
# ═════════════════════════════════════════════
def _find_nearby_mechanics(lat, lon, problem_type, db, radius_km=50):
    """Core helper used by both API and AI routes."""
    gps_data = read_gps_file()

    # Get all available mechanics, optionally filtered by specialization
    query = """
        SELECT u.id, u.name, u.phone, mp.specialization, mp.rating, mp.experience_yrs
        FROM mechanic_profiles mp
        JOIN users u ON u.id = mp.user_id
        WHERE mp.available = 1
    """
    params = []
    # Prefer specialists but don't exclude general mechanics
    all_mechs = rows_to_list(db.execute(query, params).fetchall())

    result = []
    for m in all_mechs:
        uid = m["id"]
        if uid in gps_data:
            mlat, mlon = gps_data[uid]
            dist = haversine_km(lat, lon, mlat, mlon)
            if dist <= radius_km:
                m["distance_km"] = round(dist, 2)
                m["latitude"] = mlat
                m["longitude"] = mlon
                # Boost score for specialists
                specialization_match = (
                    m["specialization"] == problem_type or
                    m["specialization"] == "general"
                )
                m["specialization_match"] = specialization_match
                result.append(m)

    result.sort(key=lambda x: (not x["specialization_match"], x["distance_km"]))
    return result


@app.route("/api/mechanics/nearby", methods=["GET"])
@token_required
def find_nearby_mechanics():
    lat = request.args.get("lat", type=float)
    lon = request.args.get("lon", type=float)
    problem = request.args.get("problem_type", "general")
    radius  = request.args.get("radius_km", 50, type=float)

    if lat is None or lon is None:
        return jsonify({"error": "lat and lon required"}), 400

    db = get_db()
    nearby = _find_nearby_mechanics(lat, lon, problem, db, radius_km=radius)

    if not nearby:
        return jsonify({
            "mechanics": [],
            "message": "No mechanics found nearby. Use /api/mechanics/invite to scout country-wide.",
            "suggest_central_dispatch": True
        })
    return jsonify({"mechanics": nearby, "count": len(nearby)})


@app.route("/api/mechanics/invite", methods=["POST"])
@token_required
def invite_mechanics_ai():
    """
    AI-powered mechanic scout.
    If a customer is 300km from base and no mechanic is nearby,
    this uses Claude to draft personalised invitation messages
    and logs them to the DB (in a real system you'd send SMS/email).
    Body: area (city/district), problem_type, customer_location (optional description)
    """
    d = request.json or {}
    area = d.get("area", "Bangladesh")
    problem_type = d.get("problem_type", "general")
    customer_location = d.get("customer_location", "a remote area")

    # Use Claude to generate professional invitation message
    prompt = f"""
You are a dispatch coordinator for RoadsideRescue Bangladesh.

A customer is stranded at: {customer_location}
They need a mechanic specializing in: {problem_type}
Target recruitment area: {area}

Write a short, professional SMS invitation (max 160 characters) to a local mechanic 
asking them to join our emergency network and help this customer.
Then write a slightly longer WhatsApp/email version (3-4 sentences).

Respond in JSON:
{{
  "sms_text": "...",
  "whatsapp_text": "...",
  "suggested_search_keywords": ["..."]
}}
"""
    try:
        response = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.content[0].text
        # Strip markdown fences if present
        raw = raw.replace("```json", "").replace("```", "").strip()
        ai_result = json.loads(raw)
    except Exception as e:
        ai_result = {
            "sms_text": f"Join RoadsideRescue BD! A customer near {area} needs {problem_type} help. Reply YES. +880-XXXX-XXXX",
            "whatsapp_text": f"Dear Mechanic, We are RoadsideRescue Bangladesh. A customer is stranded near {area} and urgently needs {problem_type} assistance. We would like to invite you to join our network and earn by helping. Contact us at rescue@example.com",
            "suggested_search_keywords": [f"mechanic {area}", f"{problem_type} repair {area}"],
            "error_note": str(e)
        }

    # Log invitation in DB
    db = get_db()
    inv_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO mechanic_invitations VALUES (?,?,?,?,?,?)",
        (inv_id, None, None, area, "sent", now_iso())
    )
    db.commit()

    return jsonify({
        "invitation_id": inv_id,
        "area": area,
        "problem_type": problem_type,
        "ai_generated_messages": ai_result,
        "message": "Invitations logged. In production these would be sent via SMS/email to mechanics in the area."
    })


@app.route("/api/gps/update", methods=["POST"])
@token_required
def update_mechanic_gps():
    d = request.json or {}
    lat = d.get("latitude")
    lon = d.get("longitude")
    if lat is None or lon is None:
        return jsonify({"error": "latitude and longitude required"}), 400
    update_gps_file(g.user_id, float(lat), float(lon))
    return jsonify({"message": "GPS updated"})


@app.route("/api/gps/<mechanic_id>", methods=["GET"])
@token_required
def get_mechanic_gps(mechanic_id):
    locations = read_gps_file()
    if mechanic_id not in locations:
        return jsonify({"error": "No GPS data for this mechanic"}), 404
    lat, lon = locations[mechanic_id]
    return jsonify({"mechanic_id": mechanic_id, "latitude": lat, "longitude": lon})


# ═════════════════════════════════════════════
# AI ASSISTANT ROUTES
# ═════════════════════════════════════════════

SYSTEM_PROMPT = """You are RescueBot, the AI assistant for RoadsideRescue Bangladesh — 
an emergency vehicle rescue service. You help stranded drivers diagnose their vehicle 
problems and suggest immediate actions to take while waiting for a mechanic.

Rules:
- Be concise, practical, and calm. The user may be stressed.
- Always suggest safe immediate actions (e.g. pull off road, turn on hazards).
- Tell the user what type of mechanic specialist they need.
- If the problem sounds severe (engine smoke, brake failure), advise NOT to drive.
- End every response with: "A mechanic has been notified. Help is on the way."
- Respond in the same language the user writes in (Bengali or English).
"""


@app.route("/api/ai/diagnose", methods=["POST"])
@token_required
def ai_diagnose_text():
    """
    Text-based vehicle problem diagnosis.
    Body: { "message": "My car is making a loud knocking sound from the engine" }
    Optional: { "history": [ {"role":"user","content":"..."}, ... ] }
    """
    d = request.json or {}
    user_message = d.get("message", "").strip()
    if not user_message:
        return jsonify({"error": "message is required"}), 400

    # Build conversation history
    history = d.get("history", [])
    messages = history + [{"role": "user", "content": user_message}]

    try:
        response = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=600,
            system=SYSTEM_PROMPT,
            messages=messages
        )
        reply = response.content[0].text

        # Infer problem type for mechanic matching
        problem_classification_prompt = f"""
Based on this vehicle problem description: "{user_message}"
Classify the problem type as exactly one of: engine | tire | fuel | electrical | general
Respond with only the single word, nothing else.
"""
        cls_resp = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=10,
            messages=[{"role": "user", "content": problem_classification_prompt}]
        )
        problem_type = cls_resp.content[0].text.strip().lower()
        if problem_type not in {"engine", "tire", "fuel", "electrical", "general"}:
            problem_type = "general"

        return jsonify({
            "reply": reply,
            "detected_problem_type": problem_type,
            "next_action": "Use /api/mechanics/nearby to find a specialist mechanic."
        })

    except anthropic.APIError as e:
        return jsonify({"error": f"AI service error: {str(e)}"}), 503


@app.route("/api/ai/diagnose-image", methods=["POST"])
@token_required
def ai_diagnose_image():
    """
    Image-based vehicle damage detection.
    Accepts multipart/form-data with:
      - image: the vehicle photo file
      - description: optional text description from user
    """
    if "image" not in request.files:
        return jsonify({"error": "image file required"}), 400

    file = request.files["image"]
    description = request.form.get("description", "")
    media_type = file.content_type or "image/jpeg"

    # Read and encode image
    image_data = base64.standard_b64encode(file.read()).decode("utf-8")

    user_content = []
    if description:
        user_content.append({"type": "text", "text": f"The driver says: {description}"})
    user_content.append({"type": "text", "text": "Please analyse this vehicle photo and identify any visible damage, issues, or warning signs."})
    user_content.append({
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": image_data
        }
    })

    try:
        response = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=700,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}]
        )
        analysis = response.content[0].text

        # Extract structured info
        extract_prompt = f"""
From this vehicle damage analysis:
\"\"\"{analysis}\"\"\"

Extract:
1. Primary problem type (engine/tire/fuel/electrical/body/unknown)
2. Severity (low/medium/high/critical)
3. Can the vehicle be driven safely? (yes/no/maybe)
4. List of parts likely needed (max 3)

Respond ONLY as JSON, no markdown:
{{"problem_type":"...","severity":"...","can_drive":"...","parts_needed":["..."]}}
"""
        ext = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=200,
            messages=[{"role": "user", "content": extract_prompt}]
        )
        raw = ext.content[0].text.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        structured = json.loads(raw)

    except (json.JSONDecodeError, KeyError):
        structured = {"problem_type": "unknown", "severity": "unknown", "can_drive": "no", "parts_needed": []}
    except anthropic.APIError as e:
        return jsonify({"error": f"AI service error: {str(e)}"}), 503

    return jsonify({
        "ai_analysis": analysis,
        "structured": structured,
        "next_action": "Use /api/mechanics/nearby with detected problem_type to find a specialist."
    })


@app.route("/api/ai/find-mechanic", methods=["POST"])
@token_required
def ai_find_mechanic():
    """
    AI-enhanced mechanic recommendation.
    Finds nearby mechanics and uses Claude to explain who is best for the problem.
    Body: { "latitude": 23.8, "longitude": 90.4, "problem_type": "engine", "description": "..." }
    """
    d = request.json or {}
    lat  = d.get("latitude")
    lon  = d.get("longitude")
    prob = d.get("problem_type", "general")
    desc = d.get("description", "")

    if lat is None or lon is None:
        return jsonify({"error": "latitude and longitude required"}), 400

    db = get_db()
    nearby = _find_nearby_mechanics(lat, lon, prob, db, radius_km=100)

    if not nearby:
        # Trigger country-wide scout
        scout_result = _ai_scout_message(prob, "your area")
        return jsonify({
            "mechanics": [],
            "ai_recommendation": (
                f"No mechanics are currently registered near you. "
                f"We are sending invitations to local mechanics in your area. "
                f"Meanwhile, you can contact our main dispatch: 01700-RESCUE"
            ),
            "scout_triggered": True,
            "scout_details": scout_result
        })

    # Ask Claude to recommend the best mechanic from the list
    mech_summary = "\n".join(
        f"- {m['name']}: {m['specialization']} specialist, {m['experience_yrs']}yrs exp, "
        f"rating {m['rating']}, {m['distance_km']}km away"
        for m in nearby[:5]
    )

    rec_prompt = f"""
A driver has a vehicle problem: "{desc or prob}"

Available mechanics nearby:
{mech_summary}

Recommend the single best mechanic for this specific problem and explain why in 2 sentences.
Then list the others as alternatives.
Be direct and helpful. Format:
BEST PICK: [name] — [reason]
ALTERNATIVES: [name1], [name2]
"""
    try:
        rec_resp = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=200,
            messages=[{"role": "user", "content": rec_prompt}]
        )
        recommendation = rec_resp.content[0].text
    except anthropic.APIError:
        recommendation = f"Best pick: {nearby[0]['name']} — closest specialist mechanic."

    return jsonify({
        "mechanics": nearby[:5],
        "ai_recommendation": recommendation,
        "count": len(nearby)
    })


def _ai_scout_message(problem_type, area):
    """Internal helper to generate scout invite (used by find-mechanic fallback)."""
    try:
        r = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=150,
            messages=[{"role": "user", "content":
                f"Write a 1-sentence urgent SMS invite for a {problem_type} mechanic in {area} to join RoadsideRescue BD emergency network."
            }]
        )
        return r.content[0].text
    except Exception:
        return f"Urgent: RoadsideRescue BD needs {problem_type} mechanics in {area}. Call 01700-RESCUE to join."


# ═════════════════════════════════════════════
# PARTS ROUTES
# ═════════════════════════════════════════════
@app.route("/api/parts", methods=["GET"])
@token_required
def get_parts():
    """
    List parts. Query params: brand, model, category
    Example: /api/parts?brand=Toyota&model=Corolla&category=engine
    """
    db = get_db()
    query = "SELECT * FROM parts WHERE 1=1"
    params = []
    for field in ("brand", "model", "category"):
        val = request.args.get(field)
        if val:
            query += f" AND {field} LIKE ?"
            params.append(f"%{val}%")
    query += " AND in_stock=1"
    rows = db.execute(query, params).fetchall()
    return jsonify({"parts": rows_to_list(rows), "count": len(rows)})


@app.route("/api/parts", methods=["POST"])
@token_required
def add_part():
    d = request.json or {}
    required = ["brand", "model", "part_name", "category", "price"]
    missing = [f for f in required if not d.get(f)]
    if missing:
        return jsonify({"error": f"Missing: {missing}"}), 400

    db = get_db()
    part_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO parts VALUES (?,?,?,?,?,?,?)",
        (part_id, d["brand"], d["model"], d["part_name"], d["category"], float(d["price"]), 1)
    )
    db.commit()
    return jsonify({"part_id": part_id, "message": "Part added"}), 201


@app.route("/api/parts/recommend", methods=["POST"])
@token_required
def ai_recommend_parts():
    """
    AI-powered parts recommendation based on vehicle and problem.
    Body: { "brand": "Toyota", "model": "Corolla", "problem_type": "engine", "description": "..." }
    """
    d = request.json or {}
    brand = d.get("brand", "")
    model = d.get("model", "")
    problem = d.get("problem_type", "")
    desc = d.get("description", "")

    db = get_db()
    # Get available parts for this vehicle
    available_parts = rows_to_list(db.execute(
        "SELECT * FROM parts WHERE brand LIKE ? AND model LIKE ? AND in_stock=1",
        (f"%{brand}%", f"%{model}%")
    ).fetchall())

    parts_list = "\n".join(f"- {p['part_name']} ({p['category']}) — ৳{p['price']}" for p in available_parts) or "No specific parts found in catalog."

    prompt = f"""
Vehicle: {brand} {model}
Problem: {problem} — {desc}

Parts available in our inventory for this vehicle:
{parts_list}

Which parts from this list are most likely needed to fix this problem?
List up to 3 parts with a brief reason for each.
If none are relevant, suggest what to order.
Keep response under 100 words.
"""
    try:
        resp = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        recommendation = resp.content[0].text
    except anthropic.APIError as e:
        recommendation = f"AI service unavailable. Showing all {brand} {model} parts."

    return jsonify({
        "available_parts": available_parts,
        "ai_recommendation": recommendation,
        "vehicle": f"{brand} {model}"
    })


# ═════════════════════════════════════════════
# BILLING ROUTES
# ═════════════════════════════════════════════
@app.route("/api/billing/create", methods=["POST"])
@token_required
def create_bill():
    """
    Create a bill for a completed/in-progress service request.
    Body: request_id, labour_cost, parts_cost, travel_cost
    """
    d = request.json or {}
    if not d.get("request_id"):
        return jsonify({"error": "request_id required"}), 400

    db = get_db()
    req = db.execute("SELECT * FROM service_requests WHERE id=?", (d["request_id"],)).fetchone()
    if not req:
        return jsonify({"error": "Service request not found"}), 404

    labour  = float(d.get("labour_cost", 0))
    parts   = float(d.get("parts_cost", 0))
    travel  = float(d.get("travel_cost", 0))
    total   = labour + parts + travel

    bill_id = str(uuid.uuid4())
    try:
        db.execute(
            "INSERT INTO bills VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (bill_id, d["request_id"], req["customer_id"], labour, parts, travel, total, None, "unpaid", None, None)
        )
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify({"error": "Bill already exists for this request"}), 409

    return jsonify({
        "bill_id": bill_id,
        "total": total,
        "breakdown": {"labour": labour, "parts": parts, "travel": travel},
        "status": "unpaid"
    }), 201


@app.route("/api/billing/pay", methods=["POST"])
@token_required
def process_payment():
    """
    Process payment for a bill.
    Body: bill_id, payment_method (bkash|nagad|visa|mastercard|cash), amount
    In production: integrate with bKash/Nagad/SSL Commerz APIs here.
    """
    d = request.json or {}
    bill_id = d.get("bill_id")
    method  = d.get("payment_method", "cash")
    amount  = float(d.get("amount", 0))

    valid_methods = {"bkash", "nagad", "visa", "mastercard", "cash"}
    if method not in valid_methods:
        return jsonify({"error": f"Payment method must be one of {valid_methods}"}), 400

    db = get_db()
    bill = db.execute("SELECT * FROM bills WHERE id=?", (bill_id,)).fetchone()
    if not bill:
        return jsonify({"error": "Bill not found"}), 404
    if bill["payment_status"] == "paid":
        return jsonify({"error": "Bill already paid"}), 400

    # In production: call payment gateway API here
    # For now: simulate successful payment
    txn_ref = f"TXN-{uuid.uuid4().hex[:10].upper()}"
    status = "paid" if amount >= bill["total"] else "partial"

    db.execute(
        "UPDATE bills SET payment_method=?, payment_status=?, paid_at=?, txn_ref=? WHERE id=?",
        (method, status, now_iso(), txn_ref, bill_id)
    )
    db.commit()

    return jsonify({
        "bill_id": bill_id,
        "txn_ref": txn_ref,
        "payment_method": method,
        "amount_paid": amount,
        "total_due": bill["total"],
        "status": status,
        "message": f"Payment {status} via {method.upper()}. Reference: {txn_ref}"
    })


@app.route("/api/billing/<bill_id>", methods=["GET"])
@token_required
def get_bill(bill_id):
    db = get_db()
    bill = db.execute("SELECT * FROM bills WHERE id=?", (bill_id,)).fetchone()
    if not bill:
        return jsonify({"error": "Bill not found"}), 404
    return jsonify(row_to_dict(bill))


# ═════════════════════════════════════════════
# VEHICLE ROUTES
# ═════════════════════════════════════════════
@app.route("/api/vehicles", methods=["GET"])
@token_required
def get_my_vehicles():
    db = get_db()
    rows = db.execute("SELECT * FROM vehicles WHERE user_id=?", (g.user_id,)).fetchall()
    return jsonify({"vehicles": rows_to_list(rows)})


@app.route("/api/vehicles", methods=["POST"])
@token_required
def add_vehicle():
    d = request.json or {}
    required = ["brand", "model", "type"]
    missing = [f for f in required if not d.get(f)]
    if missing:
        return jsonify({"error": f"Missing: {missing}"}), 400

    db = get_db()
    veh_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO vehicles VALUES (?,?,?,?,?,?,?)",
        (veh_id, g.user_id, d["brand"], d["model"], d.get("year"), d["type"], d.get("reg_number"))
    )
    db.commit()
    return jsonify({"vehicle_id": veh_id, "message": "Vehicle added"}), 201


# ═════════════════════════════════════════════
# HEALTH CHECK
# ═════════════════════════════════════════════
@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "RoadsideRescue Bangladesh API",
        "version": "1.0.0",
        "ai_enabled": bool(ANTHROPIC_API_KEY),
        "timestamp": now_iso()
    })


# ═════════════════════════════════════════════
# ENTRY POINT
# ═════════════════════════════════════════════
if __name__ == "__main__":
    init_db()
    print("🚀 RoadsideRescue API starting on http://0.0.0.0:5000")
    app.run(debug=True, host="0.0.0.0", port=5000)