# --- ВЕРСИЯ С ПОЛЬЗОВАТЕЛЬСКИМИ API-КЛЮЧАМИ ---

import os
import requests
import json
from flask import Flask, jsonify, request, g # <-- ДОБАВЛЕНО 'g'
from functools import wraps
from dotenv import load_dotenv
import sqlite3
import atexit

load_dotenv()
# --- Настройка Базы Данных ---
DB_NAME = 'users.db'
db_connection = sqlite3.connect(DB_NAME, check_same_thread=False)
atexit.register(lambda: db_connection.close())

def setup_database():
    cursor = db_connection.cursor()
    # ОБНОВЛЕННАЯ ТАБЛИЦА USERS
    cursor.execute('''

        CREATE TABLE IF NOT EXISTS users (
            api_key TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            message_count INTEGER NOT NULL DEFAULT 0,
            message_limit INTEGER NOT NULL
        )
    ''')
    # ОБНОВЛЕННАЯ ТАБЛИЦА MESSAGES
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_api_key TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    db_connection.commit()
    print("База данных (users и messages) с поддержкой API-ключей готова.")

app = Flask(__name__)

# --- Ключи провайдеров (без изменений) ---
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
# MY_PROVIDER_API_KEY больше не нужен, у каждого свой ключ

MODEL_MAPPING = {}
# ... (блок MODEL_MAPPING без изменений) ...
if OPENAI_API_KEY:
    MODEL_MAPPING.update({"klassicheskiy-gpt4": {"provider": "openai", "real_model": "gpt-3.5-turbo", "provider_url": "https://api.openai.com/v1/chat/completions", "api_key": OPENAI_API_KEY}})
if GOOGLE_API_KEY:
    MODEL_MAPPING.update({"tvoy-bystriy-gemini": {"provider": "google", "real_model": "gemini-2.0-flash", "provider_url": f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GOOGLE_API_KEY}", "api_key": GOOGLE_API_KEY}})
if GROQ_API_KEY:
    MODEL_MAPPING.update({"besplatniy-compound": { "provider": "openai", "real_model": "groq/compound-mini", "provider_url": "https://api.groq.com/openai/v1/chat/completions", "api_key": GROQ_API_KEY}})

# --- ОБНОВЛЕННАЯ СИСТЕМА БЕЗОПАСНОСТИ ---
def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"error": "Auth header is missing or invalid"}), 401
        
        provided_key = auth_header.split(' ')[1]
        
        # Ищем ключ в базе данных
        cursor = db_connection.cursor()
        cursor.execute("SELECT api_key, username, message_count, message_limit FROM users WHERE api_key = ?", (provided_key,))
        user_data = cursor.fetchone()
        
        if not user_data:
            return jsonify({"error": "Invalid API key"}), 403 # 403 Forbidden - ключ неверный
        
        # Сохраняем данные пользователя для этого запроса
        g.user = {
            'api_key': user_data[0],
            'username': user_data[1],
            'message_count': user_data[2],
            'message_limit': user_data[3]
        }
        return f(*args, **kwargs)
    return decorated_function

# --- ОБНОВЛЕННЫЕ ЭНДПОИНТЫ ---
@app.route('/v1/models', methods=['GET'])
@require_api_key # Теперь он проверяет ключ пользователя
def list_models():
    # ... (код без изменений) ...
    model_list = []
    for model_id, details in MODEL_MAPPING.items():
        if details.get("api_key"): model_list.append({"id": model_id, "object": "model", "owned_by": "bratiwka-inc"})
    return jsonify({"object": "list", "data": model_list})

@app.route('/v1/chat/completions', methods=['POST'])
@require_api_key # Этот же декоратор находит пользователя и его лимиты
def chat_completions():
    # g.user был создан в декораторе
    user = g.user
    
    # Проверяем лимит для этого конкретного пользователя
    if user['message_count'] >= user['message_limit']:
        print(f"Лимит {user['message_limit']} сообщений достигнут для пользователя: {user['username']}")
        error_response = {"id": "chatcmpl-limit-exceeded", "object": "chat.completion", "choices": [{"message": {"role": "assistant", "content": f"Извините, {user['username']}, вы достигли своего лимита в {user['message_limit']} сообщений."}}]}
        return jsonify(error_response), 429

    # --- Логика запросов и сохранения ---
    cursor = db_connection.cursor()
    request_data = request.json
    user_message = request_data.get("messages", [])[-1]
    
    # Сохраняем сообщение пользователя, используя его ключ
    if user_message:
        cursor.execute("INSERT INTO messages (user_api_key, role, content) VALUES (?, ?, ?)", (user['api_key'], user_message['role'], user_message['content']))
        db_connection.commit()

    # ... (вся остальная логика запросов к OpenAI/Google остается без изменений) ...
    model_id = request_data.get("model")
    # ...
    target = MODEL_MAPPING[model_id]
    provider = target["provider"]
    try:
        response_data = None
        if provider == "openai":
            # ...
            headers = {"Authorization": f"Bearer {target['api_key']}", "Content-Type": "application/json"}
            payload = {"model": target["real_model"], "messages": request_data.get("messages", [])}
            response = requests.post(target["provider_url"], headers=headers, json=payload)
            response.raise_for_status()
            response_data = response.json()
        elif provider == "google":
            # ...
            headers = {"Content-Type": "application/json"}
            openai_messages = request_data.get("messages", [])
            google_contents = [{"role": "user" if msg['role'] == "user" else "model", "parts": [{"text": msg['content']}]} for msg in openai_messages if msg['role'] != 'system']
            payload = {"contents": google_contents}
            response = requests.post(target["provider_url"], headers=headers, json=payload)
            response.raise_for_status()
            google_response = response.json()
            content = google_response.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "Error parsing Google response.")
            response_data = {"id": "chatcmpl-google", "object": "chat.completion", "choices": [{"message": {"role": "assistant", "content": content}}]}

        if response_data:
            # Обновляем счетчик и сохраняем ответ ассистента
            cursor.execute("UPDATE users SET message_count = ? WHERE api_key = ?", (user['message_count'] + 1, user['api_key']))
            assistant_message = response_data.get("choices", [{}])[0].get("message", {})
            if assistant_message:
                cursor.execute("INSERT INTO messages (user_api_key, role, content) VALUES (?, ?, ?)", (user['api_key'], assistant_message.get('role', 'assistant'), assistant_message.get('content', '')))
            db_connection.commit()
            print(f"Сообщение {user['message_count'] + 1}/{user['message_limit']} от {user['username']} (ключ: ...{user['api_key'][-4:]}) записано в БД")
            return jsonify(response_data)
    except Exception as e:
        # ... (обработка ошибок) ...
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    setup_database()
    print("Сервер-посредник с поддержкой пользовательских API-ключей запущен!")
    print("Используйте 'python3 manage_users.py' для управления пользователями.")
    app.run(host='0.0.0.0', port=8088)