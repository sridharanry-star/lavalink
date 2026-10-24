from __future__ import annotations
import os
import sqlite3
import json
import argparse
import tempfile
from collections import defaultdict
from typing import List, Tuple, Dict, Any

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    np = None
    HAS_NUMPY = False

from .feature_extractor import FeatureExtractor
from .ranking_model import RankingModel, HAS_LIGHTGBM
from .search_ranker import SearchFeatureExtractor
from .language_match import query_family_key

if HAS_LIGHTGBM:
    import lightgbm as lgb
else:
    lgb = None

class TrainingPipeline:
    """Offline model training from explicit listening outcomes and skip feedback."""

    DB_PATH = "data/ml/interactions.db"
    MIN_SEARCH_GROUPS = 300
    MIN_QUERY_FAMILIES = 150
    MIN_PER_CLASS = 40
    SEARCH_RELEASE_FLOOR = 0.75
    SEARCH_TARGET_ACCURACY = 0.80

    @classmethod
    def load_tamil_search_examples(cls, db_path: str = DB_PATH) -> Tuple[List[dict], Dict[str, int]]:
        """Create candidate acceptance examples from Tamil search and listening feedback."""
        if not os.path.isfile(db_path):
            return [], {"impressions": 0, "labeled_groups": 0, "query_families": 0, "positive": 0, "negative": 0, "playback_failures": 0}

        with sqlite3.connect(db_path) as con:
            rows = con.execute("""
                SELECT event_type, timestamp, completion_ratio, played_seconds,
                       COALESCE(metadata, extra_data, '{}')
                FROM interactions
                WHERE event_type IN ('SEARCH_IMPRESSION', 'LIKE', 'PLAY_COMPLETED', 'SKIP', 'PLAYBACK_FAILURE')
                ORDER BY timestamp ASC
            """).fetchall()

        impressions: Dict[str, dict] = {}
        outcomes: Dict[str, list] = defaultdict(list)
        playback_failures = 0
        for event_type, timestamp, completion_ratio, played_seconds, raw_metadata in rows:
            try:
                metadata = json.loads(raw_metadata or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(metadata, dict):
                continue
            request_id = str(metadata.get("request_id") or "").strip()
            candidate_id = str(metadata.get("candidate_id") or "").strip()
            if not request_id:
                continue
            event_type = str(event_type or "").upper()
            if event_type == "SEARCH_IMPRESSION":
                candidates = metadata.get("candidates")
                if isinstance(candidates, list) and len(candidates) >= 2:
                    impressions[request_id] = {
                        "timestamp": float(timestamp or 0),
                        "query": str(metadata.get("query") or ""),
                        "selected_id": str(metadata.get("selected_candidate_id") or metadata.get("candidate_id") or ""),
                        "candidates": candidates,
                        "is_tamil": bool(metadata.get("is_tamil_context")),
                    }
            elif event_type == "PLAYBACK_FAILURE":
                playback_failures += 1
                outcomes[request_id].append((event_type, float(timestamp or 0), float(completion_ratio or 0.0), float(played_seconds or 0.0), candidate_id))
            elif event_type in {"LIKE", "PLAY_COMPLETED", "SKIP"}:
                outcomes[request_id].append((event_type, float(timestamp or 0), float(completion_ratio or 0.0), float(played_seconds or 0.0), candidate_id))

        examples = []
        accepted_groups = 0
        for request_id, impression in impressions.items():
            if not impression["is_tamil"] or not impression["selected_id"]:
                continue
            request_outcomes = [
                outcome for outcome in outcomes.get(request_id, [])
                if outcome[4] == impression["selected_id"]
            ]
            has_failure = any(event == "PLAYBACK_FAILURE" for event, _, _, _, _ in request_outcomes)
            is_positive = any(
                event == "LIKE" or (event == "PLAY_COMPLETED" and ratio >= 0.75)
                for event, _, ratio, _, _ in request_outcomes
            )
            is_negative = not has_failure and any(
                event == "SKIP" and ratio <= 0.20 and played_seconds <= 30.0
                for event, _, ratio, played_seconds, _ in request_outcomes
            )
            if not (is_positive or is_negative):
                continue
            label = 1 if is_positive else 0

            candidate_features = []
            candidate_scores = []
            selected_features = None
            selected_index = None
            for candidate_index, candidate in enumerate(impression["candidates"]):
                if not isinstance(candidate, dict):
                    continue
                candidate_id = str(candidate.get("candidate_id") or "").strip()
                playable_id = str(candidate.get("playable_id") or "").strip()
                try:
                    features = [float(value) for value in candidate.get("features", [])]
                except (TypeError, ValueError):
                    continue
                if not features:
                    continue
                candidate_features.append(features)
                candidate_scores.append(float(candidate.get("match_score") or 0.0))
                if impression["selected_id"] in {candidate_id, playable_id}:
                    selected_features = features
                    selected_index = len(candidate_features) - 1

            if selected_features is None or len(candidate_features) < 2:
                continue
            if len({len(row) for row in candidate_features}) != 1:
                continue
            examples.append({
                "request_id": request_id,
                "timestamp": impression["timestamp"],
                "query": impression["query"],
                "query_family": query_family_key(impression["query"]) or request_id,
                "features": selected_features,
                "label": label,
                "candidate_features": candidate_features,
                "candidate_scores": candidate_scores,
                "selected_index": selected_index,
            })
            accepted_groups += int(label == 1)

        positive_count = sum(example["label"] == 1 for example in examples)
        return examples, {
            "impressions": len(impressions),
            "labeled_groups": len(examples),
            "query_families": len({example["query_family"] for example in examples}),
            "positive": positive_count,
            "negative": len(examples) - positive_count,
            "accepted_groups": accepted_groups,
            "playback_failures": playback_failures,
        }

    @staticmethod
    def _binary_metrics(labels, probabilities) -> dict:
        predictions = [int(float(probability) >= 0.5) for probability in probabilities]
        positives = sum(int(label) == 1 for label in labels)
        negatives = len(labels) - positives
        tp = sum(int(label) == 1 and prediction == 1 for label, prediction in zip(labels, predictions))
        tn = sum(int(label) == 0 and prediction == 0 for label, prediction in zip(labels, predictions))
        positive_recall = tp / positives if positives else 0.0
        negative_recall = tn / negatives if negatives else 0.0
        return {
            "accuracy": (tp + tn) / len(labels) if labels else 0.0,
            "balanced_accuracy": (positive_recall + negative_recall) / 2 if positives and negatives else 0.0,
            "positive_recall": positive_recall,
            "negative_recall": negative_recall,
        }

    @staticmethod
    def _accepted_top1_retention(booster, examples: List[dict]) -> float:
        accepted = [example for example in examples if example["label"] == 1]
        if not accepted:
            return 0.0
        retained = 0
        for example in accepted:
            probabilities = booster.predict(np.asarray(example["candidate_features"], dtype=np.float32))
            baseline = example["candidate_scores"]
            low, high = min(baseline), max(baseline)
            blended = [
                0.80 * ((score - low) / (high - low) if high - low > 1e-6 else 0.5)
                + 0.20 * max(0.0, min(1.0, float(probability)))
                for score, probability in zip(baseline, probabilities)
            ]
            retained += int(int(np.argmax(blended)) == example["selected_index"])
        return retained / len(accepted)

    @classmethod
    def run_tamil_search_training(cls, db_path: str = DB_PATH,
                                  model_path: str = "data/ml/yuna_tamil_search_ranker.booster") -> Dict[str, Any]:
        """Train a Tamil candidate-acceptance classifier and promote only after holdout gates."""
        examples, counts = cls.load_tamil_search_examples(db_path)
        print(
            "[ML TAMIL SEARCH] "
            f"impressions={counts['impressions']} labeled_groups={counts['labeled_groups']} "
            f"families={counts['query_families']} positive={counts['positive']} negative={counts['negative']} "
            f"playback_failures={counts['playback_failures']}"
        )
        if not HAS_NUMPY or not HAS_LIGHTGBM:
            print("[ML TAMIL SEARCH] numpy and lightgbm are required; the validated baseline remains active.")
            return {"status": "missing_dependencies", **counts}
        if (
            len(examples) < cls.MIN_SEARCH_GROUPS
            or counts["query_families"] < cls.MIN_QUERY_FAMILIES
            or min(counts["positive"], counts["negative"]) < cls.MIN_PER_CLASS
        ):
            print(
                f"[ML TAMIL SEARCH] Need at least {cls.MIN_SEARCH_GROUPS} labeled Tamil searches and "
                f"{cls.MIN_QUERY_FAMILIES} distinct query families, plus {cls.MIN_PER_CLASS} positive and "
                f"{cls.MIN_PER_CLASS} early-skip examples."
            )
            return {"status": "insufficient_data", **counts, "required_groups": cls.MIN_SEARCH_GROUPS}

        family_groups = defaultdict(list)
        for example in examples:
            family_groups[example["query_family"]].append(example)
        ordered_families = sorted(
            family_groups,
            key=lambda family: max(example["timestamp"] for example in family_groups[family]),
        )
        train_end = int(len(ordered_families) * 0.70)
        valid_end = int(len(ordered_families) * 0.85)
        train_families = set(ordered_families[:train_end])
        valid_families = set(ordered_families[train_end:valid_end])
        test_families = set(ordered_families[valid_end:])
        train_examples = [example for example in examples if example["query_family"] in train_families]
        valid_examples = [example for example in examples if example["query_family"] in valid_families]
        test_examples = [example for example in examples if example["query_family"] in test_families]
        if not train_examples or not valid_examples or not test_examples:
            return {"status": "insufficient_split", **counts}
        for split in (train_examples, valid_examples, test_examples):
            if {example["label"] for example in split} != {0, 1}:
                print("[ML TAMIL SEARCH] Both feedback classes are needed in each chronological split.")
                return {"status": "split_missing_class", **counts}

        x_train = np.asarray([example["features"] for example in train_examples], dtype=np.float32)
        y_train = np.asarray([example["label"] for example in train_examples], dtype=np.int32)
        x_valid = np.asarray([example["features"] for example in valid_examples], dtype=np.float32)
        y_valid = np.asarray([example["label"] for example in valid_examples], dtype=np.int32)
        widths = {len(SearchFeatureExtractor.FEATURE_NAMES), x_train.shape[1], x_valid.shape[1]}
        if len(widths) != 1:
            return {"status": "feature_schema_mismatch", **counts}

        train_data = lgb.Dataset(x_train, label=y_train, feature_name=SearchFeatureExtractor.FEATURE_NAMES)
        valid_data = lgb.Dataset(x_valid, label=y_valid, reference=train_data, feature_name=SearchFeatureExtractor.FEATURE_NAMES)
        params = {
            "objective": "binary",
            "metric": "binary_logloss",
            "learning_rate": 0.035,
            "num_leaves": 15,
            "max_depth": 5,
            "min_data_in_leaf": 12,
            "feature_fraction": 0.9,
            "lambda_l1": 0.1,
            "lambda_l2": 2.0,
            "verbosity": -1,
            "num_threads": max(1, min(4, os.cpu_count() or 1)),
            "seed": 23,
            "feature_fraction_seed": 23,
            "data_random_seed": 23,
            "deterministic": True,
        }
        booster = lgb.train(
            params,
            train_data,
            num_boost_round=200,
            valid_sets=[valid_data],
            valid_names=["validation"],
            callbacks=[lgb.early_stopping(20, verbose=False), lgb.log_evaluation(0)],
        )

        valid_metrics = cls._binary_metrics(y_valid.tolist(), booster.predict(x_valid).tolist())
        x_test = np.asarray([example["features"] for example in test_examples], dtype=np.float32)
        y_test = [example["label"] for example in test_examples]
        test_metrics = cls._binary_metrics(y_test, booster.predict(x_test).tolist())
        accepted_retention = cls._accepted_top1_retention(booster, test_examples)
        print(
            "[ML TAMIL SEARCH] "
            f"holdout_accuracy={test_metrics['accuracy']:.1%} "
            f"balanced_accuracy={test_metrics['balanced_accuracy']:.1%} "
            f"accepted_top1_retention={accepted_retention:.1%} "
            f"target={cls.SEARCH_TARGET_ACCURACY:.0%}"
        )
        if (
            valid_metrics["accuracy"] < cls.SEARCH_RELEASE_FLOOR
            or valid_metrics["balanced_accuracy"] < cls.SEARCH_RELEASE_FLOOR
            or test_metrics["balanced_accuracy"] < cls.SEARCH_RELEASE_FLOOR
            or test_metrics["accuracy"] < cls.SEARCH_RELEASE_FLOOR
            or accepted_retention < cls.SEARCH_RELEASE_FLOOR
        ):
            print("[ML TAMIL SEARCH] Holdout gate failed; keeping the current validated ranking active.")
            return {
                "status": "holdout_gate_failed",
                **counts,
                "validation_metrics": valid_metrics,
                "holdout_metrics": test_metrics,
                "accepted_top1_retention": accepted_retention,
            }

        model_dir = os.path.dirname(model_path) or "."
        os.makedirs(model_dir, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(prefix="yuna-tamil-ranker-", suffix=".booster", dir=model_dir, delete=False) as temp_file:
                temp_path = temp_file.name
            booster.save_model(temp_path, num_iteration=booster.best_iteration or booster.current_iteration())
            os.replace(temp_path, model_path)
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

        return {
            "status": "promoted",
            **counts,
            "training_groups": len(train_examples),
            "validation_groups": len(valid_examples),
            "holdout_groups": len(test_examples),
            "validation_metrics": valid_metrics,
            "holdout_metrics": test_metrics,
            "accepted_top1_retention": accepted_retention,
            "model_path": model_path,
        }

    @classmethod
    def load_dataset_from_db(cls, db_path: str = DB_PATH) -> Tuple[List[dict], List[float]]:
        """Extracts interaction logs and assigns multi-task engagement target labels."""
        if not os.path.isfile(db_path):
            return [], []

        con = sqlite3.connect(db_path)
        cur = con.cursor()
        cur.execute("""
            SELECT event_type, user_id, guild_id, track_id, title, artist,
                   album, language, mood, duration, played_duration, completion_ratio, timestamp
            FROM interactions
            ORDER BY timestamp ASC
        """)
        rows = cur.fetchall()
        con.close()

        records: List[dict] = []
        labels: List[float] = []

        for r in rows:
            event_type = str(r[0] or "").strip().upper()
            played_ratio = r[11] or 0.0

            if event_type in {"LIKE", "RECOMMENDATION_ACCEPTED"}:
                target = 5.0 if event_type == "LIKE" else 4.0
            elif event_type == "PLAY_COMPLETED" and played_ratio >= 0.75:
                target = 3.0
            elif event_type in {"SKIP", "RECOMMENDATION_SKIPPED"} and played_ratio < 0.20:
                target = 0.0
            elif event_type in {"SKIP", "RECOMMENDATION_SKIPPED"} and played_ratio < 0.50:
                target = 1.0
            else:
                continue

            track_dict = {
                "title": r[4],
                "uploader": r[5],
                "album": r[6],
                "language": r[7],
                "mood": r[8],
                "duration": r[9],
                "view_count": 0,
                "like_count": 0
            }

            records.append(track_dict)
            labels.append(target)

        return records, labels

    @classmethod
    def run_training(cls, db_path: str = DB_PATH) -> Dict[str, Any]:
        """Executes full training pipeline with chronological split and validation."""
        print("[ML PIPELINE] Loading interaction logs from database...")
        records, labels = cls.load_dataset_from_db(db_path)

        if not HAS_NUMPY or not HAS_LIGHTGBM:
            print("[ML PIPELINE NOTICE] numpy and lightgbm are required for offline model training.")
            return {"status": "missing_dependencies"}

        if len(records) < 100 or len(set(labels)) < 2:
            print(f"[ML PIPELINE NOTICE] Dataset has {len(records)} useful feedback records; at least 100 records with both positive and negative outcomes are required.")
            print("[ML PIPELINE NOTICE] Interaction Logger is capturing server activity. Heuristic ranker active.")
            return {"status": "insufficient_data", "samples": len(records), "label_count": len(set(labels))}

        print(f"[ML PIPELINE] Extracting {len(FeatureExtractor.FEATURE_NAMES)} features across {len(records)} samples...")
        X = FeatureExtractor.extract_batch(records)
        y = np.array(labels, dtype=np.float32)

        n = len(X)
        train_idx = int(n * 0.80)
        val_idx = int(n * 0.90)

        X_train, y_train = X[:train_idx], y[:train_idx]
        X_val, y_val = X[train_idx:val_idx], y[train_idx:val_idx]
        X_test, y_test = X[val_idx:], y[val_idx:]

        print(f"[ML PIPELINE] Train samples: {len(X_train)}, Val: {len(X_val)}, Test: {len(X_test)}")

        ranker = RankingModel()
        success = ranker.train_and_save(X_train, y_train)

        if not success:
            return {"status": "train_failed"}

        val_preds = ranker._booster.predict(X_val)
        test_preds = ranker._booster.predict(X_test)

        val_rmse = float(np.sqrt(np.mean((val_preds - y_val) ** 2)))
        test_rmse = float(np.sqrt(np.mean((test_preds - y_test) ** 2)))

        print(f"[ML PIPELINE SUCCESS] Validation RMSE: {val_rmse:.4f} | Test RMSE: {test_rmse:.4f}")

        return {
            "status": "success",
            "samples": n,
            "val_rmse": val_rmse,
            "test_rmse": test_rmse,
            "ndcg_10": None
        }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train Lavalink music ranking models from interaction feedback.")
    parser.add_argument("--search", action="store_true", help="Train the Tamil song-search reranker.")
    args = parser.parse_args()
    if args.search:
        TrainingPipeline.run_tamil_search_training()
    else:
        TrainingPipeline.run_training()
