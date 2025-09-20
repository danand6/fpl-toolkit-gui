"""Lightweight machine-learning helpers for FPL predictions.

The module implements a small linear regression model trained on recent
match history for each player. It avoids third-party ML dependencies by
using vanilla Python gradient descent with L2 regularisation and feature
normalisation. The goal is to generate more data-driven predictions that can
run on modest hardware.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Sequence

DEFAULT_HISTORY_WINDOW = 5


@dataclass
class RegressionModel:
    weights: List[float]
    bias: float
    feature_means: List[float]
    feature_stds: List[float]
    name: str = "LinearRegressor"
    samples: int = 0

    def predict(self, features: Sequence[float]) -> float:
        vector = _normalise(features, self.feature_means, self.feature_stds)
        prediction = self.bias
        for weight, value in zip(self.weights, vector):
            prediction += weight * value
        return prediction

    def to_dict(self) -> dict:
        return {
            "weights": self.weights,
            "bias": self.bias,
            "feature_means": self.feature_means,
            "feature_stds": self.feature_stds,
            "name": self.name,
            "samples": self.samples,
        }


def train_points_model(player_histories: Iterable[dict], history_window: int = DEFAULT_HISTORY_WINDOW) -> dict:
    """Train a linear model using sliding windows of past performance.

    Parameters
    ----------
    player_histories:
        Iterable of dictionaries with keys ``player`` (bootstrap element) and
        ``history`` (list of element-summary history entries).
    history_window:
        Number of past matches to aggregate when building each feature row.
    """
    samples, targets = _build_training_samples(player_histories, history_window)
    if not samples:
        raise RuntimeError("No training samples available for AI model")

    model = _gradient_descent_fit(samples, targets)
    model.samples = len(samples)
    return model.to_dict()


def predict_upcoming_points(model_dict: dict, player_histories: Iterable[dict], history_window: int) -> List[dict]:
    model = RegressionModel(
        weights=model_dict['weights'],
        bias=model_dict['bias'],
        feature_means=model_dict['feature_means'],
        feature_stds=model_dict['feature_stds'],
        name=model_dict.get('name', 'LinearRegressor'),
        samples=model_dict.get('samples', 0),
    )

    predictions = []
    for entry in player_histories:
        history = entry['history']
        if len(history) < history_window:
            continue
        window = history[-history_window:]
        features, avg_points = _summarise_window(window)
        predicted = model.predict(features)
        predictions.append({
            'player': entry['player'],
            'predicted': max(predicted, 0.0),
            'avg_points': avg_points,
        })

    predictions.sort(key=lambda item: item['predicted'], reverse=True)
    return predictions


# ---------------------------------------------------------------------------
# Training helpers
# ---------------------------------------------------------------------------

FEATURE_FIELDS = (
    'minutes',
    'total_points',
    'goals_scored',
    'assists',
    'clean_sheets',
    'bonus',
    'influence',
    'creativity',
    'threat',
    'ict_index',
)


def _build_training_samples(player_histories: Iterable[dict], history_window: int):
    feature_rows: List[List[float]] = []
    targets: List[float] = []

    for entry in player_histories:
        history = entry['history']
        if len(history) <= history_window:
            continue

        for idx in range(history_window, len(history)):
            window = history[idx - history_window:idx]
            next_match = history[idx]
            features, _ = _summarise_window(window)
            target = float(next_match.get('total_points', 0) or 0)
            feature_rows.append(features)
            targets.append(target)

    return feature_rows, targets


def _summarise_window(matches: Sequence[dict]) -> tuple[List[float], float]:
    total_points = 0.0
    aggregated: List[float] = []

    for field in FEATURE_FIELDS:
        values: List[float] = []
        for match in matches:
            raw = match.get(field, 0)
            if raw in (None, ''):
                raw = 0
            try:
                values.append(float(raw))
            except (ValueError, TypeError):
                values.append(0.0)
        if not values:
            aggregated.append(0.0)
        else:
            aggregated.append(sum(values) / len(values))

    for match in matches:
        try:
            total_points += float(match.get('total_points', 0) or 0)
        except (ValueError, TypeError):
            total_points += 0.0

    avg_points = total_points / len(matches) if matches else 0.0
    # Normalise minutes to a 0-1 range by dividing by 90
    if aggregated:
        aggregated[0] = aggregated[0] / 90.0
    return aggregated, avg_points


# ---------------------------------------------------------------------------
# Linear regression implementation
# ---------------------------------------------------------------------------

def _gradient_descent_fit(features: Sequence[Sequence[float]], targets: Sequence[float], *, learning_rate: float = 0.05, epochs: int = 400, l2: float = 0.01) -> RegressionModel:
    n_samples = len(features)
    n_features = len(features[0])

    means = [0.0] * n_features
    stds = [0.0] * n_features

    for j in range(n_features):
        column = [row[j] for row in features]
        mean_j = sum(column) / n_samples
        means[j] = mean_j
        variance = sum((value - mean_j) ** 2 for value in column) / max(n_samples - 1, 1)
        stds[j] = variance ** 0.5 if variance > 0 else 1.0

    normalised = [_normalise(row, means, stds) for row in features]

    weights = [0.0] * n_features
    bias = 0.0

    for _ in range(epochs):
        grad_w = [0.0] * n_features
        grad_b = 0.0

        for row, target in zip(normalised, targets):
            prediction = bias
            for weight, value in zip(weights, row):
                prediction += weight * value
            error = prediction - target
            grad_b += error
            for j, value in enumerate(row):
                grad_w[j] += error * value + l2 * weights[j]

        bias -= learning_rate * grad_b / n_samples
        for j in range(n_features):
            weights[j] -= learning_rate * grad_w[j] / n_samples

    return RegressionModel(weights=weights, bias=bias, feature_means=means, feature_stds=stds, samples=n_samples)


def _normalise(features: Sequence[float], means: Sequence[float], stds: Sequence[float]) -> List[float]:
    vector: List[float] = []
    for value, mean, std in zip(features, means, stds):
        if std == 0:
            vector.append(0.0)
        else:
            vector.append((value - mean) / std)
    return vector
