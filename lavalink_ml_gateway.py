#!/usr/bin/env python3
"""
==============================================================================
Lavalink v4 ML Search Gateway & Intelligent Audio Proxy
==============================================================================
Enhances Lavalink with:
  1. Multilingual & Tamil phonetic search reranker (LightGBM + Heuristic weights)
  2. Strict music track validation (rejects trailers, reactions, 1-hr loops, covers, unwanted edits)
  3. Studio audio & Topic channel prioritization
  4. Multi-source search aggregation (mlsearch:)
  5. Asynchronous telemetry & interaction logging (WAL SQLite) for continuous learning
  6. Transparent WebSocket audio tunnel & REST proxy
==============================================================================
"""

from __future__ import annotations
import os
import sys
import time
import json
import uuid
import shutil
import asyncio
import logging
import argparse
import subprocess
from typing import Optional, Dict, Any, List

import httpx
import uvicorn
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, PlainTextResponse
import websockets

import ml
from ml import SearchRankingModel, SearchFeatureExtractor, SongValidator, InteractionLogger, MusicTelemetryEvent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("lavalink.ml.gateway")

from contextlib import asynccontextmanager

# Configuration Defaults
CONFIG = {
    "host": "0.0.0.0",
    "port": 4998,
    "backend_url": "http://127.0.0.1:5998",
    "backend_ws_url": "ws://127.0.0.1:5998/v4/websocket",
    "password": "ryugalavalink",
    "spawn_lavalink": True,
    "jar_path": "Lavalink.jar",
    "jvm_opts": "-Xmx2G -XX:+UseG1GC -XX:+ParallelRefProcEnabled",
    "filter_junk": True,
}

_HTTP_CLIENT: Optional[httpx.AsyncClient] = None
_SEARCH_RANKER: Optional[SearchRankingModel] = None
_LOGGER: Optional[InteractionLogger] = None
_LAVALINK_PROC: Optional[subprocess.Popen] = None


def load_application_yml():
    """Extract port and password from application.yml if present."""
    config_file = "application.yml"
    if not os.path.exists(config_file):
        config_file = "application.example.yml"

    if os.path.exists(config_file):
        try:
            import yaml
            with open(config_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            
            srv = data.get("server", {})
            if "port" in srv:
                CONFIG["port"] = int(srv["port"])

            lav = data.get("lavalink", {}).get("server", {})
            if "password" in lav:
                CONFIG["password"] = str(lav["password"])
                
            logger.info(f"Loaded configuration from {config_file} (port: {CONFIG['port']})")
        except Exception as e:
            logger.warning(f"Failed parsing YAML config: {e}. Using defaults.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _HTTP_CLIENT, _SEARCH_RANKER, _LOGGER
    logger.info("Initializing Lavalink ML Gateway...")
    _HTTP_CLIENT = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))
    _SEARCH_RANKER = SearchRankingModel()
    _LOGGER = InteractionLogger.get_instance("data/ml/interactions.db")
    await _LOGGER.initialize()
    logger.info("ML Search Engine & Interaction Logger online.")
    yield
    logger.info("Shutting down Lavalink ML Gateway...")
    if _HTTP_CLIENT:
        await _HTTP_CLIENT.aclose()
    if _LOGGER:
        await _LOGGER.close()
    if _LAVALINK_PROC and _LAVALINK_PROC.poll() is None:
        logger.info("Stopping Java Lavalink process...")
        _LAVALINK_PROC.terminate()
        try:
            _LAVALINK_PROC.wait(timeout=5)
        except Exception:
            _LAVALINK_PROC.kill()

app = FastAPI(title="Lavalink ML Gateway", version="1.0.0", lifespan=lifespan)


# ------------------------------------------------------------------------------
# ML Management Endpoints
# ------------------------------------------------------------------------------

