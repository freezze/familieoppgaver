"""Familieoppgaver – enkel oppgavetavle for barna med dagens kalender.

Kun standardbibliotek. Data lagres som JSON i DATA_DIR (persistent volum i Coolify).
"""
import hashlib
import hmac
import json
import os
import threading
import time
import urllib.request
import uuid
from datetime import date as Date, datetime, timedelta, timezone
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

PORT = int(os.environ.get("PORT", "3000"))
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
SYNC_TOKEN = os.environ.get("SYNC_TOKEN", "")
PUBLIC = Path(__file__).parent / "public"
LOCK = threading.Lock()

# Tilgang: hvert barn har sin egen kode (startverdier i KID_CODES="bastian:1234,..."),
# foreldrekoden settes i ADMIN_CODE.
# Enheten husker hvem man er i et år (cookie).
ADMIN_CODE = os.environ.get("ADMIN_CODE", "")  # foreldrekode – kreves ALLTID for å endre oppgaver
ADMIN_COOKIE = "foreldre"
SECRET = (os.environ.get("COOKIE_SECRET") or SYNC_TOKEN or "lokal").encode()
COOKIE = "tilgang"
OPEN_PATHS = {"/health", "/api/calendar", "/api/sync", "/api/sync/set", "/api/login", "/api/login-info", "/api/logout",
              "/api/whoami", "/style.css", "/icon.svg", "/login.html"}
FAILS = {}  # hvem -> (antall, første forsøk)

# Vær fra Yr / MET Norway (Skien)
LAT, LON = os.environ.get("WEATHER_LAT", "59.2096"), os.environ.get("WEATHER_LON", "9.6090")
WEATHER = {"data": None, "fetched": 0, "expires": 0, "last_modified": None}

KIDS = [
    {"id": "bastian", "name": "Bastian", "color": "#3E9A5B", "cal": "Bastian", "birthday": "10-07", "born": 2015},
    {"id": "cadence", "name": "Cadence", "color": "#3B78C2", "cal": "Cadence", "birthday": "01-17", "born": 2014},
    {"id": "william", "name": "William", "color": "#E07B24", "cal": "William", "birthday": "12-08", "born": 2009},
]
FELLES_CAL = "Fellesplan"
# Bor hos oss bare i barneuker: heldagshendelse «Barneuke» i Fellesplan.
# Heldagshendelser med «pappa» i navnet (f.eks. «C+W ferie med pappa») betyr også borte.
PART_TIME = {"cadence", "william"}
KEEP_DAYS = 400

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


def covers(e, day):
    s, end = e["start"][:10], e["end"][:10]
    if end > s and e["end"][11:19] == "00:00:00":
        return s <= day < end  # slutt ved midnatt er eksklusiv
    return s <= day <= end


def auto_away(day):
    """Hvem som er borte ifølge Fellesplan. Utenfor perioden kalenderen dekker: ingen."""
    cal = load("calendar.json", {})
    gen = cal.get("generated")
    if not gen:
        return set(), {}
    g = Date.fromisoformat(gen[:10])
    if not (g - timedelta(days=1) <= Date.fromisoformat(day) <= g + timedelta(days=7)):
        return set(), {}
    fe = [e for e in cal.get("events", []) if e.get("cal") == FELLES_CAL and e.get("allDay") and covers(e, day)]
    away, why = set(), {}
    if not any("barneuke" in e["title"].lower() for e in fe):
        for k in PART_TIME:
            away.add(k)
            why[k] = "Ikke barneuke"
    for e in fe:
        if "pappa" in e["title"].lower():
            for k in PART_TIME:
                away.add(k)
                why[k] = e["title"]
    return away, why


def away_for(day):
    """Effektiv borte-liste: kalender + manuelle overstyringer («Ikke hjemme» / «Hjemme likevel»)."""
    auto, why = auto_away(day)
    manual = load("away.json", {}).get(day, {})
    if isinstance(manual, list):
        manual = {k: True for k in manual}
    away = [k["id"] for k in KIDS if manual.get(k["id"], k["id"] in auto)]
    reasons = {k: ("Satt manuelt" if k in manual else why.get(k, "")) for k in away}
    return away, reasons, manual, auto


