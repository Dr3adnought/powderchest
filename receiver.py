from flask import Flask, request
import json
import os

app = Flask(__name__)
# Where we want to save the incoming RPi5 report
SAVE_PATH = "/home/BATFE/indomitable-rapscallion/www/status/status_applepi.json"

@app.route('/update-status', methods=['POST'])
def update_status():
    data = request.json
    if data:
        with open(SAVE_PATH, 'w') as f:
            json.dump(data, f, indent=4)
        return {"status": "success"}, 200
    return {"status": "fail"}, 400

if __name__ == '__main__':
    # Listen on all interfaces on port 5000
    app.run(host='0.0.0.0', port=5000)