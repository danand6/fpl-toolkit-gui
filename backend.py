from flask import Flask, jsonify, request
from flask_cors import CORS
import fpl_logic
import json
import os
import requests
import rag_engine
import re
import textwrap
from intent_classifier import get_intent_classifier

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')

_AI_PREDICTION_CACHE = None

# 1. Initialize the Flask App
app = Flask(__name__)

# 2. Enable Cross-Origin Resource Sharing (CORS)
# This allows a React app (on a different 'origin') to make requests to this backend.
CORS(app)

CONFIG_FILE = "config.json"

# --- In-memory cache for expensive data pulls ---
# These avoid re-fetching large datasets on every single API call.
BOOTSTRAP_DATA = None
FIXTURES_DATA = None


def get_bootstrap():
    """Helper to get bootstrap data, caching it in memory after the first call."""
    global BOOTSTRAP_DATA
    if BOOTSTRAP_DATA is None:
        print("Fetching and caching bootstrap data for the session...")
        BOOTSTRAP_DATA = fpl_logic.get_bootstrap_data()
    return BOOTSTRAP_DATA


def get_fixtures():
    """Helper to get fixtures data, caching it in memory after the first call."""
    global FIXTURES_DATA
    if FIXTURES_DATA is None:
        print("Fetching and caching fixtures data for the session...")
        FIXTURES_DATA = fpl_logic.get_fixtures_data()
    return FIXTURES_DATA


def load_saved_config() -> dict:
    """Loads the saved config file, raising an error if it doesn't exist yet."""
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError("Config not found. Please log in first.")

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    if "team_id" not in data or "league_id" not in data:
        raise ValueError("Config file is missing required fields.")

    return data


def resolve_team_id() -> int:
    """Gets team_id from request args or falls back to config."""
    team_id_arg = request.args.get("team_id", type=int)
    if team_id_arg is not None:
        return team_id_arg
    try:
        config = load_saved_config()
    except FileNotFoundError as exc:
        raise ValueError("No saved team ID available. Please log in first.") from exc
    return int(config.get("team_id"))


def resolve_league_id() -> int:
    """Gets league_id from request args or falls back to config."""
    league_id_arg = request.args.get("league_id", type=int)
    if league_id_arg is not None:
        return league_id_arg
    try:
        config = load_saved_config()
    except FileNotFoundError as exc:
        raise ValueError("No saved league ID available. Please log in first.") from exc
    return int(config.get("league_id"))


def wrap_result(result):
    """Normalise logic return values into JSON-serialisable structures."""
    if isinstance(result, dict):
        return result
    return {"type": "text", "data": str(result)}


def build_context():
    """Prepares commonly used derived data for feature endpoints."""
    bootstrap_data = get_bootstrap()
    fixtures_data = get_fixtures()

    current_gameweek = fpl_logic.get_current_gameweek(bootstrap_data)
    if not current_gameweek:
        raise ValueError("Unable to determine the current gameweek from bootstrap data.")

    return {
        "bootstrap": bootstrap_data,
        "fixtures": fixtures_data,
        "player_map": fpl_logic.create_player_map(bootstrap_data),
        "team_map": fpl_logic.create_team_map(bootstrap_data),
        "position_map": fpl_logic.create_position_map(bootstrap_data),
        "player_lookup": {player['id']: player for player in bootstrap_data['elements']},
        "current_gameweek": current_gameweek,
    }


def process_feature(builder):
    """Runs a feature callable and turns the result into a JSON response."""
    try:
        result = builder()
        return jsonify(wrap_result(result))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _group_players_by_position(players):
    grouped = {"GKP": [], "DEF": [], "MID": [], "FWD": []}
    for player in players:
        key = player.get("position", "")
        if key in grouped:
            grouped[key].append(player)
    return grouped


def _compute_formation_string(starters):
    grouped = _group_players_by_position(starters)
    defence = len(grouped["DEF"])
    midfield = len(grouped["MID"])
    attack = len(grouped["FWD"])
    return f"{defence}-{midfield}-{attack}"


def _build_team_payload(title, starters, bench, metadata=None, raw=None):
    metadata = metadata or {}
    formation = _compute_formation_string(starters) if starters else ""
    return {
        "type": "team",
        "title": title,
        "formation": formation,
        "starters": starters,
        "bench": bench,
        "metadata": metadata,
        "raw": raw,
    }


def _fetch_or_train_ai_model(context):
    global _AI_PREDICTION_CACHE
    if _AI_PREDICTION_CACHE is not None:
        return _AI_PREDICTION_CACHE

    try:
        bundle = rag_engine.compute_ai_predictions(context)
        _AI_PREDICTION_CACHE = bundle
        return bundle
    except RuntimeError as exc:
        raise RuntimeError(str(exc))


