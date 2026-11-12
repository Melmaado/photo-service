from flask import Flask, request, session, redirect, render_template, Response, flash
import socket
import os
from dotenv import load_dotenv
from prometheus_flask_exporter import PrometheusMetrics
import psycopg
import hashlib
import mimetypes
import redis

load_dotenv()
APP_VERSION = os.environ.get("APP_VERSION", "0.5")
DATABASE_URLS = [
    os.environ.get("DATABASE_URL_0"),
    os.environ.get("DATABASE_URL_1"),
]

REDIS_URL = os.environ.get("REDIS_URL")
cache = redis.Redis.from_url(REDIS_URL) if REDIS_URL else None

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev")
metrics = PrometheusMetrics(app)

def shard_for(username):
    shard = hashlib.sha256(username.encode()).digest()[0]%2
    return shard

def get_db(username):
    return psycopg.connect(DATABASE_URLS[shard_for(username)])


@app.route("/")
def home():
    return f"Le nom de la machine est: {socket.gethostname()}\nla version de l'app est {APP_VERSION}\nCoucou la nouvelle version !\n Milestone 3 FAIT !\n"

@app.route("/health")
def health():
    status = "ok"
    state = {'status':status}
    return state 

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")
    username = request.form["username"]
    session["shard"] = shard_for(username)
    with get_db(username) as co:
        row = co.execute("SELECT id FROM users WHERE username = %s;", (username,)).fetchone()
        if row is None:
            row = co.execute("INSERT INTO users (username) VALUES (%s) RETURNING id;", (username,)).fetchone()
    session["user_id"] = row[0]
    session["username"] = username
    return redirect("/photos")

@app.route("/photos")
def photos():
    if "user_id" not in session:
        return redirect("/login")
    with get_db(session["username"]) as co:
        rows = co.execute("""
            SELECT id, filename, size
            FROM photos
            WHERE user_id = %s
            ORDER BY created_at DESC;
        """,(session["user_id"],)).fetchall()
        dup_rows = co.execute("""
        SELECT id, filename, size
        FROM photos
        WHERE user_id = %s
            AND pic_hash IN (
                SELECT pic_hash
                FROM photos
                WHERE user_id = %s
                GROUP BY pic_hash
                HAVING COUNT(*) > 1
            )
        ORDER BY pic_hash, created_at;
        """,(session["user_id"], session["user_id"])).fetchall()
    result = []
    for photo_id, filename, size in rows:
        result.append({"id": photo_id, "filename":filename, "size":size})
    duplicates = []
    for photo_id, filename, size in dup_rows:
        duplicates.append({"id": photo_id, "filename":filename, "size":size})
    return render_template("photos.html", photos=result, duplicates=duplicates)

@app.route("/upload", methods=["POST"])
def upload():
    if "user_id" not in session:
        return redirect("/login")
    file = request.files["photo"]
    data = file.read()
    pic_hash = hashlib.sha256(data).hexdigest()
    size = len(data)
    with get_db(session["username"]) as co:
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
    key = f"photo:{session['username']}:{photo_id}"

    if cache is not None:
        cached = cache.hgetall(key)
        if cached:
            filename = cached[b"filename"].decode()
            pic = cached[b"pic"]
            mimetype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            response = Response(pic, mimetype=mimetype)
            response.headers["X-Cache"] = "HIT"
            return response

    with get_db(session["username"]) as co:
        row = co.execute("""
            SELECT filename, pic FROM photos
            WHERE id = %s AND user_id = %s;
        """, (photo_id, session["user_id"])).fetchone()
    if row is None:
        return "Not found", 404
    filename, pic = row

    if cache is not None:
        cache.hset(key, mapping={"filename": filename, "pic": pic})
        cache.expire(key, 600)

    mimetype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    response = Response(pic, mimetype=mimetype)
    response.headers["X-Cache"] = "MISS"
    return response

@app.route("/delete/<int:photo_id>", methods=["POST"])
def delete(photo_id):
    if "user_id" not in session:
        return redirect("/login")
    with get_db(session["username"]) as co:
        co.execute("""
            DELETE FROM photos
            WHERE id = %s AND user_id = %s;
        """, (photo_id, session["user_id"]))
    if cache is not None:
        cache.delete(f"photo:{session['username']}:{photo_id}")
    return redirect("/photos")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

if __name__ == "__main__":
    app.run(host="0.0.0.0",port=8080)