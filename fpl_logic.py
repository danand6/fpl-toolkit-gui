import requests
import time
import json
import os

# --- CACHE CONFIGURATION ---
CACHE_DIR = "fpl_cache"
CACHE_EXPIRY_SECONDS = 6 * 60 * 60  # 6 hours

# 3. Set the ownership threshold for a "differential" player
DIFFERENTIAL_OWNERSHIP_THRESHOLD = 5.0

# --- SCRIPT CONSTANTS ---

# FPL API Endpoints
FPL_API_URL_BOOTSTRAP = "https://fantasy.premierleague.com/api/bootstrap-static/"
FPL_API_URL_ENTRY = "https://fantasy.premierleague.com/api/entry/{team_id}/event/{gameweek}/picks/"
FPL_API_URL_LIVE = "https://fantasy.premierleague.com/api/event/{gameweek}/live/"
FPL_API_URL_LEAGUE = "https://fantasy.premierleague.com/api/leagues-classic/{league_id}/standings/"
FPL_API_URL_GENERAL_ENTRY = "https://fantasy.premierleague.com/api/entry/{team_id}/"
FPL_API_URL_FIXTURES = "https://fantasy.premierleague.com/api/fixtures/"
FPL_API_URL_ELEMENT_SUMMARY = "https://fantasy.premierleague.com/api/element-summary/{player_id}/"

# --- INTERNAL CACHING HELPER ---

def _get_cached_data(cache_filename: str, url: str) -> dict | list:
    """Internal helper to fetch data from a URL, using a local cache to avoid repeated requests."""
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)

    cache_filepath = os.path.join(CACHE_DIR, cache_filename)

    # Check if a valid, non-expired cache file exists
    if os.path.exists(cache_filepath):
        try:
            file_mod_time = os.path.getmtime(cache_filepath)
            if (time.time() - file_mod_time) < CACHE_EXPIRY_SECONDS:
                with open(cache_filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except (json.JSONDecodeError, IOError):
            # Cache is corrupted or unreadable, proceed to fetch new data
            pass

    # If no valid cache, fetch from network
    response = requests.get(url)
    response.raise_for_status()
    data = response.json()

    # Save new data to cache
    with open(cache_filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f)
    return data

# --- API HELPER FUNCTIONS ---

def get_bootstrap_data() -> dict:
    """Fetches the main bootstrap data, using a cache."""
    return _get_cached_data("bootstrap.json", FPL_API_URL_BOOTSTRAP)

def get_live_data(gameweek: int) -> dict:
    """Fetches the live points data for a specific gameweek."""
    url = FPL_API_URL_LIVE.format(gameweek=gameweek)
    response = requests.get(url)
    response.raise_for_status()
    return response.json()

def get_team_picks(team_id: int, gameweek: int) -> dict:
    """Fetches the player picks for a specific team and gameweek."""
    url = FPL_API_URL_ENTRY.format(team_id=team_id, gameweek=gameweek)
    response = requests.get(url)
    response.raise_for_status()
    return response.json()

def get_league_data(league_id: int) -> dict:
    """Fetches standings and manager data for a classic mini-league."""
    url = FPL_API_URL_LEAGUE.format(league_id=league_id)
    response = requests.get(url)
    response.raise_for_status()
    return response.json()

def get_entry_data(team_id: int) -> dict:
    """Fetches general entry data, including bank and team value."""
    url = FPL_API_URL_GENERAL_ENTRY.format(team_id=team_id)
    response = requests.get(url)
    return response.json()

def get_fixtures_data() -> list:
    """Fetches data for all fixtures in the season, using a cache."""
    return _get_cached_data("fixtures.json", FPL_API_URL_FIXTURES)

def get_element_summary(player_id: int) -> dict:
    """Fetches detailed history for a specific player, using cache."""
    cache_filename = f"element_{player_id}.json"
    url = FPL_API_URL_ELEMENT_SUMMARY.format(player_id=player_id)
    return _get_cached_data(cache_filename, url)

# --- UTILITY FUNCTIONS ---

def get_current_gameweek(bootstrap_data: dict) -> int:
    """Finds the current, live gameweek from the bootstrap data."""
    for gw in bootstrap_data['events']:
        if gw['is_current']:
            return gw['id']
    return 0

def create_player_map(bootstrap_data: dict) -> dict:
    """Creates a simple {id: 'web_name'} mapping from bootstrap data."""
    return {player['id']: player['web_name'] for player in bootstrap_data['elements']}

def create_team_map(bootstrap_data: dict) -> dict:
    """Creates a simple {id: 'short_name'} mapping for teams."""
    return {team['id']: team['short_name'] for team in bootstrap_data['teams']}

def create_position_map(bootstrap_data: dict) -> dict:
    """Creates a simple {id: 'short_name'} mapping for player positions."""
    return {pos['id']: pos['singular_name_short'] for pos in bootstrap_data['element_types']}

def get_avg_fdr(team_id: int, current_gameweek: int, fixtures_data: list, num_games: int = 5) -> float:
    """Calculates the average fixture difficulty for a team's next N games."""
    # Find fixtures from the current gameweek onwards
    upcoming_fixtures = [f for f in fixtures_data if f.get('event') and f.get('event') >= current_gameweek]
    team_fixtures = [f for f in upcoming_fixtures if f['team_h'] == team_id or f['team_a'] == team_id][:num_games]
    
    if not team_fixtures:
        return 3.0  # Return a neutral score if no fixtures found

    total_difficulty = 0
    for fixture in team_fixtures:
        if fixture['team_h'] == team_id:
            total_difficulty += fixture['team_h_difficulty']
        else:
            total_difficulty += fixture['team_a_difficulty']
    return total_difficulty / len(team_fixtures)

def load_or_create_config() -> tuple[int, int]:
    """Loads user configuration from a file, or creates it if it doesn't exist."""
    CONFIG_FILE = 'config.json'
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                if 'team_id' in config and 'league_id' in config:
                    return config['team_id'], config['league_id']
    except (IOError, json.JSONDecodeError):
        pass  # Fall through to create a new one

    # If file doesn't exist, is invalid, or incomplete, create it.
    # For a GUI, we can't use input(), so we'll use placeholders.
    # The GUI will handle getting the real values.
    print("Config file not found or invalid. Creating with placeholder IDs.")
    team_id = 1
    league_id = 1
    
    config = {'team_id': team_id, 'league_id': league_id}
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)
    return team_id, league_id