def _execute_feature(feature_id, context, *, sort=None, extra=None):
    if feature_id == 'my-team-summary':
        team_id = resolve_team_id()
        raw_result = fpl_logic.get_my_team_summary_string(
            team_id,
            context["current_gameweek"],
            context["player_map"],
        )
        return _build_my_team_payload(team_id, context, raw_result)

    if feature_id == 'smart-captaincy':
        team_id = resolve_team_id()
        result_text = fpl_logic.get_captaincy_suggester_string(
            team_id,
            context["current_gameweek"],
            context["bootstrap"],
            context["fixtures"],
        )
        return _build_captaincy_payload(result_text, context["current_gameweek"])

    if feature_id == 'current-captain':
        team_id = resolve_team_id()
        picks = fpl_logic.get_team_picks(team_id, context['current_gameweek'])
        player_lookup = context['player_lookup']
        team_map = context['team_map']
        captain_pick = next((pick for pick in picks['picks'] if pick.get('is_captain')), None)
        vice_pick = next((pick for pick in picks['picks'] if pick.get('is_vice_captain')), None)

        def describe(pick):
            if not pick:
                return "Unknown"
            data = player_lookup.get(pick['element'], {})
            name = data.get('web_name', 'Unknown')
            team = team_map.get(data.get('team'), 'N/A')
            return f"{name} ({team})"

        rows = []
        rows.append(["Captain", describe(captain_pick)])
        rows.append(["Vice", describe(vice_pick)])

        return {
            'type': 'table',
            'title': f"Current captaincy (GW {context['current_gameweek']})",
            'headers': ['Role', 'Player'],
            'rows': rows,
            'metadata': {
                'gameweek': context['current_gameweek']
            }
        }

    if feature_id == 'transfer-suggester':
        team_id = resolve_team_id()
        result_text = fpl_logic.get_transfer_suggester_string(
            team_id,
            context["current_gameweek"],
            context["bootstrap"],
            context["fixtures"],
            context["team_map"],
            context["position_map"],
        )
        return _build_transfer_payload(result_text, context["current_gameweek"])

    if feature_id == 'league-current':
        league_id = resolve_league_id()
        league_data = fpl_logic.get_league_data(league_id)
        standings = league_data.get('standings', {}).get('results', [])

        table_rows = []
        for entry in standings[:50]:
            table_rows.append([
                str(entry.get('rank', '')),
                entry.get('player_name', ''),
                entry.get('entry_name', ''),
                str(entry.get('total', '')),
            ])

        return {
            'type': 'table',
            'title': league_data.get('league', {}).get('name', 'League standings'),
            'headers': ['Rank', 'Manager', 'Team', 'Total Points'],
            'rows': table_rows,
            'metadata': {
                'gameweek': context['current_gameweek'],
            }
        }

    if feature_id == 'league-predictions':
        league_id = resolve_league_id()
        result_text = fpl_logic.get_league_predictions_string(
            league_id,
            context["current_gameweek"],
            context["bootstrap"],
            context["fixtures"],
        )
        return _build_league_payload(result_text, context["current_gameweek"])

    if feature_id == 'league-head-to-head':
        league_id = resolve_league_id()
        result_text = fpl_logic.get_league_predictions_string(
            league_id,
            context["current_gameweek"],
            context["bootstrap"],
            context["fixtures"],
        )
        parsed = rag_engine.parse_league_predictions(result_text)
        results = parsed.get('results', [])
        league_data = fpl_logic.get_league_data(league_id)
        standings_raw = league_data.get('standings', {}).get('results', [])

        opponent_name = None
        if isinstance(extra, dict):
            opponent_name = extra.get('opponent')
        elif isinstance(sort, str):
            opponent_name = sort

        try:
            entry = fpl_logic.get_entry_data(resolve_team_id())
            user_name = f"{entry.get('player_first_name', '').strip()} {entry.get('player_last_name', '').strip()}".strip()
            user_entry_id = entry.get('entry') or entry.get('id')
        except Exception:
            user_name = None
            user_entry_id = None

        target_result = None
        user_result = None
        opponent_entry_id = None

        for record in results:
            manager_lower = record['manager'].lower()
            if opponent_name and opponent_name.lower() in manager_lower:
                target_result = record
            if user_name and user_name.lower() in manager_lower:
                user_result = record

        def lookup_entry_id(manager_name: str | None) -> int | None:
            if not manager_name:
                return None
            lower = manager_name.lower()
            for item in standings_raw:
                if item.get('player_name', '').lower() == lower:
                    return item.get('entry')
            return None

        if target_result:
            opponent_entry_id = lookup_entry_id(target_result['manager'])
        if user_entry_id is None:
            user_entry_id = lookup_entry_id(user_name)

        note = None
        if target_result and user_result:
            diff = user_result['predicted_score'] - target_result['predicted_score']
            outcome = 'beat' if diff > 0 else 'lose to' if diff < 0 else 'draw with'
            note = (
                f"Projected to {outcome} {target_result['manager']} by {abs(diff):.2f} points "
                f"(you: {user_result['predicted_score']:.2f}, opponent: {target_result['predicted_score']:.2f})."
            )
        elif user_result:
            note = (
                f"You are projected {user_result['predicted_score']:.2f} points. "
                "I couldn't find that opponent in the league standings."
            )
        elif results:
            leader = results[0]
            note = f"Projected leader: {leader['manager']} with {leader['predicted_score']:.2f} points."

        explanation = None
        if extra.get('explain') and target_result and user_result and opponent_entry_id and user_entry_id:
            try:
                ai_bundle = _fetch_or_train_ai_model(context)
                user_proj = rag_engine.compute_team_projection(context, user_entry_id, ai_bundle)
                opp_proj = rag_engine.compute_team_projection(context, opponent_entry_id, ai_bundle)
            except Exception:
                ai_bundle = None
                user_proj = None
                opp_proj = None

            if ai_bundle and user_proj and opp_proj:
                diff = opp_proj['predicted_total'] - user_proj['predicted_total']
                if diff > 0:
                    edge_line = f"{target_result['manager']} is projected {diff:.2f} points ahead."
                elif diff < 0:
                    edge_line = f"You project {abs(diff):.2f} points ahead on squad total." 
                else:
                    edge_line = "Both squads project the same total."

                your_core = ", ".join(
                    f"{p['name']} ({p['predicted']:.1f})" for p in sorted(user_proj['starters'], key=lambda p: p['predicted'], reverse=True)[:3]
                )
                rival_core = ", ".join(
                    f"{p['name']} ({p['predicted']:.1f})" for p in sorted(opp_proj['starters'], key=lambda p: p['predicted'], reverse=True)[:3]
                )

                explanation = (
                    f"{edge_line} Your top projected players: {your_core}. "
                    f"{target_result['manager']}'s key players: {rival_core}."
                )

        table_rows = [
            [str(record['rank']), record['manager'], f"{record['predicted_score']:.2f}"]
            for record in results[:20]
        ]

        series = [
            {'label': f"{record['rank']}. {record['manager']}", 'value': record['predicted_score']}
            for record in results[:10]
        ]

        return {
            'type': 'table',
            'title': parsed.get('league_name', 'League Predictions'),
            'headers': ['Rank', 'Manager', 'Predicted Score'],
            'rows': table_rows,
            'chartSeries': series,
            'chartLabel': 'Predicted Score',
            'metadata': {
                'gameweek': context['current_gameweek'],
                'league_name': parsed.get('league_name'),
                'note': note,
                'explanation': explanation,
            },
        }

    if feature_id == 'chip-advice':
        team_id = resolve_team_id()
        return fpl_logic.get_chip_advice_string(
            team_id,
            context['current_gameweek'],
            context['bootstrap'],
            context['fixtures'],
            context['team_map'],
            context['position_map']
        )

    if feature_id == 'injury-risk':
        result_text = fpl_logic.get_injury_risk_analyzer_string(
            context["bootstrap"],
            context["team_map"],
        )
        return _build_injury_payload(result_text)

    if feature_id == 'differential-hunter':
        sort_key = sort or 'form'
        return fpl_logic.get_differential_hunter_data(
            context["bootstrap"],
            context["team_map"],
            context["position_map"],
            sort_key,
        )

    if feature_id == 'predicted-top-performers':
        return fpl_logic.get_predicted_points_data(
            context["bootstrap"],
            context["fixtures"],
            context["current_gameweek"],
        )

    if feature_id == 'dream-team':
        result_text = fpl_logic.get_dream_team_optimizer_string(
            context["bootstrap"],
            context["fixtures"],
            context["current_gameweek"],
            context["position_map"],
        )
        return _build_dream_team_payload(result_text, context)

    if feature_id == 'ai-predictions':
        ai_bundle = _fetch_or_train_ai_model(context)
        table_rows = []
        series = []
        team_map = context["team_map"]
        position_map = context["position_map"]

        for item in ai_bundle['predictions']:
            table_rows.append([
                item['name'],
                item['team'],
                item['position'],
                f"{item['predicted']:.2f}",
                f"{item['avg_points']:.2f}",
                item['form'],
            ])
            series.append({
                'label': f"{item['name']} ({item['team']})",
                'value': item['predicted'],
            })

        return {
            "type": "table",
            "title": "AI Predicted Top Performers",
            "headers": [
                "Player",
                "Team",
                "Position",
                "Predicted Points (AI)",
                "Avg Points (Last 5)",
                "Form"
            ],
            "rows": table_rows,
            "chartSeries": series,
            "chartLabel": "Predicted Points (AI)",
            "metadata": {
                "model": ai_bundle['model'].get('name', 'LinearRegressor'),
                "history_window": ai_bundle['history_window'],
                "trained_samples": ai_bundle['trained_samples'],
            },
        }

    if feature_id == 'ai-team-performance':
        team_id = resolve_team_id()
        try:
            ai_bundle = _fetch_or_train_ai_model(context)
        except RuntimeError as exc:
            return {
                'type': 'text',
                'data': f"AI predictions are temporarily unavailable: {exc}",
            }

        projection = rag_engine.compute_team_projection(context, team_id, ai_bundle)
        if not projection:
            return {
                'type': 'text',
                'data': "I couldn't compute a squad projection right now. Try again later.",
            }

        table_rows = []
        series = []

        for detail in projection['starters']:
            note = 'Captain' if detail['is_captain'] else 'Vice' if detail['is_vice'] else ''
            table_rows.append([
                detail['name'],
                detail['team'],
                detail['position'],
                f"{detail['predicted']:.2f}",
                note or '-'
            ])
            series.append({
                'label': f"{detail['name']} ({detail['team']})",
                'value': detail['predicted'],
            })

        bench_summary = ", ".join(
            f"{detail['name']} {detail['predicted']:.2f}"
            for detail in projection['bench']
        )

        metadata = {
            'gameweek': projection['gameweek'],
            'predicted_total': projection['predicted_total'],
        }
        if bench_summary:
            metadata['note'] = f"Bench: {bench_summary}"

        return {
            'type': 'table',
            'title': f"Predicted squad output (GW {projection['gameweek']})",
            'headers': ['Player', 'Team', 'Position', 'Predicted Points', 'Role'],
            'rows': table_rows,
            'chartSeries': series,
            'chartLabel': 'Predicted Points',
            'metadata': metadata,
        }

    if feature_id == 'quadrant-analysis':
        return fpl_logic.get_quadrant_analysis_string(
            context["bootstrap"],
            context["fixtures"],
            context["current_gameweek"],
            context["team_map"],
        )

    raise ValueError(f"Unsupported feature id: {feature_id}")


