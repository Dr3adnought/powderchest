from flask import Flask, request, jsonify
from flask_cors import CORS
import json
import os
from datetime import datetime

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Data file path
DATA_FILE = '/data/visitors.json'

def load_data():
    """Load visitor data from JSON file"""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {'visitors': {}, 'crew': set()}
    return {'visitors': {}, 'crew': set()}

def save_data(data):
    """Save visitor data to JSON file"""
    # Convert set to list for JSON serialization
    data_to_save = {
        'visitors': data['visitors'],
        'crew': list(data['crew'])
    }
    
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, 'w') as f:
        json.dump(data_to_save, f, indent=2)

def get_counts(data):
    """Calculate visitor counts"""
    total = len(data['visitors'])
    crew = len(data['crew'])
    wanderers = total - crew
    
    return {
        'total': total,
        'crew': crew,
        'wanderers': wanderers
    }

@app.route('/api/visit', methods=['POST'])
def track_visit():
    """Track a visitor"""
    data = load_data()
    visitor_data = request.json
    visitor_id = visitor_data.get('visitorId')
    is_crew = visitor_data.get('isCrew', False)
    
    if not visitor_id:
        return jsonify({'error': 'No visitor ID provided'}), 400
    
    # Convert crew from list to set if needed
    if isinstance(data.get('crew'), list):
        data['crew'] = set(data['crew'])
    
    # Add or update visitor
    if visitor_id not in data['visitors']:
        data['visitors'][visitor_id] = {
            'first_visit': datetime.now().isoformat(),
            'last_visit': datetime.now().isoformat(),
            'visit_count': 1
        }
    else:
        data['visitors'][visitor_id]['last_visit'] = datetime.now().isoformat()
        data['visitors'][visitor_id]['visit_count'] += 1
    
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
    
    if not visitor_id:
        return jsonify({'error': 'No visitor ID provided'}), 400
    
    # Convert crew from list to set if needed
    if isinstance(data.get('crew'), list):
        data['crew'] = set(data['crew'])
    
    # Ensure visitor exists
    if visitor_id not in data['visitors']:
        data['visitors'][visitor_id] = {
            'first_visit': datetime.now().isoformat(),
            'last_visit': datetime.now().isoformat(),
            'visit_count': 1
        }
    
    # Add to crew
    data['crew'].add(visitor_id)
    
    save_data(data)
    
    return jsonify(get_counts(data))

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get current visitor statistics"""
    data = load_data()
    
    # Convert crew from list to set if needed
    if isinstance(data.get('crew'), list):
        data['crew'] = set(data['crew'])
    
    return jsonify(get_counts(data))

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'service': 'visitor-api'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