def get_predictions(bootstrap_data: dict, fixtures_data: list, current_gameweek: int) -> dict:
    """
    Generates a dictionary of {player_id: predicted_score} for the next gameweek.
    This is a refactored, reusable version of the prediction logic.
    """
    next_gameweek = current_gameweek + 1
    
    teams_data = bootstrap_data['teams']
    team_strength_map = {
        team['id']: {
            'attack': team['strength_attack_home'] + team['strength_attack_away'],
            'defence': team['strength_defence_home'] + team['strength_defence_away']
        } for team in teams_data
    }

    next_gw_fixtures = [f for f in fixtures_data if f.get('event') == next_gameweek]
    next_opponents = {}
    for f in next_gw_fixtures:
        next_opponents[f['team_h']] = {'opponent': f['team_a'], 'is_home': True}
        next_opponents[f['team_a']] = {'opponent': f['team_h'], 'is_home': False}

    all_players = {p['id']: p for p in bootstrap_data['elements'] if p.get('status', 'a') == 'a'}
    predictions = {}

    for player_id, player in all_players.items():
        try:
            base_score = (float(player['form']) * 0.6) + (float(player['ict_index']) * 0.1)
            fixture_info = next_opponents.get(player['team'])
            if not fixture_info: continue

            attack_modifier = (team_strength_map[player['team']]['attack'] - team_strength_map[fixture_info['opponent']]['defence']) / 200
            home_advantage = 0.25 if fixture_info['is_home'] else 0.0
            prediction = base_score + attack_modifier + home_advantage
            predictions[player_id] = max(0, prediction)
        except (ValueError, KeyError):
            continue
    return predictions

# --- FEATURE FUNCTIONS ---

def get_my_team_summary_string(team_id: int, current_gameweek: int, player_map: dict) -> str:
    """Generates a string summary of the user's FPL team for the current gameweek."""
    team_picks = get_team_picks(team_id, current_gameweek)
    live_data = get_live_data(current_gameweek)
    live_points_map = {p['id']: p['stats']['total_points'] for p in live_data['elements']}

    output = [f"--- Your FPL Team Summary for Gameweek {current_gameweek} ---"]
    total_points = 0
    starting_lineup, bench = [], []

    for pick in team_picks['picks']:
        player_id = pick['element']
        player_name = player_map.get(player_id, "Unknown Player")
        points = live_points_map.get(player_id, 0)
        multiplier = pick['multiplier']

        if pick['is_captain']: player_name += " (C)"
        if pick['is_vice_captain']: player_name += " (V)"

        player_points = points * multiplier
        total_points += player_points
        player_summary = f"{player_name:<20} {player_points}"

        if multiplier > 0:
            starting_lineup.append(player_summary)
        else:
            bench.append(player_summary)

    output.append("\n--- Starting XI ---")
    output.extend(starting_lineup)
    output.append("\n--- Bench ---")
    output.extend(bench)
    output.append("\n---------------------")
    output.append(f"TOTAL POINTS: {total_points}")
    output.append("---------------------")
    return "\n".join(output)

