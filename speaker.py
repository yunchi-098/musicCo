import json
from mitmproxy import http

TOKEN_FILE = "spotify_token.json"

def load_token():
    try:
        with open(TOKEN_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading token: {e}")
        return {}

def response(flow: http.HTTPFlow):
    if "accounts.spotify.com/api/token" in flow.request.url:
        token_data = load_token()
        
        if not token_data:
            flow.response.text = json.dumps({"error": "Token file missing or invalid"})
            return
        
        flow.response.text = json.dumps(token_data)
