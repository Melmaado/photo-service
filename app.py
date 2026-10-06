from flask import Flask
import socket
import os
from dotenv import load_dotenv

load_dotenv()
APP_VERSION = os.environ.get("APP_VERSION", "0.5")

app = Flask(__name__)

@app.route("/")
def home():
    return f"Le nom de la machine est: {socket.gethostname()}, la version de l'app est {APP_VERSION}"

@app.route("/health")
def health():
    status = "ok"
    state = {'status':status}
    return state 

if __name__ == "__main__":
    app.run(host="0.0.0.0",port=8080)