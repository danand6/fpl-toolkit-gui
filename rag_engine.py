"""Lightweight retrieval-augmented generation helpers for the FPL assistant."""

from __future__ import annotations

from dataclasses import dataclass
from collections import Counter, defaultdict
import math
import re
from typing import Iterable, List

import fpl_logic

try:
    import ai_models
except ImportError:  # pragma: no cover - optional dependency during initialisation
    ai_models = None

_TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9']+")


def _tokenize(text: str) -> List[str]:
    return [token.lower() for token in _TOKEN_PATTERN.findall(text)]


@dataclass
class Document:
    id: str
    title: str
    text: str
    metadata: dict
    tokens: Counter


class KnowledgeBase:
    def __init__(self, documents: Iterable[Document], extras: dict | None = None):
        self.documents = list(documents)
        self.extras = extras or {}
        self.total_docs = len(self.documents)
        self.doc_freq = defaultdict(int)
        for doc in self.documents:
            for token in doc.tokens:
                self.doc_freq[token] += 1


def _find_next_fixture(team_id: int, fixtures_data: list, current_gameweek: int) -> tuple[str, str] | tuple[None, None]:
    upcoming = [f for f in fixtures_data if f.get('event') and f['event'] >= current_gameweek]
    upcoming.sort(key=lambda f: f.get('event', 999))
    for fixture in upcoming:
        if fixture['team_h'] == team_id:
            return ('home', fixture['team_a'])
        if fixture['team_a'] == team_id:
            return ('away', fixture['team_h'])
    return None, None


def build_knowledge_base(context: dict, player_limit: int = 200, *, team_id: int | None = None, league_id: int | None = None) -> KnowledgeBase:
    bootstrap = context['bootstrap']
    fixtures = context['fixtures']
    current_gameweek = context['current_gameweek']
    team_map = context['team_map']
    position_map = context['position_map']

    predictions = fpl_logic.get_predictions(
        bootstrap,
        fixtures,
        current_gameweek,
    )

    active_players = [
        player for player in bootstrap['elements']
        if player.get('status', 'a') == 'a' and player.get('minutes', 0) > 0
    ]

    active_players.sort(key=lambda p: float(p.get('form', 0) or 0), reverse=True)
    active_players = active_players[:player_limit]

    documents: List[Document] = []

    for player in active_players:
        player_id = player['id']
        name = player['web_name']
        team_id = player['team']
        team_name = team_map.get(team_id, 'Unknown')
        position = position_map.get(player.get('element_type'), 'UNK')
        price = player.get('now_cost', 0) / 10.0
        form = player.get('form', '0')
        total_points = player.get('total_points', 0)
        ict_index = player.get('ict_index', '0')
        prediction = predictions.get(player_id, 0.0)
        chance = player.get('chance_of_playing_next_round')
        status = player.get('status', 'a')
        news = player.get('news', '')

        home_away, opponent_id = _find_next_fixture(team_id, fixtures, current_gameweek)
        if opponent_id:
            opponent = team_map.get(opponent_id, 'Unknown')
            fixture_text = f"faces {opponent} ({'home' if home_away == 'home' else 'away'})"
        else:
            fixture_text = "has no scheduled fixture"

        injury_text = ''
        if status != 'a' or (chance is not None and chance < 100):
            chance_text = f"{chance}% chance" if chance is not None else 'flagged'
            injury_text = f". Availability: {chance_text}. {news}".strip()

        text = (
            f"{name} is a {position} for {team_name}. Current form {form}, total points {total_points}, "
            f"ICT index {ict_index}. Price £{price:.1f}m. Predicted points next GW {prediction:.2f}. "
            f"Next {fixture_text}{injury_text}."
        )

        documents.append(Document(
            id=f"player-{player_id}",
            title=f"{name} ({team_name})",
            text=text,
            metadata={
                'doc_type': 'player',
                'player_id': player_id,
                'team': team_name,
                'position': position,
                'price': price,
                'prediction': prediction,
                'form': form,
                'total_points': total_points,
                'fixture': fixture_text,
                'injury_text': injury_text,
            },
            tokens=Counter(_tokenize(text)),
        ))

    teams = bootstrap['teams']
    for team in teams:
        doc_text = (
            f"{team['name']} have scored {team['strength_attack_home']} attack strength at home and "
            f"{team['strength_attack_away']} away. Defence strength home {team['strength_defence_home']}, "
            f"away {team['strength_defence_away']}."
        )
        documents.append(Document(
            id=f"team-{team['id']}",
            title=f"Team outlook: {team['name']}",
            text=doc_text,
            metadata={'doc_type': 'team', 'team_id': team['id']},
            tokens=Counter(_tokenize(doc_text)),
        ))

    ai_bundle = None
    if ai_models is not None:
        try:
            ai_bundle = compute_ai_predictions(context, player_limit=player_limit)
            documents.extend(_build_ai_prediction_docs(ai_bundle))
        except RuntimeError:
            ai_bundle = None

    if team_id:
        transfer_doc = _build_transfer_doc(context, team_id)
        if transfer_doc:
            documents.append(transfer_doc)
        if ai_bundle:
            team_projection_doc = _build_team_projection_doc(context, team_id, ai_bundle)
            if team_projection_doc:
                documents.append(team_projection_doc)
        chip_doc = _build_chip_doc(context, team_id, fixtures_data=context['fixtures'])
        if chip_doc:
            documents.append(chip_doc)

    if league_id:
        head_to_head_doc = _build_head_to_head_doc(context, league_id)
        if head_to_head_doc:
            documents.append(head_to_head_doc)
        current_doc = _build_current_league_doc(context, league_id)
        if current_doc:
            documents.append(current_doc)

    extras = {'ai_bundle': ai_bundle, 'team_id': team_id, 'league_id': league_id}
    return KnowledgeBase(documents, extras=extras)


