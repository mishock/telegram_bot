# Используем официальный образ Python для Raspberry Pi (ARM64)
FROM python:3.11-slim-bookworm

# Устанавливаем рабочую директорию
WORKDIR /app

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Копируем файл с зависимостями
COPY requirements.txt .

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем все файлы проекта
COPY . .

# Создаём необходимые директории
RUN mkdir -p user_logs exports

# Даём права на выполнение
RUN chmod +x start.sh 2>/dev/null || true

# Открываем порт (если нужен веб-интерфейс, но для бота не обязателен)
EXPOSE 8080

# Команда запуска
CMD ["python", "-u", "bot.py"]