# custom_provider.py
import os
import secrets
import json
import requests
from functools import wraps
from dotenv import load_dotenv
import time
import uuid



from flask import Flask, jsonify, request, g, Response, render_template, redirect, url_for, session, abort
from flask_sqlalchemy import SQLAlchemy
from flask_admin import Admin, AdminIndexView
from flask_admin.contrib.sqla import ModelView
import stripe # <-- импортируем Stripe

load_dotenv()

# --- ДИАГНОСТИЧЕСКИЙ БЛОК ---
print("="*60)
print("🕵️  ЗАПУСК ДИАГНОСТИКИ ЗАГРУЗКИ API-КЛЮЧЕЙ...")
print(f"   OPENAI_API_KEY: {'✅ Загружен' if os.environ.get('OPENAI_API_KEY') else '❌ НЕ НАЙДЕН'}")
print(f"   GOOGLE_API_KEY: {'✅ Загружен' if os.environ.get('GOOGLE_API_KEY') else '❌ НЕ НАЙДЕН'}")
print(f"   GROQ_API_KEY:   {'✅ Загружен' if os.environ.get('GROQ_API_KEY') else '❌ НЕ НАЙДЕН'}")
print("="*60)
# --- КОНЕЦ ДИАГНОСТИЧЕСКОГО БЛОКА ---

# --- ТАРИФНЫЕ ПЛАНЫ ---
# Управляем всеми тарифами из одного места
TARIFF_PLANS = {
    'free': {'limit': 100, 'price': 0, 'stripe_price_id': 'YOUR_FREE_PLAN_ID'},
    'pro': {'limit': 1000, 'price': 10, 'stripe_price_id': 'price_1SSI67RPenat6xXbIaMWAGdc'},
    'enterprise': {'limit': 5000, 'price': 40, 'stripe_price_id': 'price_1SSI6fRPenat6xXbv14IqeUD'}
}


basedir = os.path.abspath(os.path.dirname(__file__))
DB_NAME = 'users.db'

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('MY_PROVIDER_API_KEY', 'default-secret-key-CHANGE-ME')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, DB_NAME)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['FLASK_ADMIN_SWATCH'] = 'cerulean'

# --- Stripe Конфигурация ---
stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')
stripe_webhook_secret = os.environ.get('STRIPE_WEBHOOK_SECRET')
YOUR_DOMAIN = os.environ.get('YOUR_DOMAIN', 'http://127.0.0.1:8088')


db = SQLAlchemy(app)

# --- МОДЕЛИ (обновлена модель User) ---
class User(db.Model):
    __tablename__ = 'users'
    api_key = db.Column(db.Text, primary_key=True)
    username = db.Column(db.Text, unique=True, nullable=False)
    message_count = db.Column(db.Integer, nullable=False, default=0)
    message_limit = db.Column(db.Integer, nullable=False)
    plan = db.Column(db.Text, nullable=False, default='free') # <-- НОВОЕ ПОЛЕ

class Message(db.Model):
    __tablename__ = 'messages'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_api_key = db.Column(db.Text, db.ForeignKey('users.api_key'), nullable=False)
    role = db.Column(db.Text, nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, server_default=db.func.now())

class ProtectedAdminIndexView(AdminIndexView):
    def is_accessible(self):
        auth = request.authorization; admin_user = os.environ.get('ADMIN_USERNAME'); admin_pass = os.environ.get('ADMIN_PASSWORD')
        return auth and auth.username == admin_user and auth.password == admin_pass
    def inaccessible_callback(self, name, **kwargs):
        return Response('Login Required', 401, {'WWW-Authenticate': 'Basic realm="Login Required"'})

class UserAdminView(ModelView):
    column_list = ('username', 'api_key', 'plan', 'message_count', 'message_limit')
    column_editable_list = ('message_limit', 'username', 'plan')
    def on_model_change(self, form, model, is_created):
        if is_created or form.plan.data != model.plan:
             model.message_limit = TARIFF_PLANS.get(model.plan, {}).get('limit', 100)
        if is_created:
            model.api_key = f"user-{secrets.token_hex(16)}"

