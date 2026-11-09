"""Aritztic: portfolio backend (Flask + Firebase Firestore).
Run:  pip install -r requirements.txt  ->  python app.py  ->  http://localhost:5000
Host (you):  /            (password login)
Visitors:    /v/<token>  (links you generate from the host dashboard)
"""
import os, json, secrets, time
from functools import wraps
from flask import Flask, request, jsonify, session, send_from_directory, abort
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.exceptions import HTTPException
import firebase_admin
from firebase_admin import credentials, firestore

BASE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder="static", static_url_path="/static")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)  # correct https:// links behind Vercel
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret")
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024
PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123").strip()  # CHANGE THIS (set it in Vercel env vars)
print("[aritztic] ADMIN_PASSWORD from env:", "ADMIN_PASSWORD" in os.environ, "| length:", len(PASSWORD))
DEFAULT_PROFILE = {
    "name": "Your Name", "roles": ["web experiences", "interactive apps", "bold brands"],
    "tagline": "Art, but make it Aritz. Developer and designer turning ideas into memorable products.",
    "about": "Write a short story about yourself here.\nEdit it from the host dashboard.",
    "email": "you@email.com", "github": "", "linkedin": "",
}

# ---------- Firebase ----------
def init_firebase():
    raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT")  # full JSON string (use this on Vercel)
    key = os.path.join(BASE, "serviceAccountKey.json")  # or a local file (use this in VS Code)
    if raw:
        cred = credentials.Certificate(json.loads(raw.strip()))
    elif os.path.exists(key):
        cred = credentials.Certificate(key)
    else:
        raise SystemExit("Missing Firebase key: put serviceAccountKey.json next to app.py "
                         "or set FIREBASE_SERVICE_ACCOUNT. See README.md.")
    firebase_admin.initialize_app(cred)
    return firestore.client()

fs = init_firebase()
DESC = firestore.Query.DESCENDING

def pdict(doc):
    d = doc.to_dict()
    d["id"] = doc.id
    d.setdefault("views", 0); d.setdefault("likes", 0)
    return d

def get_profile():
    s = fs.collection("site").document("profile").get()
    return {**DEFAULT_PROFILE, **(s.to_dict() if s.exists else {})}

def clean_url(u):
    u = (u or "").strip()
    if u.startswith(("http://", "https://")):
        return u[:500]
    if u.startswith(("data:image/jpeg;base64,", "data:image/png;base64,", "data:image/webp;base64,")) and len(u) < 260_000:
        return u  # images uploaded from the dashboard are compressed in the browser
    return ""

def host_only(f):
    @wraps(f)
    def w(*a, **k):
        if not session.get("host"):
            return jsonify(error="login required"), 401
        return f(*a, **k)
    return w

# ---------- errors: show the real reason to the host ----------
@app.errorhandler(Exception)
def on_error(e):
    code = e.code if isinstance(e, HTTPException) else 500
    print("[aritztic] error:", repr(e))
    if not request.path.startswith("/api/"):
        return ("Not found" if code == 404 else "Server error. Check the Vercel logs."), code
    msg = f"{type(e).__name__}: {e}" if session.get("host") else "Request failed"
    return jsonify(error=msg[:500]), code

# ---------- pages ----------
@app.get("/")
def host_page():
    return send_from_directory("static", "host.html")

@app.get("/v/<token>")
def view_page(token):
    return send_from_directory("static", "view.html")

# ---------- diagnostics (safe: no secrets; you can delete this route later) ----------
@app.get("/api/health")
def health():
    info = {"admin_password_env_set": "ADMIN_PASSWORD" in os.environ,
            "secret_key_env_set": "SECRET_KEY" in os.environ,
            "firebase_env_set": "FIREBASE_SERVICE_ACCOUNT" in os.environ}
    try:
        next(iter(fs.collection("projects").limit(1).stream()), None)
        info["firestore"] = "ok"
    except Exception as e:
        info["firestore"] = f"{type(e).__name__}: {str(e)[:300]}"
    return jsonify(info)

# ---------- host auth ----------
@app.post("/api/login")
def login():
    given = str((request.get_json(silent=True) or {}).get("password", "")).strip()
    if secrets.compare_digest(given.encode(), PASSWORD.encode()):  # bytes: works with any characters
        session["host"] = True
        return jsonify(ok=True)
    return jsonify(error="wrong password"), 401

@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)

@app.get("/api/me")
@host_only
def me():
    return jsonify(ok=True)