def get_league_captains_string(league_id: int, current_gameweek: int, player_map: dict) -> str:
    """Generates a string of captain picks for a mini-league."""
    if league_id == 12345:
        return "\nError: Please update the LEAGUE_ID in your config file."

    output = [f"Fetching captain picks for Gameweek {current_gameweek}..."]

    league_data = get_league_data(league_id)
    league_name = league_data['league']['name']
    managers = league_data['standings']['results']

    print(f"\n--- Captains for '{league_name}' ---")
    print(f"{'Manager':<25} {'Captain':<20} {'Vice-Captain':<20}")
    print("-" * 65)
    output.append(f"\n--- Captains for '{league_name}' ---")
    output.append(f"{'Manager':<25} {'Captain':<20} {'Vice-Captain':<20}")
    output.append("-" * 65)

    for manager in managers[:15]: # Limit to top 15 to avoid long waits
        manager_name = manager['player_name']
        team_id = manager['entry']
        
        # Add a small delay to be respectful to the API
        time.sleep(0.5) 
        team_picks = get_team_picks(team_id, current_gameweek)
        
        captain_id, vice_captain_id = None, None
        for pick in team_picks['picks']:
            if pick['is_captain']: captain_id = pick['element']
            if pick['is_vice_captain']: vice_captain_id = pick['element']
        
        captain_name = player_map.get(captain_id, "N/A")
        vice_captain_name = player_map.get(vice_captain_id, "N/A")

        output.append(f"{manager_name:<25} {captain_name:<20} {vice_captain_name:<20}")
    return "\n".join(output)

def get_differential_hunter_data(bootstrap_data: dict, team_map: dict, position_map: dict, sort_by: str) -> dict:
    """Generates structured data of low-ownership players sorted by a chosen metric."""
    all_players = bootstrap_data['elements']
    differentials = [
        p for p in all_players 
        if float(p['selected_by_percent']) < DIFFERENTIAL_OWNERSHIP_THRESHOLD
    ]

    if sort_by == 'form':
        sort_key, sort_label = 'form', 'Form'
        sorted_differentials = sorted(differentials, key=lambda p: float(p['form']), reverse=True)
    elif sort_by == 'total_points':
        sort_key, sort_label = 'total_points', 'Points'
        sorted_differentials = sorted(differentials, key=lambda p: p['total_points'], reverse=True)
    elif sort_by == 'ict_index':
        sort_key, sort_label = 'ict_index', 'ICT'
        sorted_differentials = sorted(differentials, key=lambda p: float(p['ict_index']), reverse=True)
    else:
        return {"type": "string", "content": "Invalid sort key provided."}

    headers = ['Player', 'Team', 'Pos', 'Price', 'Own%', sort_label]
    rows = []
    for player in sorted_differentials[:20]:
        rows.append([
            player['web_name'],
            team_map.get(player['team'], 'N/A'),
            position_map.get(player['element_type'], 'N/A'),
            f"£{player['now_cost'] / 10.0:.1f}m",
            f"{player['selected_by_percent']}%",
            str(player[sort_key])
        ])

    return {
        "type": "table",
        "title": f"Top 20 Differentials (under {DIFFERENTIAL_OWNERSHIP_THRESHOLD}%) by {sort_label}",
        "headers": headers,
        "rows": rows
    }

def get_transfer_suggester_string(team_id: int, current_gameweek: int, bootstrap_data: dict, fixtures_data: list, team_map: dict, position_map: dict) -> str:
    """Generates a string with a data-driven transfer suggestion."""
    output = ["--- Automatic Transfer Suggester ---"]
    output.append("Analyzing your squad to find the weakest link and best replacement...")

    # --- 1. Define Scoring Logic ---
    def calculate_player_score(player: dict) -> float:
        """Calculates a desirability score for a player based on key metrics."""
        try:
            # Weights: form=50%, ict=40%, FDR=10% (Prioritizing current form)
            # A lower FDR is better, so we invert it (5 - FDR) to reward easier fixtures.
            avg_fdr = get_avg_fdr(player['team'], current_gameweek, fixtures_data)
            fdr_score = (5 - avg_fdr) * 5 # Scale it to be comparable to form/ict

            score = (float(player['form']) * 0.5) + (float(player['ict_index']) * 0.4) + (fdr_score * 0.1)
            return round(score, 2)
        except (ValueError, KeyError):
            return 0.0

    # --- 2. Get User's Squad, Bank, and Player Data ---
    all_players_data = {p['id']: p for p in bootstrap_data['elements']}
    user_picks = get_team_picks(team_id, current_gameweek)['picks']
    user_squad_ids = [p['element'] for p in user_picks]
    user_squad_players = [all_players_data[pid] for pid in user_squad_ids]
    
    entry_data = get_entry_data(team_id)
    bank = entry_data.get('last_deadline_bank', 0) / 10.0

    # --- 3. Find the Weakest Player in the Squad ---
    weakest_player = min(user_squad_players, key=calculate_player_score)
    weakest_player_score = calculate_player_score(weakest_player)

    # --- 4. Find the Best Possible Replacement ---
    budget = weakest_player['now_cost'] + (bank * 10)
    
    potential_replacements = [
        p for p in bootstrap_data['elements']
        if p['element_type'] == weakest_player['element_type']  # Same position
        and p['id'] not in user_squad_ids  # Not already in squad
        and p['now_cost'] <= budget  # Affordable
        and p.get('status', 'a') == 'a' # Available to play
    ]

    if not potential_replacements:
        return "\nCould not find any suitable replacements for your weakest player."

    best_replacement = max(potential_replacements, key=calculate_player_score)
    best_replacement_score = calculate_player_score(best_replacement)

    # --- 5. Display the Suggestion ---
    def print_player_summary(player, score):
        avg_fdr = get_avg_fdr(player['team'], current_gameweek, fixtures_data)
        price = f"£{player['now_cost'] / 10.0:.1f}m"
        summary = []
        summary.append(f"  - Name:    {player['web_name']} ({team_map.get(player['team'], 'N/A')})")
        summary.append(f"  - Score:   {score} (Form: {player['form']}, ICT: {player['ict_index']})")
        summary.append(f"  - Price:   {price}")
        summary.append(f"  - Avg FDR (Next 5): {avg_fdr:.2f}")
        return "\n".join(summary)

    output.append("\n---------------------------------")
    output.append("         TRANSFER OUT 👎")
    output.append("---------------------------------")
    output.append(print_player_summary(weakest_player, weakest_player_score))

    output.append("\n---------------------------------")
    output.append("          TRANSFER IN 👍")
    output.append("---------------------------------")
    output.append(print_player_summary(best_replacement, best_replacement_score))
    output.append("---------------------------------")

    # Final check
    if best_replacement_score <= weakest_player_score:
        output.append("\nRecommendation: HOLD transfer. No clear upgrade found within budget.")
    else:
        output.append(f"\nRecommendation: Transferring out {weakest_player['web_name']} for {best_replacement['web_name']} is a potential upgrade.")
    return "\n".join(output)

