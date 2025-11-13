# custom_provider.py
import os
import secrets
import json
import requests
from functools import wraps
from dotenv import load_dotenv



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

# ... (остальные модели и классы админки без изменений) ...
class Message(db.Model):
    __tablename__ = 'messages'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_api_key = db.Column(db.Text, db.ForeignKey('users.api_key'), nullable=False)
    role = db.Column(db.Text, nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, server_default=db.func.now())

class ProtectedAdminIndexView(AdminIndexView):
    # ... без изменений
    def is_accessible(self):
        auth = request.authorization; admin_user = os.environ.get('ADMIN_USERNAME'); admin_pass = os.environ.get('ADMIN_PASSWORD')
        return auth and auth.username == admin_user and auth.password == admin_pass
    def inaccessible_callback(self, name, **kwargs):
        return Response('Login Required', 401, {'WWW-Authenticate': 'Basic realm="Login Required"'})

class UserAdminView(ModelView):
    # Добавим plan в список для удобства
    column_list = ('username', 'api_key', 'plan', 'message_count', 'message_limit')
    column_editable_list = ('message_limit', 'username', 'plan')
    # ... остальное без изменений
    def on_model_change(self, form, model, is_created):
        if is_created or form.plan.data != model.plan:
             # Обновляем лимит, если создаем пользователя или меняем его план
             model.message_limit = TARIFF_PLANS.get(model.plan, {}).get('limit', 100)
        if is_created:
            model.api_key = f"user-{secrets.token_hex(16)}"

admin = Admin(app, name='Панель Управления', index_view=ProtectedAdminIndexView())
admin.add_view(UserAdminView(User, db.session, name='Пользователи'))


# --- API ЧАСТЬ (без изменений) ---
# ... (весь твой код API от MODEL_MAPPING до конца chat_completions) ...
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
    if user.message_count >= user.message_limit: return jsonify({"error": "Message limit exceeded"}), 429
    # ... остальная логика без изменений, только используем user.property вместо user_data['property']
    user.message_count += 1
    # ...
    db.session.commit()
    # ...


# --- НОВЫЕ РОУТЫ ДЛЯ ЛИЧНОГО КАБИНЕТА ---

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