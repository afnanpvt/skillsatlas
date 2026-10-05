"""Skill Atlas server and command line.
  skillsatlas              -> http://localhost:4747 (live scan, view, edit, remove)
  skillsatlas --export     -> read-only atlas-static.html you can share
"""
import argparse, json, os, shutil, threading, time, urllib.parse, webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from . import __version__, scan

HERE = scan.HERE
TRASH = scan.HOME / "skills-trash"  # removal = move here, never delete
TEXT_EXT = {".md", ".txt", ".json", ".py", ".js", ".ts", ".sh", ".yaml", ".yml", ".html", ".css", ".toml", ".csv", ""}
CAP = 200_000


def by_id(i):
    return next((s for s in scan.scan() if s["id"] == i), None)


def read_text(p):
    if p.suffix.lower() not in TEXT_EXT:
        return "(binary or unsupported file type)"
    return p.read_bytes()[:CAP].decode("utf-8", "replace")


def inside(child, parent):
    c, p = child.resolve(), parent.resolve()
    return c == p or p in c.parents


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def host_ok(self):  # blocks DNS rebinding
        return self.headers.get("Host", "").split(":")[0] in ("localhost", "127.0.0.1")

    def do_GET(self):
        if not self.host_ok():
            return self.send(403, {"error": "bad host"})
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        g = lambda k: (q.get(k) or [""])[0]
        if u.path == "/":
            return self.send(200, (HERE / "index.html").read_bytes(), "text/html")
        if u.path == "/api/skills":
            scan.invalidate()  # an explicit load/Rescan always reads the disk fresh
            return self.send(200, scan.payload())
        if u.path == "/api/skill":
            s = by_id(g("id"))
            if not s:
                return self.send(404, {"error": "not found"})
            d = s["_path"].parent
            files = [{"path": f.relative_to(d).as_posix(), "size": f.stat().st_size}
                     for f in sorted(d.rglob("*")) if f.is_file() and ".git" not in f.parts][:300]
            return self.send(200, {"content": read_text(s["_path"]), "files": files, "dir": str(d),
                                   "main": s["_path"].name, "mtime": str(s["_path"].stat().st_mtime_ns)})
        if u.path == "/api/file":
            s = by_id(g("id"))
            if not s:
                return self.send(404, {"error": "not found"})
            d = s["_path"].parent
            f = d / g("path")
            if not inside(f, d) or not f.is_file():
                return self.send(400, {"error": "bad path"})
            return self.send(200, {"content": read_text(f), "mtime": str(f.stat().st_mtime_ns),
                                   "editable": s["editable"] and f.suffix.lower() in TEXT_EXT})
        if u.path == "/api/trash":
            items = []
            for t in (sorted(TRASH.glob("*")) if TRASH.exists() else []):
                o = t / ".atlas-origin"
                if o.exists():
                    items.append({"trash": t.name, "origin": o.read_text(encoding="utf-8").strip()})
            return self.send(200, {"items": items})
        self.send(404, {"error": "not found"})

    def do_POST(self):
        if not self.host_ok() or self.headers.get("X-Atlas") != "1":  # custom header blocks cross-site forms
            return self.send(403, {"error": "forbidden"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self.send(400, {"error": "bad json"})
        if not isinstance(body, dict):
            return self.send(400, {"error": "bad json"})
        if self.path == "/api/remove":
            s = by_id(str(body.get("id", "")))
            if not s:
                return self.send(404, {"error": "not found"})
            if not s["removable"]:
                return self.send(400, {"error": "Only skills in your personal skills folder can be removed. Plugin skills are managed by their plugin."})
            d = s["_path"].parent
            if d.resolve() == scan.SKILLS.resolve() or not inside(d, scan.SKILLS):
                return self.send(400, {"error": "refusing path"})
            TRASH.mkdir(exist_ok=True)
            dest = TRASH / f"{d.name}__{time.strftime('%Y%m%d-%H%M%S')}"
            origin = d.relative_to(scan.SKILLS).as_posix()
            shutil.move(str(d), str(dest))
            (dest / ".atlas-origin").write_text(origin, encoding="utf-8")
            scan.invalidate()
            return self.send(200, {"ok": True, "trash": dest.name})
        if self.path in ("/api/category", "/api/category/add", "/api/category/delete", "/api/category/assign"):
            try:
                if self.path == "/api/category/assign":
                    return self.send(200, {"ok": True, "count": scan.assign_category(body.get("domain", ""), body.get("skills"))})
                if self.path == "/api/category":
                    scan.set_category(body.get("skill", ""), body.get("domain", ""))
                elif self.path.endswith("add"):
                    scan.add_category(body.get("name", ""))
                else:
                    scan.delete_category(str(body.get("name", "")))
                return self.send(200, {"ok": True})
            except ValueError as e:
                return self.send(400, {"error": str(e)})
        if self.path in ("/api/roots/add", "/api/roots/remove"):
            try:
                if self.path.endswith("add"):
                    return self.send(200, scan.add_root(body.get("path", "")))
                scan.remove_root(body.get("path", ""))
                return self.send(200, {"ok": True})
            except ValueError as e:
                return self.send(400, {"error": str(e)})
        if self.path == "/api/save":
            s = by_id(str(body.get("id", "")))
            if not s:
                return self.send(404, {"error": "not found"})
            if not s["editable"]:
                return self.send(400, {"error": "Plugin files are read-only here: a plugin update would overwrite your edits."})
            d = s["_path"].parent
            f = d / str(body.get("path") or s["_path"].name)
            text = body.get("content")
            if not isinstance(text, str) or len(text) > CAP:
                return self.send(400, {"error": "content must be text under 200 KB"})
            if not inside(f, d) or not f.is_file() or f.suffix.lower() not in TEXT_EXT:
                return self.send(400, {"error": "bad path"})
            if str(f.stat().st_mtime_ns) != str(body.get("mtime")):
                return self.send(409, {"error": "This file changed on disk since you opened it. Reopen the skill to see the latest."})
            old = f.read_bytes()
            hist = scan.HOME / "skills-history" / d.name
            hist.mkdir(parents=True, exist_ok=True)
            (hist / f"{time.strftime('%Y%m%d-%H%M%S')}__{f.relative_to(d).as_posix().replace('/', '__')}").write_bytes(old)
            out = text.replace("\r\n", "\n")
            if b"\r\n" in old:
                out = out.replace("\n", "\r\n")  # keep the file's original line endings
            tmp = f.with_name(f.name + ".atlas-tmp")
            tmp.write_bytes(out.encode("utf-8"))
            os.replace(tmp, f)
            scan.invalidate()
            return self.send(200, {"ok": True, "mtime": str(f.stat().st_mtime_ns)})
        if self.path == "/api/restore":
            t = TRASH / str(body.get("trash", ""))
            if not inside(t, TRASH) or t.resolve() == TRASH.resolve() or not (t / ".atlas-origin").exists():
                return self.send(404, {"error": "not in trash"})
            origin = (t / ".atlas-origin").read_text(encoding="utf-8").strip()
            dest = scan.SKILLS / origin
            if not inside(dest, scan.SKILLS) or dest.exists():
                return self.send(409, {"error": "a skill already exists at that location"})
            dest.parent.mkdir(parents=True, exist_ok=True)
            (t / ".atlas-origin").unlink()
            shutil.move(str(t), str(dest))
            scan.invalidate()
            return self.send(200, {"ok": True})
        self.send(404, {"error": "not found"})


class Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second server share a busy port, so refuse it there and fail with a clear message instead.
    allow_reuse_address = os.name != "nt"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="skillsatlas", description="A visual directory of every Claude Code skill on your machine.")
    ap.add_argument("--port", type=int, default=int(os.environ.get("ATLAS_PORT", 4747)), help="port to listen on (default 4747)")
    ap.add_argument("--no-browser", action="store_true", help="don't open the browser automatically")
    ap.add_argument("--export", nargs="?", const="atlas-static.html", metavar="FILE",
                    help="write a read-only, shareable HTML copy instead of starting the server")
    ap.add_argument("--version", action="version", version=f"skillsatlas {__version__}")
    args = ap.parse_args(argv)

    if args.export:
        data = scan.payload()
        data["static"] = True
        html = (HERE / "index.html").read_text(encoding="utf-8").replace("null/*DATA*/", json.dumps(data))
        with open(args.export, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Wrote {args.export} ({len(data['skills'])} skills). It is read-only: no editing, adding or removing.")
        return 0

    try:
        server = Server(("127.0.0.1", args.port), H)
    except OSError:
        print(f"Port {args.port} is busy. Is Skill Atlas already running? Try: skillsatlas --port {args.port + 1}")
        return 1
    url = f"http://localhost:{args.port}"
    print(f"Skill Atlas {__version__} is running at {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(0.6, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
