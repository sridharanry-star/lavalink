from __future__ import annotations
import random
from typing import List, Dict, Any, Optional
import re
import unicodedata

def _normalize_title(title: str) -> str:
    """Normalize song title for deduplication matching."""
    t = unicodedata.normalize("NFKC", str(title or "")).casefold()
    t = re.sub(r'[\(\[].*?[\)\]]', ' ', t)
    t = re.sub(r'[^\w\s]', ' ', t, flags=re.UNICODE)
    return ' '.join(t.split())


def _normalize_artist(artist: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(artist or "")).casefold()
    normalized = re.sub(r"\s*-\s*topic\b", " ", normalized)
    normalized = re.sub(r"\bvevo\b", " ", normalized)
    normalized = re.sub(r"[^\w\s]", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())

class ContextualBandit:
    """Context-aware exploration selector with duplicate and artist-fatigue filters."""

    def __init__(self, explore_rate: float = 0.10):
        self.explore_rate = explore_rate

    def select_best_track(
        self,
        scored_candidates: List[tuple[float, dict]],
        session_state: Any = None,
        played_history_set: Optional[set] = None
    ) -> Optional[dict]:
        """Selects the optimal track using Contextual Bandit & MMR diversity."""
        if not scored_candidates:
            return None

        played_history_set = played_history_set or set()

        target_lang = getattr(session_state, 'user_locked_language', None) or getattr(session_state, 'hard_language', None)
        if not target_lang and session_state and getattr(session_state, 'language_established', False):
            target_lang = getattr(session_state, 'active_language', None)

        act_lang = None
        if target_lang and str(target_lang).strip().casefold() not in ('unknown', 'auto', 'english'):
            act_lang = str(target_lang).strip().casefold()

        valid_candidates: List[tuple[float, dict]] = []
        for score, entry in scored_candidates:
            if not entry or not entry.get('title'):
                continue

            if score <= -100.0:
                continue

            if act_lang:
                cand_lang = str(entry.get('language') or 'unknown').strip().casefold()
                if cand_lang != act_lang and not entry.get('language_confirmed'):
                    continue

            track_id = str(entry.get('id') or entry.get('yt_video_id') or entry.get('spotify_id') or '')
            url = entry.get('url') or ''
            norm_title = _normalize_title(entry.get('title'))

            if (track_id and track_id in played_history_set) or \
               (url and url in played_history_set) or \
               (norm_title and norm_title in played_history_set):
                continue

            uploader = _normalize_artist(entry.get('artist') or entry.get('uploader') or '')
            if session_state and getattr(session_state, 'recent_artists', None):
                recent_artists = [_normalize_artist(a) for a in session_state.recent_artists]
                if recent_artists and recent_artists[-1] == uploader:
                    score -= 40.0
                elif len(recent_artists) >= 2 and uploader in recent_artists[-2:]:
                    score -= 25.0

            valid_candidates.append((score, entry))

        if not valid_candidates:
            return None

        valid_candidates.sort(key=lambda x: x[0], reverse=True)

        top_pool = valid_candidates[:10]
        is_explore = random.random() < self.explore_rate and len(top_pool) > 1

        if is_explore:
            recent_artists = getattr(session_state, 'recent_artists', []) if session_state else []
            last_artist = _normalize_artist(recent_artists[-1]) if recent_artists else None
            exploration_margin = max(3.0, min(12.0, abs(top_pool[0][0]) * 0.08))

            explore_candidates = [
                c[1] for c in top_pool[1:]
                if c[0] >= top_pool[0][0] - exploration_margin
                and c[0] > 0
                and (not last_artist or _normalize_artist(c[1].get('artist') or c[1].get('uploader') or '') != last_artist)
            ]
            chosen = random.choice(explore_candidates) if explore_candidates else top_pool[0][1]
        else:
            chosen = top_pool[0][1]

        return chosen