CHAT_SUGGESTIONS = [
    {"id": "my-team-summary", "label": "Show my team summary"},
    {"id": "smart-captaincy", "label": "Who should I captain?"},
    {"id": "current-captain", "label": "Who is my captain right now?"},
    {"id": "transfer-suggester", "label": "Suggest a transfer"},
    {"id": "injury-risk", "label": "Any injury risks?"},
    {"id": "ai-predictions", "label": "AI top performers"},
    {"id": "ai-team-performance", "label": "How will my squad perform next week?"},
    {"id": "chip-advice", "label": "Chip strategy advice"},
    {"id": "league-current", "label": "Show current league table"},
    {"id": "league-predictions", "label": "Predict my league"},
    {"id": "league-head-to-head", "label": "Will I beat my rival?"},
]


def _detect_intent(message: str):
    text = message.lower()

    if (('squad' in text or 'team' in text) and
            any(keyword in text for keyword in ('perform', 'points', 'score')) and
            any(keyword in text for keyword in ('next', 'upcoming', 'gw', 'gameweek'))):
        return 'ai-team-performance', {}

    if any(keyword in text for keyword in ("my team", "lineup", "squad", "formation", "starting")):
        return 'my-team-summary', {}
    if 'captain' in text or 'cpt' in text:
        return 'smart-captaincy', {}
    if any(keyword in text for keyword in ('chip', 'bench boost', 'triple captain', 'free hit', 'wildcard')):
        return 'chip-advice', {}
    if 'transfer' in text or 'upgrade' in text or 'sell' in text:
        return 'transfer-suggester', {}
    if 'injury' in text or 'risk' in text or 'flagged' in text:
        return 'injury-risk', {}
    if 'league' in text and any(word in text for word in ('current', 'now', 'latest', 'today')):
        return 'league-current', {}
    if 'league' in text and ('predict' in text or 'standings' in text or 'rank' in text):
        return 'league-predictions', {}
    if any(keyword in text for keyword in ('beat', 'versus', 'vs', 'head to head', 'h2h')):
        match = re.search(r"(?:beat|versus|vs|head to head with|h2h with|h2h against|h2h)\s+([\w'\s]+)", message, re.IGNORECASE)
        if match:
            opponent = match.group(1).strip().strip("?.!,'\"")
            opponent = re.sub(r"\b(next|this) week\b", '', opponent, flags=re.IGNORECASE).strip()
            if opponent:
                return 'league-head-to-head', {'opponent': opponent}
    if 'differential' in text or 'under owned' in text:
        sort_key = 'form'
        if 'ict' in text:
            sort_key = 'ict_index'
        elif 'points' in text:
            sort_key = 'total_points'
        return 'differential-hunter', {'sort': sort_key}
    if 'ai' in text or 'machine' in text or 'smart' in text:
        return 'ai-predictions', {}
    if 'predict' in text and 'top' in text:
        return 'predicted-top-performers', {}
    if 'dream team' in text or 'wildcard' in text:
        return 'dream-team', {}
    if 'quadrant' in text or ('form' in text and 'fixture' in text):
        return 'quadrant-analysis', {}

    classifier = get_intent_classifier()
    result = classifier.classify(message)
    if result.intent:
        extras = {}
        if result.intent == 'league-head-to-head':
            match = re.search(r"(?:beat|versus|vs|head to head with|h2h with|h2h against|h2h|against)\s+([\w'\s]+)", message, re.IGNORECASE)
            if match:
                opponent = match.group(1).strip().strip("?.!,'\"")
                opponent = re.sub(r"\b(next|this) week\b", '', opponent, flags=re.IGNORECASE).strip()
                if opponent:
                    extras['opponent'] = opponent
        return result.intent, extras

    return None, {}


