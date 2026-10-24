from __future__ import annotations
import os
import json
import time
import asyncio
import logging
from typing import Optional, Dict, Any, List
import aiosqlite

logger = logging.getLogger("lavalink.ml.telemetry")


class MusicTelemetryEvent:
    """Canonical behavioral, search, and operational events for ML search & ranking."""
    PLAY_REQUEST = "PLAY_REQUEST"
    SEARCH_IMPRESSION = "SEARCH_IMPRESSION"
    TRACK_RESOLVED = "TRACK_RESOLVED"
    SOURCE_SELECTED = "SOURCE_SELECTED"
    RESOLUTION_LATENCY = "RESOLUTION_LATENCY"
    EXTRACTION_LATENCY = "EXTRACTION_LATENCY"

    PREFETCH_SUCCESS = "PREFETCH_SUCCESS"
    PREFETCH_FAILURE = "PREFETCH_FAILURE"
    PLAYBACK_FAILURE = "PLAYBACK_FAILURE"
    PLAY_STARTED = "PLAY_STARTED"
    PLAY_COMPLETED = "PLAY_COMPLETED"
    PLAY_DURATION = "PLAY_DURATION"

    SKIP = "SKIP"
    MANUAL_NEXT = "MANUAL_NEXT"
    REPLAY = "REPLAY"
    LIKE = "LIKE"
    QUEUE_ADD = "QUEUE_ADD"

    ARTIST_REQUEST = "ARTIST_REQUEST"
    ALBUM_REQUEST = "ALBUM_REQUEST"
    CATALOG_TRACK_SELECTED = "CATALOG_TRACK_SELECTED"
    CATALOG_EXHAUSTED = "CATALOG_EXHAUSTED"
    SIMILAR_VIBE_SELECTED = "SIMILAR_VIBE_SELECTED"
    RECOMMENDATION_ACCEPTED = "RECOMMENDATION_ACCEPTED"
    RECOMMENDATION_SKIPPED = "RECOMMENDATION_SKIPPED"


