from __future__ import annotations
import math
import time
import datetime
import re
import unicodedata
from typing import Dict, Any, List, Optional
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    np = None
    HAS_NUMPY = False

THEATRICAL_VIDEO_KEYWORDS = [
    'video song', 'full video song', 'full video', 'movie video',
    'film version', 'movie version', 'theatrical version'
]

PURE_AUDIO_KEYWORDS = [
    'official audio', 'audio song', 'original audio', 'album track',
    'studio version', 'original sound track', 'official track',
    'lyric video', 'lyrical video', 'lyrical'
]

def _normalize_title(title: str) -> str:
    """Normalize song title for deduplication matching in feature extraction."""
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

class FeatureExtractor:
    """Extracts dense numerical feature vectors for (User, Candidate Track, MusicSessionState) tuples.
    Used for LightGBM ranking and candidate scoring in Yuna's ML recommendation pipeline.
    """

    FEATURE_NAMES: List[str] = [
        "track_duration",
        "is_topic_channel",
        "is_pure_audio",
        "is_theatrical_video",
        "is_verified_channel",
        "view_count_log",
        "like_count_log",
        "like_to_view_ratio",
        "artist_match_seed",
        "artist_recent_freq",
        "artist_in_last_2",
        "language_match",
        "language_conflict",
        "language_is_unknown",
        "version_tag_match",
        "mood_match",
        "mood_count_ratio",
        "session_length",
        "skipped_overlap",
        "hour_of_day_norm",
        "is_weekend",
        "title_word_count",
        "has_featured_artist",
        "is_major_record_label",
        "user_artist_affinity",
        "user_artist_skip_ratio"
    ]

    @classmethod
    def extract_features(
        cls,
        candidate: dict,
        session_state: Any = None,
        user_id: int = 0,
        user_stats: Optional[dict] = None
    ) -> np.ndarray:
        """Extracts a 1D float32 numpy feature array for a single candidate track."""
        title = candidate.get('title', '') or ''
        t_low = title.lower()
        uploader = (candidate.get('uploader') or candidate.get('channel') or candidate.get('artist') or '').lower()
        duration = float(candidate.get('duration', 0) or 0.0)
        views = float(candidate.get('view_count', 0) or 0.0)
        likes = float(candidate.get('like_count', 0) or 0.0)

        is_topic = 1.0 if '- topic' in uploader else 0.0
        is_pure_audio = 1.0 if any(pa in t_low for pa in PURE_AUDIO_KEYWORDS) else 0.0
        is_theatrical = 1.0 if any(tv in t_low for tv in THEATRICAL_VIDEO_KEYWORDS) else 0.0
        is_verified = 1.0 if candidate.get('channel_is_verified') else 0.0

        major_labels = [
            "sony music", "sonymusic", "t-series", "tseries", "zee music",
            "saregama", "think music", "aditya music", "lahari", "vevo",
            "yrf", "tips", "speed records", "muzik247", "warner", "universal"
        ]
        is_major_label = 1.0 if any(lbl in uploader for lbl in major_labels) else 0.0

        view_log = math.log1p(views)
        like_log = math.log1p(likes)
        like_view_ratio = (likes / views) if views > 0 else 0.0

        artist_match_seed = 0.0
        artist_recent_freq = 0.0
        artist_in_last_2 = 0.0
        lang_match = 0.0
        lang_conflict = 0.0
        lang_unknown = 0.0
        version_tag_match = 0.0
        mood_match = 0.0
        mood_ratio = 0.0
        session_len = 0.0
        skip_overlap = 0.0

        cand_artist = _normalize_artist(uploader)

        if session_state:
            session_len = float(len(getattr(session_state, 'recent_tracks', [])))
            recent_artists = [
                _normalize_artist(artist)
                for artist in getattr(session_state, 'recent_artists', [])
            ]
            if recent_artists:
                if recent_artists[-1] == cand_artist:
                    artist_match_seed = 1.0
                artist_recent_freq = float(recent_artists.count(cand_artist))
                if cand_artist in recent_artists[-2:]:
                    artist_in_last_2 = 1.0

            active_lang = str(getattr(session_state, 'active_language', 'unknown') or 'unknown').strip().casefold()
            cand_lang = str(candidate.get('language') or 'unknown').strip().casefold()

            if active_lang not in ('unknown', 'auto'):
                if cand_lang == active_lang:
                    lang_match = 1.0
                elif cand_lang not in ('unknown', 'auto'):
                    lang_conflict = 1.0

            if cand_lang in ('unknown', 'auto'):
                lang_unknown = 1.0

            if active_lang not in ('unknown', 'auto'):
                cand_source = candidate.get('language_source') or ''
                if cand_source == 'explicit_version_tag' and cand_lang == active_lang:
                    version_tag_match = 1.0
                elif re.search(r'[\(\[\{/\-_|]\s*' + re.escape(active_lang), t_low):
                    version_tag_match = 1.0

            target_mood = str(getattr(session_state, 'target_mood', 'auto') or 'auto').strip().casefold()
            cand_mood = str(candidate.get('mood') or 'auto').strip().casefold()
            if target_mood != 'auto' and cand_mood == target_mood:
                mood_match = 1.0

            mood_counts = getattr(session_state, 'mood_counts', {})
            total_moods = sum(mood_counts.values()) if mood_counts else 0
            if total_moods > 0 and cand_mood in mood_counts:
                mood_ratio = mood_counts[cand_mood] / total_moods

            skipped_history = getattr(session_state, 'skipped_history', [])
            if skipped_history:
                norm_t = _normalize_title(title)
                if any(norm_t in sk or sk in norm_t for sk in skipped_history):
                    skip_overlap = 1.0

        now = datetime.datetime.now()
        hour_norm = now.hour / 24.0
        is_weekend = 1.0 if now.weekday() >= 5 else 0.0

        word_count = float(len(t_low.split()))
        has_feat = 1.0 if ('feat' in t_low or 'ft.' in t_low or 'featuring' in t_low) else 0.0

        user_affinity = 0.0
        user_skip_ratio = 0.0
        if user_stats and cand_artist:
            artist_stats = user_stats.get(cand_artist, {})
            plays = artist_stats.get('plays', 0)
            skips = artist_stats.get('skips', 0)
            user_affinity = math.log1p(plays)
            user_skip_ratio = (skips / plays) if plays > 0 else 0.0

        features = [
            duration,
            is_topic,
            is_pure_audio,
            is_theatrical,
            is_verified,
            view_log,
            like_log,
            like_view_ratio,
            artist_match_seed,
            artist_recent_freq,
            artist_in_last_2,
            lang_match,
            lang_conflict,
            lang_unknown,
            version_tag_match,
            mood_match,
            mood_ratio,
            session_len,
            skip_overlap,
            hour_norm,
            is_weekend,
            word_count,
            has_feat,
            is_major_label,
            user_affinity,
            user_skip_ratio
        ]

        if HAS_NUMPY and np is not None:
            return np.array(features, dtype=np.float32)
        return features

    @classmethod
    def extract_batch(
        cls,
        candidates: List[dict],
        session_state: Any = None,
        user_id: int = 0,
        user_stats: Optional[dict] = None
    ) -> Any:
        """Extracts numerical features for a batch of candidate tracks."""
        if not candidates:
            if HAS_NUMPY and np is not None:
                return np.empty((0, len(cls.FEATURE_NAMES)), dtype=np.float32)
            return []
        rows = [cls.extract_features(c, session_state, user_id, user_stats) for c in candidates]
        if HAS_NUMPY and np is not None:
            return np.vstack(rows)
        return rows
