/**
 * ==============================================================================
 * ML Music Search Ranker & SongValidator (Node.js / JavaScript)
 * ==============================================================================
 * Drop-in zero-dependency module for Discord Bots (Poru, Kazagumo, Magma, etc.)
 * - Multilingual & Tamil phonetic search matching
 * - Strict SongValidator (rejects trailers, reactions, 1-hr loops, covers, edits)
 * - Topic channel & verified studio audio prioritization (+55 pts)
 * ==============================================================================
 */

const TAMIL_VOWELS = {
  "அ": "a", "ஆ": "aa", "இ": "i", "ஈ": "ii", "உ": "u",
  "ஊ": "uu", "எ": "e", "ஏ": "ee", "ஐ": "ai", "ஒ": "o",
  "ஓ": "oo", "ஔ": "au", "ஃ": "h",
};
const TAMIL_SIGNS = {
  "ா": "aa", "ி": "i", "ீ": "ii", "ு": "u", "ூ": "uu",
  "ெ": "e", "ே": "ee", "ை": "ai", "ொ": "o", "ோ": "oo",
  "ௌ": "au",
};
const TAMIL_CONSONANTS = {
  "க": "k", "ங": "ng", "ச": "s", "ஞ": "ny", "ட": "t",
  "ண": "n", "த": "th", "ந": "n", "ப": "p", "ம": "m",
  "ய": "y", "ர": "r", "ல": "l", "வ": "v", "ழ": "zh",
  "ள": "l", "ற": "r", "ன": "n", "ஜ": "j", "ஷ": "sh",
  "ஸ": "s", "ஹ": "h", "க்ஷ": "ksh",
};

const THEATRICAL_VIDEO_KEYWORDS = [
  'video song', 'full video song', 'full video', 'movie video',
  'film version', 'movie version', 'theatrical version'
];

const PURE_AUDIO_KEYWORDS = [
  'official audio', 'audio song', 'original audio', 'album track',
  'studio version', 'original sound track', 'official track',
  'lyric video', 'lyrical video', 'lyrical'
];

const DIALOGUE_KEYWORDS = [
  'dialogue', 'dialogues', 'dialog', 'with dialogue', 'with dialogues',
  'dialogue promo', 'dialogue teaser', 'movie scene', 'deleted scene',
  'scene cut', 'intro scene', 'climax scene', 'comedy scene', 'movie clip',
  'film scene', 'fight scene', 'scenes'
];

const NON_MUSIC_KEYWORDS = [
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
  '10 hours', '10 hr', '1 hour', '1 hr', 'loop audio',
  'dance class', 'dance cover', 'dance choreography', 'beginners class', 'bhangra performance'
].concat(DIALOGUE_KEYWORDS);

const UNWANTED_EDIT_KEYWORDS = [
  'slowed', 'reverb', 'sped up', 'speed up', 'speedup', 'pitched', 'pitch shifted',
  'bass boosted', 'bassboost', 'boosted', 'nightcore', '8d audio', '8d music',
  'ringtone', 'status video', 'whatsapp status', 'shorts'
];

const MAJOR_LABELS = [
  'sony music', 'sonymusic', 't-series', 'tseries', 'zee music', 'saregama',
  'think music', 'aditya music', 'lahari', 'vevo', 'yrf', 'tips', 'speed records',
  'muzik247', 'warner music', 'universal music', 'think indie', 'divo'
];

const TAMIL_HINTS = [
  'tamil', 'kollywood', 'tamizh', 'thamizh', 'tanglish', 'kuthu', 'anbe', 'nenje',
  'oorum blood', 'hukum', 'badass', 'naa ready', 'vaathi', 'anirudh', 'yuvan', 'ar rahman', 'ilayaraja'
];

