from __future__ import annotations
import os
from typing import List, Dict, Any, Optional

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    np = None
    HAS_NUMPY = False

try:
    import lightgbm as lgb
    HAS_LIGHTGBM = True
except ImportError:
    HAS_LIGHTGBM = False

from .feature_extractor import FeatureExtractor
from .embedding_engine import EmbeddingEngine

class RankingModel:
    """Stage 2 Scoring & Ranking Model for Machine Learning Recommender.
    Scores candidates using a trained LightGBM booster or high-precision fallback heuristics.
    Supports both accelerated NumPy/LightGBM inference and zero-dependency pure Python fallbacks.
    """

    MODEL_PATH = "data/ml/yuna_ranker.booster"

    FALLBACK_WEIGHTS: List[float] = [
        0.0,    # 0: track_duration
        35.0,   # 1: is_topic_channel
        30.0,   # 2: is_pure_audio
        -40.0,  # 3: is_theatrical_video
        15.0,   # 4: is_verified_channel
        2.0,    # 5: view_count_log
        3.0,    # 6: like_count_log
        10.0,   # 7: like_to_view_ratio
        25.0,   # 8: artist_match_seed
        -15.0,  # 9: artist_recent_freq (anti-fatigue)
        -30.0,  # 10: artist_in_last_2
        60.0,   # 11: language_match (strong alignment)
        -250.0, # 12: language_conflict (destructive penalty for cross-language)
        -25.0,  # 13: language_is_unknown
        45.0,   # 14: version_tag_match (e.g. "(Tamil)" in Tamil session)
        20.0,   # 15: mood_match
        10.0,   # 16: mood_count_ratio
        0.0,    # 17: session_length
        -40.0,  # 18: skipped_overlap
        0.0,    # 19: hour_of_day_norm
        0.0,    # 20: is_weekend
        0.0,    # 21: title_word_count
        5.0,    # 22: has_featured_artist
        25.0,   # 23: is_major_record_label
        20.0,   # 24: user_artist_affinity
        -30.0   # 25: user_artist_skip_ratio
    ]

    def __init__(self, model_path: str = MODEL_PATH):
        self.model_path = model_path
        self._booster: Optional[Any] = None
        self._embedding_engine = EmbeddingEngine()
        self.load_model()

    def load_model(self) -> bool:
        """Loads serialized LightGBM booster if present on disk."""
        if HAS_LIGHTGBM and os.path.isfile(self.model_path):
            try:
                self._booster = lgb.Booster(model_file=self.model_path)
                return True
            except Exception as e:
                print(f"[ML RANKING MODEL LOAD ERROR] {e}")
                self._booster = None
        return False

    def is_trained(self) -> bool:
        return self._booster is not None

    def rank_candidates(
        self,
        candidates: List[dict],
        session_state: Any = None,
        user_id: int = 0,
        user_stats: Optional[dict] = None
    ) -> List[tuple[float, dict]]:
        """Scores and ranks a list of candidate tracks."""
        if not candidates:
            return []

        features = FeatureExtractor.extract_batch(candidates, session_state, user_id, user_stats)

        raw_scores = None
        if self._booster is not None and HAS_LIGHTGBM:
            try:
                raw_scores = self._booster.predict(features).tolist()
            except Exception as e:
                print(f"[ML RANKING PREDICT ERROR] {e}")
                raw_scores = None

        if raw_scores is None:
            if HAS_NUMPY and np is not None and isinstance(features, np.ndarray):
                weights = np.array(self.FALLBACK_WEIGHTS, dtype=np.float32)
                raw_scores = np.dot(features, weights).tolist()
            else:
                raw_scores = [
                    sum(f * w for f, w in zip(row, self.FALLBACK_WEIGHTS))
                    for row in features
                ]

        scored = list(zip(raw_scores, candidates))

        target_lang = getattr(session_state, 'user_locked_language', None) or getattr(session_state, 'hard_language', None)
        if not target_lang and session_state and getattr(session_state, 'language_established', False):
            target_lang = getattr(session_state, 'active_language', None)

        if target_lang and str(target_lang).strip().casefold() not in ('unknown', 'auto', 'english'):
            act_lang = str(target_lang).strip().casefold()
            filtered_scored = []
            for score, entry in scored:
                cand_lang = str(entry.get('language') or 'unknown').strip().casefold()
                if cand_lang != act_lang and not entry.get('language_confirmed'):
                    score = -9999.0
                filtered_scored.append((score, entry))
            scored = filtered_scored

        recent_tracks = getattr(session_state, 'recent_tracks', []) if session_state else []
        if recent_tracks:
            try:
                session_vec = self._embedding_engine.compute_session_vector(recent_tracks[-10:])
                similarities = self._embedding_engine.score_candidates_by_similarity(
                    session_vec,
                    [entry for _, entry in scored]
                )
                usable_scores = [score for score, _ in scored if score > -100.0]
                if usable_scores:
                    low_score = min(usable_scores)
                    high_score = max(usable_scores)
                    blended = []
                    for (score, entry), similarity in zip(scored, similarities):
                        if score <= -100.0:
                            blended.append((score, entry))
                            continue
                        model_score = (
                            0.5 if high_score - low_score < 1e-6
                            else (score - low_score) / (high_score - low_score)
                        )
                        semantic_score = (max(-1.0, min(1.0, float(similarity))) + 1.0) / 2.0
                        blended.append((100.0 * (0.82 * model_score + 0.18 * semantic_score), entry))
                    scored = blended
            except Exception as e:
                print(f"[ML EMBEDDING RANK ERROR] {e}")

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored

    def train_and_save(self, X: Any, y: Any, groups: Optional[List[int]] = None) -> bool:
        """Trains LightGBM model on interaction dataset and saves to disk."""
        if not HAS_LIGHTGBM or len(X) < 20:
            return False

        try:
            os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
            train_data = lgb.Dataset(X, label=y, group=groups, feature_name=FeatureExtractor.FEATURE_NAMES)
            
            params = {
                'objective': 'lambdarank' if groups else 'regression',
                'metric': 'ndcg' if groups else 'rmse',
                'boosting_type': 'gbdt',
                'learning_rate': 0.05,
                'num_leaves': 31,
                'min_data_in_leaf': 5,
                'verbose': -1
            }

            self._booster = lgb.train(params, train_data, num_boost_round=100)
            self._booster.save_model(self.model_path)
            return True
        except Exception as e:
            print(f"[ML RANKING TRAIN ERROR] {e}")
            return False