def get_predicted_points_data(bootstrap_data: dict, fixtures_data: list, current_gameweek: int) -> dict:
    """Generates structured data of the top-performing players for the next gameweek."""
    next_gameweek = current_gameweek + 1

    player_map = create_player_map(bootstrap_data)
    predictions = get_predictions(bootstrap_data, fixtures_data, current_gameweek)
    
    sorted_predictions = sorted(predictions.items(), key=lambda item: item[1], reverse=True)

    headers = ['Player', 'Predicted Points']
    rows = []
    for player_id, score in sorted_predictions[:20]:
        rows.append([player_map.get(player_id, 'N/A'), f"{score:.2f}"])

    return {
        "type": "table",
        "title": f"Top 20 Predicted Scorers for Gameweek {next_gameweek}",
        "headers": headers,
        "rows": rows
    }

def get_dream_team_optimizer_string(bootstrap_data: dict, fixtures_data: list, current_gameweek: int, position_map: dict) -> str:
    """Generates a string for the optimal squad for a £100m budget."""
    output = ["--- Wildcard / Dream Team Optimizer ---"]
    output.append("Building the best possible squad for a £100m budget. This may take a minute...")

    # --- 1. Setup and Data Preparation ---
    BUDGET = 1000 # Use integer prices (e.g., 10.5m = 105)
    all_players = {p['id']: p for p in bootstrap_data['elements'] if p.get('status', 'a') == 'a'}
    predictions = get_predictions(bootstrap_data, fixtures_data, current_gameweek)
    
    pos_limits = {1: 2, 2: 5, 3: 5, 4: 3} # GKP, DEF, MID, FWD

    # --- 2. Build an initial, cheap, valid squad ---
    squad_ids = []
    team_counts = {i: 0 for i in range(1, 21)}
    pos_counts = {i: 0 for i in range(1, 5)}
    
    sorted_by_price = sorted(all_players.values(), key=lambda p: p['now_cost'])
    for p in sorted_by_price:
        pos = p['element_type']
        team = p['team']
        if pos_counts[pos] < pos_limits[pos] and team_counts[team] < 3:
            squad_ids.append(p['id'])
            pos_counts[pos] += 1
            team_counts[team] += 1
        if len(squad_ids) == 15:
            break

    # --- 3. Iteratively improve the squad ---
    while True:
        best_improvement = 0
        best_swap = None # (player_out_id, player_in_id)

        squad_cost = sum(all_players[p_id]['now_cost'] for p_id in squad_ids)
        
        for p_out_id in squad_ids:
            p_out = all_players[p_out_id]
            
            # Find all potential replacements for this player
            potential_replacements = [
                p_in for p_in in all_players.values()
                if p_in['id'] not in squad_ids
                and p_in['element_type'] == p_out['element_type']
                and (squad_cost - p_out['now_cost'] + p_in['now_cost']) <= BUDGET
            ]

            for p_in in potential_replacements:
                # Check team constraint
                p_out_team_count = team_counts[p_out['team']]
                p_in_team_count = team_counts.get(p_in['team'], 0)
                if p_in['team'] == p_out['team'] or p_in_team_count < 3:
                    improvement = predictions.get(p_in['id'], 0) - predictions.get(p_out_id, 0)
                    if improvement > best_improvement:
                        best_improvement = improvement
                        best_swap = (p_out_id, p_in['id'])
        
        if best_swap:
            p_out_id, p_in_id = best_swap
            # output.append(f"Swapping... Improvement: {best_improvement:.2f}") # Optional: for debugging
            
            # Update squad
            squad_ids.remove(p_out_id)
            squad_ids.append(p_in_id)
            
            # Update team counts
            team_counts[all_players[p_out_id]['team']] -= 1
            team_counts[all_players[p_in_id]['team']] += 1
        else:
            output.append("\nOptimization complete!")
            break # No more improvements found

    # --- 4. Display the final squad ---
    final_squad = [all_players[p_id] for p_id in squad_ids]
    final_squad_cost = sum(p['now_cost'] for p in final_squad) / 10.0
    total_predicted_score = sum(predictions.get(p_id, 0) for p_id in squad_ids)

    output.append("\n--- Optimized Dream Team ---")
    output.append(f"Total Predicted Score: {total_predicted_score:.2f}")
    output.append(f"Total Cost: £{final_squad_cost:.1f}m")
    output.append("-" * 40)

    final_squad.sort(key=lambda p: p['element_type'])
    for player in final_squad:
        pos = position_map.get(player['element_type'], 'N/A')
        price = f"£{player['now_cost'] / 10.0:.1f}m"
        pred_pts = predictions.get(player['id'], 0)
        output.append(f"{player['web_name']:<20} {pos:<5} {price:<7} (Pred: {pred_pts:.2f})")
    return "\n".join(output)