def compute_ai_predictions(context: dict, player_limit: int = 200) -> dict:
    if ai_models is None:
        raise RuntimeError("AI prediction module not available")

    bootstrap = context['bootstrap']

    active_players = [
        player for player in bootstrap['elements']
        if player.get('status', 'a') == 'a' and player.get('minutes', 0) > 0
    ]

    if not active_players:
        raise RuntimeError("No eligible players available for AI predictions")

    def player_priority(player: dict) -> float:
        try:
            return float(player.get('form', 0))
        except (TypeError, ValueError):
            return 0.0

    shortlisted = sorted(active_players, key=player_priority, reverse=True)[:player_limit]

    player_histories = []
    for player in shortlisted:
        try:
            summary = fpl_logic.get_element_summary(player['id'])
        except Exception:
            continue
        history = summary.get('history', [])
        if len(history) < 6:
            continue
        player_histories.append({'player': player, 'history': history})

    if len(player_histories) < 15:
        raise RuntimeError("Insufficient history to train AI model")

    model = ai_models.train_points_model(player_histories, history_window=5)
    predictions = ai_models.predict_upcoming_points(model, player_histories, history_window=5)

    team_map = context['team_map']
    position_map = context['position_map']

    prediction_map = {}
    top_predictions = []

    for index, item in enumerate(predictions):
        player = item['player']
        entry = {
            'player': player,
            'player_id': player['id'],
            'name': player.get('web_name', 'Unknown'),
            'team': team_map.get(player.get('team'), 'N/A'),
            'position': position_map.get(player.get('element_type'), 'UNK'),
            'predicted': item['predicted'],
            'avg_points': item.get('avg_points', 0.0),
            'form': player.get('form', '0'),
        }
        prediction_map[player['id']] = entry
        if index < 30:
            top_predictions.append(entry)

    return {
        'model': model,
        'prediction_map': prediction_map,
        'predictions': top_predictions,
        'raw_predictions': predictions,
        'history_window': 5,
        'trained_samples': model.get('samples', 0),
    }


def _build_ai_prediction_docs(ai_bundle: dict) -> List[Document]:
    documents: List[Document] = []
    top_summary_lines = []

    for entry in ai_bundle['predictions']:
        summary = (
            f"{entry['name']} ({entry['team']}) predicted {entry['predicted']:.2f} pts, "
            f"avg last 5 {entry['avg_points']:.2f}, form {entry['form']}."
        )
        top_summary_lines.append(summary)

        documents.append(Document(
            id=f"ai-player-{entry['player_id']}",
            title=f"AI prediction: {entry['name']}",
            text=summary,
            metadata={
                'doc_type': 'ai_player',
                'player_id': entry['player_id'],
                'team': entry['team'],
                'position': entry['position'],
                'predicted': entry['predicted'],
                'avg_points': entry['avg_points'],
                'form': entry['form'],
            },
            tokens=Counter(_tokenize(summary)),
        ))

    overview_text = "Top AI predictions: " + " ".join(top_summary_lines[:10])
    documents.append(Document(
        id="ai-overview",
        title="AI Top Performer Overview",
        text=overview_text,
        metadata={
            'doc_type': 'ai_overview',
            'model': ai_bundle['model'].get('name', 'LinearRegressor'),
            'trained_samples': ai_bundle['model'].get('samples', 0),
        },
        tokens=Counter(_tokenize(overview_text)),
    ))

    return documents