admin = Admin(app, name='Панель Управления', index_view=ProtectedAdminIndexView())
admin.add_view(UserAdminView(User, db.session, name='Пользователи'))


OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
MODEL_MAPPING = {}
if OPENAI_API_KEY: MODEL_MAPPING.update({"klassicheskiy-gpt4": {"provider": "openai", "real_model": "gpt-3.5-turbo", "provider_url": "https://api.openai.com/v1/chat/completions", "api_key": OPENAI_API_KEY}})
if GOOGLE_API_KEY: MODEL_MAPPING.update({"tvoy-bystriy-gemini": {"provider": "google", "real_model": "gemini-2.0-flash", "provider_url": f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GOOGLE_API_KEY}", "api_key": GOOGLE_API_KEY}})
if GROQ_API_KEY: MODEL_MAPPING.update({"besplatniy-compound": { "provider": "openai", "real_model": "groq/compound-mini", "provider_url": "https://api.groq.com/openai/v1/chat/completions", "api_key": GROQ_API_KEY}})
def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization');
        if not auth_header or not auth_header.startswith('Bearer '): return jsonify({"error": "Auth header is missing or invalid"}), 401
        provided_key = auth_header.split(' ')[1]; user = User.query.filter_by(api_key=provided_key).first()
        if not user: return jsonify({"error": "Invalid API key"}), 403
        g.user = user; return f(*args, **kwargs)
    return decorated_function
@app.route('/v1/models', methods=['GET'])
@require_api_key
def list_models():
    return jsonify({"object": "list", "data": [{"id": model_id, "object": "model", "owned_by": "bratiwka-inc"} for model_id, details in MODEL_MAPPING.items() if details.get("api_key")]})
@app.route('/v1/chat/completions', methods=['POST'])
@require_api_key
def chat_completions():
    user = g.user

    # --- ИЗМЕНЕНИЕ НАЧИНАЕТСЯ ЗДЕСЬ ---
    if user.message_count >= user.message_limit:
        # Вместо ошибки 429, мы формируем успешный ответ с предложением обновиться.
        
        # Генерируем полную ссылку на страницу профиля пользователя.
        # _external=True добавляет домен и порт (http://127.0.0.1:8088/profile)
        payment_url = url_for('profile', _external=True)

        # Создаем текст сообщения с использованием Markdown для красивой ссылки.
        response_text = (
            "**Лимит сообщений исчерпан!** 😢\n\n"
            "На вашем текущем тарифе закончились доступные сообщения. "
            "Чтобы продолжить общение без ограничений, пожалуйста, обновите ваш тарифный план.\n\n"
            f"👉 **[Перейти к выбору тарифа]({payment_url})**"
        )
        
        # Собираем JSON-ответ, который выглядит как обычный ответ от модели.
        # Интерфейс Open WebUI покажет это как сообщение в чате.
        limit_exceeded_response = {
            "id": f"chatcmpl-limit-{uuid.uuid4()}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": request.json.get('model', 'system-notification'),
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": response_text
                },
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            }
        }
        return jsonify(limit_exceeded_response)
    # --- ИЗМЕНЕНИЕ ЗАКАНЧИВАЕТСЯ ЗДЕСЬ ---


    # 1. Получаем запрос от интерфейса Open WebUI (этот блок без изменений)
    request_data = request.json
    model_id = request_data.get('model')
    messages = request_data.get('messages')

    model_config = MODEL_MAPPING.get(model_id)
    if not model_config:
        return jsonify({"error": f"Model '{model_id}' not found"}), 404

    # 2. Отправляем запрос настоящему провайдеру (этот блок без изменений)
    response_text = ""
    try:
        headers = {'Authorization': f'Bearer {model_config["api_key"]}', 'Content-Type': 'application/json'}
        
        if model_config["provider"] == "google":
            google_payload = {"contents": [{"parts": [{"text": msg["content"]}] for msg in messages if msg['role'] == 'user'}]}
            response = requests.post(model_config["provider_url"], headers=headers, json=google_payload)
            response.raise_for_status()
            response_text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        
        else: # provider == "openai"
            payload = {"model": model_config["real_model"], "messages": messages}
            response = requests.post(model_config["provider_url"], headers=headers, json=payload)
            response.raise_for_status()
            response_text = response.json()["choices"][0]["message"]["content"]

    except requests.exceptions.RequestException as e:
        print(f"ОШИБКА: Не удалось связаться с API провайдера: {e}")
        return jsonify({"error": "Failed to get response from the underlying model provider."}), 500
    except (KeyError, IndexError) as e:
        print(f"ОШИБКА: Не удалось разобрать ответ от API провайдера: {e}")
        return jsonify({"error": "Invalid response format from the underlying model provider."}), 500

    # Увеличиваем счетчик и сохраняем в БД (этот блок без изменений)
    user.message_count += 1
    db.session.commit()

    # Формируем финальный успешный ответ (этот блок без изменений)
    final_response = {
        "id": f"chatcmpl-{uuid.uuid4()}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_id,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": response_text.strip()
            },
            "finish_reason": "stop"
        }],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0
        }
    }

    return jsonify(final_response)

