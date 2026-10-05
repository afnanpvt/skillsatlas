"""Find every installed skill, categorise it, write a plain-English summary."""
import os, re, json, time, hashlib, pathlib, datetime
from . import __version__

HOME = pathlib.Path(os.environ.get("ATLAS_HOME") or pathlib.Path.home() / ".claude")
SKILLS = HOME / "skills"
HERE = pathlib.Path(__file__).parent

DOMAINS = {
  "Design & UI":         ("Taste, systems, critique and polish for interfaces", r"design|ui|ux|taste|brand|brandkit|minimal|brutal|redesign|impeccable|stitch|frontend|figma|theme|image-to-code|imagegen|vengeance|md|media-use|banner|gpt-taste|full-output-enforcement"),
  "Motion & Video":      ("Animation, transitions and launch videos", r"hyperframes|onetake|brag|gsap|transitions?|keyframes?|animation|motion|video"),
  "Platform Guidelines": ("Apple, Android and spatial HIG rules", r"(?:ios|ipados|macos|tvos|watchos|visionos|android)-design-guidelines"),
  "Frontend Engineering":("React, cloning, building web UIs", r"react|clone|nextjs|web|archify|diagram|website"),
  "Project Workflow":    ("GSD phases, planning and shipping", r"gsd"),
  "Engineering Practice":("Debugging, review, testing, planning", r"superpowers|debug|review|testing|architecture|deploy|worktree|simplify|security|commit|pr-review|feature-dev|ponytail|pathfinder"),
  "Knowledge & Meta":    ("Graphs, memory, skill authoring, setup", r"graph|graphify|task-observer|skills?|memory|init|learn|claude-md|find-skills|setup|schedule|loop"),
  "Docs & Files":        ("PDF, Word, Excel, slides, docs", r"pdf|docx|xlsx|pptx|docs|document|google-workspace|slides|wowerpoint"),
  "Browser & Automation":("Drive browsers and run apps", r"agent-browser|browser|run"),
  "Data & Backend":      ("Databases and backend platforms", r"supabase|postgres|database|dataviz|chart|xlsx"),
  "Business Ops":       ("Sales, marketing, legal, productivity, Jira", r"sales|marketing|legal|productivity|atlassian|jira|confluence|standup"),
}
ORDER = list(DOMAINS)
CHECK = ["Platform Guidelines", "Project Workflow", "Motion & Video", "Docs & Files", "Data & Backend",
         "Business Ops", "Browser & Automation", "Engineering Practice", "Frontend Engineering",
         "Knowledge & Meta", "Design & UI"]


CONFIG = HOME / "skill-atlas.json"  # folders the user added from the UI
IGNORE = {"node_modules", "__pycache__", "venv", "dist", "build", "graphify-out"}
DOT_OK = {".claude", ".agents", ".codex", ".cursor", ".github"}  # hidden folders that commonly hold skills
MAX_DEPTH, MAX_DIRS, MAX_REPORT = 8, 20000, 40


