# --- ФАЙЛ MANAGE_USERS.PY ---

import sqlite3
import argparse
import secrets # Для генерации безопасных ключей

DB_NAME = 'users.db'

def setup_database():
    """Эта функция теперь живет и здесь, чтобы скрипт мог сам создать БД."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            api_key TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            message_count INTEGER NOT NULL DEFAULT 0,
            message_limit INTEGER NOT NULL
        )
    ''')
    # Вторая таблица нам тут не нужна, она используется только основным сервером
    conn.commit()
    conn.close()

def add_user(username, limit):
    """Добавляет нового пользователя с уникальным ключом и лимитом."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Генерируем новый, безопасный API-ключ
    api_key = f"user-{secrets.token_hex(16)}"
    
    try:
        cursor.execute(
            "INSERT INTO users (api_key, username, message_limit) VALUES (?, ?, ?)",
            (api_key, username, limit)
        )
        conn.commit()
        print("="*50)
        print(f"✅ Пользователь '{username}' успешно добавлен!")
        print(f"   Лимит сообщений: {limit}")
        print(f"   API Ключ: {api_key}")
        print("="*50)
    except sqlite3.IntegrityError:
        print(f"❌ Ошибка: Пользователь с именем '{username}' уже существует.")
    finally:
        conn.close()

def list_users():
    """Показывает список всех пользователей в базе."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("SELECT username, api_key, message_count, message_limit FROM users")
    users = cursor.fetchall()
    
    if not users:
        print("В базе данных пока нет пользователей.")
        return

    print("="*70)
    print(f"{'Username':<20} {'API Key':<38} {'Usage':<12}")
    print("-"*70)
    for user in users:
        usage = f"{user[2]}/{user[3]}"
        print(f"{user[0]:<20} {user[1]:<38} {usage:<12}")
    print("="*70)
    
    conn.close()


if __name__ == '__main__':
    # Создаем базу, если ее нет
    setup_database()
    
    parser = argparse.ArgumentParser(description="Утилита для управления пользователями.")
    subparsers = parser.add_subparsers(dest='command', required=True)
    
    # Команда 'add'
    parser_add = subparsers.add_parser('add', help='Добавить нового пользователя')
    parser_add.add_argument('username', type=str, help='Имя пользователя')
    parser_add.add_argument('--limit', type=int, default=100, help='Лимит сообщений (по умолчанию: 100)')
    
    # Команда 'list'
    parser_list = subparsers.add_parser('list', help='Показать список всех пользователей')
    
    args = parser.parse_args()
    
    if args.command == 'add':
        add_user(args.username, args.limit)
    elif args.command == 'list':
        list_users()