class InteractionLogger:
    """Non-blocking, asynchronous dual-plane interaction logging for Lavalink ML Recommender.
    Records behavioral, search, and operational events into SQLite WAL for offline ranking.
    Zero playback blocking: events are queued in-memory and batch-written in background.
    """

    _instance: Optional[InteractionLogger] = None
    DB_PATH = "data/ml/interactions.db"

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=20000)
        self._worker_task: Optional[asyncio.Task] = None
        self._is_running: bool = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._recent_search_by_track: Dict[tuple, tuple] = {}

    @classmethod
    def get_instance(cls, db_path: str = DB_PATH) -> InteractionLogger:
        if cls._instance is None:
            cls._instance = InteractionLogger(db_path=db_path)
        return cls._instance

    async def initialize(self):
        """Initializes SQLite WAL database with common telemetry envelope and starts worker."""
        if self._is_running:
            return

        try:
            self._loop = asyncio.get_running_loop()
            os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("PRAGMA journal_mode=WAL;")
                await db.execute("PRAGMA synchronous=NORMAL;")
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS interactions (
                        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp REAL NOT NULL,
                        guild_id INTEGER NOT NULL,
                        user_id INTEGER NOT NULL,
                        session_id TEXT,
                        event_type TEXT NOT NULL,
                        track_id TEXT,
                        title TEXT,
                        artist TEXT,
                        artist_id TEXT,
                        album TEXT,
                        album_id TEXT,
                        language TEXT,
                        mood TEXT,
                        queue_mode TEXT,
                        source TEXT,
                        position INTEGER DEFAULT 0,
                        played_seconds REAL DEFAULT 0.0,
                        track_duration REAL DEFAULT 0.0,
                        completion_ratio REAL DEFAULT 0.0,
                        latency_ms REAL DEFAULT 0.0,
                        metadata TEXT,
                        duration REAL DEFAULT 0.0,
                        played_duration REAL DEFAULT 0.0,
                        extra_data TEXT
                    )
                """)
                await db.execute("CREATE INDEX IF NOT EXISTS idx_int_event ON interactions(event_type, timestamp);")
                await db.execute("CREATE INDEX IF NOT EXISTS idx_int_guild ON interactions(guild_id, timestamp);")
                await db.execute("CREATE INDEX IF NOT EXISTS idx_int_track ON interactions(track_id);")
                await db.commit()

            self._is_running = True
            self._worker_task = asyncio.create_task(self._process_queue())
        except Exception as e:
            logger.error(f"[TELEMETRY INIT ERROR] Failed to initialize interactions database: {e}")

    async def _process_queue(self):
        """Background batch writer for ultra-fast non-blocking persistence."""
        batch: List[tuple] = []
        while self._is_running:
            try:
                while len(batch) < 50:
                    try:
                        timeout = 1.5 if not batch else 0.1
                        item = await asyncio.wait_for(self._queue.get(), timeout=timeout)
                        batch.append(item)
                        self._queue.task_done()
                    except asyncio.TimeoutError:
                        break

                if batch:
                    async with aiosqlite.connect(self.db_path) as db:
                        await db.executemany("""
                            INSERT INTO interactions (
                                timestamp, guild_id, user_id, session_id, event_type,
                                track_id, title, artist, artist_id, album, album_id,
                                language, mood, queue_mode, source, position,
                                played_seconds, track_duration, completion_ratio, latency_ms, metadata,
                                duration, played_duration, extra_data
                            ) VALUES (
                                ?, ?, ?, ?, ?,
                                ?, ?, ?, ?, ?, ?,
                                ?, ?, ?, ?, ?,
                                ?, ?, ?, ?, ?,
                                ?, ?, ?
                            )
                        """, batch)
                        await db.commit()
                    batch.clear()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[TELEMETRY WRITER ERROR] Batch persist failed: {e}")
                batch.clear()
                await asyncio.sleep(1.0)

    def log_event_sync(
        self,
        event_type: str,
        guild_id: int = 0,
        user_id: int = 0,
        track: Optional[dict] = None,
        played_seconds: float = 0.0,
        latency_ms: float = 0.0,
        session_id: Optional[str] = None,
        queue_mode: Optional[str] = None,
        source: Optional[str] = None,
        position: int = 0,
        metadata: Optional[dict] = None,
        **kwargs
    ) -> None:
        """Thread-safe synchronous enqueue that never blocks or raises."""
        try:
            loop = self._loop
            if loop is None:
                loop = asyncio.get_running_loop()
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self.log_event(
                        event_type=event_type,
                        guild_id=guild_id,
                        user_id=user_id,
                        track=track,
                        played_seconds=played_seconds,
                        latency_ms=latency_ms,
                        session_id=session_id,
                        queue_mode=queue_mode,
                        source=source,
                        position=position,
                        metadata=metadata,
                        **kwargs
                    ),
                    loop
                )
        except Exception:
            pass

    async def log_event(
        self,
        event_type: str,
        guild_id: int = 0,
        user_id: int = 0,
        track: Optional[dict] = None,
        played_seconds: float = 0.0,
        latency_ms: float = 0.0,
        session_id: Optional[str] = None,
        queue_mode: Optional[str] = None,
        source: Optional[str] = None,
        position: int = 0,
        metadata: Optional[dict] = None,
        **kwargs
    ) -> None:
        """Asynchronously and non-blockingly enqueues a telemetry interaction event."""
        if not self._is_running:
            await self.initialize()

        try:
            track = track or {}
            track_id = str(track.get('id') or track.get('yt_video_id') or track.get('spotify_id') or track.get('url') or '')
            title = str(track.get('title') or kwargs.get('title') or '')
            artist = str(track.get('uploader') or track.get('artist') or kwargs.get('artist') or '')
            artist_id = str(track.get('artist_id') or kwargs.get('artist_id') or artist)
            album = str(track.get('album_name') or track.get('album') or kwargs.get('album') or '')
            album_id = str(track.get('album_id') or kwargs.get('album_id') or album)
            language = str(track.get('language') or kwargs.get('language') or 'unknown')
            mood = str(track.get('mood') or kwargs.get('mood') or 'auto')
            track_source = str(source or track.get('source') or 'unknown')
            q_mode = str(queue_mode or track.get('queue_mode') or 'standard')

            duration = float(track.get('duration') or kwargs.get('duration') or 0.0)
            played_sec = max(0.0, float(played_seconds or kwargs.get('played_duration') or 0.0))
            ratio = (played_sec / duration) if duration > 0 else 0.0
            ratio = min(1.0, max(0.0, ratio))

            meta = dict(metadata or {})
            if kwargs:
                for k, v in kwargs.items():
                    if k not in meta and k not in ('duration', 'played_duration', 'title', 'artist'):
                        meta[k] = v

            meta_json = json.dumps(meta)

            item = (
                time.time(),
                int(guild_id or 0),
                int(user_id or 0),
                str(session_id or f"guild_{guild_id}"),
                str(event_type),
                track_id,
                title,
                artist,
                artist_id,
                album,
                album_id,
                language,
                mood,
                q_mode,
                track_source,
                int(position or 0),
                played_sec,
                duration,
                ratio,
                float(latency_ms or 0.0),
                meta_json,
                duration,
                played_sec,
                meta_json
            )

            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            pass
        except Exception as e:
            logger.debug(f"[TELEMETRY ENQUEUE ERROR] {e}")

    async def flush(self):
        while not self._queue.empty():
            await asyncio.sleep(0.05)

    async def close(self):
        self._is_running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