# ---------- host: projects ----------
def read_project():
    j = request.json or {}
    return {
        "title": (j.get("title") or "Untitled").strip()[:120],
        "description": (j.get("description") or "").strip()[:3000],
        "tags": [t.strip()[:30] for t in j.get("tags", []) if t.strip()][:12],
        "live": clean_url(j.get("live")), "repo": clean_url(j.get("repo")),
        "images": [clean_url(i) for i in j.get("images", []) if clean_url(i)][:5],
        "featured": bool(j.get("featured")),
    }

@app.get("/api/projects")
@host_only
def list_projects():
    docs = fs.collection("projects").order_by("created", direction=DESC).stream()
    return jsonify([pdict(d) for d in docs])

@app.post("/api/projects")
@host_only
def add_project():
    fs.collection("projects").add({**read_project(), "views": 0, "likes": 0, "created": time.time()})
    return jsonify(ok=True)

@app.put("/api/projects/<pid>")
@host_only
def edit_project(pid):
    fs.collection("projects").document(pid).update(read_project())
    return jsonify(ok=True)

@app.delete("/api/projects/<pid>")
@host_only
def del_project(pid):
    fs.collection("projects").document(pid).delete()
    return jsonify(ok=True)

# ---------- host: profile, links, messages ----------
@app.get("/api/profile")
@host_only
def read_profile():
    return jsonify(get_profile())

@app.post("/api/profile")
@host_only
def save_profile():
    j = request.json or {}
    p = {k: j.get(k, DEFAULT_PROFILE[k]) for k in DEFAULT_PROFILE}
    if isinstance(p["roles"], str):
        p["roles"] = [r.strip() for r in p["roles"].split(",") if r.strip()]
    fs.collection("site").document("profile").set(p)
    return jsonify(ok=True)

@app.get("/api/links")
@host_only
def list_links():
    docs = fs.collection("links").order_by("created", direction=DESC).stream()
    return jsonify([{**d.to_dict(), "token": d.id} for d in docs])

@app.post("/api/links")
@host_only
def create_link():
    token = secrets.token_urlsafe(8)
    label = ((request.json or {}).get("label") or "Visitor link").strip()[:60]
    fs.collection("links").document(token).set({"label": label, "created": time.time(), "views": 0, "active": 1})
    return jsonify(token=token, url=request.host_url + "v/" + token)

@app.post("/api/links/<token>/toggle")
@host_only
def toggle_link(token):
    ref = fs.collection("links").document(token)
    s = ref.get()
    if s.exists:
        ref.update({"active": 0 if s.to_dict().get("active") else 1})
    return jsonify(ok=True)

@app.delete("/api/links/<token>")
@host_only
def del_link(token):
    fs.collection("links").document(token).delete()
    return jsonify(ok=True)

@app.get("/api/messages")
@host_only
def list_messages():
    docs = fs.collection("messages").order_by("created", direction=DESC).stream()
    return jsonify([{**d.to_dict(), "id": d.id} for d in docs])

@app.delete("/api/messages/<mid>")
@host_only
def del_message(mid):
    fs.collection("messages").document(mid).delete()
    return jsonify(ok=True)

# ---------- visitors (token required, no login) ----------
def valid_link(token):
    ref = fs.collection("links").document(token)
    s = ref.get()
    if not s.exists or not s.to_dict().get("active"):
        abort(404)
    return ref

@app.get("/api/public/<token>")
def public_data(token):
    valid_link(token).update({"views": firestore.Increment(1)})
    docs = fs.collection("projects").order_by("created", direction=DESC).stream()
    projects = sorted((pdict(d) for d in docs), key=lambda p: not p.get("featured"))  # featured first, stable
    return jsonify(profile=get_profile(), projects=projects)

@app.post("/api/public/<token>/event")
def public_event(token):
    valid_link(token)
    j = request.json or {}
    col = {"view": "views", "like": "likes"}.get(j.get("type"))
    if col and isinstance(j.get("id"), str):
        try:
            fs.collection("projects").document(j["id"]).update({col: firestore.Increment(1)})
        except Exception:
            pass  # project was deleted
    return jsonify(ok=True)

@app.post("/api/public/<token>/contact")
def public_contact(token):
    valid_link(token)
    j = request.json or {}
    if not (j.get("name") and j.get("email") and j.get("msg")):
        return jsonify(error="missing fields"), 400
    fs.collection("messages").add({"name": j["name"][:80], "email": j["email"][:120],
                                   "msg": j["msg"][:3000], "created": time.time()})
    return jsonify(ok=True)

if __name__ == "__main__":
    app.run(debug=True, port=5000)