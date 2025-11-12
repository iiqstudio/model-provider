# Dockerfile

# Используем официальный легковесный образ Python
FROM python:3.9-slim

# Устанавливаем рабочую директорию внутри контейнера
WORKDIR /app

# Копируем сначала файл с зависимостями, чтобы использовать кэш Docker
COPY requirements.txt .

# Устанавливаем зависимости
# --no-cache-dir уменьшает размер образа
RUN pip install --no-cache-dir -r requirements.txt

# Копируем все остальные файлы проекта в рабочую директорию
COPY . .

# Сообщаем Docker, что приложение будет слушать порт 8088
EXPOSE 8088

# Команда для запуска приложения с помощью Gunicorn
# Используем 1 воркера и 4 потока - это безопасно для SQLite
CMD ["gunicorn", "--workers", "1", "--threads", "4", "--bind", "0.0.0.0:8088", "custom_provider:app"]