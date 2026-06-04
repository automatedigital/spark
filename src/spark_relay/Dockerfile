# Spark OAuth Relay — minimal container image.
#
# Build (from repo root):
#   docker build -f src/spark_relay/Dockerfile -t spark-relay .
# Run:
#   docker run -p 8088:8088 \
#     -e RELAY_GOOGLE_CLIENT_ID=...apps.googleusercontent.com \
#     -e RELAY_GOOGLE_CLIENT_SECRET=... \
#     -e RELAY_SIGNING_SECRET="$(openssl rand -hex 32)" \
#     -e RELAY_REDIRECT_URI=https://auth.yourdomain.com/callback \
#     spark-relay
FROM python:3.11-slim

WORKDIR /app
RUN pip install --no-cache-dir "fastapi>=0.110" "uvicorn[standard]>=0.29" "httpx>=0.27"

COPY src/spark_relay /app/spark_relay

EXPOSE 8088
CMD ["uvicorn", "spark_relay.app:app", "--host", "0.0.0.0", "--port", "8088"]