def read_cfg():
    """The settings file: {roots: [...], categories: [...], overrides: {skill name: category}}. Tolerates a missing or corrupt file."""
    try:
        raw = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    raw = raw if isinstance(raw, dict) else {}
    cats = [c for c in raw.get("categories", []) if isinstance(c, str)]
    ov = raw.get("overrides", {})
    return dict(roots=[r for r in raw.get("roots", []) if isinstance(r, str)], categories=cats,
                overrides={k: v for k, v in ov.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(ov, dict) else {})


def write_cfg(cfg):
    tmp = CONFIG.with_name(CONFIG.name + ".tmp")
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    os.replace(tmp, CONFIG)


def load_roots():
    return read_cfg()["roots"]


def save_roots(roots):
    cfg = read_cfg()
    cfg["roots"] = roots
    write_cfg(cfg)


def add_category(name):
    name = " ".join(str(name).split())[:40]
    if not name:
        raise ValueError("Give the category a name.")
    cfg = read_cfg()
    if name not in ORDER and name not in cfg["categories"]:
        cfg["categories"].append(name)
        write_cfg(cfg)
        invalidate()
    return name


def set_category(skill, domain):
    """Move one skill (by name) into a category, creating the category if it's new. Empty domain = back to automatic."""
    skill = str(skill)
    if not skill or len(skill) > 200:
        raise ValueError("Unknown skill.")
    domain = " ".join(str(domain).split())[:40]
    if domain:
        add_category(domain)
    cfg = read_cfg()
    if domain:
        cfg["overrides"][skill] = domain
    else:
        cfg["overrides"].pop(skill, None)
    write_cfg(cfg)
    invalidate()


def assign_category(domain, skills):
    """Put several existing skills into one category in a single write. Metadata only: no skill file is touched."""
    if not isinstance(skills, list) or not skills or len(skills) > 500:
        raise ValueError("Pick at least one skill.")
    names = [s for s in skills if isinstance(s, str) and 0 < len(s) <= 200]
    domain = add_category(domain)
    cfg = read_cfg()
    for n in names:
        cfg["overrides"][n] = domain
    write_cfg(cfg)
    invalidate()
    return len(names)


def delete_category(name):
    cfg = read_cfg()
    if name not in cfg["categories"]:
        raise ValueError("Only categories you created can be deleted.")
    cfg["categories"].remove(name)
    cfg["overrides"] = {k: v for k, v in cfg["overrides"].items() if v != name}
    write_cfg(cfg)
    invalidate()


def extra_roots():
    """[(path, removable)]: folders added in the UI (removable) plus ATLAS_ROOTS entries (set outside the app)."""
    env = [r for r in os.environ.get("ATLAS_ROOTS", "").split(os.pathsep) if r.strip()]
    return [(pathlib.Path(r).expanduser(), True) for r in load_roots()] + [(pathlib.Path(r).expanduser(), False) for r in env]


def add_root(raw):
    raw = str(raw).strip().strip('"')
    if not raw:
        raise ValueError("Enter a folder path.")
    p = pathlib.Path(raw).expanduser()
    try:
        p = p.resolve()
    except OSError:
        raise ValueError("That path isn't valid.")
    if not p.is_dir():
        raise ValueError(f"Folder not found: {p}")
    if p.parent == p:
        raise ValueError("Pick a folder, not a drive root.")
    skills = SKILLS.resolve()
    if p == skills or skills in p.parents:
        raise ValueError("Your personal skills folder is already scanned.")
    roots = load_roots()
    if any(pathlib.Path(r) == p for r in roots):
        raise ValueError("That folder is already added.")
    save_roots(roots + [str(p)])
    invalidate()
    res = inspect(p)
    return {"skills": len(res["skills"]), "problems": len(res["problems"])}


def remove_root(raw):
    roots = load_roots()
    keep = [r for r in roots if r != str(raw)]
    if len(keep) == len(roots):
        raise ValueError("That folder isn't in your added list.")
    save_roots(keep)
    invalidate()


def inspect(root):
    """Walk `root` and sort what is in it: real skills, and things that look like skills but aren't (with the reason)."""
    out = dict(skills=[], problems=[], truncated=False)
    root, seen, skill_tops = pathlib.Path(root), 0, set()

    reported = set()  # top-level folders that already have a more specific note

    def problem(path, reason, level="skipped"):
        if path != root:
            reported.add(path.relative_to(root).parts[0])
        if len(out["problems"]) < MAX_REPORT:
            out["problems"].append(dict(path=str(path.relative_to(root)) if path != root else ".", reason=reason, level=level))
        else:
            out["more"] = out.get("more", 0) + 1

    for dirpath, dirs, files in os.walk(root):
        seen += 1
        here = pathlib.Path(dirpath)
        depth = len(here.relative_to(root).parts)
        if seen > MAX_DIRS:
            out["truncated"] = True
            break
        dirs[:] = sorted(d for d in dirs if d not in IGNORE and (not d.startswith(".") or d in DOT_OK))
        if "SKILL.md" in files:
            dirs[:] = []  # a skill folder is a leaf: its references/templates are not separate skills
            f = here / "SKILL.md"
            try:
                fm = parse(f)
            except OSError as e:
                problem(f, f"Can't read file ({e.strerror})")
                continue
            fm = fm or {}
            if not fm:
                problem(f, "No frontmatter. Listed by folder name, but Claude can't tell when to use it. Add a --- block with name: and description:", "warning")
            elif "name" not in fm:
                problem(f, "Frontmatter has no name:. Listed by folder name.", "warning")
            elif not fm.get("description"):
                problem(f, "Listed, but has no description:. Claude uses the description to decide when to load it.", "warning")
            fm.setdefault("name", here.name)
            out["skills"].append((f, fm))
            skill_tops.add(here.relative_to(root).parts[:1])
            continue
        for name in files:
            if name.lower() == "skill.md":
                problem(here / name, f"File is named {name}; it must be exactly SKILL.md")
            elif name.lower().endswith(".md") and name.lower() != "readme.md" and depth <= 2:
                try:
                    fm = parse(here / name)
                except OSError:
                    continue
                if fm and "name" in fm and "description" in fm:
                    problem(here / name, "Has skill-style frontmatter but isn't inside a folder as SKILL.md (a slash command or a loose note?)")
        if depth >= MAX_DEPTH:
            dirs[:] = []
    if not out["truncated"]:
        try:
            for child in sorted(root.iterdir()):
                if child.is_dir() and child.name not in IGNORE and not child.name.startswith(".") and (child.name,) not in skill_tops and child.name not in reported:
                    problem(child, "Folder contains no SKILL.md, so it isn't a skill")
        except OSError:
            pass
    return out


def parse(path):
    txt = path.read_text(encoding="utf-8", errors="ignore")
    m = re.match(r"---\s*\r?\n(.*?)\r?\n---", txt, re.S)
    if not m:
        return None
    lines, fm, i = m.group(1).splitlines(), {}, 0
    while i < len(lines):
        k = re.match(r"^([\w-]+):\s*(.*)$", lines[i])
        if k:
            key, val = k.group(1), k.group(2).strip()
            if val in (">", "|", ">-", "|-", ""):
                buf = []
                while i + 1 < len(lines) and (lines[i + 1].startswith((" ", "\t")) or not lines[i + 1].strip()):
                    i += 1
                    buf.append(lines[i].strip())
                val = " ".join(b for b in buf if b)
            fm[key] = val.strip("\"'")
        i += 1
    return fm


def categorise(name, plugin):
    if name.startswith("gsd-"):
        return "Project Workflow"
    if plugin == "claude-mem":
        return "Knowledge & Meta"
    hay = f"{plugin}:{name}".lower()
    for d in CHECK:
        if re.search(r"(?<![a-z])(" + DOMAINS[d][1] + r")(?![a-z])", hay):
            return d
    return "Knowledge & Meta"


def summarise(desc):
    clean = re.sub(r"\s+", " ", desc).strip()
    first = re.split(r"(?<=[.!?])\s", clean, maxsplit=1)[0]
    when = re.search(r"(?:use (?:this skill )?(?:when|whenever)|triggers? (?:on|when)|use for)\s*(.+?)(?:\.\s|$)", clean, re.I)
    short = first if len(first) <= 150 else first[:147].rsplit(" ", 1)[0] + "..."
    return short, (when.group(1)[:200] if when else "")


_cache = {"t": 0.0, "v": None}


def invalidate():
    _cache["v"] = None


def snapshot(ttl=2.0):
    """(skills, sources) computed together and cached briefly so one page load doesn't rescan the disk repeatedly."""
    if _cache["v"] is None or time.time() - _cache["t"] > ttl:
        _cache["v"] = build()
        _cache["t"] = time.time()
    return _cache["v"]


def build():
    """Scan every source once. Returns (deduped skills, per-folder source report)."""
    found, report, uniq = {}, [], {}

    def add(path, fm, source, plugin, root_label):
        name, mt = fm["name"], path.stat().st_mtime
        key = (plugin, name)
        uniq.setdefault(root_label, set()).add(key)
        if key in found and found[key]["_mt"] >= mt:
            return
        desc = fm.get("description", "")
        summary, when = summarise(desc)
        found[key] = dict(
            id=hashlib.sha1(str(path).encode()).hexdigest()[:10], name=name, plugin=plugin, source=source,
            desc=desc, summary=summary, when=when,
            invoke=f"/{plugin + ':' if plugin else ''}{name}", domain=categorise(name, plugin),
            updated=datetime.date.fromtimestamp(mt).isoformat(), root=root_label,
            editable=source != "Plugin",
            removable=source == "Personal" and SKILLS.resolve() in path.resolve().parents,
            _mt=mt, _path=path)

    def report_for(label, path, kind, note, res, removable=False):
        report.append(dict(
            label=label, path=str(path), exists=pathlib.Path(path).exists(), kind=kind, note=note, removable=removable,
            count=len(uniq.get(label, ())), problems=res["problems"], more=res.get("more", 0), truncated=res["truncated"]))

    empty = dict(skills=[], problems=[], truncated=False)
    personal = inspect(SKILLS) if SKILLS.exists() else empty
    for p, fm in personal["skills"]:
        rel = p.relative_to(SKILLS).parts
        pl = rel[0] if len(rel) > 2 else ""
        add(p, fm, "Personal", "anthropic-skills" if pl == "synced" else pl, "Personal skills")
    report_for("Personal skills", SKILLS, "personal", "Your own skills. Editable and removable.", personal)

    cache = HOME / "plugins" / "cache"
    for p in (cache.rglob("SKILL.md") if cache.exists() else []):
        fm = parse(p)
        if fm and "name" in fm:
            rel = p.relative_to(cache).parts
            add(p, fm, "Plugin", rel[1] if len(rel) > 3 else "", "Plugin cache")
    report_for("Plugin cache", cache, "plugin", "Installed by plugins. Read-only here: plugin updates overwrite edits.", empty)

    for root, removable in extra_roots():
        label = f"Custom: {root}"
        res = inspect(root) if root.is_dir() else empty
        for p, fm in res["skills"]:
            add(p, fm, "Custom", "", label)
        note = ("Added by you. Editable. Removing it from the list never touches the files." if removable
                else "Set through the ATLAS_ROOTS environment variable. Editable.")
        report_for(label, root, "custom" if removable else "env", note, res, removable)

    rank = {"Personal": 0, "Custom": 1, "Plugin": 2}
    by_name = {}
    for s in sorted(found.values(), key=lambda s: (rank[s["source"]], s["plugin"])):
        if s["name"] in by_name:
            by_name[s["name"]].setdefault("also", []).append(s["invoke"])  # same skill installed several ways -> one card
        else:
            by_name[s["name"]] = s
    cfg = read_cfg()
    every = ORDER + [c for c in cfg["categories"] if c not in ORDER]
    for s in by_name.values():  # the user's own category choice beats the automatic one
        s["auto_domain"], mine = s["domain"], cfg["overrides"].get(s["name"])
        s["overridden"] = mine in every
        if s["overridden"]:
            s["domain"] = mine
    skills = sorted(by_name.values(), key=lambda s: (every.index(s["domain"]), s["name"]))
    return skills, report


def scan():
    return snapshot()[0]


def sources():
    return snapshot()[1]


def public(s):
    return {k: v for k, v in s.items() if not k.startswith("_")}


def payload():
    domains = [dict(name=d, blurb=DOMAINS[d][0]) for d in ORDER]
    domains += [dict(name=c, blurb="A category you created", custom=True) for c in read_cfg()["categories"] if c not in ORDER]
    paths = dict(settings=str(CONFIG), trash=str(HOME / "skills-trash"), history=str(HOME / "skills-history"), skills=str(SKILLS))
    return dict(version=__version__, domains=domains, skills=[public(s) for s in scan()], sources=sources(), paths=paths)
