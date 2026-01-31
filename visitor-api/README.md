# Visitor API

Flask-based API for tracking website visitors and crew members.

## Endpoints

- `POST /api/visit` - Track a visitor
- `POST /api/join-crew` - Mark visitor as crew member
- `GET /api/stats` - Get visitor statistics
- `GET /health` - Health check

## Running Locally

```bash
cd visitor-api
pip install -r requirements.txt
python app.py
```

## Running with Docker

```bash
docker build -t visitor-api .
docker run -p 5000:5000 -v $(pwd)/data:/data visitor-api
```

## Data Storage

Visitor data is stored in `/data/visitors.json` with the following structure:

```json
{
  "visitors": {
    "visitor_id": {
      "first_visit": "2026-01-30T12:00:00",
      "last_visit": "2026-01-30T15:30:00",
      "visit_count": 5
    }
  },
  "crew": ["visitor_id_1", "visitor_id_2"]
}
```
