"""Lightweight intent classifier without external ML dependencies."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable

_DEFAULT_INTENTS: Dict[str, Iterable[str]] = {
    "my-team-summary": [
        "show my team",
        "display my squad",
        "what is my lineup",
        "give me squad summary",
    ],
    "ai-team-performance": [
        "how will my team perform next week",
        "predict my squad score",
        "forecast my team points",
        "how did i score this week",
        "how did i do this week",
    ],
    "smart-captaincy": [
        "who should i captain",
        "captain suggestion",
        "best captain pick",
    ],
    "current-captain": [
        "who is my captain",
        "current captain",
        "who is captain right now",
    ],
    "chip-advice": [
        "when should i use my chips",
        "chip strategy",
        "bench boost or triple captain",
        "should i free hit",
        "wildcard advice",
    ],
    "transfer-suggester": [
        "recommend a transfer",
        "who should i sell",
        "transfer advice",
    ],
    "injury-risk": [
        "any injury risks",
        "who is flagged",
        "players with injury",
    ],
    "ai-predictions": [
        "ai top performers",
        "who will score the most",
        "best players next week",
    ],
    "league-head-to-head": [
        "will i beat",
        "head to head",
        "versus in my league",
    ],
    "league-current": [
        "current league standings",
        "show table now",
        "league position right now",
    ],
    "league-predictions": [
        "predict my league",
        "league standings forecast",
    ],
    "differential-hunter": [
        "show me differentials",
        "low owned players",
    ],
    "predicted-top-performers": [
        "predict top performers",
        "top scorers next week",
    ],
    "dream-team": [
        "build dream team",
        "wildcard squad",
    ],
    "quadrant-analysis": [
        "form vs fixture",
        "quadrant analysis",
    ],
}

_TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9']+")


def _tokenize(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN_PATTERN.findall(text)]


@dataclass
class ClassificationResult:
    intent: str | None
    score: float


class IntentClassifier:
    def __init__(self, intent_examples: Dict[str, Iterable[str]] | None = None):
        self.intent_examples = intent_examples or _DEFAULT_INTENTS
        self.intent_vectors: Dict[str, Dict[str, float]] = {}
        self.idf: Dict[str, float] = {}
        self._fit()

    def _fit(self) -> None:
        documents: list[list[str]] = []
        labels: list[str] = []

        for intent, examples in self.intent_examples.items():
            for example in examples:
                tokens = _tokenize(example)
                if not tokens:
                    continue
                documents.append(tokens)
                labels.append(intent)

        if not documents:
            raise ValueError("No intent examples provided")

        doc_freq: Dict[str, int] = defaultdict(int)
        for tokens in documents:
            for token in set(tokens):
                doc_freq[token] += 1

        total_docs = len(documents)
        self.idf = {
            token: math.log((total_docs + 1) / (freq + 1)) + 1.0
            for token, freq in doc_freq.items()
        }

        intent_vectors: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        intent_counts: Dict[str, int] = defaultdict(int)

        for tokens, label in zip(documents, labels):
            tf = Counter(tokens)
            norm = math.sqrt(sum((tf[token] * self.idf[token]) ** 2 for token in tf)) or 1.0
            for token, count in tf.items():
                weight = (count * self.idf[token]) / norm
                intent_vectors[label][token] += weight
            intent_counts[label] += 1

        for intent, vector in intent_vectors.items():
            count = max(intent_counts[intent], 1)
            self.intent_vectors[intent] = {token: weight / count for token, weight in vector.items()}

    def classify(self, text: str, threshold: float = 0.3) -> ClassificationResult:
        tokens = _tokenize(text)
        if not tokens:
            return ClassificationResult(intent=None, score=0.0)

        tf = Counter(tokens)
        vec = {}
        norm = 0.0
        for token, count in tf.items():
            idf = self.idf.get(token)
            if idf is None:
                continue
            weight = count * idf
            vec[token] = weight
            norm += weight * weight
        norm = math.sqrt(norm) or 1.0
        for token in vec:
            vec[token] /= norm

        best_intent = None
        best_score = 0.0

        for intent, centroid in self.intent_vectors.items():
            score = _cosine_similarity(vec, centroid)
            if score > best_score:
                best_score = score
                best_intent = intent

        if best_score >= threshold:
            return ClassificationResult(intent=best_intent, score=best_score)
        return ClassificationResult(intent=None, score=best_score)


def _cosine_similarity(vec_a: Dict[str, float], vec_b: Dict[str, float]) -> float:
    numerator = 0.0
    for token, weight in vec_a.items():
        numerator += weight * vec_b.get(token, 0.0)
    denom_a = math.sqrt(sum(weight * weight for weight in vec_a.values())) or 1.0
    denom_b = math.sqrt(sum(weight * weight for weight in vec_b.values())) or 1.0
    return numerator / (denom_a * denom_b)


_classifier: IntentClassifier | None = None


def get_intent_classifier() -> IntentClassifier:
    global _classifier
    if _classifier is None:
        _classifier = IntentClassifier()
    return _classifier
