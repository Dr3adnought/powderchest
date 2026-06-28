from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
import json
import os
from datetime import UTC, datetime
import secrets
import time
import hashlib

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Data file path: use /data in containers, fallback to local visitor-api/data for local runs.
LOCAL_DATA_FILE = os.path.join(os.path.dirname(__file__), 'data', 'visitors.json')
DEFAULT_DATA_FILE = '/data/visitors.json' if os.path.isdir('/data') else LOCAL_DATA_FILE
DATA_FILE = os.environ.get('VISITOR_DATA_FILE', DEFAULT_DATA_FILE)
ABOUT_PIN = os.environ.get('ABOUT_PIN', '1749')
ABOUT_PIN_HASH = os.environ.get('ABOUT_PIN_HASH', '').strip()
ABOUT_AUTH_SECRET = os.environ.get('ABOUT_AUTH_SECRET', 'powderchest-about-secret-change-me')
ABOUT_AUTH_MAX_AGE_SECONDS = int(os.environ.get('ABOUT_AUTH_MAX_AGE_SECONDS', '86400'))
ABOUT_AUTH_COOKIE_NAME = os.environ.get('ABOUT_AUTH_COOKIE_NAME', 'powderchest_about_auth')
ABOUT_COOKIE_SECURE = os.environ.get('ABOUT_COOKIE_SECURE', 'true').strip().lower() in {'1', 'true', 'yes', 'on'}
ABOUT_ADMIN_TOKEN = os.environ.get('ABOUT_ADMIN_TOKEN', '').strip()
ABOUT_IP_HASH_SALT = os.environ.get('ABOUT_IP_HASH_SALT', 'powderchest-about-ip-salt-change-me')
ABOUT_EVENT_LOG_LIMIT = int(os.environ.get('ABOUT_EVENT_LOG_LIMIT', '200'))
ABOUT_UNLOCK_RATE_WINDOW_SECONDS = int(os.environ.get('ABOUT_UNLOCK_RATE_WINDOW_SECONDS', '300'))
ABOUT_UNLOCK_RATE_MAX_ATTEMPTS = int(os.environ.get('ABOUT_UNLOCK_RATE_MAX_ATTEMPTS', '8'))
ABOUT_UNLOCK_LOCK_SECONDS = int(os.environ.get('ABOUT_UNLOCK_LOCK_SECONDS', '900'))

# In-memory unlock guardrails. These naturally reset if the container restarts.
unlock_attempts = {}


def utc_now_iso():
    return datetime.now(UTC).isoformat()


def normalize_data(raw_data):
    visitors = raw_data.get('visitors', {}) if isinstance(raw_data, dict) else {}
    if not isinstance(visitors, dict):
        visitors = {}

    crew_raw = raw_data.get('crew', []) if isinstance(raw_data, dict) else []
    if isinstance(crew_raw, set):
        crew = crew_raw
    elif isinstance(crew_raw, list):
        crew = set(crew_raw)
    else:
        crew = set()

    about_access_raw = raw_data.get('about_access', {}) if isinstance(raw_data, dict) else {}
    if not isinstance(about_access_raw, dict):
        about_access_raw = {}

    about_access = {
        'unlock_count': int(about_access_raw.get('unlock_count', 0) or 0),
        'view_count': int(about_access_raw.get('view_count', 0) or 0),
        'last_access_at': about_access_raw.get('last_access_at'),
        'events': about_access_raw.get('events', []) if isinstance(about_access_raw.get('events', []), list) else []
    }

    return {'visitors': visitors, 'crew': crew, 'about_access': about_access}


def clean_crew_name(name):
    if not isinstance(name, str):
        return None
    cleaned = name.strip()
    if not cleaned:
        return None
    return cleaned[:32]

def load_data():
    """Load visitor data from JSON file"""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                return normalize_data(json.load(f))
        except json.JSONDecodeError:
            return normalize_data({})
    return normalize_data({})

def save_data(data):
    """Save visitor data to JSON file"""
    # Convert set to list for JSON serialization
    data_to_save = {
        'visitors': data['visitors'],
        'crew': sorted(list(data['crew'])),
        'about_access': data.get('about_access', {
            'unlock_count': 0,
            'view_count': 0,
            'last_access_at': None,
            'events': []
        })
    }
    
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, 'w') as f:
        json.dump(data_to_save, f, indent=2)

def get_counts(data):
    """Calculate visitor counts"""
    total = len(data['visitors'])
    crew = len(data['crew'])
    wanderers = total - crew

    crew_members = []
    for visitor_id in data['crew']:
        visitor = data['visitors'].get(visitor_id, {})
        crew_name = visitor.get('crew_name')
        if crew_name:
            crew_members.append(crew_name)

    crew_members = sorted(set(crew_members), key=str.lower)
    
    return {
        'total': total,
        'crew': crew,
        'wanderers': wanderers,
        'crewMembers': crew_members
    }


