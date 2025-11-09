# --- ТВОЙ КОД, ПРОКАЧАННЫЙ С ПОМОЩЬЮ SQLITE ---

import os
import requests
import json
from flask import Flask, jsonify, request
from functools import wraps
from dotenv import load_dotenv
import sqlite3  # <-- 1. ДОБАВЛЕНО
import atexit   # <-- 2. ДОБАВЛЕНО

load_dotenv()

# --- Настройка Базы Данных ---
DB_NAME = 'users.db'
db_connection = sqlite3.connect(DB_NAME, check_same_thread=False)
atexit.register(lambda: db_connection.close())

def setup_database():
    """Создает таблицу для пользователей, если она еще не существует."""
    cursor = db_connection.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            ip TEXT PRIMARY KEY,
            message_count INTEGER NOT NULL DEFAULT 0
        )
    ''')
    db_connection.commit()
    print("База данных готова к работе.")
# --- КОНЕЦ БЛОКА БД ---

app = Flask(__name__)

# --- 1. ЦЕНТР УПРАВЛЕНИЯ (без изменений, кроме удаления словаря) ---
MY_PROVIDER_API_KEY = os.environ.get('MY_PROVIDER_API_KEY')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY') 
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY') 
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')

MESSAGE_LIMIT = 100
# user_message_counts = {} # <-- 3. УДАЛЕНО. Больше не нужно, у нас есть БД.

MODEL_MAPPING = {}
if OPENAI_API_KEY:
    MODEL_MAPPING.update({
        "umniy-gpt4o-mini": {"provider": "openai", "real_model": "gpt-4o-mini", "provider_url": "https://api.openai.com/v1/chat/completions", "api_key": OPENAI_API_KEY},
        "klassicheskiy-gpt4": {"provider": "openai", "real_model": "gpt-3.5-turbo", "provider_url": "https://api.openai.com/v1/chat/completions", "api_key": OPENAI_API_KEY}
    })
if GOOGLE_API_KEY:
    MODEL_MAPPING.update({
        "tvoy-bystriy-gemini": {"provider": "google", "real_model": "gemini-2.0-flash", "provider_url": f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GOOGLE_API_KEY}", "api_key": GOOGLE_API_KEY}
    })
if GROQ_API_KEY:
    MODEL_MAPPING.update({
        "besplatniy-compound": { "provider": "openai", "real_model": "groq/compound-mini", "provider_url": "https://api.groq.com/openai/v1/chat/completions", "api_key": GROQ_API_KEY}
    })

# --- 2. СИСТЕМА БЕЗОПАСНОСТИ (без изменений) ---
def require_api_key(f):
    @wraps(f)
    # ... (код без изменений) ...
    def decorated_function(*args, **kwargs):
        if not MY_PROVIDER_API_KEY: return f(*args, **kwargs)
        auth_header = request.headers.get('Authorization')
        if not auth_header or len(auth_header.split()) != 2: return jsonify({"error": "Auth header missing"}), 401
        if auth_header.split()[1] != MY_PROVIDER_API_KEY: return jsonify({"error": "Invalid API key"}), 401
        return f(*args, **kwargs)
    return decorated_function

# --- 3. ГЛАВНЫЕ ЭНДПОИНТЫ (API) ---

@app.route('/v1/models', methods=['GET'])
@require_api_key
def list_models():
    # ... (код без изменений) ...
    model_list = []
    for model_id, details in MODEL_MAPPING.items():
        if details.get("api_key"): model_list.append({"id": model_id, "object": "model", "owned_by": "bratiwka-inc"})
    return jsonify({"object": "list", "data": model_list})

@app.route('/v1/chat/completions', methods=['POST'])
@require_api_key
def chat_completions():
    # --- НАЧАЛО ОБНОВЛЕННОГО БЛОКА ПРОВЕРКИ ЛИМИТА ---
    user_ip = request.remote_addr
    cursor = db_connection.cursor()

    cursor.execute("SELECT message_count FROM users WHERE ip = ?", (user_ip,))
    result = cursor.fetchone()

    if result:
        current_count = result[0]
    else:
        cursor.execute("INSERT INTO users (ip, message_count) VALUES (?, 0)", (user_ip,))
        db_connection.commit()
        current_count = 0
    
    if current_count >= MESSAGE_LIMIT:
        print(f"Лимит {MESSAGE_LIMIT} сообщений достигнут для IP: {user_ip}")
        error_response = {"id": "chatcmpl-limit-exceeded", "object": "chat.completion", "choices": [{"message": {"role": "assistant", "content": f"Извините, вы достигли лимита в {MESSAGE_LIMIT} сообщений. Для продолжения, пожалуйста, приобретите подписку."}}]}
        return jsonify(error_response), 429
    # --- КОНЕЦ ОБНОВЛЕННОГО БЛОКА ПРОВЕРКИ ЛИМИТА ---

    request_data = request.json
    model_id = request_data.get("model")
    if model_id not in MODEL_MAPPING or not MODEL_MAPPING[model_id].get("api_key"): return jsonify({"error": f"Model '{model_id}' not configured"}), 404
    
    target = MODEL_MAPPING[model_id]
    provider = target["provider"]
    
    try:
        response_data = None
        # ... (здесь вся твоя рабочая логика для openai и google, без изменений) ...
        if provider == "openai":
            headers = {"Authorization": f"Bearer {target['api_key']}", "Content-Type": "application/json"}
            payload = {"model": target["real_model"], "messages": request_data.get("messages", [])}
            response = requests.post(target["provider_url"], headers=headers, json=payload)
            response.raise_for_status()
            response_data = response.json()
        elif provider == "google":
            headers = {"Content-Type": "application/json"}
            openai_messages = request_data.get("messages", [])
            google_contents = [{"role": "user" if msg['role'] == "user" else "model", "parts": [{"text": msg['content']}]} for msg in openai_messages if msg['role'] != 'system']
            payload = {"contents": google_contents}
            response = requests.post(target["provider_url"], headers=headers, json=payload)
            response.raise_for_status()
            google_response = response.json()
            content = google_response.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "Error parsing Google response.")
            response_data = {"id": "chatcmpl-google", "object": "chat.completion", "choices": [{"message": {"role": "assistant", "content": content}}]}

        # --- ОБНОВЛЕННЫЙ БЛОК УСПЕХА ---
        if response_data:
            # Увеличиваем счетчик В БАЗЕ ДАННЫХ
            cursor.execute("UPDATE users SET message_count = ? WHERE ip = ?", (current_count + 1, user_ip))
            db_connection.commit()
            print(f"Сообщение {current_count + 1}/{MESSAGE_LIMIT} от IP: {user_ip} (записано в БД)")
            return jsonify(response_data)
        
        return jsonify({"error": "Provider logic failed to return data"}), 500

    except requests.exceptions.RequestException as e:
        # ... (обработка ошибок без изменений) ...
        error_details = str(e)
        if e.response is not None: error_details = e.response.text
        return jsonify({"error": f"Ошибка при обращении к '{provider}': {error_details}"}), 502

# --- 4. ЗАПУСК! ---
if __name__ == '__main__':
    setup_database() # <-- ВЫЗЫВАЕМ ФУНКЦИЮ ПОДГОТОВКИ БД
    print("Сервер-посредник с БД SQLite запущен!") # <-- Обновленное сообщение
    print(f"Установлен лимит: {MESSAGE_LIMIT} сообщений на один IP.")
    print("Доступные модели: " + ", ".join(MODEL_MAPPING.keys()))
    app.run(host='0.0.0.0', port=8088)