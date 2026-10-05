"""Stress test: runs the real server against a throwaway ATLAS_HOME. Run: python tests/test_server.py"""
import os, sys, json, tempfile, pathlib, threading, http.client

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
tmp = pathlib.Path(tempfile.mkdtemp())
os.environ["ATLAS_HOME"] = str(tmp)
sk = tmp / "skills"
(sk / "alpha").mkdir(parents=True)
(sk / "alpha" / "SKILL.md").write_text("---\nname: alpha\ndescription: >\n  Design a screen.\n  Use when building UI.\n---\nbody", encoding="utf-8")
(sk / "alpha" / "ref.md").write_text("ref", encoding="utf-8")
(sk / "grp" / "nested").mkdir(parents=True)
(sk / "grp" / "nested" / "SKILL.md").write_text("---\nname: nested\ndescription: Nested one.\n---\n", encoding="utf-8")
(sk / "broken").mkdir()
(sk / "broken" / "SKILL.md").write_text("no frontmatter here", encoding="utf-8")
plug = tmp / "plugins" / "cache" / "mkt" / "pluggy" / "1.0" / "skills" / "p1"
plug.mkdir(parents=True)
(plug / "SKILL.md").write_text("---\nname: p1\ndescription: Plugin skill.\n---\n", encoding="utf-8")
secret = tmp / "secret.txt"
secret.write_text("TOP SECRET", encoding="utf-8")

from skillsatlas import server, scan, __version__
from http.server import ThreadingHTTPServer
srv = server.Server(("127.0.0.1", 0), server.H)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()


def call(method, path, body=None, headers=None, host=None):
    c = http.client.HTTPConnection("127.0.0.1", port)
    h = {"Host": host or f"localhost:{port}"}
    h.update(headers or {})
    data = json.dumps(body).encode() if body is not None else None
    if data: h["Content-Type"] = "application/json"
    c.request(method, path, data, h)
    r = c.getresponse()
    raw = r.read()
    try: return r.status, json.loads(raw)
    except ValueError: return r.status, raw

POST = {"X-Atlas": "1"}
fails = []
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: fails.append(name)

st, data = call("GET", "/api/skills")
names = {s["name"]: s for s in data["skills"]}
check("lists personal, nested and plugin skills", {"alpha", "nested", "p1"} <= set(names))
check("SKILL.md without frontmatter is listed by folder name", names["broken"]["desc"] == "")
check("multi-line description parsed", "Design a screen" in names["alpha"]["desc"])
check("personal removable, plugin not", names["alpha"]["removable"] and not names["p1"]["removable"])

st, d = call("GET", f"/api/skill?id={names['alpha']['id']}")
check("skill detail returns source + files", st == 200 and "body" in d["content"] and len(d["files"]) == 2)
st, _ = call("GET", f"/api/file?id={names['alpha']['id']}&path=../../secret.txt")
check("path traversal on /api/file blocked", st == 400)
st, _ = call("GET", f"/api/file?id={names['alpha']['id']}&path=C:/Windows/win.ini")
check("absolute path on /api/file blocked", st == 400)

st, _ = call("POST", "/api/remove", {"id": names["alpha"]["id"]})
check("POST without X-Atlas header rejected", st == 403)
st, _ = call("POST", "/api/remove", {"id": names["alpha"]["id"]}, POST, host="evil.com")
check("foreign Host header rejected (DNS rebinding)", st == 403)
st, _ = call("GET", "/api/skills", host="evil.com")
check("GET with foreign Host rejected", st == 403)
check("alpha untouched after rejected requests", (sk / "alpha" / "SKILL.md").exists())

st, _ = call("POST", "/api/remove", {"id": names["p1"]["id"]}, POST)
check("plugin skill removal refused", st == 400 and (plug / "SKILL.md").exists())
st, _ = call("POST", "/api/remove", {"id": "../../"}, POST)
check("bogus id rejected", st == 404)