@app.get("/v4/ml/status")
async def ml_status():
    """Return status of ML ranking models and telemetry."""
    return {
        "status": "online",
        "gateway_version": "1.0.0",
        "backend_url": CONFIG["backend_url"],
        "lightgbm_available": ml.search_ranker.HAS_LIGHTGBM,
        "numpy_available": ml.search_ranker.HAS_NUMPY,
        "model_loaded": _SEARCH_RANKER.is_trained() if hasattr(_SEARCH_RANKER, "is_trained") else False,
        "feature_count": len(SearchFeatureExtractor.FEATURE_NAMES),
        "features": SearchFeatureExtractor.FEATURE_NAMES,
        "database": _LOGGER.db_path if _LOGGER else None,
    }


@app.get("/v4/ml/test")
async def ml_test(q: str):
    """Test ML reranker on a live search query without needing a bot."""
    t_start = time.time()
    url = f"{CONFIG['backend_url']}/v4/loadtracks"
    headers = {"Authorization": CONFIG["password"]}
    params = {"identifier": f"ytmsearch:{q}"}
    
    try:
        resp = await _HTTP_CLIENT.get(url, headers=headers, params=params)
        raw_data = resp.json()
        tracks = raw_data.get("data", []) if raw_data.get("loadType") == "search" else []
        candidates = [convert_track_to_candidate(t) for t in tracks]
        ranked = _SEARCH_RANKER.rank_candidates(q, candidates)
        latency = (time.time() - t_start) * 1000
        
        return {
            "query": q,
            "latency_ms": round(latency, 2),
            "raw_count": len(tracks),
            "ranked_count": len(ranked),
            "ranked_candidates": [
                {
                    "rank": idx + 1,
                    "score": round(score, 1),
                    "title": cand.get("title"),
                    "uploader": cand.get("uploader"),
                    "duration_sec": cand.get("duration"),
                    "source": cand.get("source"),
                    "uri": cand.get("url")
                }
                for idx, (score, cand) in enumerate(ranked)
            ]
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/v4/ml/train")
async def ml_train():
    """Trigger offline LightGBM training from accumulated user listening feedback."""
    loop = asyncio.get_running_loop()
    res = await loop.run_in_executor(None, ml.TrainingPipeline.run_tamil_search_training)
    return {"result": res}


# ------------------------------------------------------------------------------
# Core ML Search Interception (/v4/loadtracks)
# ------------------------------------------------------------------------------

def convert_track_to_candidate(track: dict) -> dict:
    """Format Lavalink v4 track info into SearchRankingModel candidate dictionary."""
    info = track.get("info", {})
    length_ms = info.get("length") or 0
    duration_sec = int(length_ms / 1000) if length_ms else 0
    title = info.get("title", "")
    author = info.get("author", "")
    source = info.get("sourceName", "youtube")
    
    t_low = title.lower()
    a_low = author.lower()
    is_studio = ("- topic" in a_low) or any(k in t_low for k in ["official audio", "album track", "studio version"])

    return {
        "title": title,
        "song_name": title,
        "artist": author,
        "artists": author,
        "uploader": author,
        "channel": author,
        "duration": duration_sec,
        "id": info.get("identifier", ""),
        "yt_video_id": info.get("identifier", ""),
        "url": info.get("uri", ""),
        "source": "ytm_song" if is_studio else source,
        "is_studio_song": is_studio,
        "_raw_track": track
    }


def clean_search_query(identifier: str) -> tuple[str, bool, str]:
    """Extract clean search query and determine search mode."""
    prefixes = ["mlsearch:", "ytmsearch:", "ytsearch:", "spsearch:", "scsearch:", "search:"]
    for p in prefixes:
        if identifier.startswith(p):
            return identifier[len(p):].strip(), True, p
            
    is_url = identifier.startswith("http://") or identifier.startswith("https://")
    if not is_url:
        return identifier.strip(), True, "search:"
        
    return identifier, False, ""


async def execute_ml_search(clean_query: str, search_prefix: str, headers: dict) -> dict:
    """Execute high-precision ML search query against Lavalink backend."""
    t_start = time.time()
    url = f"{CONFIG['backend_url']}/v4/loadtracks"
    raw_tracks = []
    
    if search_prefix == "mlsearch:":
        # Multi-source discovery: fetch from both YouTube Music (ytmsearch) and YouTube (ytsearch)
        tasks = [
            _HTTP_CLIENT.get(url, headers=headers, params={"identifier": f"ytmsearch:{clean_query}"}),
            _HTTP_CLIENT.get(url, headers=headers, params={"identifier": f"ytsearch:{clean_query}"})
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        seen_ids = set()
        for r in responses:
            if isinstance(r, httpx.Response) and r.status_code == 200:
                try:
                    data = r.json()
                    if data.get("loadType") == "search":
                        for t in data.get("data", []):
                            ident = t.get("info", {}).get("identifier") or t.get("info", {}).get("uri")
                            if ident and ident not in seen_ids:
                                seen_ids.add(ident)
                                raw_tracks.append(t)
                except Exception:
                    pass
    else:
        # Standard search through user's chosen prefix
        backend_identifier = f"{search_prefix}{clean_query}"
        resp = await _HTTP_CLIENT.get(url, headers=headers, params={"identifier": backend_identifier})
        if resp.status_code != 200:
            return resp.json()
        data = resp.json()
        if data.get("loadType") != "search":
            return data
        raw_tracks = data.get("data", [])

    if not raw_tracks:
        return {"loadType": "empty", "data": []}

    # Pass all candidate tracks into SearchRankingModel & SongValidator
    candidates = [convert_track_to_candidate(t) for t in raw_tracks]
    ranked = _SEARCH_RANKER.rank_candidates(clean_query, candidates)

    ranked_tracks = []
    used_tracks = set()

    for score, cand in ranked:
        raw_t = cand.get("_raw_track")
        if raw_t:
            # Annotate track with ML scoring metadata
            info = raw_t.setdefault("info", {})
            raw_t.setdefault("pluginInfo", {})["mlScore"] = round(score, 1)
            raw_t["pluginInfo"]["mlValidated"] = True
            ranked_tracks.append(raw_t)
            used_tracks.add(id(raw_t))

    # Append any unranked tracks to the end unless strict filtering is enabled
    if not CONFIG["filter_junk"]:
        for t in raw_tracks:
            if id(t) not in used_tracks:
                t.setdefault("pluginInfo", {})["mlValidated"] = False
                ranked_tracks.append(t)

    # Log telemetry event for continuous self-learning
    try:
        request_id = uuid.uuid4().hex
        selected_track = ranked_tracks[0]["info"] if ranked_tracks else {}
        _LOGGER.log_event_sync(
            MusicTelemetryEvent.SEARCH_IMPRESSION,
            guild_id=0,
            track={"title": selected_track.get("title"), "artist": selected_track.get("author")},
            metadata={
                "request_id": request_id,
                "query": clean_query,
                "latency_ms": round((time.time() - t_start) * 1000, 2),
                "candidates_count": len(raw_tracks),
                "ranked_count": len(ranked_tracks),
            }
        )
    except Exception:
        pass

    logger.info(f"[ML SEARCH] '{clean_query}' -> {len(raw_tracks)} candidates -> top hit: '{ranked_tracks[0]['info']['title']}' ({round(ranked[0][0], 1) if ranked else 0} pts)")

    return {
        "loadType": "search",
        "data": ranked_tracks
    }


# ------------------------------------------------------------------------------
# Transparent Reverse Proxy & WebSocket Tunnel
# ------------------------------------------------------------------------------

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def proxy_http(request: Request, path: str):
    """Proxy HTTP requests between client bots and backend Lavalink with ML search intercept."""
    # Check if this is a track load request
    if path == "v4/loadtracks":
        identifier = request.query_params.get("identifier", "")
        clean_q, is_search, prefix = clean_search_query(identifier)
        if is_search and clean_q:
            headers = dict(request.headers)
            headers.pop("host", None)
            headers.pop("content-length", None)
            result = await execute_ml_search(clean_q, prefix, headers)
            return JSONResponse(result)

    # Forward all other requests directly to backend Lavalink
    backend_target = f"{CONFIG['backend_url']}/{path}"
    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("content-length", None)

    body = await request.body()
    try:
        resp = await _HTTP_CLIENT.request(
            method=request.method,
            url=backend_target,
            params=request.query_params,
            headers=headers,
            content=body
        )
        excluded_headers = {"content-encoding", "transfer-encoding", "content-length"}
        res_headers = {k: v for k, v in resp.headers.items() if k.lower() not in excluded_headers}
        return Response(content=resp.content, status_code=resp.status_code, headers=res_headers)
    except Exception as e:
        logger.error(f"Error forwarding HTTP request to {backend_target}: {e}")
        return JSONResponse({"error": "Lavalink backend unreachable", "details": str(e)}, status_code=502)


@app.websocket("/v4/websocket")
async def proxy_websocket(client_ws: WebSocket):
    """Full-duplex WebSocket audio tunnel forwarding opcodes and tracking telemetry events."""
    await client_ws.accept()
    
    headers = {}
    for h in ["authorization", "user-id", "client-name"]:
        val = client_ws.headers.get(h)
        if val:
            headers[h] = val

    backend_ws_url = CONFIG["backend_ws_url"]
    logger.info(f"Client connected to /v4/websocket (User-Id: {client_ws.headers.get('user-id')})")

    try:
        async with websockets.connect(backend_ws_url, extra_headers=headers) as backend_ws:
            async def client_to_backend():
                try:
                    while True:
                        msg = await client_ws.receive_text()
                        await backend_ws.send(msg)
                except WebSocketDisconnect:
                    pass
                except Exception as ex:
                    logger.debug(f"client_to_backend closed: {ex}")

            async def backend_to_client():
                try:
                    while True:
                        msg = await backend_ws.recv()
                        # Inspect events for ML feedback logging
                        try:
                            payload = json.loads(msg)
                            op = payload.get("op")
                            event_type = payload.get("type")
                            guild_id = int(payload.get("guildId") or 0)
                            
                            if op == "event" and _LOGGER:
                                if event_type == "TrackStartEvent":
                                    track = payload.get("track", {}).get("info", {})
                                    _LOGGER.log_event_sync(MusicTelemetryEvent.PLAY_STARTED, guild_id=guild_id, track=track)
                                elif event_type == "TrackEndEvent":
                                    reason = payload.get("reason")
                                    track = payload.get("track", {}).get("info", {})
                                    if reason == "FINISHED":
                                        _LOGGER.log_event_sync(MusicTelemetryEvent.PLAY_COMPLETED, guild_id=guild_id, track=track)
                                    elif reason in ("STOPPED", "REPLACED"):
                                        _LOGGER.log_event_sync(MusicTelemetryEvent.SKIP, guild_id=guild_id, track=track)
                                elif event_type == "TrackExceptionEvent":
                                    track = payload.get("track", {}).get("info", {})
                                    _LOGGER.log_event_sync(MusicTelemetryEvent.PLAYBACK_FAILURE, guild_id=guild_id, track=track, metadata={"error": payload.get("exception", {}).get("message")})
                        except Exception:
                            pass

                        await client_ws.send_text(msg)
                except Exception as ex:
                    logger.debug(f"backend_to_client closed: {ex}")

            await asyncio.gather(client_to_backend(), backend_to_client())

    except Exception as e:
        logger.error(f"WebSocket tunnel error: {e}")
        try:
            await client_ws.close(code=1011, reason="Backend Lavalink unreachable")
        except Exception:
            pass


# ------------------------------------------------------------------------------
# Autonomous Java Lavalink Child Process
# ------------------------------------------------------------------------------

def launch_lavalink_backend(jar_path: str, backend_port: int) -> Optional[subprocess.Popen]:
    """Launch Lavalink.jar in background on backend_port with memory optimization."""
    java_cmd = shutil.which("java")
    if not java_cmd:
        logger.warning("[WARNING] 'java' command not found in system PATH. Cannot auto-spawn Lavalink.jar.")
        logger.warning(f"Please ensure Lavalink is running separately on port {backend_port}.")
        return None

    if not os.path.isfile(jar_path):
        logger.warning(f"[WARNING] {jar_path} not found. Cannot auto-spawn Lavalink.")
        return None

    cmd = [java_cmd] + CONFIG["jvm_opts"].split() + ["-jar", jar_path, f"--server.port={backend_port}"]
    logger.info(f"Starting Lavalink backend on internal port {backend_port}...")
    logger.info(f"Command: {' '.join(cmd)}")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )

        def stream_logs():
            for line in iter(proc.stdout.readline, ''):
                clean_line = line.strip()
                if clean_line:
                    print(f"[Lavalink-Core] {clean_line}")

        import threading
        t = threading.Thread(target=stream_logs, daemon=True)
        t.start()
        return proc
    except Exception as e:
        logger.error(f"Failed to spawn Lavalink process: {e}")
        return None


# ------------------------------------------------------------------------------
# Entrypoint
# ------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Lavalink v4 ML Search Gateway")
    parser.add_argument("--port", type=int, default=None, help="Public port for bots to connect (default from application.yml or 4998)")
    parser.add_argument("--backend-port", type=int, default=5998, help="Internal port for Java Lavalink (default: 5998)")
    parser.add_argument("--no-spawn", action="store_true", help="Do not auto-spawn Java Lavalink (use if running in separate container/process)")
    parser.add_argument("--backend-url", type=str, default=None, help="Custom backend Lavalink HTTP URL")
    parser.add_argument("--keep-junk", action="store_true", help="Do not filter out rejected tracks (place at end of results)")
    args = parser.parse_args()

    load_application_yml()

    public_port = args.port or CONFIG["port"]
    backend_port = args.backend_port
    CONFIG["port"] = public_port
    CONFIG["filter_junk"] = not args.keep_junk

    if args.backend_url:
        CONFIG["backend_url"] = args.backend_url.rstrip("/")
        ws_scheme = "wss" if CONFIG["backend_url"].startswith("https") else "ws"
        host_part = CONFIG["backend_url"].split("://")[-1]
        CONFIG["backend_ws_url"] = f"{ws_scheme}://{host_part}/v4/websocket"
    else:
        CONFIG["backend_url"] = f"http://127.0.0.1:{backend_port}"
        CONFIG["backend_ws_url"] = f"ws://127.0.0.1:{backend_port}/v4/websocket"

    print("=" * 65)
    print("        🚀 RYUGA LAVALINK v4 - ML SEARCH INTELLIGENCE NODE")
    print("=" * 65)
    print(f" [Public Gateway Port]   : {public_port}  (Discord bots connect here!)")
    print(f" [Internal Backend Port] : {backend_port}")
    print(f" [ML Search Reranker]    : Active (24 dense features + LightGBM)")
    print(f" [Phonetic & Tamil Match]: Active (Orthographic & Script transliteration)")
    print(f" [Junk/Cover Filter]     : {'Strict Quality Gate (Active)' if CONFIG['filter_junk'] else 'Appended at end'}")
    print(f" [Continuous Learning]   : Active (SQLite WAL: data/ml/interactions.db)")
    print("=" * 65)

    if not args.no_spawn:
        global _LAVALINK_PROC
        _LAVALINK_PROC = launch_lavalink_backend(CONFIG["jar_path"], backend_port)

    uvicorn.run(app, host=CONFIG["host"], port=public_port, log_level="warning")


if __name__ == "__main__":
    main()
