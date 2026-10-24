from __future__ import annotations
import re
import unicodedata
from typing import Dict, Set

def normalize_title(title: str) -> str:
    """Normalize song title for strict deduplication."""
    t = unicodedata.normalize("NFKC", str(title or "")).casefold()
    t = re.sub(r'[\(\[].*?[\)\]]', ' ', t)
    t = re.sub(r'[^\w\s]', ' ', t, flags=re.UNICODE)
    return ' '.join(t.split())

DIALOGUE_KEYWORDS = [
    'dialogue', 'dialogues', 'dialog', 'with dialogue', 'with dialogues',
    'dialogue promo', 'dialogue teaser', 'movie scene', 'deleted scene',
    'scene cut', 'intro scene', 'climax scene', 'comedy scene', 'movie clip',
    'film scene', 'fight scene', 'scenes'
]

THEATRICAL_VIDEO_KEYWORDS = [
    'video song', 'full video song', 'full video', 'movie video',
    'film version', 'movie version', 'theatrical version'
]

PURE_AUDIO_KEYWORDS = [
    'official audio', 'audio song', 'original audio', 'album track',
    'studio version', 'original sound track', 'official track',
    'lyric video', 'lyrical video', 'lyrical'
]

NON_MUSIC_KEYWORDS = [
    'trailer', 'teaser', 'interview', 'podcast', 'news', 'live stream', 'reaction',
    'review', 'explained', 'episode', 'documentary', 'shorts', 'behind the scenes',
    'bts', 'making of', 'making video', 'commentary', 'debate', 'talk', 'radio', 'stream',
    'premiere', 'press conference', 'press meet', 'audio launch', 'success meet',
    'fan reaction', 'gameplay', 'walkthrough', 'promo', 'single promo', 'first single promo',
    'glimpse', 'motion poster', 'sneak peek', 'title announcement',
    'parody', 'unboxing', 'tutorial', 'vlog', 'speedrun', 'discussion',
    'jukebox', 'full album', 'all songs', 'compilation', 'mashup', 'top 10', 'top 20', 'top 50',
    'playlist', 'hits collection', 'non stop', 'non-stop', 'audio jukebox', 'video jukebox',
    'all hit songs', 'song collection', 'hits jukebox', 'mega jukebox', 'full audio jukebox',
    '10 hours', '10 hr', '1 hour', '1 hr', 'loop audio'
] + DIALOGUE_KEYWORDS

PREFERRED_CHANNEL_INDICATORS = [
    '- topic', 'vevo', 'official', 'records', 'music', 'audio', 'label',
    'soundtracks', 'studio', 'entertainment'
]

MAJOR_INTERNATIONAL_LABELS = [
    'warner music', 'atlantic records', 'universal music', 'def jam', 'columbia records',
    'interscope', 'republic records', 'rca records', 'epic records', 'ncs', 'spinnin',
    'monstercat', 'sony music', 'virgin music', 'capitol records', 'geffen', 'asylum records',
    'fueled by ramen', 'island records', 'polydor', 'parlophone', 'century media', 'think indie',
    'big hit', 'hybe', 'sm entertainment', 'jyp', 'yg entertainment'
]

REGIONAL_CHANNEL_PATTERNS: Dict[str, re.Pattern] = {
    "tamil": re.compile(
        r'\b(saregama tamil|t-series tamil|think music tamil|sony music tamil|noise and grains|sun tv|sun pictures|kalaignar tv|divo tamil|trendmusic tamil)\b',
        re.IGNORECASE
    ),
    "telugu": re.compile(
        r'\b(aditya music|saregama telugu|t-series telugu|mango music|madhura audio|sony music telugu)\b',
        re.IGNORECASE
    ),
    "malayalam": re.compile(
        r'\b(muzik247|saina music|satyam audios|goodwill entertainments|saregama malayalam|think music malayalam|sony music malayalam)\b',
        re.IGNORECASE
    ),
    "kannada": re.compile(
        r'\b(anand audio|jhankar music|a2 music|saregama kannada|t-series kannada)\b',
        re.IGNORECASE
    ),
    "hindi": re.compile(
        r'\b(t-series(?!.*(?:tamil|telugu|kannada|malayalam))|zee music company|zee music|sony music india|yrf|tips official|tips music)\b',
        re.IGNORECASE
    ),
    "punjabi": re.compile(
        r'\b(speed records|geet mp3)\b',
        re.IGNORECASE
    ),
}

SOUTH_MULTI_REGIONAL_LABELS: re.Pattern = re.compile(
    r'\b(sony music south|think music|think indie|saregama south|lahari music south|lahari music|trendmusic|divo)\b',
    re.IGNORECASE
)

UNWANTED_EDIT_KEYWORDS = [
    'slowed', 'reverb', 'sped up', 'speed up', 'speedup', 'pitched', 'pitch shifted',
    'bass boosted', 'bassboost', 'boosted', 'nightcore', '8d audio', '8d music',
    'ringtone', 'status video', 'whatsapp status', 'shorts', '#shorts', 'dance class',
    'dance cover', 'dance choreography', 'beginners class', 'bhangra performance'
]

LANGUAGES = {
    "tamil": {
        "flag": "🇮🇳", "name": "Tamil", "unicode": (0x0B80, 0x0BFF),
        "keywords": [
            "tamil", "kollywood", "tamizh", "thamizh", "tanglish",
            "oorum blood", "oorum", "ooru", "oorin", "oorla", "oorukku", "captain miller",
            "hukum", "badass", "naa ready", "pathala pathala", "hunter", "fire song",
            "manasilaayo", "spark", "matta", "chinna chinna kangal", "the greatest of all time",
            "hey minnale", "saiyyan", "adangaatha asuran", "water packet", "usure", "po nee po",
            "why this kolaveri", "kolaveri", "rowdy baby", "arabic kuthu", "halamithi habibo", "jolly o gymkhana",
            "marana mass", "ullaallaa", "kaadhal sadugudu", "pachai nirame", "munbe vaa", "new york nagaram",
            "anbe", "nenje", "kuthu", "vaathi", "anirudh", "yuvan", "ilayaraja", "ar rahman"
        ]
    }
}

def is_verified_music_channel(uploader: str, artist: str = "") -> bool:
    """Returns True if the channel belongs to a verified record label, artist channel, or official Topic release."""
    up_low = str(uploader or "").strip().lower()
    if not up_low:
        return False
    if up_low.endswith('- topic') or ' - topic' in up_low:
        return True
    if 'vevo' in up_low:
        return True
    for pat in REGIONAL_CHANNEL_PATTERNS.values():
        if pat.search(up_low):
            return True
    if SOUTH_MULTI_REGIONAL_LABELS.search(up_low):
        return True
    for lbl in MAJOR_INTERNATIONAL_LABELS:
        if lbl in up_low:
            return True
    if artist:
        a_low = str(artist).strip().lower()
        if a_low and (a_low == up_low or a_low in up_low or up_low in a_low):
            return True
    return False