def get_chip_advice_string(team_id: int, current_gameweek: int, bootstrap_data: dict, fixtures_data: list,
                           team_map: dict, position_map: dict) -> str:
    """Generate heuristic advice for FPL chips based on upcoming predictions and squad depth."""
    predictions = get_predictions(bootstrap_data, fixtures_data, current_gameweek)
    picks = get_team_picks(team_id, current_gameweek)
    entry_data = get_entry_data(team_id)
    player_lookup_map = {player['id']: player for player in bootstrap_data['elements']}

    starters, bench = [], []
    flagged_count = 0

    for pick in picks['picks']:
        player_id = pick['element']
        multiplier = pick.get('multiplier', 1)
        player_data = player_lookup_map.get(player_id)
        if not player_data:
            continue
        predicted = predictions.get(player_id, 0.0)
        chip_info = {
            'player': player_data,
            'predicted': predicted,
            'multiplier': multiplier,
            'is_captain': bool(pick.get('is_captain')),
            'is_vice': bool(pick.get('is_vice_captain')),
        }
        if multiplier > 0:
            starters.append(chip_info)
        else:
            bench.append(chip_info)
        if player_data.get('status') != 'a':
            flagged_count += 1

    output = [f"--- Chip Strategy Advisor (GW {current_gameweek}) ---"]

    if not starters:
        return "Unable to evaluate chips because your squad could not be retrieved."

    output.append("")

    # Triple Captain: look for highest predicted starter and check upcoming fixtures
    best_starter = max(starters, key=lambda s: s['predicted'])
    best_name = best_starter['player']['web_name']
    best_team = team_map.get(best_starter['player']['team'], 'N/A')
    best_points = best_starter['predicted']
    if best_points >= 7.5:
        tc_blurb = (
            f"TRIPLE CAPTAIN: {best_name} ({best_team}) projects {best_points:.2f} points. "
            "Looks like a strong week if you want an aggressive play."
        )
    elif best_points >= 6.0:
        tc_blurb = (
            f"TRIPLE CAPTAIN: {best_name} ({best_team}) sits around {best_points:.2f} predicted points. "
            "Solid, but you might wait for a double gameweek."
        )
    else:
        tc_blurb = (
            f"TRIPLE CAPTAIN: No standout option this week (top projection {best_points:.2f}). "
            "Probably better to hold."
        )
    output.append(tc_blurb)

    # Bench Boost: aggregate bench predicted points
    bench_total = sum(player['predicted'] for player in bench)
    if bench_total >= 16:
        bb_blurb = (
            f"BENCH BOOST: Bench projects {bench_total:.2f} points. This is a very healthy bench boost week." )
    elif bench_total >= 12:
        bb_blurb = (
            f"BENCH BOOST: Bench projects {bench_total:.2f} points. Decent potential if you need a chip soon." )
    else:
        bb_blurb = (
            f"BENCH BOOST: Bench projects only {bench_total:.2f} points. Better to hold unless you expect late doubles." )
    output.append(bb_blurb)

    # Wildcard / Free Hit suggestions based on flagged players and fixture difficulty
    total_players = len(starters) + len(bench)
    flagged_ratio = flagged_count / total_players if total_players else 0

    if flagged_ratio >= 0.3:
        wc_blurb = (
            "WILDCARD: Over 30% of your squad is flagged. Strong case to reset with a wildcard." )
    elif flagged_ratio >= 0.2:
        wc_blurb = (
            "WILDCARD: A few injuries piling up. Consider a wildcard if future fixtures are poor." )
    else:
        wc_blurb = (
            "WILDCARD: Squad health is solid right now. Save the wildcard unless you plan for doubles." )
    output.append(wc_blurb)

    upcoming_blanks = _count_blank_players(starters + bench, fixtures_data, current_gameweek)
    if upcoming_blanks >= 6:
        fh_blurb = (
            f"FREE HIT: You have {upcoming_blanks} players projected to blank soon. Free Hit could stabilise that GW." )
    elif upcoming_blanks >= 4:
        fh_blurb = (
            f"FREE HIT: {upcoming_blanks} players may blank soon; keep it in mind if transfers won't cover it." )
    else:
        fh_blurb = "FREE HIT: No major blank warning. Keep the chip unless fixtures flip quickly."
    output.append(fh_blurb)

    output.append("")
    output.append("Bank: £{:.1f}m, Free transfers: {}".format(
        entry_data.get('last_deadline_bank', 0) / 10.0,
        entry_data.get('last_deadline_total_transfers', 0)
    ))
    return "\n".join(output)