@app.route('/v1/me', methods=['GET'])
@require_api_key
def get_current_user_info():
    user = g.user
    return jsonify({
        "username": user.username,
        "plan": user.plan
    })

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        api_key = request.form.get('api_key')
        user = User.query.filter_by(api_key=api_key).first()
        if user:
            session['api_key'] = user.api_key # Запоминаем ключ в сессии
            return redirect(url_for('profile'))
        else:
            return render_template('login.html', error="Неверный API ключ")
    return render_template('login.html')

@app.route('/profile')
def profile():
    if 'api_key' not in session:
        return redirect(url_for('login'))
    
    user = User.query.filter_by(api_key=session['api_key']).first()
    if not user:
        session.clear() # Ключ недействителен, чистим сессию
        return redirect(url_for('login'))
        
    return render_template('profile.html', user=user, plans=TARIFF_PLANS)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# --- НОВЫЕ РОУТЫ ДЛЯ ИНТЕГРАЦИИ С ОПЛАТОЙ ---

@app.route('/create-checkout-session/<plan>')
def create_checkout_session(plan):
    if 'api_key' not in session:
        return redirect(url_for('login'))
    if plan not in TARIFF_PLANS:
        return abort(404)
        
    try:
        checkout_session = stripe.checkout.Session.create(
            line_items=[{'price': TARIFF_PLANS[plan]['stripe_price_id'], 'quantity': 1}],
            mode='payment',
            success_url=YOUR_DOMAIN + '/profile?payment=success',
            cancel_url=YOUR_DOMAIN + '/profile?payment=cancel',
            # ВАЖНО: передаем ключ пользователя, чтобы знать, кого обновлять
            client_reference_id=session['api_key'] 
        )
    except Exception as e:
        return str(e)
        
    return redirect(checkout_session.url, code=303)

@app.route('/stripe-webhook', methods=['POST'])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')
    event = None

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, stripe_webhook_secret)
    except ValueError as e: # Неверный payload
        return 'Invalid payload', 400
    except stripe.error.SignatureVerificationError as e: # Неверная подпись
        return 'Invalid signature', 400

    # Обрабатываем событие checkout.session.completed
    if event['type'] == 'checkout.session.completed':
        session_data = event['data']['object']
        api_key = session_data.get('client_reference_id')
        # Тут может быть логика поиска плана по price_id, но для простоты мы найдем по api_key
        user = User.query.get(api_key)
        if user:
            # Находим, какой план был куплен (в реальном проекте - по ID)
            # Здесь для простоты обновим до 'pro'
            new_plan = 'pro' # <-- В проде нужно определять по session_data
            user.plan = new_plan
            user.message_limit = TARIFF_PLANS[new_plan]['limit']
            # Можно сбросить счетчик или добавить лимит к существующему
            user.message_count = 0 
            db.session.commit()
            print(f"✅ Пользователь {user.username} успешно обновил тариф до {new_plan}")

    return 'OK', 200


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=8088, debug=True) # debug=True поможет видеть ошибки