st, r = call("POST", "/api/remove", {"id": names["alpha"]["id"]}, POST)
check("remove personal skill succeeds", st == 200 and not (sk / "alpha").exists())
check("removed skill sits in trash with all files", (server.TRASH / r["trash"] / "ref.md").exists())
st, data = call("GET", "/api/skills")
check("removed skill disappears from listing", "alpha" not in {s["name"] for s in data["skills"]})
st, _ = call("POST", "/api/remove", {"id": names["alpha"]["id"]}, POST)
check("removing twice gives 404, no crash", st == 404)

st, t = call("GET", "/api/trash")
check("trash lists the item", [i["origin"] for i in t["items"]] == ["alpha"])
st, _ = call("POST", "/api/restore", {"trash": "../.."}, POST)
check("restore path traversal blocked", st == 404)
st, _ = call("POST", "/api/restore", {"trash": ""}, POST)
check("restore of trash root blocked", st == 404)

(sk / "alpha").mkdir()
st, _ = call("POST", "/api/restore", {"trash": r["trash"]}, POST)
check("restore refuses to overwrite existing skill (409)", st == 409)
(sk / "alpha").rmdir()
st, _ = call("POST", "/api/restore", {"trash": r["trash"]}, POST)
check("restore puts skill back", st == 200 and (sk / "alpha" / "SKILL.md").exists())
check("restore cleans up marker file", not (sk / "alpha" / ".atlas-origin").exists())

st, data = call("GET", "/api/skills")
nid = {s["name"]: s["id"] for s in data["skills"]}["nested"]
st, r2 = call("POST", "/api/remove", {"id": nid}, POST)
st2, _ = call("POST", "/api/restore", {"trash": r2["trash"]}, POST)
check("nested skill remove + restore keeps its group path", st == 200 and st2 == 200 and (sk / "grp" / "nested" / "SKILL.md").exists())
check("skills root itself never removed", sk.exists() and secret.exists())
st, _ = call("POST", "/api/remove", b"not json".decode(), POST)
check("malformed body does not crash server", st in (400, 404))

# ---- editing ----
st, data = call("GET", "/api/skills")
ids = {s["name"]: s["id"] for s in data["skills"]}
alpha = ids["alpha"]
st, f = call("GET", f"/api/file?id={alpha}&path=SKILL.md")
check("file read returns mtime + editable flag", st == 200 and f["editable"] and f["mtime"])
check("mtime sent as string (nanoseconds overflow JS numbers)", isinstance(f["mtime"], str))
body = {"id": alpha, "path": "SKILL.md", "content": "---\nname: alpha\ndescription: Edited!\n---\nnew body", "mtime": f["mtime"]}
st, _ = call("POST", "/api/save", body)
check("save without X-Atlas header rejected", st == 403)
st, r = call("POST", "/api/save", body, POST)
check("save succeeds", st == 200 and "Edited!" in (sk / "alpha" / "SKILL.md").read_text(encoding="utf-8"))
hist = list((tmp / "skills-history" / "alpha").glob("*__SKILL.md"))
check("previous version backed up before overwrite", len(hist) == 1 and "Design a screen" in hist[0].read_text(encoding="utf-8"))
st, _ = call("POST", "/api/save", body, POST)
check("stale mtime -> 409, no silent overwrite", st == 409)
st, data = call("GET", "/api/skills")
check("edited description shows up on rescan", next(s for s in data["skills"] if s["name"] == "alpha")["desc"] == "Edited!")

crlf = sk / "alpha" / "ref.md"
crlf.write_bytes(b"line1\r\nline2\r\n")
st, f2 = call("GET", f"/api/file?id={alpha}&path=ref.md")
st, _ = call("POST", "/api/save", {"id": alpha, "path": "ref.md", "content": "a\nb\nc", "mtime": f2["mtime"]}, POST)
check("CRLF line endings preserved on save", crlf.read_bytes() == b"a\r\nb\r\nc")

