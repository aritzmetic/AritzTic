"""Aritztic: portfolio backend (Flask + Firebase Firestore over plain HTTPS/REST).
Run:  pip install -r requirements.txt  ->  python app.py  ->  http://localhost:5000
Host (you):  /            (password login)
Visitors:    /v/<token>  (links you generate from the host dashboard)
"""
import os, json, secrets, time
from urllib.parse import quote
from functools import wraps
from flask import Flask, request, jsonify, session, send_from_directory, abort
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.exceptions import HTTPException

BASE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder="static", static_url_path="/static")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)  # correct https:// links behind Vercel
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret")
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024
PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123").strip()  # CHANGE THIS (set it in Vercel env vars)
DEFAULT_PROFILE = {
    "name": "Your Name", "roles": ["web experiences", "interactive apps", "bold brands"],
    "tagline": "Art, but make it Aritz. Developer and designer turning ideas into memorable products.",
    "about": "Write a short story about yourself here.\nEdit it from the host dashboard.",
    "email": "you@email.com", "github": "", "linkedin": "",
}

# ================= Firestore over REST (no gRPC, fast cold starts) =================
_S = {}

def _session():
    """Created on first use, so a bad key shows up as a readable error instead of a crash."""
    if not _S:
        from google.oauth2 import service_account
        from google.auth.transport.requests import AuthorizedSession
        raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT")  # full JSON string (use this on Vercel)
        key = os.path.join(BASE, "serviceAccountKey.json")  # or a local file (use this in VS Code)
        if raw:
            info = json.loads(raw.strip())
        elif os.path.exists(key):
            info = json.load(open(key, encoding="utf-8"))
        else:
            raise RuntimeError("Missing Firebase key: put serviceAccountKey.json next to app.py or set FIREBASE_SERVICE_ACCOUNT")
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/datastore"])
        _S["project"] = info["project_id"]
        _S["root"] = f"https://firestore.googleapis.com/v1/projects/{info['project_id']}/databases/(default)/documents"
        _S["s"] = AuthorizedSession(creds, refresh_timeout=10)
    return _S

def enc(v):
    if v is None: return {"nullValue": None}
    if isinstance(v, bool): return {"booleanValue": v}
    if isinstance(v, int): return {"integerValue": str(v)}
    if isinstance(v, float): return {"doubleValue": v}
    if isinstance(v, str): return {"stringValue": v}
    if isinstance(v, (list, tuple)): return {"arrayValue": {"values": [enc(x) for x in v]}}
    if isinstance(v, dict): return {"mapValue": {"fields": {k: enc(x) for k, x in v.items()}}}
    raise TypeError(f"cannot store {type(v)}")

def dec(v):
    if "stringValue" in v: return v["stringValue"]
    if "integerValue" in v: return int(v["integerValue"])
    if "doubleValue" in v: return v["doubleValue"]
    if "booleanValue" in v: return v["booleanValue"]
    if "arrayValue" in v: return [dec(x) for x in v["arrayValue"].get("values", [])]
    if "mapValue" in v: return {k: dec(x) for k, x in v["mapValue"].get("fields", {}).items()}
    if "timestampValue" in v: return v["timestampValue"]
    return None

def _doc(d):
    out = {k: dec(v) for k, v in d.get("fields", {}).items()}
    out["_id"] = d["name"].rsplit("/", 1)[1]
    return out

def _call(method, url, **kw):
    r = _session()["s"].request(method, url, timeout=(5, 10), **kw)
    if r.status_code >= 400:
        if r.status_code == 404 and method == "GET":
            return None
        raise RuntimeError(f"Firestore HTTP {r.status_code}: {r.text[:300]}")
    return r.json() if r.text else {}

def _path(col, doc_id): return f"{_session()['root']}/{col}/{quote(doc_id, safe='')}"

def list_docs(col, limit=None):
    q = {"from": [{"collectionId": col}], "orderBy": [{"field": {"fieldPath": "created"}, "direction": "DESCENDING"}]}
    if limit: q["limit"] = limit
    res = _call("POST", _session()["root"] + ":runQuery", json={"structuredQuery": q})
    return [_doc(x["document"]) for x in res if "document" in x]

def get_doc(col, doc_id):
    d = _call("GET", _path(col, doc_id))
    return _doc(d) if d else None

def add_doc(col, data):
    _call("POST", f"{_session()['root']}/{col}", json={"fields": {k: enc(v) for k, v in data.items()}})

def set_doc(col, doc_id, data):  # create or fully replace
    _call("PATCH", _path(col, doc_id), json={"fields": {k: enc(v) for k, v in data.items()}})

def update_doc(col, doc_id, data):  # change some fields; the doc must exist
    params = [("updateMask.fieldPaths", k) for k in data] + [("currentDocument.exists", "true")]
    _call("PATCH", _path(col, doc_id), params=params, json={"fields": {k: enc(v) for k, v in data.items()}})

def delete_doc(col, doc_id):
    _call("DELETE", _path(col, doc_id))

