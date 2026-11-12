FROM python:3.12-slim
RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn>=0.30" "httpx>=0.27" "docker>=7.1"
WORKDIR /app
COPY app.py ./
EXPOSE 8090
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090"]
