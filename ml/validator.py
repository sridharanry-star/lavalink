from __future__ import annotations
import re
import unicodedata
from typing import Tuple, Optional, Dict, Any, List
from .constants import (
    NON_MUSIC_KEYWORDS,
    PREFERRED_CHANNEL_INDICATORS,
    DIALOGUE_KEYWORDS,
    THEATRICAL_VIDEO_KEYWORDS,
    PURE_AUDIO_KEYWORDS,
    UNWANTED_EDIT_KEYWORDS,
    is_verified_music_channel,
    normalize_title
)
from .language_match import best_similarity, is_tamil_context, matching_forms, token_recall

class SongValidator:
    """Strict Music Track Resolver & Validation Engine.
    Ensures ONLY actual music tracks enter the queue (rejects trailers, podcasts, interviews,
    reactions, news, shorts, commentary, jukeboxes, long compilations, and unverified amateur uploads).
    """

    QUERY_NOISE = {
        "play", "please", "listen", "youtube", "yt", "music", "song", "songs",
        "track", "audio", "video", "full", "original", "official", "by", "on",
        "to", "from", "in", "of"
    }

    @staticmethod
    def _match_tokens(text: str, remove_query_noise: bool = False) -> set[str]:
        normalized = unicodedata.normalize("NFKC", str(text or "")).casefold()
        normalized = re.sub(r"[\(\[\{].*?[\)\]\}]", " ", normalized)
        normalized = re.sub(r"[^\w\s]", " ", normalized, flags=re.UNICODE)
        tokens = {token for token in normalized.split() if len(token) > 1}
        if remove_query_noise:
            tokens.difference_update(SongValidator.QUERY_NOISE)
        return tokens

    @staticmethod
    def _token_recall(query_tokens: set[str], candidate_tokens: set[str]) -> float:
        if not query_tokens:
            return 0.0
        return len(query_tokens & candidate_tokens) / len(query_tokens)

    @staticmethod
    def is_non_music_content(title: str, uploader: str, target_title: str = "") -> bool:
        t_low = title.lower()
        u_low = uploader.lower()
        t_compressed = re.sub(r'(?<=\b\w)\s+(?=\w\b)', '', t_low)

        all_non_music = NON_MUSIC_KEYWORDS + [
            'dance class', 'dance cover', 'dance choreography', 'beginners class', 'bhangra performance'
        ]
        for kw in all_non_music:
            if re.search(r'\b' + re.escape(kw) + r'\b', t_low) or re.search(r'\b' + re.escape(kw) + r'\b', u_low) or kw in t_compressed:
                # Exception: unless 'trailer' or 'theme' is part of an official soundtrack/OST track title
                if kw in ['trailer', 'teaser', 'podcast', 'episode'] and any(ost_kw in t_low for ost_kw in ['soundtrack', 'ost', 'theme song', 'theme', 'official audio', 'official music video', 'speech', 'reality']):
                    continue
                return True
        return False

    @staticmethod
    def validate_and_score(candidate: dict, target_title: str = "", target_artist: str = "", expected_duration: int = 0) -> Tuple[int, str]:
        title = candidate.get('title', '')
        uploader = candidate.get('uploader') or candidate.get('channel') or ''
        candidate_artist = candidate.get('artist') or candidate.get('artists') or uploader
        duration = candidate.get('duration', 0) or 0
        view_count = candidate.get('view_count', 0) or 0
        source = str(candidate.get('source') or '').casefold()
        is_video = bool(candidate.get('is_video') or source in ("ytm_video", "video") or candidate.get('video_type') == "video")
        is_studio_song = bool(candidate.get('is_studio_song') or source == "ytm_song") and not is_video
        is_featured = bool(candidate.get('featured') or source == "ytm_featured") and not is_video

        t_low = title.lower()
        up_low = uploader.lower()
        target_low = target_title.lower() if target_title else ""
        t_compressed = re.sub(r'(?<=\b\w)\s+(?=\w\b)', '', t_low)

        # 1. Immediate rejection check for non-music indicators & long compilations/jukeboxes
        if SongValidator.is_non_music_content(title, uploader, target_title=target_title):
            return -100, "LOW"

        # 1b. Strict Unofficial / User Edit Rejection (slowed, reverb, sped up, pitched, bass boosted, nightcore, 8d)
        unwanted_edits = [
            'slowed', 'reverb', 'sped up', 'speed up', 'speedup', 'pitched', 'pitch shifted',
            'bass boosted', 'bassboost', 'boosted', 'nightcore', '8d audio', '8d music',
            'ringtone', 'status video', 'whatsapp status', 'shorts'
        ]
        for edit in unwanted_edits:
            if edit not in target_low:
                if re.search(r'\b' + re.escape(edit) + r'\b', t_low) or edit in t_compressed:
                    return -100, "LOW"

        # 1c. Strict Channel Verification Gate for standard YouTube search
        is_official_channel = is_verified_music_channel(uploader, candidate_artist) or is_verified_music_channel(uploader, target_artist)
        if source == "youtube" and not is_official_channel:
            # Let topic channels and verified sources pass; penalize plain uploads
            if not ('- topic' in up_low or 'vevo' in up_low):
                pass

        norm_title = normalize_title(title)
        norm_target_title = normalize_title(target_title) if target_title else ""
        target_tokens = SongValidator._match_tokens(target_title, remove_query_noise=True)
        title_tokens = SongValidator._match_tokens(title)
        identity_text = f"{title} {candidate_artist} {uploader}"
        query_recall = token_recall(target_title, identity_text, ignored=SongValidator.QUERY_NOISE)
        artist_tokens = SongValidator._match_tokens(target_artist)
        artist_recall = token_recall(target_artist, identity_text)

        if target_tokens and query_recall < 0.25 and not (artist_tokens and artist_recall >= 0.8):
            return -100, "LOW"

        if duration > 0:
            if expected_duration == 0 and duration > 1200:
                if not any(k in norm_target_title for k in ['album', 'playlist', 'compilation', 'full songs']):
                    return -100, "LOW"
            if expected_duration == 0 and duration < 20:
                return -100, "LOW"

        score = 0
        norm_uploader = normalize_title(uploader)

        # 2. Title Match (Exact, Transliterated, and Fuzzy Similarity)
        if norm_target_title:
            tamil_aware = is_tamil_context(target_title, [candidate])
            target_forms = matching_forms(target_title, tamil_aware=tamil_aware)
            title_forms = matching_forms(title, tamil_aware=tamil_aware)
            exact_form_match = any(left == right for left in target_forms for right in title_forms)
            substring_match = any(
                len(left) >= 3 and (left in right or right in left)
                for left in target_forms for right in title_forms
            )
            if norm_target_title == norm_title or exact_form_match:
                score += 60  # Perfect exact match (raw or transliterated)
            elif norm_target_title and norm_title and (
                norm_target_title in norm_title
                or (len(title_tokens) >= 2 and norm_title in norm_target_title)
            ):
                score += 45
            elif substring_match:
                score += 45  # Cross-script or transliterated substring match
            elif best_similarity(target_title, title, tamil_aware=tamil_aware) >= 0.85:
                score += 40  # High fuzzy similarity match
            elif query_recall >= 0.80:
                score += 45  # Query contains both title and artist metadata.
            elif query_recall >= 0.60:
                score += 35
            elif query_recall >= 0.40:
                score += 20
            elif any(w in title_tokens for w in target_tokens if len(w) > 2):
                score += 15
        else:
            score += 10

        # 3. Artist Match & Channel Verification
        if artist_tokens:
            if artist_recall >= 0.8:
                score += 50
            elif artist_recall >= 0.5:
                score += 25
            else:
                is_label = any(lbl in norm_uploader for lbl in ['records', 'music', 'audio', 'series', 'vevo', 'entertainment', 'cinema', 'company', 'corp', 'label']) or '- topic' in uploader.lower()
                score -= 20 if is_label else 35

        # 4. Duration Validation
        if expected_duration > 0 and duration > 0:
            diff = abs(duration - expected_duration)
            if diff <= 8:
                score += 20
            elif diff <= 20:
                score += 10
            elif diff <= 45:
                score -= 8
            elif diff <= 90:
                score -= 20
            else:
                score -= 35

        # 5. Pure Audio vs Theatrical / Video Song Intelligence
        wants_cover = any(v in target_low for v in ['cover', 'karaoke', 'tribute', 'parody'])
        if not wants_cover:
            cover_patterns = [
                r'\bcovers?\b', r'[\(\[\{]\s*covers?\s*[\)\]\}]',
                r'\bkaraoke\b', r'\btribute\b', r'\bparody\b', r'\bsoundalike\b',
                r'\brendition\b', r'\boriginally performed\b', r'\bin the style of\b'
            ]
            if any(re.search(pat, t_low) for pat in cover_patterns) or any(re.search(pat, up_low) for pat in cover_patterns):
                return -100, "LOW"

        # Pure Audio Studio Boost
        if is_studio_song or '- topic' in up_low:
            score += 55
        elif is_featured:
            score += 50
        elif any(pa in t_low for pa in ['official audio', 'audio song', 'original audio', '(audio)', '[audio]', 'studio version', 'album version', 'original sound track', 'soundtrack']):
            score += 45
        elif is_official_channel and any(lv in t_low for lv in ['lyric video', 'lyrical video', 'lyrical song', 'lyrics video', 'with lyrics', '(lyrics)', '[lyrics]']):
            score += 40

        # Theatrical Video Song Penalty
        if not any(v in target_low for v in ['video song', 'full video', 'movie video']):
            if is_video or any(tv in t_low for tv in THEATRICAL_VIDEO_KEYWORDS):
                score -= 45

        # Version Intelligence
        if not any(v in target_low for v in ['live', 'remix', 'acoustic', 'instrumental', 'reverb', 'slowed', 'unplugged', 'orchestral', '8d']):
            if any(v in t_low for v in ['unplugged', 'orchestral', 'instrumental', 'live performance', 'live at', '(live)', '[live]', 'remix', 'acoustic version', 'reverb', 'slowed', '8d audio', '8d music', 'rage rock', 'bgm', 'score', 'interval']):
                score -= 60

        # Channel Identity & Official Quality
        if is_official_channel:
            score += 25
        elif (source == "ytm_song" or source == "ytm_featured") and not is_video:
            score += 20
        else:
            score -= 20

        # Popularity
        if view_count >= 50000000:
            score += 15
        elif view_count >= 10000000:
            score += 10
        elif view_count >= 1000000:
            score += 5

        if score >= 35:
            confidence = "HIGH"
        elif score >= 20:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"

        return score, confidence

    @classmethod
    def select_best_music_candidate(cls, entries: list, target_title: str = "", target_artist: str = "", expected_duration: int = 0) -> dict | None:
        if not entries:
            return None

        candidates = []
        for entry in entries:
            if not entry or not entry.get('title'):
                continue
            score, confidence = cls.validate_and_score(entry, target_title, target_artist, expected_duration)
            if confidence in ["HIGH", "MEDIUM"] and score > 0:
                candidates.append((score, entry))

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]
