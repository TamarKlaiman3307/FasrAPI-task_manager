import psycopg2

DB_CONFIG = {
    "host": "localhost",
    "database": "task_manager",
    "user": "postgres",
    "password": "a1b2c3d4",   # ← החלפי בסיסמה האמיתית
    "port": 5432,
}

def get_connection():
    return psycopg2.connect(**DB_CONFIG)