FEATURE_INTENT_RESPONSES = {
    'my-team-summary': "Here is your squad layout.",
    'smart-captaincy': "Based on the data, these look like strong captain options.",
    'current-captain': "This is your current captain set for the live gameweek.",
    'transfer-suggester': "Here is a data-driven transfer suggestion.",
    'injury-risk': "These players carry the highest risk right now.",
    'chip-advice': "Here's how I'd use your chips based on the data.",
    'league-current': "Here is the current league table.",
    'league-predictions': "Here is how your league might shake out.",
    'league-head-to-head': "Here is how the projections look for your league battle.",
    'differential-hunter': "Here are some low-owned players worth a look.",
    'predicted-top-performers': "Projected top performers for the next gameweek.",
    'dream-team': "Here's a wildcard-friendly dream team.",
    'ai-predictions': "AI-driven predictions for upcoming standouts.",
    'ai-team-performance': "Here's how your squad is forecast to perform next week.",
    'quadrant-analysis': "Form vs. fixtures quadrant overview.",
}


@app.route("/api/chat", methods=['POST'])
def chat():
    data = request.get_json(silent=True) or {}
    message = (data.get('message') or '').strip()

    if not message:
        return jsonify({
            "type": "chat",
            "reply": "I didn't catch that. Ask me about your team, transfers, or injuries.",
            "suggestions": CHAT_SUGGESTIONS,
        }), 400

    lower = message.lower()
    if any(greet in lower for greet in ("hi", "hello", "hey", "yo")) and len(lower.split()) <= 3:
        return jsonify({
            "type": "chat",
            "reply": "Hey! I can analyse your team, suggest captains, highlight injuries, and more. Try a suggestion below.",
            "suggestions": CHAT_SUGGESTIONS,
        })

    try:
        context = build_context()
    except ValueError as exc:
        message_text = str(exc)
        if 'No saved team ID' in message_text or 'No saved league ID' in message_text:
            message_text = "I need your team and league IDs first. Please log in from the settings screen."
        return jsonify({
            "type": "chat",
            "reply": message_text,
            "suggestions": CHAT_SUGGESTIONS,
        }), 400
    except requests.exceptions.RequestException as exc:
        return jsonify({
            "type": "chat",
            "reply": f"I couldn't reach the FPL API: {exc}",
            "suggestions": CHAT_SUGGESTIONS,
        }), 502

    try:
        team_id = resolve_team_id()
    except ValueError:
        team_id = None

    try:
        league_id = resolve_league_id()
    except ValueError:
        league_id = None

    feature_id, extra = _detect_intent(message)

    if feature_id:
        extra = extra or {}
        try:
            feature_payload = _execute_feature(feature_id, context, sort=extra.get('sort'), extra=extra)
            wrapped = wrap_result(feature_payload)

            reply_text = FEATURE_INTENT_RESPONSES.get(
                feature_id, "Here are the insights you asked for."
            )

            return jsonify({
                "type": "chat",
                "reply": reply_text,
                "featureId": feature_id,
                "feature": wrapped,
                "suggestions": CHAT_SUGGESTIONS,
            })

        except ValueError as exc:
            message_text = str(exc)
            if 'No saved team ID' in message_text or 'No saved league ID' in message_text:
                message_text = "I need your team and league IDs first. Please log in from the settings screen."
            return jsonify({
                "type": "chat",
                "reply": message_text,
                "suggestions": CHAT_SUGGESTIONS,
            }), 400
        except RuntimeError as exc:
            return jsonify({
                "type": "chat",
                "reply": str(exc),
                "suggestions": CHAT_SUGGESTIONS,
            }), 500
        except requests.exceptions.RequestException as exc:
            return jsonify({
                "type": "chat",
                "reply": f"I couldn't reach the FPL API: {exc}",
                "suggestions": CHAT_SUGGESTIONS,
            }), 502

    # RAG fallback
    try:
        kb = rag_engine.build_knowledge_base(context, team_id=team_id, league_id=league_id)
        docs = rag_engine.retrieve(message, kb)
        rag_answer = rag_engine.generate_answer(message, docs)

        llm_reply = _maybe_generate_llm_reply(message, rag_answer['text'], docs)

        wrapped = wrap_result({
            "type": "text",
            "data": llm_reply or rag_answer['text'],
            "metadata": {"citations": rag_answer['citations']},
        })

        return jsonify({
            "type": "chat",
            "reply": llm_reply or "Here is what I found in your FPL knowledge base.",
            "feature": wrapped,
            "suggestions": CHAT_SUGGESTIONS,
        })
    except RuntimeError as exc:
        return jsonify({
            "type": "chat",
            "reply": str(exc),
            "suggestions": CHAT_SUGGESTIONS,
        })

    return jsonify({
        "type": "chat",
        "reply": "I'm not sure what you meant. You can ask me to show your team, suggest transfers, or check injuries.",
        "suggestions": CHAT_SUGGESTIONS,
    })


