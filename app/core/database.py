import psycopg2
from app.core.config import DB_CONN

def get_connection():
    return psycopg2.connect(DB_CONN)