def _count_blank_players(players: list, fixtures_data: list, current_gameweek: int) -> int:
    upcoming = [f for f in fixtures_data if f.get('event') and f['event'] >= current_gameweek]
    players_with_fixtures = set()
    for fixture in upcoming:
        players_with_fixtures.add(fixture['team_a'])
        players_with_fixtures.add(fixture['team_h'])

    blanks = 0
    for info in players:
        team_id = info['player'].get('team')
        if team_id not in players_with_fixtures:
            blanks += 1
    return blanks

def generate_ai_prediction_table(bootstrap_data: dict, history_window: int = 5, max_players: int = 200) -> dict:
    """Uses an AI model to predict next-match points for active players."""
    try:
        import ai_models
    except ImportError as exc:
        raise RuntimeError("AI models module not available") from exc

    active_players = [
        player for player in bootstrap_data['elements']
        if player.get('status', 'a') == 'a' and player.get('minutes', 0) > 0
    ]

    if not active_players:
        return {"type": "string", "data": "No active player data available."}

    # Prioritise players with good form or total points to limit API calls
    def player_priority(player: dict) -> float:
        try:
            return float(player.get('form', 0))
        except (TypeError, ValueError):
            return 0.0

    shortlisted = sorted(active_players, key=player_priority, reverse=True)[:max_players]

    player_histories = []
    for player in shortlisted:
        try:
            summary = get_element_summary(player['id'])
        except requests.exceptions.RequestException:
            continue
        history = summary.get('history', [])
        if len(history) < history_window + 1:
            continue
        player_histories.append({
            'player': player,
            'history': history,
        })

    if len(player_histories) < 15:
        return {"type": "string", "data": "Insufficient player history to train AI model."}

    model = ai_models.train_points_model(player_histories, history_window=history_window)
    predictions = ai_models.predict_upcoming_points(model, player_histories, history_window)

    team_map = create_team_map(bootstrap_data)
    position_map = create_position_map(bootstrap_data)

    table_rows = []
    series = []

    for item in predictions[:30]:
        player = item['player']
        player_id = player['id']
        name = player.get('web_name', 'Unknown')
        team = team_map.get(player.get('team'), 'N/A')
        position = position_map.get(player.get('element_type'), 'UNK')
        ai_score = item['predicted']
        avg_points = item.get('avg_points', 0.0)
        form = player.get('form', '0')

        table_rows.append([
            name,
            team,
            position,
            f"{ai_score:.2f}",
            f"{avg_points:.2f}",
            str(form),
        ])
        series.append({
            'label': f"{name} ({team})",
            'value': ai_score,
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
            "model": model.get('name', 'Linear Regressor'),
            "history_window": history_window,
            "trained_samples": model.get('samples', 0)
        }
    }

def get_league_predictions_string(league_id: int, current_gameweek: int, bootstrap_data: dict, fixtures_data: list) -> str:
    """Generates a string of predicted scores for every manager in the league."""
    if league_id == 12345: # Default value check
        return "\nError: Please update the LEAGUE_ID in your config file."

    next_gameweek = current_gameweek + 1
    output = [f"--- Predicted League Standings for Gameweek {next_gameweek} ---"]

    # 1. Get player predictions and league data
    predictions = get_predictions(bootstrap_data, fixtures_data, current_gameweek)
    league_data = get_league_data(league_id)
    managers = league_data['standings']['results']

    manager_scores = []

    # 2. Loop through each manager and calculate their predicted score
    for manager in managers[:15]: # Limit to top 15
        manager_name = manager['player_name']
        team_id = manager['entry']
        
        time.sleep(0.5) # Be respectful to the API
        
        try:
            # Use the team from the current gameweek as the basis for next week's prediction
            team_picks = get_team_picks(team_id, current_gameweek)['picks']
            
            total_predicted_score = 0
            starting_lineup_ids = [p['element'] for p in team_picks if p['multiplier'] > 0]
            captain_id = next((p['element'] for p in team_picks if p['is_captain']), None)

            # Calculate score for starting 11
            for player_id in starting_lineup_ids:
                total_predicted_score += predictions.get(player_id, 0.0)

            # Add captain's bonus points
            if captain_id in starting_lineup_ids:
                total_predicted_score += predictions.get(captain_id, 0.0)
            
            manager_scores.append((manager_name, total_predicted_score))

        except requests.exceptions.RequestException:
            continue

    # 3. Sort and display the results
    sorted_manager_scores = sorted(manager_scores, key=lambda item: item[1], reverse=True)
    output.append(f"\n--- Predicted Results for '{league_data['league']['name']}' (GW{next_gameweek}) ---")
    output.append(f"{'Rank':<5} {'Manager':<25} {'Predicted Score'}")
    output.append("-" * 55)
    for i, (name, score) in enumerate(sorted_manager_scores, 1):
        output.append(f"{i:<5} {name:<25} {score:.2f}")
    return "\n".join(output)