def applies(t, day):
    return not t["days"] or Date.fromisoformat(day).weekday() in t["days"]


def record_plan(day):
    """Lagrer hvilke oppgaver som gjaldt denne dagen – grunnlaget for statistikken."""
    away, _, _, _ = away_for(day)
    t = [x for x in tasks() if applies(x, day)]
    plan = {"kids": {k["id"]: [x["id"] for x in t if x["owner"] == k["id"]] for k in KIDS if k["id"] not in away},
            "felles": [x["id"] for x in t if x["owner"] == "felles"], "away": away,
            "titles": {x["id"]: f'{x["emoji"]} {x["title"]}'.strip() for x in t},
            "owners": {x["id"]: x["owner"] for x in t}}
    plans = load("plans.json", {})
    if plans.get(day) != plan:
        plans[day] = plan
        for k in sorted(plans)[:-KEEP_DAYS]:
            del plans[k]
        save("plans.json", plans)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sign(text):
    return hmac.new(SECRET, text.encode(), hashlib.sha256).hexdigest()[:32]


def hash_code(code, salt):
    return hashlib.pbkdf2_hmac("sha256", code.encode(), salt.encode(), 100_000).hex()


def set_code(kid, code):
    codes = load("codes.json", {})
    salt = uuid.uuid4().hex
    codes[kid] = {"salt": salt, "hash": hash_code(code, salt)}
    save("codes.json", codes)


def seed_codes():
    """Legger inn startkoder fra KID_CODES for barn som ikke har kode ennå."""
    codes = load("codes.json", {})
    for part in os.environ.get("KID_CODES", "").split(","):
        kid, _, code = part.strip().partition(":")
        if kid and code and kid not in codes:
            set_code(kid, code.strip())
            codes = load("codes.json", {})


def kid_token(kid):
    """Cookie-verdi for et barn. Blir ugyldig når koden nullstilles eller byttes."""
    c = load("codes.json", {}).get(kid)
    return f"{kid}.{sign(kid + ':' + c['hash'])}" if c else None


def weather():
    """Henter varsel fra api.met.no, maks hvert 30. minutt (følger Expires)."""
    now = time.time()
    if WEATHER["data"] and now < max(WEATHER["expires"], WEATHER["fetched"] + 1800):
        return WEATHER["data"]
    url = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={LAT}&lon={LON}"
    headers = {"User-Agent": "familieoppgaver/1.0 https://github.com/freezze/familieoppgaver"}
    if WEATHER["last_modified"]:
        headers["If-Modified-Since"] = WEATHER["last_modified"]
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10) as r:
            raw = json.loads(r.read())
            WEATHER["last_modified"] = r.headers.get("Last-Modified")
        series = []
        for e in raw["properties"]["timeseries"]:
            d = e["data"]
            nxt = d.get("next_1_hours") or d.get("next_6_hours") or {}
            series.append({
                "t": e["time"],
                "temp": d["instant"]["details"].get("air_temperature"),
                "wind": d["instant"]["details"].get("wind_speed"),
                "sym": nxt.get("summary", {}).get("symbol_code"),
                "pr": nxt.get("details", {}).get("precipitation_amount"),
                "h": 1 if "next_1_hours" in d else 6,
            })
        WEATHER["data"] = {"series": series, "updated": raw["properties"]["meta"]["updated_at"]}
    except urllib.error.HTTPError as err:
        if err.code != 304:
            print("vær feilet:", err, flush=True)
    except Exception as err:
        print("vær feilet:", err, flush=True)
    WEATHER["fetched"] = now
    WEATHER["expires"] = now + 1800
    return WEATHER["data"]