def _maybe_generate_llm_reply(query: str, fallback_text: str, docs) -> str | None:
    if not OPENAI_API_KEY:
        return None

    context_snippets = []
    for doc in docs[:4]:
        snippet = textwrap.shorten(doc.text, width=600, placeholder='…')
        context_snippets.append(f"{doc.title}: {snippet}")
    context_blob = "\n".join(context_snippets) or fallback_text

    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an FPL assistant. Ground every answer in the provided context. "
                    "If projections are available, mention totals and key players."
                )
            },
            {
                "role": "user",
                "content": (
                    f"Question: {query}\n\nContext:\n{context_blob}\n\n"
                    "Respond in under 6 sentences."
                )
            }
        ],
        "max_tokens": 280,
    }

    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=12,
        )
        response.raise_for_status()
        data = response.json()
        return data['choices'][0]['message']['content'].strip()
    except Exception:
        return None


def _build_my_team_payload(team_id, context, raw_summary):
    current_gameweek = context["current_gameweek"]
    picks = fpl_logic.get_team_picks(team_id, current_gameweek)
    live_data = fpl_logic.get_live_data(current_gameweek)
    live_points_map = {p['id']: p['stats']['total_points'] for p in live_data['elements']}

    player_lookup = context["player_lookup"]
    position_map = context["position_map"]
    team_map = context["team_map"]

    starters, bench = [], []
    total_points = 0

    for pick in picks['picks']:
        player_id = pick['element']
        player_data = player_lookup.get(player_id, {})
        position_id = player_data.get('element_type')
        position = position_map.get(position_id, 'UNK')
        points = live_points_map.get(player_id, 0) * pick['multiplier']
        total_points += points

        player_entry = {
            "id": player_id,
            "name": player_data.get('web_name', "Unknown"),
            "position": position,
            "club": team_map.get(player_data.get('team'), ''),
            "value": points,
            "is_captain": bool(pick.get('is_captain')),
            "is_vice": bool(pick.get('is_vice_captain')),
            "multiplier": pick.get('multiplier', 1),
        }

        if pick.get('multiplier', 0) > 0:
            player_entry['role'] = 'starter'
            starters.append(player_entry)
        else:
            player_entry['role'] = 'bench'
            bench.append(player_entry)

    metadata = {
        "current_gameweek": current_gameweek,
        "total_points": total_points,
        "total_players": len(starters) + len(bench),
    }

    title = f"Your FPL Team Summary for Gameweek {current_gameweek}"
    return _build_team_payload(title, starters, bench, metadata=metadata, raw=raw_summary)


def _compute_best_starting_eleven(players):
    group = _group_players_by_position(players)

    formations = [
        (3, 4, 3),
        (3, 5, 2),
        (4, 4, 2),
        (4, 3, 3),
        (4, 5, 1),
        (5, 3, 2),
        (5, 4, 1),
    ]

    best_score = -1
    best_selection = None
    best_formation = None

    keepers = sorted(group.get("GKP", []), key=lambda p: p.get('value', 0), reverse=True)
    if not keepers:
        fallback = [dict(player, role='starter') for player in players]
        return fallback, [], ""

    for defence, midfield, attack in formations:
        if len(group["DEF"]) < defence or len(group["MID"]) < midfield or len(group["FWD"]) < attack:
            continue

        selection = [keepers[0]]
        selection += sorted(group["DEF"], key=lambda p: p.get('value', 0), reverse=True)[:defence]
        selection += sorted(group["MID"], key=lambda p: p.get('value', 0), reverse=True)[:midfield]
        selection += sorted(group["FWD"], key=lambda p: p.get('value', 0), reverse=True)[:attack]

        score = sum(player.get('value', 0) for player in selection)
        if score > best_score:
            best_score = score
            best_selection = selection
            best_formation = f"{defence}-{midfield}-{attack}"

    if not best_selection:
        fallback = [dict(player, role='starter') for player in players]
        return fallback, [], ""

    starter_ids = {player['id'] for player in best_selection}
    starters, bench = [], []
    for player in players:
        entry = dict(player)
        if player['id'] in starter_ids:
            entry['role'] = 'starter'
            starters.append(entry)
        else:
            entry['role'] = 'bench'
            bench.append(entry)

    return starters, bench, best_formation


