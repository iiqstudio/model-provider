# --- ВЕРСИЯ С АБСОЛЮТНЫМ ПУТЕМ К БД (ФИНАЛЬНАЯ) ---

import os # <-- ДОБАВЛЕН ИМПОРТ
import requests
import json
from flask import Flask, jsonify, request, g, Response
from functools import wraps
from dotenv import load_dotenv
import secrets

from flask_sqlalchemy import SQLAlchemy
from flask_admin import Admin, AdminIndexView
from flask_admin.contrib.sqla import ModelView

load_dotenv()

# --- ГЛАВНОЕ ИЗМЕНЕНИЕ: АБСОЛЮТНЫЙ ПУТЬ К БАЗЕ ДАННЫХ ---
# Вычисляем абсолютный путь к директории, где находится этот скрипт
basedir = os.path.abspath(os.path.dirname(__file__))
DB_NAME = 'users.db'

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('MY_PROVIDER_API_KEY', 'default-secret-key-CHANGE-ME')
# Создаем полный, абсолютный путь к файлу базы данных
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, DB_NAME)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['FLASK_ADMIN_SWATCH'] = 'cerulean'
# --- КОНЕЦ ГЛАВНОГО ИЗМЕНЕНИЯ ---

db = SQLAlchemy(app)

# --- Все остальные классы и функции остаются без изменений ---

class User(db.Model):
    __tablename__ = 'users'
    api_key = db.Column(db.Text, primary_key=True)
    username = db.Column(db.Text, unique=True, nullable=False)
    message_count = db.Column(db.Integer, nullable=False, default=0)
    message_limit = db.Column(db.Integer, nullable=False)

    def __repr__(self):
        return self.username

class Message(db.Model):
    __tablename__ = 'messages'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_api_key = db.Column(db.Text, db.ForeignKey('users.api_key'), nullable=False)
    role = db.Column(db.Text, nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, server_default=db.func.now())

class ProtectedAdminIndexView(AdminIndexView):
    def is_accessible(self):
        auth = request.authorization
        admin_user = os.environ.get('ADMIN_USERNAME')
        admin_pass = os.environ.get('ADMIN_PASSWORD')
        if not auth or not (auth.username == admin_user and auth.password == admin_pass):
            return False
        return True

    def inaccessible_callback(self, name, **kwargs):
        return Response(
            'Could not verify your access level for that URL.\n'
            'You have to login with proper credentials', 401,
            {'WWW-Authenticate': 'Basic realm="Login Required"'})

class UserAdminView(ModelView):
    column_list = ('username', 'api_key', 'message_count', 'message_limit')
    column_searchable_list = ('username', 'api_key')
    column_editable_list = ('message_limit', 'username')
    form_columns = ('username', 'message_limit')
    form_widget_args = {'api_key': {'readonly': True}, 'message_count': {'readonly': True}}
    can_create = True
    can_delete = True

    def on_model_change(self, form, model, is_created):
        if is_created:
            model.api_key = f"user-{secrets.token_hex(16)}"
            print(f"✅ Пользователь '{model.username}' создан через админ-панель. Ключ: {model.api_key}")

admin = Admin(app, name='Панель Управления', index_view=ProtectedAdminIndexView())
admin.add_view(UserAdminView(User, db.session, name='Пользователи'))

# --- Ключи провайдеров (без изменений) ---
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
MODEL_MAPPING = {}
if OPENAI_API_KEY:
    MODEL_MAPPING.update({"klassicheskiy-gpt4": {"provider": "openai", "real_model": "gpt-3.5-turbo", "provider_url": "https://api.openai.com/v1/chat/completions", "api_key": OPENAI_API_KEY}})
if GOOGLE_API_KEY:
    MODEL_MAPPING.update({"tvoy-bystriy-gemini": {"provider": "google", "real_model": "gemini-2.0-flash", "provider_url": f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GOOGLE_API_KEY}", "api_key": GOOGLE_API_KEY}})
if GROQ_API_KEY:
    MODEL_MAPPING.update({"besplatniy-compound": { "provider": "openai", "real_model": "groq/compound-mini", "provider_url": "https://api.groq.com/openai/v1/chat/completions", "api_key": GROQ_API_KEY}})

# --- СИСТЕМА БЕЗОПАСНОСТИ API (без изменений) ---
def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"error": "Auth header is missing or invalid"}), 401
        
        provided_key = auth_header.split(' ')[1]
        user = User.query.filter_by(api_key=provided_key).first()
        
        if not user:
            return jsonify({"error": "Invalid API key"}), 403
        
        g.user = {'api_key': user.api_key, 'username': user.username, 'message_count': user.message_count, 'message_limit': user.message_limit}
        return f(*args, **kwargs)
    return decorated_function

# --- ЭНДПОИНТЫ API (без изменений) ---
@app.route('/v1/models', methods=['GET'])
@require_api_key
def list_models():
    model_list = []
    for model_id, details in MODEL_MAPPING.items():
        if details.get("api_key"): model_list.append({"id": model_id, "object": "model", "owned_by": "bratiwka-inc"})
    return jsonify({"object": "list", "data": model_list})

@app.route('/v1/chat/completions', methods=['POST'])
@require_api_key
def chat_completions():
    user_data = g.user
    if user_data['message_count'] >= user_data['message_limit']:
        print(f"Лимит {user_data['message_limit']} сообщений достигнут для пользователя: {user_data['username']}")
        error_response = {"id": "chatcmpl-limit-exceeded", "object": "chat.completion", "choices": [{"message": {"role": "assistant", "content": f"Извините, {user_data['username']}, вы достигли своего лимита в {user_data['message_limit']} сообщений."}}]}
        return jsonify(error_response), 429

    request_data = request.json
    user_message_data = request_data.get("messages", [])[-1]
    
    if user_message_data:
        new_user_message = Message(user_api_key=user_data['api_key'], role=user_message_data['role'], content=user_message_data['content'])
        db.session.add(new_user_message)

    model_id = request_data.get("model")
    if not model_id or model_id not in MODEL_MAPPING:
        return jsonify({"error": f"Model '{model_id}' not found."}), 404

    target = MODEL_MAPPING[model_id]
    provider = target["provider"]
    try:
        response_data = None
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

        if response_data:
            user_to_update = User.query.get(user_data['api_key'])
            user_to_update.message_count += 1
            assistant_message = response_data.get("choices", [{}])[0].get("message", {})
            if assistant_message:
                new_assistant_message = Message(user_api_key=user_data['api_key'], role=assistant_message.get('role', 'assistant'), content=assistant_message.get('content', ''))
                db.session.add(new_assistant_message)
            db.session.commit()
            print(f"Сообщение {user_to_update.message_count}/{user_data['message_limit']} от {user_data['username']} (ключ: ...{user_data['api_key'][-4:]}) записано в БД")
            return jsonify(response_data)
        
        return jsonify({"error": "Failed to get a response from any provider."}), 500
        
    except Exception as e:
        db.session.rollback()
        print(f"An error occurred: {e}")
        return jsonify({"error": str(e)}), 500

def setup_database():
    with app.app_context():
        print("Проверяем и создаем таблицы, если их нет...")
        db.create_all()
        print("База данных готова к работе.")

if __name__ == '__main__':
    setup_database()
    print("Сервер-посредник с поддержкой пользовательских API-ключей запущен!")
    print("✅ Панель администратора доступна по адресу http://127.0.0.1:8088/admin")
    app.run(host='0.0.0.0', port=8088)