def compute_team_projection(context: dict, team_id: int, ai_bundle: dict) -> dict | None:
    try:
        picks = fpl_logic.get_team_picks(team_id, context['current_gameweek'])
    except Exception:
        return None

    prediction_map = ai_bundle.get('prediction_map', {})
    fallback_predictions = fpl_logic.get_predictions(
        context['bootstrap'],
        context['fixtures'],
        context['current_gameweek'],
    )

    player_lookup = context['player_lookup']
    position_map = context['position_map']
    team_map = context['team_map']

    starters = []
    bench = []
    predicted_total = 0.0

    for pick in picks['picks']:
        player_id = pick['element']
        multiplier = pick.get('multiplier', 1)
        player_data = player_lookup.get(player_id, {})
        base_entry = prediction_map.get(player_id)
        predicted = base_entry['predicted'] if base_entry else fallback_predictions.get(player_id, 0.0)
        name = player_data.get('web_name', 'Unknown')
        team = team_map.get(player_data.get('team'), 'N/A')
        position = position_map.get(player_data.get('element_type'), 'UNK')

        detail = {
            'player_id': player_id,
            'name': name,
            'team': team,
            'position': position,
            'predicted': predicted,
            'multiplier': multiplier,
            'is_captain': bool(pick.get('is_captain')),
            'is_vice': bool(pick.get('is_vice_captain')),
        }

        if multiplier > 0:
            predicted_total += predicted * multiplier
            starters.append(detail)
        else:
            bench.append(detail)

    return {
        'predicted_total': predicted_total,
        'starters': starters,
        'bench': bench,
        'gameweek': context['current_gameweek'],
    }


def _build_team_projection_doc(context: dict, team_id: int, ai_bundle: dict) -> Document | None:
    projection = compute_team_projection(context, team_id, ai_bundle)
    if not projection:
        return None

    lines = [
        f"Predicted squad total for GW {projection['gameweek']}: {projection['predicted_total']:.2f} points.",
        "Starters:",
    ]

    for detail in projection['starters']:
        note = ' (C)' if detail['is_captain'] else ' (V)' if detail['is_vice'] else ''
        multiplier_text = f" x{detail['multiplier']}" if detail['multiplier'] > 1 else ''
        lines.append(
            f"- {detail['name']} ({detail['team']}, {detail['position']}){note}: {detail['predicted']:.2f} pts{multiplier_text}"
        )

    if projection['bench']:
        lines.append('Bench:')
        for detail in projection['bench']:
            lines.append(
                f"- {detail['name']} ({detail['team']}, {detail['position']}): {detail['predicted']:.2f} pts"
            )

    text = "\n".join(lines)

    return Document(
        id='team-projection',
        title=f"Squad projection GW {projection['gameweek']}",
        text=text,
        metadata={
            'doc_type': 'team_projection',
            'predicted_total': projection['predicted_total'],
            'starters': projection['starters'],
            'bench': projection['bench'],
            'gameweek': projection['gameweek'],
        },
        tokens=Counter(_tokenize(text)),
    )


def _build_transfer_doc(context: dict, team_id: int) -> Document | None:
    try:
        text = fpl_logic.get_transfer_suggester_string(
            team_id,
            context['current_gameweek'],
            context['bootstrap'],
            context['fixtures'],
            context['team_map'],
            context['position_map'],
        )
    except Exception:
        return None

    if not text:
        return None

    return Document(
        id="transfer-suggestion",
        title="Recommended transfer",
        text=text,
        metadata={'doc_type': 'transfer'},
        tokens=Counter(_tokenize(text)),
    )


def parse_league_predictions(text: str) -> dict:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    league_name = None
    results = []

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

    if start_index is not None:
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
            results.append({
                'rank': rank,
                'manager': manager,
                'predicted_score': score,
            })

    return {'league_name': league_name, 'results': results}


def _build_head_to_head_doc(context: dict, league_id: int) -> Document | None:
    try:
        text = fpl_logic.get_league_predictions_string(
            league_id,
            context['current_gameweek'],
            context['bootstrap'],
            context['fixtures'],
        )
    except Exception:
        return None

    if not text:
        return None

    parsed = parse_league_predictions(text)

    return Document(
        id="league-head-to-head",
        title="Upcoming league predictions",
        text=text,
        metadata={
            'doc_type': 'head_to_head',
            'league_id': league_id,
            'league_name': parsed.get('league_name'),
            'results': parsed.get('results', []),
        },
        tokens=Counter(_tokenize(text)),
    )