def _build_dream_team_payload(result_text: str, context: dict) -> dict | str:
    player_lookup = context["player_lookup"]
    team_map = context["team_map"]

    lines = [line.strip() for line in result_text.splitlines() if line.strip()]
    try:
        start_index = lines.index('--- Optimized Dream Team ---') + 1
    except ValueError:
        start_index = 0

    players = []
    total_predicted = None

    for line in lines[start_index:]:
        if line.startswith('-') or line.lower().startswith('total predicted score'):
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            pos = parts[-4]
            pred_part = parts[-1]
            if not pred_part.endswith(')'):
                continue
            pred_value = pred_part.replace(')', '').replace('Pred:', '').strip()
            predicted = float(pred_value)
        except (ValueError, IndexError):
            continue

        price = parts[-3]
        name = " ".join(parts[:-4]).strip()

        lookup = None
        for player in player_lookup.values():
            if player.get('web_name') == name:
                lookup = player
                break
        if not lookup:
            continue

        players.append({
            "id": lookup['id'],
            "name": name,
            "position": pos,
            "club": team_map.get(lookup.get('team'), ''),
            "value": predicted,
            "price": price,
        })

    for line in lines:
        if line.lower().startswith('total predicted score'):
            try:
                total_predicted = float(line.split(':', 1)[1].strip().lstrip('£'))
            except (ValueError, IndexError):
                total_predicted = None
            break

    starters, bench, formation = _compute_best_starting_eleven(players)
    metadata = {
        "total_players": len(players),
        "formation": formation,
    }
    if total_predicted is not None:
        metadata['total_predicted_score'] = total_predicted

    title = "Optimized Dream Team"
    payload = _build_team_payload(title, starters, bench, metadata=metadata, raw=result_text)
    if formation:
        payload['formation'] = formation
    return payload


def _build_captaincy_payload(result_text: str, gameweek: int) -> dict | str:
    lines = [line.rstrip() for line in result_text.splitlines() if line.strip()]
    if not lines:
        return result_text

    title = lines[0]
    start_index = None
    for idx, line in enumerate(lines):
        lower_line = line.lower()
        if lower_line.startswith('player') and 'predicted' in lower_line:
            start_index = idx + 2
            break

    if start_index is None:
        return result_text

    rows = []
    series = []
    recommendation = None

    for line in lines[start_index:]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith('---'):
            break
        if stripped.lower().startswith('recommendation:'):
            recommendation = stripped.split(':', 1)[1].strip()
            continue

        annotation = ''
        if '<--' in stripped:
            stripped, annotation = [part.strip() for part in stripped.split('<--', 1)]

        parts = stripped.split()
        if len(parts) < 2:
            continue

        try:
            score = float(parts[-1])
        except ValueError:
            continue

        name = " ".join(parts[:-1]).strip()
        if not name:
            continue

        role = '-'
        annotation_lower = annotation.lower()
        if 'captain pick' in annotation_lower or '🥇' in annotation:
            role = 'Captain'
        elif 'vice-captain' in annotation_lower or '🥈' in annotation:
            role = 'Vice-Captain'

        rows.append([name, role, f"{score:.2f}"])
        label = f"{name}{' (' + role + ')' if role != '-' else ''}"
        series.append({"label": label, "value": score})

    if not rows:
        return result_text

    metadata = {"gameweek": gameweek}
    if recommendation:
        metadata['recommendation'] = recommendation

    return {
        "type": "table",
        "title": title,
        "headers": ["Player", "Role", "Predicted Score"],
        "rows": rows,
        "chartSeries": series,
        "chartLabel": "Predicted Score",
        "metadata": metadata,
        "raw": result_text,
    }


def _build_transfer_payload(result_text: str, gameweek: int) -> dict | str:
    lines = [line.rstrip() for line in result_text.splitlines() if line.strip()]
    if not lines:
        return result_text

    sections = {}
    current = None
    recommendation = None

    for line in lines:
        stripped = line.strip()
        upper = stripped.upper()
        if 'TRANSFER OUT' in upper:
            current = sections.setdefault('out', {"role": "Out"})
            continue
        if 'TRANSFER IN' in upper:
            current = sections.setdefault('in', {"role": "In"})
            continue

        if stripped.startswith('Recommendation:'):
            recommendation = stripped.split(':', 1)[1].strip()
            continue

        if not current or not stripped.startswith('-') or ':' not in stripped:
            continue

        key, value = stripped[1:].split(':', 1)
        key = key.strip().lower()
        value = value.strip()

        if key.startswith('name'):
            match = re.match(r"^(?P<name>.+?)\s*\((?P<club>[^)]+)\)", value)
            if match:
                current['name'] = match.group('name').strip()
                current['club'] = match.group('club').strip()
            else:
                current['name'] = value
        elif key.startswith('score'):
            score_match = re.search(r"-?\d+(?:\.\d+)?", value)
            if score_match:
                current['score'] = float(score_match.group())
            form_match = re.search(r"Form:\s*(-?\d+(?:\.\d+)?)", value)
            ict_match = re.search(r"ICT:\s*(-?\d+(?:\.\d+)?)", value)
            if form_match:
                current['form'] = float(form_match.group(1))
            if ict_match:
                current['ict'] = float(ict_match.group(1))
        elif key.startswith('price'):
            current['price'] = value
        elif 'avg fdr' in key:
            try:
                current['avg_fdr'] = float(value)
            except ValueError:
                current['avg_fdr'] = value

    if 'out' not in sections or 'in' not in sections:
        return result_text

    headers = ["Player", "Club", "Role", "Score", "Form", "ICT", "Avg FDR (Next 5)", "Price"]
    rows = []
    series = []

    for key in ('out', 'in'):
        entry = sections[key]
        rows.append([
            entry.get('name', 'Unknown'),
            entry.get('club', ''),
            entry.get('role', key.title()),
            _format_optional_float(entry.get('score')),
            _format_optional_float(entry.get('form')),
            _format_optional_float(entry.get('ict')),
            _format_optional_float(entry.get('avg_fdr')),
            entry.get('price', ''),
        ])

        score_value = entry.get('score')
        if isinstance(score_value, (int, float)):
            label = f"{entry.get('name', 'Unknown')} ({entry.get('role', key.title())})"
            series.append({"label": label, "value": score_value})

    metadata = {"gameweek": gameweek}
    if recommendation:
        metadata['recommendation'] = recommendation

    return {
        "type": "table",
        "title": "Transfer Suggester",
        "headers": headers,
        "rows": rows,
        "chartSeries": series,
        "chartLabel": "Score",
        "metadata": metadata,
        "raw": result_text,
    }


