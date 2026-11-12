# Build context: the plugins/ folder (docker build -f ssh/Dockerfile plugins)
FROM python:3.12-slim
RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn[standard]>=0.30" "httpx>=0.27" "asyncssh>=2.17"
RUN useradd --system --uid 10001 plugin && mkdir /data && chown plugin /data
WORKDIR /app
COPY sdk/netsync_plugin.py ssh/app.py ssh/bastion.py ssh/gateway.py ssh/setup.sh ssh/netsync-account ./
USER plugin
ENV NETSYNC_DATA=/data
VOLUME /data
EXPOSE 8080 2222
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--ws-max-size", "1048576"]