def get_captaincy_suggester_string(team_id: int, current_gameweek: int, bootstrap_data: dict, fixtures_data: list) -> str:
    """Generates a string with captaincy recommendations for the user's squad."""
    next_gameweek = current_gameweek + 1
    output = [f"--- Smart Captaincy Suggester for Gameweek {next_gameweek} ---"]

    # 1. Get predictions and player map
    predictions = get_predictions(bootstrap_data, fixtures_data, current_gameweek)
    player_map = create_player_map(bootstrap_data)

    # 2. Get user's squad
    try:
        user_picks = get_team_picks(team_id, current_gameweek)['picks']
        squad_ids = [p['element'] for p in user_picks]
    except requests.exceptions.RequestException:
        return "Could not fetch your current team."

    # 3. Score players in the squad
    squad_predictions = []
    for player_id in squad_ids:
        score = predictions.get(player_id, 0.0)
        squad_predictions.append((player_map.get(player_id, "N/A"), score))

    # 4. Sort and display
    sorted_squad = sorted(squad_predictions, key=lambda item: item[1], reverse=True)
    
    output.append(f"\n{'Player':<20} {'Predicted Score'}")
    output.append("-" * 40)
    for i, (name, score) in enumerate(sorted_squad):
        recommendation = ""
        if i == 0:
            recommendation = "  <-- 🥇 Captain Pick"
        elif i == 1:
            recommendation = "  <-- 🥈 Vice-Captain Pick"
        output.append(f"{name:<20} {score:<17.2f}{recommendation}")
    return "\n".join(output)

def get_quadrant_analysis_string(bootstrap_data: dict, fixtures_data: list, current_gameweek: int, team_map: dict) -> str:
    """Generates a string categorizing players into four strategic quadrants."""
    output = ["--- Form vs. Fixture Quadrant Analysis ---"]

    # 1. Prepare data
    relevant_players = [p for p in bootstrap_data['elements'] if p.get('status', 'a') == 'a' and p['minutes'] > 0]
    if not relevant_players:
        return "Not enough player data to perform analysis."

    # 2. Calculate average form and FDR to define quadrants
    avg_form = sum(float(p['form']) for p in relevant_players) / len(relevant_players)
    avg_fdr = sum(get_avg_fdr(p['team'], current_gameweek, fixtures_data) for p in relevant_players) / len(relevant_players)

    print(f"(Average Form: {avg_form:.2f}, Average FDR: {avg_fdr:.2f})")

    # 3. Categorize players into quadrants
    quadrants = {
        "Prime Targets (High Form, Easy Fixtures)": [],
        "Form Traps (High Form, Hard Fixtures)": [],
        "Future Gems (Low Form, Easy Fixtures)": [],
        "Players to Avoid (Low Form, Hard Fixtures)": [],
    }

    for p in relevant_players:
        form = float(p['form'])
        fdr = get_avg_fdr(p['team'], current_gameweek, fixtures_data)
        
        if form >= avg_form and fdr <= avg_fdr:
            quadrants["Prime Targets (High Form, Easy Fixtures)"].append(p)
        elif form >= avg_form and fdr > avg_fdr:
            quadrants["Form Traps (High Form, Hard Fixtures)"].append(p)
        elif form < avg_form and fdr <= avg_fdr:
            quadrants["Future Gems (Low Form, Easy Fixtures)"].append(p)
        else:
            quadrants["Players to Avoid (Low Form, Hard Fixtures)"].append(p)

    # 4. Display results
    for quadrant_name, players in quadrants.items():
        output.append(f"\n--- {quadrant_name} ---")
        sorted_players = sorted(players, key=lambda p: float(p['form']), reverse=True)
        for p in sorted_players[:5]: # Show top 5 from each quadrant
            output.append(f"  - {p['web_name']:<20} (Form: {p['form']}, FDR: {get_avg_fdr(p['team'], current_gameweek, fixtures_data):.2f})")
    return "\n".join(output)

