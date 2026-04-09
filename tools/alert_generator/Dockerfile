FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir httpx

COPY gen.py /app/gen.py

ENTRYPOINT ["python", "/app/gen.py"]