class Handler(BaseHTTPRequestHandler):
    server_version = "Familieoppgaver/1"

    def log_message(self, fmt, *args):
        pass

    def cookies(self):
        return SimpleCookie(self.headers.get("Cookie", ""))

    def is_admin(self):
        c = self.cookies()
        return bool(ADMIN_CODE) and ADMIN_COOKIE in c and hmac.compare_digest(c[ADMIN_COOKIE].value, sign("admin:" + ADMIN_CODE))

    def me(self):
        """Hvilket barn denne enheten tilhører, «foreldre», eller None."""
        if self.is_admin():
            return "foreldre"
        c = self.cookies()
        if COOKIE in c:
            kid = c[COOKIE].value.split(".")[0]
            tok = kid_token(kid)
            if tok and hmac.compare_digest(c[COOKIE].value, tok):
                return kid
        return None

    def has_access(self):
        return not ADMIN_CODE or self.me() is not None

    def guard(self, p, method="GET"):
        """Returnerer True hvis forespørselen er stoppet (ingen tilgang)."""
        if p in OPEN_PATHS:
            return False
        admin_needed = p in ("/admin", "/admin/", "/admin.html", "/api/tasks", "/statistikk", "/statistikk.html", "/api/stats")
        if (self.is_admin() or not ADMIN_CODE) if admin_needed else self.has_access():
            return False
        if p.startswith("/api/"):
            self.send_json({"error": "kode"}, 401)
        else:
            self.send_file(PUBLIC / "login.html")
        return True

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
        if self.guard(u.path):
            return
        if u.path == "/api/whoami":
            return self.send_json({"me": self.me()})
        if u.path == "/api/login-info":
            codes = load("codes.json", {})
            return self.send_json({"kids": [dict(k, hasCode=k["id"] in codes) for k in KIDS]})
        if u.path == "/api/sync":
            # Brukes av Macen for å speile dagens oppgaver i Påminnelser
            if not SYNC_TOKEN or self.headers.get("X-Sync-Token") != SYNC_TOKEN:
                return self.send_json({"error": "nei"}, 403)
            date = (q.get("date") or [""])[0][:10]
            with LOCK:
                record_plan(date)
                return self.send_json({"kids": KIDS, "tasks": tasks(), "done": load("done.json", {}).get(date, {}),
                                       "away": away_for(date)[0]})
        if u.path == "/api/weather":
            return self.send_json(weather() or {"series": []})
        if u.path == "/api/state":
            date = (q.get("date") or [""])[0][:10]
            today = (q.get("today") or [""])[0][:10]
            with LOCK:
                done = load("done.json", {})
                away, reasons, _, _ = away_for(date)
                cal = load("calendar.json", {"events": [], "generated": None})
                t = tasks()
                if date and date == today:
                    record_plan(date)
            return self.send_json({
                "kids": KIDS, "fellesCal": FELLES_CAL, "tasks": t,
                "done": done.get(date, {}), "away": away, "awayReason": reasons,
                "events": cal.get("events", []), "calendarUpdated": cal.get("generated"),
                "me": self.me(),
            })
        if u.path == "/api/stats":
            if not self.is_admin():
                return self.send_json({"error": "kode"}, 401)
            days = min(int((q.get("days") or ["84"])[0]), KEEP_DAYS)
            with LOCK:
                plans, done = load("plans.json", {}), load("done.json", {})
            keys = sorted(plans)[-days:]
            return self.send_json({"kids": KIDS, "plans": {d: plans[d] for d in keys},
                                   "done": {d: done.get(d, {}) for d in keys}})
        if u.path == "/api/tasks":
            with LOCK:
                codes = load("codes.json", {})
                return self.send_json({"kids": [dict(k, hasCode=k["id"] in codes) for k in KIDS], "tasks": tasks()})
        if u.path == "/health":
            return self.send_json({"ok": True})
        name = {"/admin": "admin.html", "/admin/": "admin.html", "/statistikk": "statistikk.html"}.get(u.path) or (u.path.lstrip("/") or "index.html")
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

        if u.path == "/api/login":
            who, code = str(body.get("who", "")), str(body.get("code", "")).strip()
            kids = {k["id"] for k in KIDS}
            if who != "foreldre" and who not in kids:
                return self.send_json({"error": "Velg hvem du er"}, 400)
            now = time.time()
            n, first = FAILS.get(who, (0, now))
            if now - first > 900:
                n, first = 0, now
            if n >= 10:
                return self.send_json({"error": "For mange feil. Vent et kvarter og prøv igjen."}, 429)
            with LOCK:
                codes = load("codes.json", {})
                if who == "foreldre":
                    ok = bool(ADMIN_CODE) and hmac.compare_digest(code, ADMIN_CODE)
                elif who not in codes:
                    return self.send_json({"error": "Du har ingen kode ennå – spør mamma eller pappa"}, 403)
                else:
                    c = codes[who]
                    ok = hmac.compare_digest(hash_code(code, c["salt"]), c["hash"])
            if not ok:
                FAILS[who] = (n + 1, first)
                return self.send_json({"error": "Feil kode"}, 403)
            FAILS.pop(who, None)
            name, tok = (ADMIN_COOKIE, sign("admin:" + ADMIN_CODE)) if who == "foreldre" else (COOKIE, kid_token(who))
            payload = json.dumps({"ok": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Set-Cookie", f"{name}={tok}; Max-Age=31536000; Path=/; HttpOnly; SameSite=Lax; Secure")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if u.path == "/api/sync/set":
            if not SYNC_TOKEN or self.headers.get("X-Sync-Token") != SYNC_TOKEN:
                return self.send_json({"error": "nei"}, 403)
            date, tid = str(body.get("date", ""))[:10], str(body.get("taskId", ""))
            with LOCK:
                done = load("done.json", {})
                day = done.setdefault(date, {})
                if body.get("done"):
                    day.setdefault(tid, {"by": body.get("by"), "at": body.get("at") or now_iso(), "via": "påminnelser"})
                else:
                    day.pop(tid, None)
                save("done.json", done)
            return self.send_json({"ok": True})

        if u.path == "/api/logout":
            self.send_response(200)
            for name in (COOKIE, ADMIN_COOKIE):
                self.send_header("Set-Cookie", f"{name}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax; Secure")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if u.path == "/api/set-code":
            # Foreldre bytter et barns kode. Enheter som var logget inn som barnet må taste ny kode.
            if not self.is_admin():
                return self.send_json({"error": "kode"}, 401)
            kid, code = str(body.get("kid", "")), str(body.get("code", "")).strip()
            if kid not in {k["id"] for k in KIDS} or not (code.isdigit() and 4 <= len(code) <= 8):
                return self.send_json({"error": "Koden må være 4–8 tall"}, 400)
            with LOCK:
                set_code(kid, code)
            return self.send_json({"ok": True})

        if self.guard(u.path):
            return

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
                    day[tid] = {"by": by, "at": now_iso(), "via": "skjerm"}
                record_plan(date)
                for k in sorted(done)[:-KEEP_DAYS]:
                    del done[k]
                save("done.json", done)
                return self.send_json({"done": day})

        if u.path == "/api/away":
            date, kid = str(body.get("date", ""))[:10], str(body.get("kid", ""))
            with LOCK:
                eff, _, manual, auto = away_for(date)
                manual = dict(manual)
                new = kid not in eff  # snu det som gjelder nå
                if new == (kid in auto):
                    manual.pop(kid, None)  # samme som kalenderen – ingen overstyring trengs
                else:
                    manual[kid] = new
                allaway = load("away.json", {})
                allaway[date] = manual
                for k in sorted(allaway)[:-KEEP_DAYS]:
                    del allaway[k]
                save("away.json", allaway)
                away, reasons, _, _ = away_for(date)
                return self.send_json({"away": away, "awayReason": reasons})

        if u.path == "/api/calendar":
            if not SYNC_TOKEN or self.headers.get("X-Sync-Token") != SYNC_TOKEN:
                return self.send_json({"error": "nei"}, 403)
            with LOCK:
                save("calendar.json", {"events": body.get("events", []), "generated": body.get("generated")})
            return self.send_json({"ok": True, "count": len(body.get("events", []))})

        self.send_json({"error": "ikke funnet"}, 404)

    def do_PUT(self):
        if self.guard(urlparse(self.path).path):
            return
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
    seed_codes()
    print(f"Familieoppgaver på port {PORT}, data i {DATA_DIR}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
