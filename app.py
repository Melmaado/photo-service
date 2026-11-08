from flask import Flask, request, session, redirect, render_template, Response, flash
import socket
import os
from dotenv import load_dotenv
from prometheus_flask_exporter import PrometheusMetrics
import psycopg
import hashlib
import mimetypes

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
            SELECT id, filename, size
            FROM photos
            WHERE user_id = %s
            ORDER BY created_at DESC;
        """,(session["user_id"],)).fetchall()
    result = []
    for photo_id, filename, size in rows:
        result.append({ "id": photo_id, "filename":filename, "size":size})
    return render_template("photos.html", photos=result)

@app.route("/upload", methods=["POST"])
def upload():
    if "user_id" not in session:
        return redirect("/login")
    file = request.files["photo"]
    data = file.read()
    pic_hash = hashlib.sha256(data).hexdigest()
    size = len(data)
    with get_db() as co:
        existing = co.execute("""
            SELECT id FROM photos
            WHERE user_id = %s AND pic_hash = %s
        """, (session["user_id"], pic_hash)).fetchone()
        if existing is not None:
            flash("This photo is already in your library.")
        co.execute("""
            INSERT INTO photos (user_id, filename, size, pic_hash, pic)
            VALUES (%s, %s, %s, %s, %s);
        """, (session["user_id"], file.filename, size, pic_hash, data))
    return redirect("/photos")

@app.route("/photo/<int:photo_id>")
def photo(photo_id):
    if "user_id" not in session:
        return redirect("/login")
    with get_db() as co:
        row = co.execute("""
            SELECT filename, pic FROM photos
            WHERE id = %s AND user_id = %s        
        """, (photo_id, session["user_id"])).fetchone()
    if row is None:
        return "Not found", 404
    filename, pic = row
    mimetype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return Response(pic, mimetype=mimetype)

if __name__ == "__main__":
    app.run(host="0.0.0.0",port=8080)