st, f3 = call("GET", f"/api/file?id={alpha}&path=SKILL.md")
st, _ = call("POST", "/api/save", {"id": alpha, "path": "../../secret.txt", "content": "pwn", "mtime": 0}, POST)
check("save path traversal blocked", st == 400 and secret.read_text() == "TOP SECRET")
st, _ = call("POST", "/api/save", {"id": alpha, "path": "SKILL.md", "content": "x" * 300000, "mtime": f3["mtime"]}, POST)
check("oversized save rejected", st == 400)
st, _ = call("POST", "/api/save", {"id": alpha, "path": "SKILL.md", "content": 123, "mtime": f3["mtime"]}, POST)
check("non-string content rejected", st == 400)
(sk / "alpha" / "pic.png").write_bytes(b"\x89PNG")
st, _ = call("POST", "/api/save", {"id": alpha, "path": "pic.png", "content": "x", "mtime": (sk / "alpha" / "pic.png").stat().st_mtime_ns}, POST)
check("binary file save refused", st == 400)
st, _ = call("POST", "/api/save", {"id": ids["p1"], "path": "SKILL.md", "content": "x", "mtime": 0}, POST)
check("plugin skill save refused", st == 400 and "Plugin skill" in (plug / "SKILL.md").read_text())
st, _ = call("POST", "/api/save", {"id": "nope", "content": "x"}, POST)
check("save on unknown skill -> 404", st == 404)
check("no temp files left behind", not list(sk.rglob("*.atlas-tmp")))

st, data = call("GET", "/api/skills")
labels = {s["label"]: s for s in data["sources"]}
check("sources report lists scanned directories with counts", labels["Personal skills"]["count"] >= 2 and labels["Plugin cache"]["count"] == 1)

# ---- custom folders + skill / non-skill detection ----
proj = tmp / "proj"
def mk(rel, text):
    f = proj / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")
mk(".claude/skills/good/SKILL.md", "---\nname: good\ndescription: A fine skill.\n---\nbody")
mk("nodoc/SKILL.md", "---\nname: nodoc\n---\nbody")
mk("nofm/SKILL.md", "just text, no frontmatter")
mk("wrongcase/skill.md", "---\nname: wrongcase\ndescription: x\n---\n")
mk("notes/cmd.md", "---\nname: cmd\ndescription: a slash command\n---\n")
mk("notes/readme.md", "---\nname: readme\ndescription: ignored\n---\n")
mk("node_modules/dep/SKILL.md", "---\nname: ignored-dep\ndescription: x\n---\n")
mk("good2/SKILL.md", "---\nname: good2\ndescription: Has a nested example.\n---\n")
mk("good2/templates/inner/SKILL.md", "---\nname: inner-example\ndescription: should not count\n---\n")
mk("a/b/c/d/e/f/g/h/i/SKILL.md", "---\nname: too-deep\ndescription: x\n---\n")
(proj / "emptyfolder").mkdir()

st, r = call("POST", "/api/roots/add", {"path": str(proj)})
check("add folder without X-Atlas header rejected", st == 403)
st, r = call("POST", "/api/roots/add", {"path": str(proj)}, POST)
check("add folder succeeds and reports counts", st == 200 and r["skills"] == 4 and r["problems"] >= 4)
st, data = call("GET", "/api/skills")
names = {s["name"]: s for s in data["skills"]}
check("valid skills in custom folder listed", {"good", "nodoc", "nofm", "good2"} <= set(names))
check("skill without frontmatter listed by folder name", names["nofm"]["source"] == "Custom")
check("node_modules, nested examples and too-deep folders ignored", not ({"ignored-dep", "inner-example", "too-deep"} & set(names)))
check("wrong-case skill.md not treated as a skill", "wrongcase" not in names and "cmd" not in names)
src = next(s for s in data["sources"] if s["kind"] == "custom")
reasons = {(p["path"].replace("\\", "/"), p["level"]) for p in src["problems"]}
check("sources lists why things were skipped", ("wrongcase/skill.md", "skipped") in reasons and ("notes/cmd.md", "skipped") in reasons
      and ("emptyfolder", "skipped") in reasons and ("nofm/SKILL.md", "warning") in reasons and ("nodoc/SKILL.md", "warning") in reasons)