def incr(col, doc_id, field, n=1):  # atomic counter
    s = _session()
    name = f"projects/{s['project']}/databases/(default)/documents/{col}/{doc_id}"
    _call("POST", s["root"].split("/documents")[0] + "/documents:commit", json={"writes": [{
        "update": {"name": name}, "updateMask": {"fieldPaths": []},
        "updateTransforms": [{"fieldPath": field, "increment": {"integerValue": str(n)}}],
        "currentDocument": {"exists": True}}]})
# ===================================================================================

def pdict(d):
    d["id"] = d.pop("_id")
    d.setdefault("views", 0); d.setdefault("likes", 0); d.setdefault("tags", []); d.setdefault("images", [])
    return d

def get_profile():
    d = get_doc("site", "profile") or {}
    d.pop("_id", None)
    return {**DEFAULT_PROFILE, **d}

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

# ---------- diagnostics (safe: no secrets; you can delete this route later) ----------
@app.get("/api/health")
def health():
    info = {"admin_password_env_set": "ADMIN_PASSWORD" in os.environ,
            "secret_key_env_set": "SECRET_KEY" in os.environ,
            "firebase_env_set": "FIREBASE_SERVICE_ACCOUNT" in os.environ}
    try:
        t0 = time.time()
        info["project_id"] = _session()["project"]
        list_docs("projects", 1)
        info["firestore"] = f"ok ({int((time.time() - t0) * 1000)} ms)"
    except Exception as e:
        info["firestore"] = f"{type(e).__name__}: {str(e)[:400]}"
    return jsonify(info)

# ---------- pages ----------
@app.get("/")
def host_page():
    return send_from_directory("static", "host.html")

@app.get("/v/<token>")
def view_page(token):
    return send_from_directory("static", "view.html")

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

# ---------- host: dashboard + projects ----------
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

@app.get("/api/dashboard")
@host_only
def dashboard():
    """Everything the host dashboard needs, in ONE request."""
    links = [{**d, "token": d.pop("_id")} for d in list_docs("links")]
    messages = [{**d, "id": d.pop("_id")} for d in list_docs("messages")]
    return jsonify(projects=[pdict(d) for d in list_docs("projects")], links=links,
                   messages=messages, profile=get_profile())

@app.post("/api/projects")
@host_only
def add_project():
    add_doc("projects", {**read_project(), "views": 0, "likes": 0, "created": time.time()})
    return jsonify(ok=True)

@app.put("/api/projects/<pid>")
@host_only
def edit_project(pid):
    update_doc("projects", pid, read_project())
    return jsonify(ok=True)

@app.delete("/api/projects/<pid>")
@host_only
def del_project(pid):
    delete_doc("projects", pid)
    return jsonify(ok=True)

# ---------- host: profile, links, messages ----------
@app.post("/api/profile")
@host_only
def save_profile():
    j = request.json or {}
    p = {k: j.get(k, DEFAULT_PROFILE[k]) for k in DEFAULT_PROFILE}
    if isinstance(p["roles"], str):
        p["roles"] = [r.strip() for r in p["roles"].split(",") if r.strip()]
    set_doc("site", "profile", p)
    return jsonify(ok=True)

@app.post("/api/links")
@host_only
def create_link():
    token = secrets.token_urlsafe(8)
    label = ((request.json or {}).get("label") or "Visitor link").strip()[:60]
    set_doc("links", token, {"label": label, "created": time.time(), "views": 0, "active": 1})
    return jsonify(token=token, url=request.host_url + "v/" + token)

@app.post("/api/links/<token>/toggle")
@host_only
def toggle_link(token):
    d = get_doc("links", token)
    if d:
        update_doc("links", token, {"active": 0 if d.get("active") else 1})
    return jsonify(ok=True)

@app.delete("/api/links/<token>")
@host_only
def del_link(token):
    delete_doc("links", token)
    return jsonify(ok=True)

@app.delete("/api/messages/<mid>")
@host_only
def del_message(mid):
    delete_doc("messages", mid)
    return jsonify(ok=True)

# ---------- visitors (token required, no login) ----------
def valid_link(token):
    d = get_doc("links", token)
    if not d or not d.get("active"):
        abort(404)

@app.get("/api/public/<token>")
def public_data(token):
    valid_link(token)
    incr("links", token, "views")
    projects = sorted((pdict(d) for d in list_docs("projects")), key=lambda p: not p.get("featured"))  # featured first
    return jsonify(profile=get_profile(), projects=projects)

@app.post("/api/public/<token>/event")
def public_event(token):
    valid_link(token)
    j = request.json or {}
    col = {"view": "views", "like": "likes"}.get(j.get("type"))
    if col and isinstance(j.get("id"), str):
        try:
            incr("projects", j["id"], col)
        except Exception:
            pass  # project was deleted
    return jsonify(ok=True)

@app.post("/api/public/<token>/contact")
def public_contact(token):
    valid_link(token)
    j = request.json or {}
    if not (j.get("name") and j.get("email") and j.get("msg")):
        return jsonify(error="missing fields"), 400
    add_doc("messages", {"name": j["name"][:80], "email": j["email"][:120],
                         "msg": j["msg"][:3000], "created": time.time()})
    return jsonify(ok=True)

if __name__ == "__main__":
    app.run(debug=True, port=5000)