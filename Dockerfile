# Dockerfile для PortableAI Creator
FROM python:3.11-slim-bookworm

LABEL description="PortableAI Creator — веб-интерфейс для сборки портативных AI-приложений"

# Устанавливаем системные зависимости (git, build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем исходный код
COPY . .

# Создаём папки для вывода
RUN mkdir -p output/portable output/reports

EXPOSE 5000
ENV FLASK_ENV=production
ENV ALLOWED_HOSTS=127.0.0.1,localhost

# Запуск через gunicorn (или fallback на flask)
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "900", "main:app"]
