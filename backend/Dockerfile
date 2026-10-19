FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml ./
COPY netsync ./netsync
RUN pip install --no-cache-dir .

# Unprivileged ICMP for the latency plugin is enabled through the
# net.ipv4.ping_group_range sysctl in docker-compose.yml.
RUN useradd --system --uid 1000 netsync
USER netsync

EXPOSE 8000
CMD ["netsync-api"]
