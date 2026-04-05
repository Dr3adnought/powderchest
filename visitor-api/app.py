from flask import Flask, request, jsonify
from flask_cors import CORS
import json
import os
from datetime import UTC, datetime

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Data file path: use /data in containers, fallback to local visitor-api/data for local runs.
LOCAL_DATA_FILE = os.path.join(os.path.dirname(__file__), 'data', 'visitors.json')
DEFAULT_DATA_FILE = '/data/visitors.json' if os.path.isdir('/data') else LOCAL_DATA_FILE
DATA_FILE = os.environ.get('VISITOR_DATA_FILE', DEFAULT_DATA_FILE)


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

    return {'visitors': visitors, 'crew': crew}


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
        'crew': sorted(list(data['crew']))
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

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'service': 'visitor-api'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
