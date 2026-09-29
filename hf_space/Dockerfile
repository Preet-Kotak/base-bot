FROM python:3.11-slim

WORKDIR /app

# system deps for opencv
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# copy app + src modules + model weights
COPY app.py .
COPY extractor.py .
COPY model/ ./model/

EXPOSE 7860

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
