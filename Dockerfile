# Use lightweight Eclipse Temurin 21 JRE Alpine image
FROM eclipse-temurin:21-jre-alpine

# Set working directory
WORKDIR /opt/lavalink

# Create dedicated non-root user
RUN addgroup -S lavalink && adduser -S lavalink -G lavalink

# Copy server, configuration, and offline plugins
COPY Lavalink.jar .
COPY application.example.yml application.yml
COPY plugins/ ./plugins/
COPY lavalink-plugins/ ./lavalink-plugins/

# Ensure proper permissions
RUN mkdir -p logs && chown -R lavalink:lavalink /opt/lavalink

USER lavalink

EXPOSE 4998

CMD ["java", "-Xmx2G", "-XX:+UseG1GC", "-jar", "Lavalink.jar"]
