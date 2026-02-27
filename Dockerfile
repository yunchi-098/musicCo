FROM python:3.9-slim

# Çalışma dizinini ayarla
WORKDIR /app

# Gerekli sistem paketlerini yükle (gerekirse)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Bağımlılıkları kopyala ve yükle
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Prodüksiyon sunucusu için gunicorn ve eventlet (SocketIO için) ekle
RUN pip install --no-cache-dir gunicorn eventlet

# Uygulama kodlarını kopyala
COPY . .

# Portu dışa aç
EXPOSE 8000

# Uygulamayı başlat
# SocketIO kullandığımız için worker-class eventlet olmalı
# Tekworker yeterli olacaktır, concurrency'i eventlet halleder.
CMD ["gunicorn", "--worker-class", "eventlet", "-w", "1", "-b", "0.0.0.0:8000", "app:app"]