// Helper Utilities
function normalizeSearchText(text) {
  if (!text) return '';
  return text.normalize('NFKC')
    .toLowerCase()
    .replace(/[\(\[\{].*?[\)\]\}]/g, ' ')
    .replace(/[^\p{L}\p{N}\s]/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function containsTamilScript(text) {
  if (!text) return false;
  for (let i = 0; i < text.length; i++) {
    const code = text.charCodeAt(i);
    if (code >= 0x0B80 && code <= 0x0BFF) return true;
  }
  return false;
}

function tamilScriptToLatin(text) {
  if (!text) return '';
  const norm = text.normalize('NFKC');
  const out = [];
  let i = 0;
  while (i < norm.length) {
    const char = norm[i];
    if (norm.startsWith('க்ஷ', i)) {
      out.push('ksh');
      i += 3;
      continue;
    }
    if (TAMIL_CONSONANTS[char]) {
      const syllable = TAMIL_CONSONANTS[char];
      const next = norm[i + 1] || '';
      if (next === '்') {
        out.push(syllable);
        i += 2;
        continue;
      }
      if (TAMIL_SIGNS[next]) {
        out.push(syllable + TAMIL_SIGNS[next]);
        i += 2;
        continue;
      }
      out.push(syllable + 'a');
    } else if (TAMIL_VOWELS[char]) {
      out.push(TAMIL_VOWELS[char]);
    } else if (char !== '்' && char !== '\u200C' && char !== '\u200D') {
      out.push(char);
    }
    i++;
  }
  return normalizeSearchText(out.join(''));
}

function phoneticNormalize(text) {
  let val = normalizeSearchText(text);
  val = val.replace(/aai/g, 'ai');
  const pairs = [
    ['ae', 'e'], ['aa', 'a'], ['ee', 'i'], ['ii', 'i'], ['oo', 'u'], ['uu', 'u'],
    ['dh', 'th'], ['bh', 'b'], ['ph', 'p'], ['zh', 'l'], ['ch', 's'], ['c', 's'],
    ['thth', 'th'], ['ngng', 'ng'], ['kk', 'k'], ['pp', 'p'], ['tt', 't'],
    ['nn', 'n'], ['ll', 'l'], ['rr', 'r']
  ];
  for (const [src, tgt] of pairs) {
    val = val.split(src).join(tgt);
  }
  val = val.replace(/\b(y|ya)(e|a)/g, 'e');
  return val.replace(/\s+/g, ' ').trim();
}

function isTamilContext(query, candidates = []) {
  if (containsTamilScript(query)) return true;
  const qNorm = ` ${normalizeSearchText(query)} `;
  if (TAMIL_HINTS.some(h => qNorm.includes(` ${h} `))) return true;

  for (const c of candidates) {
    const text = `${c.title || ''} ${c.author || c.uploader || ''} ${c.artist || ''}`;
    if (containsTamilScript(text)) return true;
    const tNorm = ` ${normalizeSearchText(text)} `;
    if (TAMIL_HINTS.some(h => tNorm.includes(` ${h} `))) return true;
  }
  return false;
}

function matchingForms(text, tamilAware = false) {
  const raw = normalizeSearchText(text);
  const roman = containsTamilScript(text) ? tamilScriptToLatin(text) : raw;
  const forms = [raw, roman];
  if (tamilAware) {
    forms.push(phoneticNormalize(roman));
  }
  return Array.from(new Set(forms.filter(Boolean)));
}

function tokenRecall(left, right, ignored = new Set()) {
  const lForms = matchingForms(left, true);
  const rForms = matchingForms(right, true);
  let best = 0.0;

  for (const lf of lForms) {
    const lTokens = lf.split(' ').filter(t => t.length > 1 && !ignored.has(t));
    if (!lTokens.length) continue;
    for (const rf of rForms) {
      const rTokens = new Set(rf.split(' ').filter(t => t.length > 1));
      const matchCount = lTokens.filter(t => rTokens.has(t)).length;
      best = Math.max(best, matchCount / lTokens.length);
    }
  }
  return best;
}

function isVerifiedMusicChannel(uploader = '', artist = '') {
  const up = uploader.toLowerCase();
  if (!up) return false;
  if (up.includes('- topic') || up.includes('vevo')) return true;
  if (MAJOR_LABELS.some(lbl => up.includes(lbl))) return true;
  if (artist) {
    const a = artist.toLowerCase();
    if (a && (up.includes(a) || a.includes(up))) return true;
  }
  return false;
}

/**
 * Validates candidate against non-music noise and returns [score, confidence]
 */
function validateAndScore(candidate, targetTitle = '', targetArtist = '', expectedDuration = 0) {
  const title = candidate.title || candidate.name || '';
  const uploader = candidate.author || candidate.uploader || candidate.channel || '';
  const artist = candidate.artist || uploader;
  const duration = Math.round((candidate.length || candidate.duration || 0) / (candidate.length > 10000 ? 1000 : 1));

  const tLow = title.toLowerCase();
  const upLow = uploader.toLowerCase();
  const targetLow = targetTitle.toLowerCase();

  // 1. Immediate rejection for non-music indicators (trailers, reactions, etc.)
  for (const kw of NON_MUSIC_KEYWORDS) {
    const reg = new RegExp(`\\b${kw.replace(/[-\/\\^$*+?.()|[\]{}]/g, '\\$&')}\\b`, 'i');
    if (reg.test(tLow) || reg.test(upLow)) {
      if (['trailer', 'teaser', 'podcast'].includes(kw) && tLow.includes('soundtrack')) continue;
      return [-100, "LOW"];
    }
  }

  // 2. Strict unwanted edit rejection (slowed, reverb, bass boosted, 8d)
  for (const edit of UNWANTED_EDIT_KEYWORDS) {
    if (!targetLow.includes(edit)) {
      const reg = new RegExp(`\\b${edit.replace(/[-\/\\^$*+?.()|[\]{}]/g, '\\$&')}\\b`, 'i');
      if (reg.test(tLow)) return [-100, "LOW"];
    }
  }

  // 3. Strict Cover & Karaoke rejection unless user asked for it
  const wantsCover = ['cover', 'karaoke', 'tribute', 'parody'].some(w => targetLow.includes(w));
  if (!wantsCover) {
    const coverPatterns = [/\bcovers?\b/i, /\bkaraoke\b/i, /\btribute\b/i, /\bparody\b/i];
    if (coverPatterns.some(p => p.test(tLow) || p.test(upLow))) {
      return [-100, "LOW"];
    }
  }

  // 4. Duration check
  if (duration > 0 && expectedDuration === 0) {
    if (duration > 1200 && !['album', 'playlist', 'compilation'].some(k => targetLow.includes(k))) {
      return [-100, "LOW"];
    }
    if (duration < 20) return [-100, "LOW"];
  }

  let score = 0;
  const isOfficial = isVerifiedMusicChannel(uploader, artist);
  const tamilAware = isTamilContext(targetTitle, [candidate]);

  // 5. Title Match (Exact & Transliterated)
  const normTarget = normalizeSearchText(targetTitle);
  const normTitle = normalizeSearchText(title);

  if (normTarget) {
    const targetForms = matchingForms(targetTitle, tamilAware);
    const titleForms = matchingForms(title, tamilAware);
    const exactMatch = targetForms.some(tf => titleForms.includes(tf));

    if (normTarget === normTitle || exactMatch) {
      score += 60; // Perfect match
    } else if (normTitle.includes(normTarget) || normTarget.includes(normTitle)) {
      score += 45;
    } else {
      const recall = tokenRecall(targetTitle, `${title} ${artist} ${uploader}`);
      if (recall >= 0.8) score += 45;
      else if (recall >= 0.5) score += 30;
      else if (recall >= 0.3) score += 15;
    }
  }

  // 6. Studio & Official Quality Boosts
  const isTopic = upLow.includes('- topic');
  const hasPureAudio = PURE_AUDIO_KEYWORDS.some(k => tLow.includes(k));

  if (isTopic) score += 55; // Topic channel pure studio recording
  else if (hasPureAudio) score += 45;
  else if (isOfficial) score += 25;

  // Theatrical video song penalty (dialogues and background actor noise)
  const isTheatrical = THEATRICAL_VIDEO_KEYWORDS.some(k => tLow.includes(k));
  if (isTheatrical && !['video song', 'full video'].some(k => targetLow.includes(k))) {
    score -= 40;
  }

  const confidence = score >= 35 ? "HIGH" : (score >= 20 ? "MEDIUM" : "LOW");
  return [score, confidence];
}

/**
 * Main ML search ranker: takes search query and array of tracks from Lavalink (Poru)
 * and returns the tracks sorted by highest studio audio quality & relevance.
 */
function rankTracks(query, tracks = []) {
  if (!tracks || !tracks.length) return [];

  const candidates = tracks.map(track => {
    // Poru stores info inside track.info
    const info = track.info || track;
    const [score, confidence] = validateAndScore(info, query);
    return { track, score, confidence };
  });

  // Filter and sort
  const validated = candidates.filter(c => c.confidence !== "LOW" && c.score > 0);
  
  if (validated.length > 0) {
    validated.sort((a, b) => b.score - a.score);
    return validated.map(c => c.track);
  }

  // Fallback: if all scored LOW, return all candidates sorted by score
  candidates.sort((a, b) => b.score - a.score);
  return candidates.map(c => c.track);
}

module.exports = {
  rankTracks,
  validateAndScore,
  isTamilContext,
  normalizeSearchText,
  containsTamilScript,
  phoneticNormalize
};

// ==============================================================================
// Standalone Zero-Dependency ML Reverse Proxy for Lavalink (when run directly)
// ==============================================================================
if (require.main === module) {
  const http = require('http');
  const net = require('net');
  const url = require('url');

  const PROXY_PORT = parseInt(process.env.PORT || process.env.LAVALINK_PROXY_PORT || '4998', 10);
  const BACKEND_PORT = parseInt(process.env.LAVALINK_PORT || '4999', 10);
  const BACKEND_HOST = process.env.LAVALINK_HOST || '127.0.0.1';

  const server = http.createServer((req, res) => {
    const reqUrl = url.parse(req.url, true);

    // Intercept /v4/loadtracks to apply ML Ranking
    if (reqUrl.pathname === '/v4/loadtracks' && req.method === 'GET') {
      const backendReq = http.request({
        hostname: BACKEND_HOST,
        port: BACKEND_PORT,
        path: req.url,
        method: 'GET',
        headers: req.headers
      }, (backendRes) => {
        const chunks = [];
        backendRes.on('data', chunk => chunks.push(chunk));
        backendRes.on('end', () => {
          const raw = Buffer.concat(chunks).toString('utf-8');
          try {
            const data = JSON.parse(raw);
            const identifier = reqUrl.query.identifier || '';
            let tracks = null;

            if (data.loadType === 'search' && Array.isArray(data.data)) {
              tracks = data.data;
            } else if (data.loadType === 'playlist' && data.data && Array.isArray(data.data.tracks)) {
              tracks = data.data.tracks;
            } else if (Array.isArray(data.tracks)) {
              tracks = data.tracks;
            }

            if (tracks && tracks.length > 1) {
              const cleanQuery = identifier.replace(/^[a-z]+search:/i, '');
              const ranked = rankTracks(cleanQuery, tracks);
              if (data.loadType === 'search') data.data = ranked;
              else if (data.loadType === 'playlist') data.data.tracks = ranked;
              else data.tracks = ranked;
            }

            const modified = Buffer.from(JSON.stringify(data), 'utf-8');
            const headers = { ...backendRes.headers, 'content-length': modified.length };
            res.writeHead(backendRes.statusCode, headers);
            res.end(modified);
          } catch (e) {
            res.writeHead(backendRes.statusCode, backendRes.headers);
            res.end(raw);
          }
        });
      });

      backendReq.on('error', (err) => {
        res.writeHead(502, { 'content-type': 'application/json' });
        res.end(JSON.stringify({ loadType: 'error', data: { message: `Lavalink ML Gateway unreachable: ${err.message}` } }));
      });
      req.pipe(backendReq);
      return;
    }

    // Default transparent HTTP proxy
    const proxyReq = http.request({
      hostname: BACKEND_HOST,
      port: BACKEND_PORT,
      path: req.url,
      method: req.method,
      headers: req.headers
    }, (proxyRes) => {
      res.writeHead(proxyRes.statusCode, proxyRes.headers);
      proxyRes.pipe(res);
    });

    proxyReq.on('error', (err) => {
      res.writeHead(502, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ error: err.message }));
    });
    req.pipe(proxyReq);
  });

  // WebSocket transparent tunneling (for /v4/websocket)
  server.on('upgrade', (req, clientSocket, head) => {
    const backendSocket = net.connect(BACKEND_PORT, BACKEND_HOST, () => {
      backendSocket.write(
        `${req.method} ${req.url} HTTP/${req.httpVersion}\r\n` +
        Object.entries(req.headers).map(([k, v]) => `${k}: ${v}`).join('\r\n') +
        '\r\n\r\n'
      );
      if (head && head.length) backendSocket.write(head);
      backendSocket.pipe(clientSocket);
      clientSocket.pipe(backendSocket);
    });

    backendSocket.on('error', (err) => {
      console.error('[ML Proxy WS Error]', err.message);
      clientSocket.destroy();
    });
    clientSocket.on('error', () => backendSocket.destroy());
  });

  server.listen(PROXY_PORT, '0.0.0.0', () => {
    console.log(`===================================================`);
    console.log(`    Ryuga Lavalink ML Gateway (Node.js)`);
    console.log(`===================================================`);
    console.log(`[INFO] Listening on port ${PROXY_PORT} (Public)`);
    console.log(`[INFO] Forwarding to Lavalink backend at ${BACKEND_HOST}:${BACKEND_PORT}`);
    console.log(`[INFO] ML Search Ranking & SongValidator: ACTIVE`);
  });
}