def _build_current_league_doc(context: dict, league_id: int) -> Document | None:
    try:
        league_data = fpl_logic.get_league_data(league_id)
    except Exception:
        return None

    standings = league_data.get('standings', {}).get('results', [])
    if not standings:
        return None

    lines = []
    for entry in standings[:20]:
        lines.append(
            f"#{entry.get('rank')} {entry.get('player_name')} ({entry.get('entry_name')}): {entry.get('total')} pts"
        )

    text = "Current standings: " + "; ".join(lines)

    return Document(
        id="league-current-standings",
        title="Current league standings",
        text=text,
        metadata={
            'doc_type': 'league_current',
            'league_id': league_id,
            'league_name': league_data.get('league', {}).get('name'),
            'standings': standings,
        },
        tokens=Counter(_tokenize(text)),
    )


def _build_chip_doc(context: dict, team_id: int, fixtures_data: list) -> Document | None:
    try:
        text = fpl_logic.get_chip_advice_string(
            team_id,
            context['current_gameweek'],
            context['bootstrap'],
            fixtures_data,
            context['team_map'],
            context['position_map']
        )
    except Exception:
        return None

    return Document(
        id='chip-advice',
        title='Chip strategy advice',
        text=text,
        metadata={'doc_type': 'chip'},
        tokens=Counter(_tokenize(text)),
    )


def retrieve(query: str, kb: KnowledgeBase, top_k: int = 5) -> List[Document]:
    if kb.total_docs == 0:
        return []

    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    query_counter = Counter(query_tokens)
    scored_docs = []

    for doc in kb.documents:
        score = 0.0
        for token, q_tf in query_counter.items():
            if token not in doc.tokens:
                continue
            tf = doc.tokens[token]
            idf = math.log((kb.total_docs + 1) / (kb.doc_freq[token] + 1)) + 1
            score += q_tf * tf * idf
        if score > 0:
            scored_docs.append((score, doc))

    scored_docs.sort(key=lambda item: item[0], reverse=True)
    return [doc for _, doc in scored_docs[:top_k]]


def generate_answer(query: str, documents: List[Document]) -> dict:
    if not documents:
        return {
            'text': "I couldn't find anything relevant. Try being more specific about players or teams.",
            'citations': [],
        }

    lines = ["Here's what I found:"]
    citations = []

    for index, doc in enumerate(documents, 1):
        meta = doc.metadata
        doc_type = meta.get('doc_type')

        if doc_type == 'player':
            bullet = (
                f"{index}. {doc.title}: form {meta['form']}, total points {meta['total_points']}, "
                f"next {meta['fixture']}. Model prediction {meta['prediction']:.2f} pts."
            )
        elif doc_type == 'ai_player':
            bullet = (
                f"{index}. AI favours {doc.title} with {meta['predicted']:.2f} pts (avg {meta['avg_points']:.2f}, form {meta['form']})."
            )
        elif doc_type == 'ai_overview':
            bullet = f"{index}. {doc.text}"
        elif doc_type == 'transfer':
            bullet = f"{index}. Transfer insight: {doc.text[:300]}..."
        elif doc_type == 'team_projection':
            bullet = (
                f"{index}. Squad projection: {meta['predicted_total']:.2f} pts next GW; "
                f"key starters include {', '.join(d['name'] for d in meta['starters'][:3])}."
            )
            bench = meta.get('bench') or []
            if bench:
                bench_snippet = ', '.join(d['name'] for d in bench[:3])
                bullet += f" Bench depth: {bench_snippet}."
        elif doc_type == 'head_to_head':
            top_results = meta.get('results', [])[:3]
            summary = ", ".join(f"{r['manager']} {r['predicted_score']:.1f}" for r in top_results)
            bullet = f"{index}. League projection: {summary}" if summary else f"{index}. {doc.title}"
        elif doc_type == 'league_current':
            top_rows = meta.get('standings', [])[:3]
            summary = ", ".join(f"#{row['rank']} {row['player_name']} {row['total']} pts" for row in top_rows)
            bullet = f"{index}. Current league standings: {summary}" if summary else f"{index}. {doc.title}"
        elif doc_type == 'chip':
            bullet = f"{index}. Chip overview: {doc.text.splitlines()[1] if '\n' in doc.text else doc.text[:200]}"
        else:
            bullet = f"{index}. {doc.title}: {doc.text[:250]}..."

        note = meta.get('note')
        if note:
            bullet += f" {note}"

        lines.append(bullet)
        citations.append({
            'id': doc.id,
            'title': doc.title,
        })

    return {
        'text': "\n".join(lines),
        'citations': citations,
    }