def _build_league_payload(result_text: str, gameweek: int) -> dict | str:
    lines = [line.rstrip() for line in result_text.splitlines() if line.strip()]
    if not lines:
        return result_text

    title = lines[0]
    league_name = None
    rows = []
    series = []

    for line in lines:
        if "Predicted Results for" in line:
            match = re.search(r"'([^']+)'", line)
            if match:
                league_name = match.group(1)
            break

    start_index = None
    for idx, line in enumerate(lines):
        if line.startswith('Rank') and 'Manager' in line:
            start_index = idx + 2
            break

    if start_index is None:
        return result_text

    for line in lines[start_index:]:
        stripped = line.strip()
        if not stripped or stripped.startswith('-'):
            continue
        parts = stripped.split()
        if len(parts) < 3:
            continue
        try:
            rank = int(parts[0])
            score = float(parts[-1])
        except ValueError:
            continue
        manager = " ".join(parts[1:-1]).strip()
        rows.append([str(rank), manager, f"{score:.2f}"])
        series.append({"label": f"{rank}. {manager}", "value": score})

    if not rows:
        return result_text

    metadata = {"gameweek": gameweek}
    if league_name:
        metadata['league_name'] = league_name

    return {
        "type": "table",
        "title": title,
        "headers": ["Rank", "Manager", "Predicted Score"],
        "rows": rows,
        "chartSeries": series,
        "chartLabel": "Predicted Score",
        "metadata": metadata,
        "raw": result_text,
    }


def _build_injury_payload(result_text: str) -> dict | str:
    lines = [line.rstrip() for line in result_text.splitlines() if line.strip()]
    if not lines:
        return result_text

    title = lines[0]
    start_index = None
    for idx, line in enumerate(lines):
        if line.lower().startswith('player') and 'risk score' in line.lower():
            start_index = idx + 2
            break

    if start_index is None:
        return result_text

    entries = []
    current = None

    for line in lines[start_index:]:
        if line.startswith('---'):
            continue
        if line.startswith('-'):
            continue

        if '└─' in line:
            if current is not None and 'news' not in current:
                news_text = line.split('News:', 1)[-1].strip()
                current['news'] = news_text
            continue

        name = line[:20].strip()
        team = line[20:26].strip()
        score_str = line[26:38].strip()
        reasons = line[38:].strip()

        try:
            score = float(score_str)
        except ValueError:
            continue

        current = {
            'name': name,
            'team': team,
            'score': score,
            'reasons': reasons,
            'news': '',
        }
        entries.append(current)

    if not entries:
        return result_text

    rows = [
        [
            entry['name'],
            entry['team'],
            f"{entry['score']:.0f}",
            entry['reasons'],
            entry['news'],
        ]
        for entry in entries
    ]

    series = [{"label": f"{entry['name']} ({entry['team']})", "value": entry['score']} for entry in entries]

    return {
        "type": "table",
        "title": title,
        "headers": ["Player", "Team", "Risk Score", "Reasons", "Latest News"],
        "rows": rows,
        "chartSeries": series,
        "chartLabel": "Risk Score",
        "raw": result_text,
    }


def _format_optional_float(value):
    if isinstance(value, (int, float)):
        return f"{value:.2f}"
    return value if value is not None else ''


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
        config = {
            'team_id': team_id,
            'league_id': league_id,
            'user_name': user_name
        }
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4)

        return jsonify({
            "message": f"Welcome, {user_name}!",
            "team_id": team_id,
            "league_id": league_id,
            "user_name": user_name
        })

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/session", methods=['GET'])
def session_info():
    """Returns the saved session information, if any."""
    try:
        config = load_saved_config()
        return jsonify({
            "logged_in": True,
            "team_id": config.get("team_id"),
            "league_id": config.get("league_id"),
            "user_name": config.get("user_name")
        })
    except FileNotFoundError:
        return jsonify({"logged_in": False})
    except Exception as e:
        return jsonify({"logged_in": False, "error": str(e)}), 500


@app.route("/api/logout", methods=['POST'])
def logout():
    """Clears the saved session/configuration."""
    try:
        if os.path.exists(CONFIG_FILE):
            os.remove(CONFIG_FILE)
        return jsonify({"message": "Logged out."})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/features/injury-risk", methods=['GET'])
def get_injury_risk():
    """Endpoint for the Injury/Risk Analyzer feature."""

    def run():
        context = build_context()
        result_text = fpl_logic.get_injury_risk_analyzer_string(
            context["bootstrap"],
            context["team_map"],
        )
        return _build_injury_payload(result_text)

    return process_feature(run)


@app.route("/api/features/my-team-summary", methods=['GET'])
def my_team_summary():
    def run():
        context = build_context()
        team_id = resolve_team_id()
        raw_result = fpl_logic.get_my_team_summary_string(
            team_id,
            context["current_gameweek"],
            context["player_map"],
        )
        return _build_my_team_payload(team_id, context, raw_result)

    return process_feature(run)


