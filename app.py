from flask import Flask
import socket
import os
from dotenv import load_dotenv
from prometheus_flask_exporter import PrometheusMetrics
import psycopg

load_dotenv()
APP_VERSION = os.environ.get("APP_VERSION", "0.5")
DATABASE_URL = os.environ.get("DATABASE_URL")

app = Flask(__name__)
metrics = PrometheusMetrics(app)

def get_db():
    return psycopg.connect(DATABASE_URL)

@app.route("/")
def home():
    return f"Le nom de la machine est: {socket.gethostname()}\nla version de l'app est {APP_VERSION}\nCoucou la nouvelle version !\n Milestone 3 FAIT !\n"

@app.route("/health")
def health():
    status = "ok"
    state = {'status':status}
    return state 

@app.route("/photos")
def photos():
    with get_db() as co:
        rows = co.execute("""
            SELECT filename, size
            FROM photos
            WHERE user_id = %s
            ORDER BY created_at DESC;
        """,(1,)).fetchall()
    result = []
    for filename, size in rows:
        result.append({"filename":filename, "size":size})
    return result

if __name__ == "__main__":
    app.run(host="0.0.0.0",port=8080)