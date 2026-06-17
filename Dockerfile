FROM python:3.11

RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

RUN pip install playwright fastapi uvicorn

RUN playwright install chromium

WORKDIR /app
COPY . .

CMD ["python", "app.py"]