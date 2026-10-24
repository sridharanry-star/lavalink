#!/usr/bin/env bash
echo "==================================================="
echo "    Starting Ryuga Lavalink v4 Audio Server"
echo "==================================================="
exec java -Xmx2G -XX:+UseG1GC -jar Lavalink.jar
