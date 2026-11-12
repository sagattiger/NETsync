FROM python:3.12-slim
RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn>=0.30" "httpx>=0.27"
RUN useradd --system --uid 10001 plugin
WORKDIR /app
COPY sdk/netsync_plugin.py examples/hello/app.py ./
USER plugin
EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
