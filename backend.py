from flask import Flask, jsonify, request
from flask_cors import CORS
import fpl_logic
import json

# 1. Initialize the Flask App
app = Flask(__name__)

# 2. Enable Cross-Origin Resource Sharing (CORS)
# This allows a React app (on a different 'origin') to make requests to this backend.
CORS(app)

# --- In-memory cache for bootstrap data ---
# This avoids re-fetching this large dataset on every single API call.
BOOTSTRAP_DATA = None

def get_bootstrap():
    """Helper to get bootstrap data, caching it in memory after the first call."""
    global BOOTSTRAP_DATA
    if BOOTSTRAP_DATA is None:
        print("Fetching and caching bootstrap data for the session...")
        BOOTSTRAP_DATA = fpl_logic.get_bootstrap_data()
    return BOOTSTRAP_DATA


# --- API Endpoints ---

@app.route("/api/login", methods=['POST'])
def login():
    """
    Handles user login. Validates team_id and saves config.
    Expects a JSON body with 'team_id' and 'league_id'.
    """
    data = request.get_json()
    team_id = data.get('team_id')
    league_id = data.get('league_id')

    if not team_id or not league_id:
        return jsonify({"error": "team_id and league_id are required"}), 400

    try:
        entry_data = fpl_logic.get_entry_data(team_id)
        if not entry_data or 'player_first_name' not in entry_data:
            return jsonify({"error": "Invalid Team ID or FPL API is down."}), 404
        
        user_name = f"{entry_data['player_first_name']} {entry_data['player_last_name']}"

        # Save the valid config
        config = {'team_id': team_id, 'league_id': league_id}
        with open('config.json', 'w') as f:
            json.dump(config, f, indent=4)

        return jsonify({
            "message": f"Welcome, {user_name}!",
            "team_id": team_id,
            "league_id": league_id,
            "user_name": user_name
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/features/injury-risk", methods=['GET'])
def get_injury_risk():
    """Endpoint for the Injury/Risk Analyzer feature."""
    try:
        bootstrap_data = get_bootstrap()
        team_map = fpl_logic.create_team_map(bootstrap_data)
        
        # We need to convert the string output to structured data (a dictionary)
        # For now, we'll just return the string, but ideally, the logic function would be refactored.
        result_string = fpl_logic.get_injury_risk_analyzer_string(bootstrap_data, team_map)
        
        # A better approach is to refactor get_injury_risk_analyzer_string to return a dict/list
        # But for now, we can wrap the string in a JSON object.
        return jsonify({"type": "string", "data": result_string})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# --- Main execution ---

if __name__ == "__main__":
    print("Starting FPL Toolkit Backend Server...")
    # The host='0.0.0.0' makes the server accessible on your local network
    app.run(host='0.0.0.0', port=5000, debug=True)