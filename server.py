"""Familieoppgaver – enkel oppgavetavle for barna med dagens kalender.

Kun standardbibliotek. Data lagres som JSON i DATA_DIR (persistent volum i Coolify).
"""
import json
import os
import threading
import uuid
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

PORT = int(os.environ.get("PORT", "3000"))
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
SYNC_TOKEN = os.environ.get("SYNC_TOKEN", "")
PUBLIC = Path(__file__).parent / "public"
LOCK = threading.Lock()

KIDS = [
    {"id": "bastian", "name": "Bastian", "color": "#C8453C", "cal": "Bastian", "birthday": "10-07", "born": 2015},
    {"id": "cadence", "name": "Cadence", "color": "#3B78C2", "cal": "Cadence", "birthday": "01-17", "born": 2014},
    {"id": "william", "name": "William", "color": "#3E9A5B", "cal": "William", "birthday": "12-08", "born": 2009},
]
FELLES_CAL = "Fellesplan"

# Dager: 0 = mandag ... 6 = søndag. Tom liste = hver dag.
DEFAULT_TASKS = [
    # Bastian (11)
    {"owner": "bastian", "title": "Re opp senga", "emoji": "🛏️", "days": []},
    {"owner": "bastian", "title": "Skittentøy i skittentøykurven", "emoji": "🧦", "days": []},
    {"owner": "bastian", "title": "Sette tallerken og glass i oppvaskmaskinen", "emoji": "🍽️", "days": []},
    {"owner": "bastian", "title": "Pakke skolesekken til i morgen", "emoji": "🎒", "days": [6, 0, 1, 2, 3]},
    {"owner": "bastian", "title": "Pakke gymbagen til i morgen", "emoji": "👟", "days": [2]},
    {"owner": "bastian", "title": "Rydde rommet (15 min)", "emoji": "🧹", "days": [5]},
    # Cadence (13)
    {"owner": "cadence", "title": "Re opp senga", "emoji": "🛏️", "days": []},
    {"owner": "cadence", "title": "Skittentøy i skittentøykurven", "emoji": "🧺", "days": []},
    {"owner": "cadence", "title": "Rydde etter seg på kjøkkenet", "emoji": "🍽️", "days": []},
    {"owner": "cadence", "title": "Pakke skolesekken til i morgen", "emoji": "🎒", "days": [6, 0, 1, 2, 3]},
    {"owner": "cadence", "title": "Pakke gymbagen til i morgen", "emoji": "👟", "days": [2]},
    {"owner": "cadence", "title": "Skifte sengetøy", "emoji": "🛌", "days": [6]},
    # William (17)
    {"owner": "william", "title": "Re opp senga", "emoji": "🛏️", "days": []},
    {"owner": "william", "title": "Skittentøy i skittentøykurven", "emoji": "🧺", "days": []},
    {"owner": "william", "title": "Rydde etter seg på kjøkkenet", "emoji": "🍽️", "days": []},
    {"owner": "william", "title": "Sjekke timeplan og lekser for i morgen", "emoji": "📅", "days": [6, 0, 1, 2, 3]},
    {"owner": "william", "title": "Pakke gymbagen til i morgen", "emoji": "👟", "days": [2]},
    {"owner": "william", "title": "Skifte sengetøy", "emoji": "🛌", "days": [6]},
    # Felles – hvem som helst
    {"owner": "felles", "title": "Tømme oppvaskmaskinen", "emoji": "🍽️", "days": []},
    {"owner": "felles", "title": "Ta ut søpla", "emoji": "🗑️", "days": []},
    {"owner": "felles", "title": "Tørke av kjøkkenbordet etter middag", "emoji": "🧽", "days": []},
    {"owner": "felles", "title": "Rydde skoene i gangen", "emoji": "👟", "days": []},
    {"owner": "felles", "title": "Støvsuge stua", "emoji": "🧹", "days": [1, 4]},
    {"owner": "felles", "title": "Brette og bære opp ren klesvask", "emoji": "👕", "days": [6]},
]


def path(name):
    return DATA_DIR / name


def load(name, default):
    p = path(name)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text("utf-8"))
    except Exception:
        return default


