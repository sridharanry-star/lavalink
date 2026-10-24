from __future__ import annotations
import math
import hashlib
import re
import unicodedata
from typing import List, Dict, Any, Optional

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    np = None
    HAS_NUMPY = False

class EmbeddingEngine:
    """Builds deterministic multilingual feature vectors for track/session similarity.

    Uses weighted title, artist, album, language, and mood features with character
    n-grams; this is a lightweight lexical similarity model, not a learned language model.
    """

    DIMENSION = 128

    def __init__(self, dimension: int = DIMENSION):
        self.dimension = dimension
        self._track_cache: Dict[tuple, Any] = {}

    def _new_vector(self):
        if HAS_NUMPY and np is not None:
            return np.zeros(self.dimension, dtype=np.float32)
        return [0.0] * self.dimension

    def _add_feature(self, vec: Any, feature: str, weight: float) -> None:
        text_start = min(8, max(0, self.dimension // 8))
        text_dimensions = self.dimension - text_start
        if text_dimensions <= 0 or not feature:
            return
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "little")
        slot = text_start + value % text_dimensions
        sign = 1.0 if (value >> 63) & 1 else -1.0
        vec[slot] += sign * weight

    def _add_text(self, vec: Any, field: str, text: str, weight: float) -> None:
        normalized = unicodedata.normalize("NFKC", str(text or "")).casefold()
        tokens = re.findall(r"[^\W_]+", normalized, flags=re.UNICODE)
        for token in tokens:
            self._add_feature(vec, f"{field}:word:{token}", weight)
        for left, right in zip(tokens, tokens[1:]):
            self._add_feature(vec, f"{field}:pair:{left} {right}", weight * 0.65)

        if field == "title":
            for token in tokens:
                if len(token) < 3:
                    continue
                for size in (3, 4):
                    for start in range(max(0, len(token) - size + 1)):
                        self._add_feature(vec, f"title:char:{token[start:start + size]}", weight * 0.12)

    def embed_text(self, text: str) -> Any:
        """Projects textual metadata into a dense unit-normalized embedding vector."""
        if not text:
            return self._new_vector()

        vec = self._new_vector()
        self._add_text(vec, "text", text, 1.0)

        if HAS_NUMPY and np is not None:
            norm = float(np.linalg.norm(vec))
            if norm > 1e-6:
                vec /= norm
            return vec
        else:
            norm = math.sqrt(sum(x * x for x in vec))
            if norm > 1e-6:
                return [x / norm for x in vec]
            return vec

    def embed_track(self, track: dict) -> Any:
        """Embeds a music track from title, artist, album, language, and mood metadata."""
        track_id = str(track.get('id') or track.get('yt_video_id') or track.get('spotify_id') or track.get('url') or '')
        title = track.get('title', '')
        artist = track.get('uploader') or track.get('artist') or ''
        album = track.get('album_name') or track.get('album') or ''
        lang = track.get('language') or ''
        mood = track.get('mood') or ''
        dur = float(track.get('duration') or 0.0)
        cache_key = (
            track_id, str(title), str(artist), str(album), str(lang), str(mood), dur
        )
        if track_id and cache_key in self._track_cache:
            return self._track_cache[cache_key]

        vec = self._new_vector()
        self._add_text(vec, "title", title, 1.7)
        self._add_text(vec, "artist", artist, 1.25)
        self._add_text(vec, "album", album, 0.55)
        self._add_text(vec, "language", lang, 1.0)
        self._add_text(vec, "mood", mood, 0.9)

        if self.dimension:
            vec[0] = 0.25 * math.tanh(dur / 240.0) if dur > 0 else 0.0

        if HAS_NUMPY and np is not None:
            norm = float(np.linalg.norm(vec))
            if norm > 1e-6:
                vec /= norm
        else:
            norm = math.sqrt(sum(x * x for x in vec))
            if norm > 1e-6:
                vec = [x / norm for x in vec]

        if track_id:
            if len(self._track_cache) > 20000:
                keys_to_remove = list(self._track_cache.keys())[:10000]
                for k in keys_to_remove:
                    self._track_cache.pop(k, None)
            self._track_cache[cache_key] = vec

        return vec

    def compute_session_vector(self, recent_tracks: List[dict], decay: float = 0.75) -> Any:
        """Computes the Exponential Moving Average (EMA) vector representing the session's active vibe."""
        if not recent_tracks:
            if HAS_NUMPY and np is not None:
                return np.zeros(self.dimension, dtype=np.float32)
            return [0.0] * self.dimension

        if HAS_NUMPY and np is not None:
            session_vec = np.zeros(self.dimension, dtype=np.float32)
        else:
            session_vec = [0.0] * self.dimension

        weight = 1.0
        total_weight = 0.0

        for t in reversed(recent_tracks[-10:]):
            t_vec = self.embed_track(t)
            if HAS_NUMPY and np is not None:
                session_vec += weight * t_vec
            else:
                session_vec = [s + weight * val for s, val in zip(session_vec, t_vec)]
            total_weight += weight
            weight *= decay

        if total_weight > 0:
            if HAS_NUMPY and np is not None:
                session_vec /= total_weight
            else:
                session_vec = [s / total_weight for s in session_vec]

        if HAS_NUMPY and np is not None:
            norm = float(np.linalg.norm(session_vec))
            if norm > 1e-6:
                session_vec /= norm
        else:
            norm = math.sqrt(sum(x * x for x in session_vec))
            if norm > 1e-6:
                session_vec = [x / norm for x in session_vec]

        return session_vec

    def score_candidates_by_similarity(self, session_vec: Any, candidates: List[dict]) -> List[float]:
        """Returns cosine similarity for each candidate in its original order."""
        if not candidates:
            return []

        if HAS_NUMPY and np is not None and isinstance(session_vec, np.ndarray):
            if np.linalg.norm(session_vec) < 1e-6:
                return [0.0 for _ in candidates]
            cand_matrix = np.vstack([self.embed_track(c) for c in candidates])
            similarities = np.dot(cand_matrix, session_vec)
            return similarities.tolist()
        else:
            session_norm = math.sqrt(sum(value * value for value in session_vec))
            if session_norm < 1e-6:
                return [0.0 for _ in candidates]
            scored = []
            for c in candidates:
                cand_vec = self.embed_track(c)
                cand_norm = math.sqrt(sum(value * value for value in cand_vec))
                dot = sum(a * b for a, b in zip(cand_vec, session_vec))
                scored.append(dot / (cand_norm * session_norm) if cand_norm > 1e-6 else 0.0)
            return scored

    def rank_candidates_by_similarity(self, session_vec: Any, candidates: List[dict]) -> List[tuple[float, dict]]:
        """Ranks candidates by cosine similarity against the session vector."""
        scored = list(zip(self.score_candidates_by_similarity(session_vec, candidates), candidates))
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored
