# migrate.py
import sqlite3

DB_NAME = 'users.db'

print("Запуск миграции базы данных...")

try:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Проверяем, существует ли уже колонка 'plan'
    cursor.execute("PRAGMA table_info(users)")
    columns = [info[1] for info in cursor.fetchall()]

    if 'plan' not in columns:
        print("Колонка 'plan' не найдена. Добавляем...")
        # Добавляем новую колонку 'plan' с тарифом 'free' по умолчанию для всех
        cursor.execute("ALTER TABLE users ADD COLUMN plan TEXT NOT NULL DEFAULT 'free'")
        conn.commit()
        print("✅ Колонка 'plan' успешно добавлена. Все существующие пользователи получили тариф 'free'.")
    else:
        print("✅ Колонка 'plan' уже существует. Миграция не требуется.")

except Exception as e:
    print(f"❌ Произошла ошибка: {e}")
finally:
    if conn:
        conn.close()