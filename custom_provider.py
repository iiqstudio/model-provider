import os
import requests
import json
from flask import Flask, jsonify, request
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)


MY_PROVIDER_API_KEY = os.environ.get('MY_PROVIDER_API_KEY')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY') 
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY') 

MODEL_MAPPING = {}

if OPENAI_API_KEY:
    MODEL_MAPPING.update({
        "umniy-gpt4o-mini": {
            "provider": "openai",
            "real_model": "gpt-4o-mini",
            "provider_url": "https://api.openai.com/v1/chat/completions",
            "api_key": OPENAI_API_KEY
        },
        "klassicheskiy-gpt4": {
            "provider": "openai",
            "real_model": "gpt-3.5-turbo",
            "provider_url": "https://api.openai.com/v1/chat/completions",
            "api_key": OPENAI_API_KEY
        }
    })

if GOOGLE_API_KEY:
    MODEL_MAPPING.update({
        "tvoy-bystriy-gemini": { 
            "provider": "google",
            "real_model": "gemini-2.0-flash",
            "provider_url": f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GOOGLE_API_KEY}", # Правильный URL Google
            "api_key": GOOGLE_API_KEY
        }
    })
def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not MY_PROVIDER_API_KEY: return f(*args, **kwargs)
        auth_header = request.headers.get('Authorization')
        if not auth_header or len(auth_header.split()) != 2: return jsonify({"error": "Auth header missing"}), 401
        if auth_header.split()[1] != MY_PROVIDER_API_KEY: return jsonify({"error": "Invalid API key"}), 401
        return f(*args, **kwargs)
    return decorated_function


@app.route('/v1/models', methods=['GET'])
@require_api_key
def list_models():
    """Отдает Open WebUI список НАШИХ моделей."""
    model_list = []
    for model_id, details in MODEL_MAPPING.items():
        if details.get("api_key"):
            model_list.append({"id": model_id, "object": "model", "owned_by": "bratiwka-inc"})
    return jsonify({"object": "list", "data": model_list})

@app.route('/v1/chat/completions', methods=['POST'])
@require_api_key
def chat_completions():
    """Принимает запрос и перенаправляет его в OpenAI или Google."""
    request_data = request.json
    model_id = request_data.get("model")

    if model_id not in MODEL_MAPPING or not MODEL_MAPPING[model_id].get("api_key"):
        return jsonify({"error": f"Model '{model_id}' not configured"}), 404

    target = MODEL_MAPPING[model_id]
    provider = target["provider"]

    try:
        if provider == "openai":
            headers = {"Authorization": f"Bearer {target['api_key']}", "Content-Type": "application/json"}
            payload = {"model": target["real_model"], "messages": request_data.get("messages", [])}
            response = requests.post(target["provider_url"], headers=headers, json=payload)
            response.raise_for_status()
            return jsonify(response.json())

        elif provider == "google":
            headers = {"Content-Type": "application/json"}
            openai_messages = request_data.get("messages", [])
            google_contents = []
            for msg in openai_messages:
                if msg['role'] == 'system':
                    continue # Простой вариант - пропустить
                google_contents.append({"role": "user" if msg['role'] == "user" else "model", "parts": [{"text": msg['content']}]})
            
            payload = {"contents": google_contents}
            response = requests.post(target["provider_url"], headers=headers, json=payload)
            response.raise_for_status()
            
            google_response = response.json()
            content = google_response.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "Извините, ответа от Google не получено.")
            
            openai_format_response = {
                "id": "chatcmpl-google", "object": "chat.completion",
                "choices": [{"message": {"role": "assistant", "content": content}}],
            }
            return jsonify(openai_format_response)

    except requests.exceptions.RequestException as e:
        error_details = str(e)
        if e.response is not None:
            error_details = e.response.text
        return jsonify({"error": f"Ошибка при обращении к '{provider}': {error_details}"}), 502
    
    return jsonify({"error": "Provider not implemented"}), 501

# --- 4. ЗАПУСК! ---
if __name__ == '__main__':
    print("Сервер-посредник запущен!")
    print("Доступные модели: " + ", ".join(MODEL_MAPPING.keys()))
    if not MY_PROVIDER_API_KEY:
        print("\n!!! ВНИМАНИЕ: Переменная MY_PROVIDER_API_KEY не задана. Доступ к серверу открыт для всех в локальной сети!!!\n")
    app.run(host='0.0.0.0', port=8088)