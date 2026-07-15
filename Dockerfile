FROM python:3.11-slim

WORKDIR /app

# system deps kept minimal on purpose to keep the image small and the
# container's memory footprint low (see performance requirement in README)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY sample_topics.json ./sample_topics.json
COPY verify.sh ./verify.sh
RUN chmod +x verify.sh

# generated at first run and cached, but pre-generate at build time so the
# 100-topic throughput run isn't paying corpus-generation cost
RUN python -c "from src.data.mock_search_dataset import ensure_dataset; ensure_dataset()"

ENV PYTHONUNBUFFERED=1 \
    OUTPUT_DIR=/app/outputs

RUN mkdir -p /app/outputs

ENTRYPOINT ["python", "-m", "src.main"]
CMD ["--topics-file", "sample_topics.json", "--output-dir", "/app/outputs"]
