FROM python:3.11-slim

WORKDIR /app

# ── Zona horaria del negocio (Bogotá) ──────────────────────────────────────────
ENV TZ=America/Bogota
RUN apt-get update && apt-get install -y tzdata wget \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt
RUN pip install fastapi uvicorn sqlalchemy psycopg2-binary pydantic apscheduler python-dotenv

COPY . .

ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
