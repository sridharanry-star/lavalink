# Use lightweight Eclipse Temurin 21 JRE Alpine image
FROM eclipse-temurin:21-jre-alpine

# Install Python 3 and native libraries for ML Gateway
RUN apk add --no-cache python3 py3-pip py3-numpy py3-scipy build-base python3-dev

# Set working directory
WORKDIR /opt/lavalink

# Copy requirements and install python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --break-system-packages

# Create dedicated non-root user
RUN addgroup -S lavalink && adduser -S lavalink -G lavalink

# Copy server, configuration, offline plugins, and ML modules
COPY Lavalink.jar .
COPY application.example.yml application.yml
COPY plugins/ ./plugins/
COPY lavalink-plugins/ ./lavalink-plugins/
COPY ml/ ./ml/
COPY lavalink_ml_gateway.py .

# Ensure proper permissions
RUN mkdir -p logs data/ml && chown -R lavalink:lavalink /opt/lavalink

USER lavalink

# Expose default public gateway port
EXPOSE 4998

# Launch ML Gateway (auto-spawns Java Lavalink backend on internal port 5998)
ENTRYPOINT ["python3", "lavalink_ml_gateway.py", "--port", "4998", "--backend-port", "5998"]