check("readme.md never reported", not any("readme" in p["path"] for p in src["problems"]))
check("custom folder is removable-from-list", src["removable"] and src["count"] == 4)
check("config persisted", json.loads((tmp / "skill-atlas.json").read_text())["roots"] == [str(proj.resolve())])

for bad, why in [(str(tmp / "nope"), "missing folder"), (str(secret), "file not folder"), (tmp.anchor, "drive root"),
                 (str(proj), "duplicate"), (str(sk), "personal folder"), (str(sk / "alpha"), "inside personal folder"), ("", "empty")]:
    st, _ = call("POST", "/api/roots/add", {"path": bad}, POST)
    check(f"add rejected: {why}", st == 400)

good = names["good"]
st, f = call("GET", f"/api/file?id={good['id']}&path=SKILL.md")
st, _ = call("POST", "/api/save", {"id": good["id"], "path": "SKILL.md", "content": "---\nname: good\ndescription: Edited in custom.\n---\n", "mtime": f["mtime"]}, POST)
check("custom folder skills are editable", st == 200 and "Edited in custom" in (proj / ".claude/skills/good/SKILL.md").read_text())
st, _ = call("POST", "/api/remove", {"id": good["id"]}, POST)
check("custom folder skills are not removable via Trash", st == 400 and (proj / ".claude/skills/good/SKILL.md").exists())

st, _ = call("POST", "/api/roots/remove", {"path": str(tmp / "never-added")}, POST)
check("removing an unknown folder -> 400", st == 400)
st, _ = call("POST", "/api/roots/remove", {"path": str(proj.resolve())}, POST)
st2, data = call("GET", "/api/skills")
check("removing a folder drops its skills but leaves files", st == 200 and "good" not in {s["name"] for s in data["skills"]} and (proj / "good2/SKILL.md").exists())

# ---- custom categories ----
st, data = call("GET", "/api/skills")
alpha_s = next(s for s in data["skills"] if s["name"] == "alpha")
check("skills expose auto category and override flag", alpha_s["auto_domain"] == alpha_s["domain"] and alpha_s["overridden"] is False)
st, _ = call("POST", "/api/category", {"skill": "alpha", "domain": "Client work"})
check("category change without X-Atlas header rejected", st == 403)
st, _ = call("POST", "/api/roots/add", {"path": str(proj)}, POST)
st, _ = call("POST", "/api/category", {"skill": "alpha", "domain": "  Client   work  "}, POST)
st, data = call("GET", "/api/skills")
alpha_s = next(s for s in data["skills"] if s["name"] == "alpha")
check("moving a skill to a new category creates it (whitespace tidied)", st == 200 and alpha_s["domain"] == "Client work" and alpha_s["overridden"]
      and any(d["name"] == "Client work" and d.get("custom") for d in data["domains"]))
check("original automatic category is remembered", alpha_s["auto_domain"] != "Client work")
check("category change does not clobber added folders", json.loads((tmp / "skill-atlas.json").read_text())["roots"] == [str(proj.resolve())])
check("category change leaves the skill file alone", "Edited!" in (sk / "alpha" / "SKILL.md").read_text(encoding="utf-8"))

st, _ = call("POST", "/api/category", {"skill": "p1", "domain": "Client work"}, POST)
st2, data = call("GET", "/api/skills")
check("plugin skills can be re-categorised too", st == 200 and next(s for s in data["skills"] if s["name"] == "p1")["domain"] == "Client work")
st, _ = call("POST", "/api/category", {"skill": "", "domain": "X"}, POST)
check("empty skill name rejected", st == 400)
st, _ = call("POST", "/api/category/add", {"name": "   "}, POST)
check("blank category name rejected", st == 400)
st, _ = call("POST", "/api/category/add", {"name": "Z" * 100}, POST)
st2, data = call("GET", "/api/skills")
check("category names capped at 40 chars", st == 200 and any(d["name"] == "Z" * 40 for d in data["domains"]))
st, _ = call("POST", "/api/category/add", {"name": "Design & UI"}, POST)
st2, data = call("GET", "/api/skills")
check("re-adding a built-in category is a no-op", sum(d["name"] == "Design & UI" for d in data["domains"]) == 1)
st, _ = call("POST", "/api/category/delete", {"name": "Design & UI"}, POST)
check("built-in categories cannot be deleted", st == 400)