def get_about_access_stats(data):
    about_access = data.get('about_access', {})
    return {
        'unlockCount': int(about_access.get('unlock_count', 0) or 0),
        'viewCount': int(about_access.get('view_count', 0) or 0),
        'lastAccessAt': about_access.get('last_access_at')
    }


def mark_about_access(data, key):
    about_access = data.setdefault('about_access', {
        'unlock_count': 0,
        'view_count': 0,
        'last_access_at': None,
        'events': []
    })
    about_access[key] = int(about_access.get(key, 0) or 0) + 1
    about_access['last_access_at'] = utc_now_iso()


def get_client_ip(req):
    forwarded_for = req.headers.get('X-Forwarded-For', '')
    if forwarded_for:
        # Keep the left-most original client IP.
        return forwarded_for.split(',')[0].strip()
    return (req.remote_addr or '').strip() or 'unknown'


def hash_ip(ip_value):
    material = f"{ABOUT_IP_HASH_SALT}:{ip_value}".encode('utf-8', errors='ignore')
    # Short hash is easier to scan in dashboards while still hiding raw IPs.
    return hashlib.sha256(material).hexdigest()[:16]


def log_about_event(data, event_type, req):
    about_access = data.setdefault('about_access', {
        'unlock_count': 0,
        'view_count': 0,
        'last_access_at': None,
        'events': []
    })

    events = about_access.get('events')
    if not isinstance(events, list):
        events = []

    ip_value = get_client_ip(req)
    events.append({
        'ts': utc_now_iso(),
        'type': event_type,
        'ip_hash': hash_ip(ip_value)
    })

    if len(events) > ABOUT_EVENT_LOG_LIMIT:
        events = events[-ABOUT_EVENT_LOG_LIMIT:]

    about_access['events'] = events


def get_recent_about_events(data, count=10):
    about_access = data.get('about_access', {})
    events = about_access.get('events', [])
    if not isinstance(events, list):
        return []
    return list(reversed(events[-count:]))


def verify_about_pin(pin_value):
    pin_candidate = str(pin_value or '').strip()
    if not pin_candidate:
        return False

    if ABOUT_PIN_HASH:
        return check_password_hash(ABOUT_PIN_HASH, pin_candidate)

    return secrets.compare_digest(pin_candidate, ABOUT_PIN)


def get_unlock_state_for_ip(ip_value):
    state = unlock_attempts.get(ip_value)
    if not state:
        state = {'attempts': [], 'locked_until': 0}
        unlock_attempts[ip_value] = state
    return state


def prune_attempts(state, now_ts):
    cutoff = now_ts - ABOUT_UNLOCK_RATE_WINDOW_SECONDS
    state['attempts'] = [ts for ts in state.get('attempts', []) if ts >= cutoff]


def unlock_is_limited(ip_value):
    now_ts = int(time.time())
    state = get_unlock_state_for_ip(ip_value)
    prune_attempts(state, now_ts)
    return now_ts < int(state.get('locked_until', 0) or 0)


def unlock_rate_limit_remaining(ip_value):
    now_ts = int(time.time())
    state = get_unlock_state_for_ip(ip_value)
    locked_until = int(state.get('locked_until', 0) or 0)
    return max(0, locked_until - now_ts)


def register_unlock_failure(ip_value):
    now_ts = int(time.time())
    state = get_unlock_state_for_ip(ip_value)
    prune_attempts(state, now_ts)
    attempts = state.get('attempts', [])
    attempts.append(now_ts)
    state['attempts'] = attempts

    if len(attempts) >= ABOUT_UNLOCK_RATE_MAX_ATTEMPTS:
        state['locked_until'] = now_ts + ABOUT_UNLOCK_LOCK_SECONDS
        state['attempts'] = []


def clear_unlock_failures(ip_value):
    if ip_value in unlock_attempts:
        unlock_attempts[ip_value] = {'attempts': [], 'locked_until': 0}


def build_about_serializer():
    return URLSafeTimedSerializer(ABOUT_AUTH_SECRET, salt='powderchest-about-auth')