@app.route("/api/features/smart-captaincy", methods=['GET'])
def smart_captaincy():
    def run():
        context = build_context()
        team_id = resolve_team_id()
        result_text = fpl_logic.get_captaincy_suggester_string(
            team_id,
            context["current_gameweek"],
            context["bootstrap"],
            context["fixtures"],
        )
        return _build_captaincy_payload(result_text, context["current_gameweek"])

    return process_feature(run)


@app.route("/api/features/differential-hunter", methods=['GET'])
def differential_hunter():
    def run():
        context = build_context()
        sort_by = request.args.get("sort", default="form")
        return fpl_logic.get_differential_hunter_data(
            context["bootstrap"],
            context["team_map"],
            context["position_map"],
            sort_by,
        )

    return process_feature(run)


@app.route("/api/features/transfer-suggester", methods=['GET'])
def transfer_suggester():
    def run():
        context = build_context()
        team_id = resolve_team_id()
        result_text = fpl_logic.get_transfer_suggester_string(
            team_id,
            context["current_gameweek"],
            context["bootstrap"],
            context["fixtures"],
            context["team_map"],
            context["position_map"],
        )
        return _build_transfer_payload(result_text, context["current_gameweek"])

    return process_feature(run)


@app.route("/api/features/current-captain", methods=['GET'])
def current_captain():
    def run():
        context = build_context()
        return _execute_feature('current-captain', context)

    return process_feature(run)


@app.route("/api/features/predicted-top-performers", methods=['GET'])
def predicted_top_performers():
    def run():
        context = build_context()
        return fpl_logic.get_predicted_points_data(
            context["bootstrap"],
            context["fixtures"],
            context["current_gameweek"],
        )

    return process_feature(run)


@app.route("/api/features/ai-predictions", methods=['GET'])
def ai_predictions():
    def run():
        context = build_context()
        window = request.args.get('window', default=5, type=int)
        max_players = request.args.get('players', default=200, type=int)
        return fpl_logic.generate_ai_prediction_table(
            context["bootstrap"],
            history_window=max(3, min(window, 10)),
            max_players=max(50, min(max_players, 400))
        )

    return process_feature(run)


@app.route("/api/features/ai-team-performance", methods=['GET'])
def ai_team_performance():
    def run():
        context = build_context()
        team_id = resolve_team_id()
        ai_bundle = _fetch_or_train_ai_model(context)
        projection = rag_engine.compute_team_projection(context, team_id, ai_bundle)
        if not projection:
            raise RuntimeError("Unable to compute team projection right now.")

        table_rows = []
        series = []

        for detail in projection['starters']:
            note = 'Captain' if detail['is_captain'] else 'Vice' if detail['is_vice'] else ''
            table_rows.append([
                detail['name'],
                detail['team'],
                detail['position'],
                f"{detail['predicted']:.2f}",
                note or '-'
            ])
            series.append({
                'label': f"{detail['name']} ({detail['team']})",
                'value': detail['predicted'],
            })

        metadata = {
            'gameweek': projection['gameweek'],
            'predicted_total': projection['predicted_total'],
        }
        if projection['bench']:
            bench_summary = ", ".join(
                f"{detail['name']} {detail['predicted']:.2f}"
                for detail in projection['bench']
            )
            metadata['note'] = f"Bench: {bench_summary}"

        return {
            'type': 'table',
            'title': f"Predicted squad output (GW {projection['gameweek']})",
            'headers': ['Player', 'Team', 'Position', 'Predicted Points', 'Role'],
            'rows': table_rows,
            'chartSeries': series,
            'chartLabel': 'Predicted Points',
            'metadata': metadata,
        }

    return process_feature(run)


@app.route("/api/features/chip-advice", methods=['GET'])
def chip_advice():
    def run():
        context = build_context()
        return _execute_feature('chip-advice', context)

    return process_feature(run)


@app.route("/api/features/dream-team", methods=['GET'])
def dream_team():
    def run():
        context = build_context()
        result_text = fpl_logic.get_dream_team_optimizer_string(
            context["bootstrap"],
            context["fixtures"],
            context["current_gameweek"],
            context["position_map"],
        )
        return _build_dream_team_payload(result_text, context)

    return process_feature(run)


@app.route("/api/features/league-predictions", methods=['GET'])
def league_predictions():
    def run():
        context = build_context()
        league_id = resolve_league_id()
        result_text = fpl_logic.get_league_predictions_string(
            league_id,
            context["current_gameweek"],
            context["bootstrap"],
            context["fixtures"],
        )
        return _build_league_payload(result_text, context["current_gameweek"])

    return process_feature(run)


@app.route("/api/features/league-current", methods=['GET'])
def league_current():
    def run():
        context = build_context()
        return _execute_feature('league-current', context)

    return process_feature(run)


@app.route("/api/features/quadrant-analysis", methods=['GET'])
def quadrant_analysis():
    def run():
        context = build_context()
        return fpl_logic.get_quadrant_analysis_string(
            context["bootstrap"],
            context["fixtures"],
            context["current_gameweek"],
            context["team_map"],
        )

    return process_feature(run)


@app.route("/api/search/entries", methods=['GET'])
def search_entries():
    query = request.args.get('q', '').strip()
    if len(query) < 3:
        return jsonify({"error": "Query too short"}), 400

    try:
        response = requests.get(
            "https://fantasy.premierleague.com/api/search/",
            params={"query": query},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502

    entries = []
    for entry in data.get('entry', [])[:12]:
        entries.append({
            'id': entry.get('id'),
            'team_name': entry.get('entry_name'),
            'manager_name': entry.get('player_name'),
        })

    return jsonify({'entries': entries})


# --- Main execution ---

if __name__ == "__main__":
    print("Starting FPL Toolkit Backend Server...")
    # The host='0.0.0.0' makes the server accessible on your local network
    app.run(host='0.0.0.0', port=5001, debug=True)


# 2934260
# 474540