def get_injury_risk_analyzer_string(bootstrap_data: dict, team_map: dict) -> str:
    """Generates a string analyzing all players for potential injury or rotation risk."""
    output = ["--- Player Rotation & Injury Risk Analyzer ---"]

    def calculate_risk(player: dict) -> tuple[int, list[str]]:
        """Calculates a risk score and reasons based on player data."""
        risk_score = 0
        reasons = []

        # 1. Check official status
        if player.get('status') == 'd': # 75% or 50% chance
            risk_score += 4
            reasons.append("Flagged as doubtful")

        # 2. Check news for keywords
        news = player.get('news', '').lower()
        if news:
            risk_keywords = ['knock', 'doubt', 'assessment', 'rest', 'miss', 'late test']
            if any(keyword in news for keyword in risk_keywords):
                risk_score += 2
                reasons.append("Manager comments")

        # 3. Check explicit chance of playing
        chance = player.get('chance_of_playing_next_round')
        if chance is not None and chance < 100:
            risk_score += 3
            reasons.append(f"{chance}% chance of playing")
        
        return risk_score, list(set(reasons)) # Use set to remove duplicate reasons

    at_risk_players = []
    for player in bootstrap_data['elements']:
        risk_score, reasons = calculate_risk(player)
        if risk_score > 0:
            at_risk_players.append({
                'name': player['web_name'],
                'team': team_map.get(player['team'], 'N/A'),
                'news': player.get('news', 'No news.'),
                'score': risk_score,
                'reasons': ", ".join(reasons)
            })

    sorted_at_risk = sorted(at_risk_players, key=lambda p: p['score'], reverse=True)
    output.append(f"\n--- Top 25 At-Risk Players ---")
    output.append(f"{'Player':<20} {'Team':<6} {'Risk Score':<12} {'Reasons'}")
    output.append("-" * 75)
    for player in sorted_at_risk[:25]:
        output.append(f"{player['name']:<20} {player['team']:<6} {player['score']:<12} {player['reasons']}")
        if player['news'] and player['news'] != 'No news.':
            output.append(f"  └─ News: {player['news']}")
    return "\n".join(output)

def main():
    """Main function to run the FPL toolkit."""
    # --- Initial Setup ---
    try:
        # Load configuration
        team_id, league_id = load_or_create_config()

        print("Fetching essential FPL data...")
        bootstrap_data = get_bootstrap_data()
        fixtures_data = get_fixtures_data()
        # Create maps for players and teams to use throughout the app
        player_map = create_player_map(bootstrap_data)
        team_map = create_team_map(bootstrap_data)
        position_map = create_position_map(bootstrap_data)
        current_gameweek = get_current_gameweek(bootstrap_data)

        if not current_gameweek:
            print("No active gameweek found. Is the season running?")
            return
    except requests.exceptions.RequestException as e:
        print(f"Fatal Error: Could not fetch essential data from FPL API. {e}")
        return

    # --- Main Menu Loop ---
    while True:
        print("\n=====================================")
        print("          FPL Toolkit Menu           ")
        print("=====================================")
        print(f"(Current Gameweek: {current_gameweek})")
        print("1. My Team's Live Summary")
        print("2. Mini-League Captain Tracker")
        print("3. Differential Hunter")
        print("4. Automatic Transfer Suggester")
        print("5. Predict Top Performers (Next GW)")
        print("6. Wildcard / Dream Team Optimizer")
        print("7. Predicted League Standings (Next GW)")
        print("8. Player Rotation & Injury Risk")
        print("9. Smart Captaincy Suggester (Your Team)")
        print("0. Form vs. Fixture Quadrant Analysis")
        print("q. Quit")
        
        choice = input("Enter your choice: ").strip()

        try:
            if choice == '1':
                show_my_team_summary(team_id, current_gameweek, player_map)
            elif choice == '2':
                show_league_captains(league_id, current_gameweek, player_map)
            elif choice == '3':
                show_differential_hunter(bootstrap_data, team_map, position_map)
            elif choice == '4':
                show_transfer_suggester(team_id, current_gameweek, bootstrap_data, fixtures_data, team_map, position_map)
            elif choice == '5':
                show_predicted_points(bootstrap_data, fixtures_data, current_gameweek)
            elif choice == '6':
                show_dream_team_optimizer(bootstrap_data, fixtures_data, current_gameweek, position_map)
            elif choice == '7':
                show_league_predictions(league_id, current_gameweek, bootstrap_data, fixtures_data)
            elif choice == '8':
                show_injury_risk_analyzer(bootstrap_data, team_map, position_map)
            elif choice == '9':
                show_captaincy_suggester(team_id, current_gameweek, bootstrap_data, fixtures_data)
            elif choice == '0':
                show_quadrant_analysis(bootstrap_data, fixtures_data, current_gameweek, team_map)
            elif choice.lower() == 'q':
                print("Exiting FPL Toolkit. Goodbye!")
                break
            else:
                print("Invalid choice. Please try again.")
        except requests.exceptions.RequestException as e:
            print(f"\nAn error occurred while fetching data: {e}")
        except KeyError:
            print("\nCould not parse the data. The FPL API structure might have changed.")

if __name__ == "__main__":
    main()
