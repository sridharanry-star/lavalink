<div align="center">

# 🎧 Ryuga Lavalink v4 Server

**High-Performance • Standalone • Multi-Source Discord Audio Node**

[![Lavalink Version](https://img.shields.io/badge/Lavalink-v4.2.2-blueviolet?style=for-the-badge&logo=spring&logoColor=white)](https://github.com/lavalink-devs/Lavalink)
[![Java Version](https://img.shields.io/badge/Java-17%20%7C%2021%20LTS-orange?style=for-the-badge&logo=openjdk&logoColor=white)](https://adoptium.net/)
[![Plugins](https://img.shields.io/badge/Plugins-Bundled%20Local-success?style=for-the-badge&logo=coffeescript&logoColor=white)](#-bundled-plugins)
[![License](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge)](LICENSE)

<br/>

<p align="center">
  A tuned, turnkey <b>Lavalink v4</b> audio node configured for maximum reliability and playback fidelity. Featuring <b>Zero Remote Plugin Dependencies</b>, pre-configured YouTube OAuth with Cipher bypass, and SolaceAudio for unrestricted Spotify & Indian streaming support.
</p>

---

[Key Features](#-key-features) •
[Bundled Plugins](#-bundled-plugins) •
[Quick Start](#-quick-start) •
[Configuration](#-configuration) •
[Client Integration](#-client-integration) •
[Troubleshooting](#-troubleshooting)

---

</div>

<br/>

## ✨ Key Features

- ⚡ **Zero Remote Dependencies**: Plugins are pre-bundled as local JARs in `./plugins/` — boots instantly without relying on JitPack, GitHub releases, or Maven Central network requests during startup.
- 🎯 **Advanced YouTube & YouTube Music**:
  - Multi-client fallback rotation (`MUSIC`, `ANDROID_MUSIC`, `TV`, `TVHTML5_SIMPLY`, `WEBEMBEDDED`, etc.).
  - YouTube OAuth integration for bypassing age-gated and restricted tracks.
  - Remote Cipher integration (`cipher.kikkia.dev`) for seamless YouTube signature decoding.
- 🟢 **Spotify & JioSaavn Support (SolaceAudio)**:
  - Employs internal GraphQL resolution — **No Spotify Developer App or Spotify Premium subscription required**!
  - Native track, album, and playlist resolution with auto-fallback to YouTube Music.
  - Full support for JioSaavn (`jssearch:`) streaming.
- 🎛️ **Full Audio Filter Suite**: Built-in real-time filters: 15-band Equalizer, Karaoke, Timescale (Speed/Pitch/Rate), Tremolo, Vibrato, Distortion, Rotation (8D Audio), Channel Mix, and Low-Pass.
- 🚀 **High-Throughput Undertow Tuning**: Direct buffers enabled, custom worker threads, and tuned buffer durations for zero audio stutter even under heavy load.

<br/>

---

## 🧩 Bundled Plugins

All plugins are located in the [`plugins/`](./plugins/) directory and loaded automatically:

| Plugin | Version | Capabilities | Description |
| :--- | :--- | :--- | :--- |
| **`solaceaudio-plugin`** | `1.0.18` | Spotify, JioSaavn | GraphQL-based Spotify/JioSaavn source with zero developer quota limits |
| **`ryuga-youtube-plugin`** | `v4` | YouTube, YouTube Music | Upstream dev.lavalink.youtube with cipher & multi-client playback |
| **`ryuga-lavasrc-plugin`** | `4.3.0` | Extended Sources | LavaSrc source provider support |
| **`ryuga-lavasearch-plugin`** | `v4` | Search APIs | Enhanced REST search endpoint for track, album, and artist lookups |

<br/>

---

## 📁 Repository Structure

```plaintext
├── application.yml                 # Active Lavalink v4 configuration
├── application.example.yml         # Sanitized configuration template for deployment
├── Lavalink.jar                    # Lavalink v4 server executable
├── start.bat                       # One-click Windows startup script
├── start.sh                        # Optimized Linux / macOS startup script
├── plugins/                        # Pre-bundled local plugin JARs
│   ├── ryuga-lavasearch-plugin.jar
│   ├── ryuga-lavasrc-plugin.jar
│   ├── ryuga-youtube-plugin.jar
│   └── solaceaudio-plugin-1.0.18.jar
├── lavalink-plugins/               # Plugin metadata configuration
│   └── lavasrc-plugin.properties
└── README.md                       # Documentation & usage guide
```

<br/>

---

## 🚀 Quick Start

### Prerequisites

- **Java 17 or Java 21+ LTS** (64-bit) installed.
  - Download from [Eclipse Adoptium (Temurin)](https://adoptium.net/) or [Oracle Java](https://www.oracle.com/java/technologies/downloads/).
  - Verify your installation:
    ```bash
    java -version
    ```

### Launching the Server

#### 🪟 Windows
Double-click `start.bat` or run:
```bat
start.bat
```

#### 🐧 Linux / macOS
Grant execution permissions and execute `start.sh`:
```bash
chmod +x start.sh
./start.sh
```

#### ⌨️ Manual Command
```bash
java -Xmx2G -XX:+UseG1GC -jar Lavalink.jar
```

Once started, Lavalink will bind to `0.0.0.0:4998` (or the port specified in `application.yml`).

<br/>

---

## ⚙️ Configuration Guide

The primary configuration is defined in [`application.yml`](./application.yml).

### 1. Server & Authentication
```yaml
server:
  address: 0.0.0.0
  port: 4998               # Port your bot connects to

lavalink:
  server:
    password: "ryugalavalink" # Secret password for WebSocket and REST API
    resamplingQuality: HIGH
    sources:
      youtube: false       # Handled by dev.lavalink.youtube plugin
      soundcloud: false
      bandcamp: true
      twitch: true
      vimeo: true
      http: true
```

### 2. YouTube OAuth & Remote Cipher
Configured under `plugins.youtube`:
```yaml
plugins:
  youtube:
    enabled: true
    clients:
      - MUSIC
      - ANDROID_MUSIC
      - TV
      - TVHTML5_SIMPLY
      - WEBEMBEDDED
    oauth:
      enabled: true
      skipInitialization: true
      refreshToken: "YOUR_YOUTUBE_REFRESH_TOKEN"
    remoteCipher:
      url: "https://cipher.kikkia.dev"
      userAgent: "yt-source"
```

### 3. SolaceAudio (Spotify & JioSaavn)
SolaceAudio uses internal GraphQL tokens so you never hit Spotify Developer API quotas:
```yaml
plugins:
  solaceaudio:
    sources:
      spotify: true
      jiosaavn: true
    providers:
      - "ytmsearch:\"{isrc}\""
      - "ytmsearch:{query}"
      - "jssearch:{query}"
    spotify:
      countryCode: "IN"
      playlistLoadLimit: 50
      albumLoadLimit: 50
      spDc: "YOUR_SPDC_COOKIE" # Optional: unlocks user personal playlists
```

> [!TIP]
> Use [`application.example.yml`](./application.example.yml) as a clean template when sharing your code or deploying on public infrastructure.

<br/>

---

## 🔌 Client Integration

Connect any popular Discord audio library to this Lavalink node:

### 🟩 Node.js (Kazagurumo / Poru / Discord.js)
```javascript
const { Kazagurumo } = require("kazagurumo");
const Spotify = require("kazagurumo-spotify");

const Nodes = [
  {
    name: "Ryuga-Node",
    url: "localhost:4998",
    auth: "ryugalavalink",
    secure: false
  }
];

const kazagurumo = new Kazagurumo({
  defaultSearchEngine: "youtube_music",
  send: (guildId, payload) => {
    const guild = client.guilds.cache.get(guildId);
    if (guild) guild.shard.send(payload);
  }
}, new Connectors.DiscordJS(client), Nodes);
```

### 🐍 Python (Wavelink / Discord.py)
```python
import discord
from discord.ext import commands
import wavelink

bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())

@bot.event
async def on_ready():
    node = wavelink.Node(
        uri="http://localhost:4998",
        password="ryugalavalink"
    )
    await wavelink.Pool.connect(nodes=[node], client=bot)
    print("✅ Connected to Lavalink Node")
```

### ☕ Java (Lavalink-Client / JDA)
```java
LavalinkClient client = new LavalinkClient(userId);
client.addNode(
    new NodeOptions.Builder()
        .setName("Ryuga-Node")
        .setServerUri(URI.create("ws://localhost:4998"))
        .setPassword("ryugalavalink")
        .build()
);
```

<br/>

---

## 🛠️ Production Deployment (Systemd Service)

To run Lavalink 24/7 as a background service on Linux Ubuntu/Debian:

1. Create a service file:
   ```bash
   sudo nano /etc/systemd/system/lavalink.service
   ```
2. Paste the following configuration:
   ```ini
   [Unit]
   Description=Lavalink v4 Audio Node
   After=network.target

   [Service]
   Type=simple
   User=root
   WorkingDirectory=/path/to/lavalink
   ExecStart=/usr/bin/java -Xmx2G -XX:+UseG1GC -jar Lavalink.jar
   Restart=always
   RestartSec=10
   StandardOutput=syslog
   StandardError=syslog
   SyslogIdentifier=lavalink

   [Install]
   WantedBy=multi-user.target
   ```
3. Enable and start:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now lavalink
   sudo journalctl -u lavalink -f
   ```

<br/>

---

## ❓ Troubleshooting & FAQ

<details>
<summary><b>1. YouTube 429 (Too Many Requests) or "Sign in to confirm you're not a bot"</b></summary>
<br/>
YouTube frequently throttles IP addresses from shared data centers. To resolve:
- Ensure <code>remoteCipher</code> is enabled in <code>application.yml</code>.
- Supply a valid <code>refreshToken</code> under <code>plugins.youtube.oauth</code>.
- Utilize residential proxies or IPv6 /29 or /64 blocks if running on a cloud VPS.
</details>

<details>
<summary><b>2. "Unsupported major.minor version" on startup</b></summary>
<br/>
Lavalink v4 requires <b>Java 17 or higher</b> (Java 21 LTS recommended). Update your Java runtime using Adoptium Temurin.
</details>

<details>
<summary><b>3. Port already in use (BindException)</b></summary>
<br/>
Change <code>server.port</code> in <code>application.yml</code> to another free port (e.g., <code>2333</code> or <code>8080</code>), or terminate any previous process still bound to port <code>4998</code>.
</details>

<br/>

---

## 🔒 Security Best Practices

> [!WARNING]
> - **Change the Default Password**: Update `lavalink.server.password` before opening your port to the internet.
> - **Protect Secrets**: Never publish your Spotify `spDc` cookie or YouTube OAuth `refreshToken` to public repositories.
> - **Firewall Protection**: Bind to `127.0.0.1` if your bot and Lavalink reside on the same server, or configure `ufw` to whitelist only your bot's IP.

---

<div align="center">
  <sub>Crafted for high performance Discord audio bots. Built with ❤️.</sub>
</div>