st, _ = call("POST", "/api/category", {"skill": "alpha", "domain": ""}, POST)
st2, data = call("GET", "/api/skills")
alpha_s = next(s for s in data["skills"] if s["name"] == "alpha")
check("empty category resets a skill to automatic", st == 200 and not alpha_s["overridden"] and alpha_s["domain"] == alpha_s["auto_domain"])
st, r = call("POST", "/api/category/assign", {"domain": "Client work", "skills": ["alpha", "nested", "p1"]}, POST)
st2, data = call("GET", "/api/skills")
inside = [s["name"] for s in data["skills"] if s["domain"] == "Client work"]
check("assigning several existing skills puts them all in the category", st == 200 and r["count"] == 3 and sorted(inside) == ["alpha", "nested", "p1"])
check("a skill lives in only one category (gone from its old one)", all(s["auto_domain"] != "Client work" for s in data["skills"] if s["name"] in inside)
      and sum(1 for s in data["skills"] if s["name"] == "alpha") == 1)
check("assigning moves no files", (sk / "alpha" / "SKILL.md").exists() and (sk / "grp" / "nested" / "SKILL.md").exists() and (plug / "SKILL.md").exists())
st, _ = call("POST", "/api/category/assign", {"domain": "Client work", "skills": []}, POST)
check("assigning nothing rejected", st == 400)
st, _ = call("POST", "/api/category/assign", {"domain": "Client work", "skills": "alpha"}, POST)
check("assign needs a list", st == 400)
st, _ = call("POST", "/api/category/assign", {"domain": "", "skills": ["alpha"]}, POST)
check("assign needs a category name", st == 400)
st, _ = call("POST", "/api/category/assign", {"domain": "Client work", "skills": ["alpha"]})
check("assign without X-Atlas header rejected", st == 403)
st, _ = call("POST", "/api/category/delete", {"name": "Client work"}, POST)
st2, data = call("GET", "/api/skills")
check("deleting a category returns its skills to automatic", st == 200 and next(s for s in data["skills"] if s["name"] == "p1")["overridden"] is False
      and not any(d["name"] == "Client work" for d in data["domains"]))
st, _ = call("POST", "/api/category/delete", {"name": "Client work"}, POST)
check("deleting a missing category -> 400", st == 400)
check("payload exposes where Atlas stores its files", set(data["paths"]) == {"settings", "trash", "history", "skills"})
call("POST", "/api/roots/remove", {"path": str(proj.resolve())}, POST)

(tmp / "skill-atlas.json").write_text("{ this is not json", encoding="utf-8")
st, data = call("GET", "/api/skills")
check("corrupt config file does not crash", st == 200 and data["skills"])

# ---- command line ----
out_file = tmp / "export.html"
rc = server.main(["--export", str(out_file)])
html = out_file.read_text(encoding="utf-8")
check("--export writes a self-contained read-only copy", rc == 0 and '"static": true' in html and '"alpha"' in html and "null/*DATA*/" not in html)
check("served page has the data placeholder for export", "null/*DATA*/" in (server.HERE / "index.html").read_text(encoding="utf-8"))
check("starting on a busy port exits cleanly", server.main(["--port", str(port), "--no-browser"]) == 1)
check("version string is set", __version__.count(".") == 2)

print("\n%d failed" % len(fails) if fails else "\nALL PASSED")
sys.exit(1 if fails else 0)
