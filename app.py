from flask import Flask, request, session, redirect, render_template
import socket
import os
from dotenv import load_dotenv
from prometheus_flask_exporter import PrometheusMetrics
import psycopg

load_dotenv()
APP_VERSION = os.environ.get("APP_VERSION", "0.5")
DATABASE_URL = os.environ.get("DATABASE_URL")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev")
metrics = PrometheusMetrics(app)

def get_db():
    return psycopg.connect(DATABASE_URL)

@app.route("/")
def home():
    return f"Le nom de la machine est: {socket.gethostname()}\nla version de l'app est {APP_VERSION}\nCoucou la nouvelle version !\n Milestone 3 FAIT !\n"

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")
    username = request.form["username"]
    with get_db() as co:
        row = co.execute("SELECT id FROM users WHERE username = %s;", (username,)).fetchone()
        if row is None:
            row = co.execute("INSERT INTO users (username) VALUES (%s) RETURNING id;", (username,)).fetchone()
    session["user_id"] = row[0]
    return redirect("/photos")

@app.route("/health")
def health():
    status = "ok"
    state = {'status':status}
    return state 

@app.route("/photos")
def photos():
    if "user_id" not in session:
        return redirect("/login")
    with get_db() as co:
        rows = co.execute("""
            SELECT filename, size
            FROM photos
            WHERE user_id = %s
            ORDER BY created_at DESC;
        """,(session["user_id"],)).fetchall()
    result = []
    for filename, size in rows:
        result.append({"filename":filename, "size":size})
    return result

if __name__ == "__main__":
    app.run(host="0.0.0.0",port=8080)