def is_about_session_valid(req):
    token = req.cookies.get(ABOUT_AUTH_COOKIE_NAME)
    if not token:
        return False

    serializer = build_about_serializer()
    try:
        payload = serializer.loads(token, max_age=ABOUT_AUTH_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return False

    return isinstance(payload, dict) and payload.get('scope') == 'about'


def clear_about_cookie(response):
    response.set_cookie(
        ABOUT_AUTH_COOKIE_NAME,
        '',
        path='/',
        httponly=True,
        secure=ABOUT_COOKIE_SECURE,
        samesite='Lax',
        expires=0
    )

@app.route('/api/visit', methods=['POST'])
def track_visit():
    """Track a visitor"""
    data = load_data()
    visitor_data = request.json
    visitor_id = visitor_data.get('visitorId')
    is_crew = visitor_data.get('isCrew', False)
    crew_name = clean_crew_name(visitor_data.get('crewName'))
    
    if not visitor_id:
        return jsonify({'error': 'No visitor ID provided'}), 400
    
    # Add or update visitor
    if visitor_id not in data['visitors']:
        data['visitors'][visitor_id] = {
            'first_visit': utc_now_iso(),
            'last_visit': utc_now_iso(),
            'visit_count': 1
        }
    else:
        data['visitors'][visitor_id]['last_visit'] = utc_now_iso()
        data['visitors'][visitor_id]['visit_count'] += 1

    if crew_name:
        data['visitors'][visitor_id]['crew_name'] = crew_name
    
    # Update crew status if applicable
    if is_crew and visitor_id not in data['crew']:
        data['crew'].add(visitor_id)
    
    save_data(data)
    
    return jsonify(get_counts(data))

@app.route('/api/join-crew', methods=['POST'])
def join_crew():
    """Mark a visitor as crew member"""
    data = load_data()
    visitor_data = request.json
    visitor_id = visitor_data.get('visitorId')
    crew_name = clean_crew_name(visitor_data.get('crewName'))
    
    if not visitor_id:
        return jsonify({'error': 'No visitor ID provided'}), 400
    
    # Ensure visitor exists
    if visitor_id not in data['visitors']:
        data['visitors'][visitor_id] = {
            'first_visit': utc_now_iso(),
            'last_visit': utc_now_iso(),
            'visit_count': 1
        }

    if crew_name:
        data['visitors'][visitor_id]['crew_name'] = crew_name
    
    # Add to crew
    data['crew'].add(visitor_id)
    
    save_data(data)
    
    return jsonify(get_counts(data))

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get current visitor statistics"""
    data = load_data()

    return jsonify(get_counts(data))


@app.route('/api/about/unlock', methods=['POST'])
def about_unlock():
    payload = request.json or {}
    pin = payload.get('pin')
    client_ip = get_client_ip(request)

    if unlock_is_limited(client_ip):
        retry_after = unlock_rate_limit_remaining(client_ip)
        return jsonify({
            'ok': False,
            'error': 'Too many attempts. Try again later.',
            'retryAfterSeconds': retry_after
        }), 429

    if not verify_about_pin(pin):
        register_unlock_failure(client_ip)
        return jsonify({'ok': False, 'error': 'Invalid PIN'}), 401

    clear_unlock_failures(client_ip)

    data = load_data()
    mark_about_access(data, 'unlock_count')
    log_about_event(data, 'unlock', request)
    save_data(data)

    serializer = build_about_serializer()
    token = serializer.dumps({'scope': 'about'})

    response = make_response(jsonify({'ok': True, 'stats': get_about_access_stats(data)}))
    response.set_cookie(
        ABOUT_AUTH_COOKIE_NAME,
        token,
        max_age=ABOUT_AUTH_MAX_AGE_SECONDS,
        path='/',
        httponly=True,
        secure=ABOUT_COOKIE_SECURE,
        samesite='Lax'
    )
    return response


@app.route('/api/about/session-check', methods=['GET'])
def about_session_check():
    if is_about_session_valid(request):
        return ('', 200)

    response = make_response('', 401)
    clear_about_cookie(response)
    return response


@app.route('/api/about/record-view', methods=['POST'])
def about_record_view():
    if not is_about_session_valid(request):
        return jsonify({'ok': False, 'error': 'Unauthorized'}), 401

    data = load_data()
    mark_about_access(data, 'view_count')
    log_about_event(data, 'view', request)
    save_data(data)
    return jsonify({'ok': True, 'stats': get_about_access_stats(data)})


@app.route('/api/about/stats', methods=['GET'])
def about_stats():
    data = load_data()
    return jsonify(get_about_access_stats(data))


@app.route('/api/about/admin-stats', methods=['GET'])
def about_admin_stats():
    if not ABOUT_ADMIN_TOKEN:
        return jsonify({'ok': False, 'error': 'Admin stats are disabled'}), 503

    provided_token = request.headers.get('X-About-Admin-Token', '').strip()
    if not secrets.compare_digest(provided_token, ABOUT_ADMIN_TOKEN):
        return jsonify({'ok': False, 'error': 'Unauthorized'}), 401

    data = load_data()
    return jsonify({
        'ok': True,
        'summary': get_about_access_stats(data),
        'recentEvents': get_recent_about_events(data, count=10)
    })

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'service': 'visitor-api'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