def save(name, data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path(name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
    tmp.replace(path(name))


def tasks():
    t = load("tasks.json", None)
    if t is None:
        t = [dict(x, id=uuid.uuid4().hex[:8]) for x in DEFAULT_TASKS]
        save("tasks.json", t)
    return t


class Handler(BaseHTTPRequestHandler):
    server_version = "Familieoppgaver/1"

    def log_message(self, fmt, *args):
        pass

    def send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 2_000_000:
            raise ValueError("for stor")
        return json.loads(self.rfile.read(n) or b"{}")

    def send_file(self, f):
        types = {".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css",
                 ".svg": "image/svg+xml", ".png": "image/png", ".webmanifest": "application/manifest+json"}
        body = f.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", types.get(f.suffix, "application/octet-stream"))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/api/state":
            date = (q.get("date") or [""])[0][:10]
            with LOCK:
                done = load("done.json", {})
                away = load("away.json", {})
                cal = load("calendar.json", {"events": [], "generated": None})
                t = tasks()
            return self.send_json({
                "kids": KIDS, "fellesCal": FELLES_CAL, "tasks": t,
                "done": done.get(date, {}), "away": away.get(date, []),
                "events": cal.get("events", []), "calendarUpdated": cal.get("generated"),
            })
        if u.path == "/api/tasks":
            with LOCK:
                return self.send_json({"kids": KIDS, "tasks": tasks()})
        if u.path == "/health":
            return self.send_json({"ok": True})
        name = "admin.html" if u.path in ("/admin", "/admin/") else (u.path.lstrip("/") or "index.html")
        f = (PUBLIC / name).resolve()
        if PUBLIC.resolve() in f.parents and f.is_file():
            return self.send_file(f)
        self.send_json({"error": "ikke funnet"}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        try:
            body = self.read_body()
        except Exception:
            return self.send_json({"error": "ugyldig"}, 400)

        if u.path == "/api/toggle":
            date, tid = str(body.get("date", ""))[:10], str(body.get("taskId", ""))
            by = body.get("by")
            if len(date) != 10 or not tid:
                return self.send_json({"error": "mangler felt"}, 400)
            with LOCK:
                done = load("done.json", {})
                day = done.setdefault(date, {})
                if tid in day:
                    del day[tid]
                else:
                    day[tid] = {"by": by}
                # Behold bare de siste 60 dagene
                for k in sorted(done)[:-60]:
                    del done[k]
                save("done.json", done)
                return self.send_json({"done": day})

        if u.path == "/api/away":
            date, kid = str(body.get("date", ""))[:10], str(body.get("kid", ""))
            with LOCK:
                away = load("away.json", {})
                lst = away.setdefault(date, [])
                if kid in lst:
                    lst.remove(kid)
                else:
                    lst.append(kid)
                for k in sorted(away)[:-60]:
                    del away[k]
                save("away.json", away)
                return self.send_json({"away": lst})

        if u.path == "/api/calendar":
            if not SYNC_TOKEN or self.headers.get("X-Sync-Token") != SYNC_TOKEN:
                return self.send_json({"error": "nei"}, 403)
            with LOCK:
                save("calendar.json", {"events": body.get("events", []), "generated": body.get("generated")})
            return self.send_json({"ok": True, "count": len(body.get("events", []))})

        self.send_json({"error": "ikke funnet"}, 404)

    def do_PUT(self):
        if urlparse(self.path).path != "/api/tasks":
            return self.send_json({"error": "ikke funnet"}, 404)
        try:
            body = self.read_body()
        except Exception:
            return self.send_json({"error": "ugyldig"}, 400)
        valid_owners = {k["id"] for k in KIDS} | {"felles"}
        clean = []
        for t in body.get("tasks", []):
            title = str(t.get("title", "")).strip()[:120]
            if not title or t.get("owner") not in valid_owners:
                continue
            days = sorted({int(d) for d in t.get("days", []) if str(d).isdigit() and 0 <= int(d) <= 6})
            clean.append({"id": str(t.get("id") or uuid.uuid4().hex[:8])[:16], "owner": t["owner"],
                          "title": title, "emoji": str(t.get("emoji", ""))[:8], "days": days})
        with LOCK:
            save("tasks.json", clean)
        self.send_json({"tasks": clean})


if __name__ == "__main__":
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Familieoppgaver på port {PORT}, data i {DATA_DIR}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
