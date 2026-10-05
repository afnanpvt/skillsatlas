<p align="center">
  <img src="assets/logo/skillsatlas-icon.svg" width="112" alt="Skill Atlas logo">
</p>

<h1 align="center">Skill Atlas</h1>

<p align="center"><b>Find the skill you forgot you had.</b></p>

<p align="center">
  <a href="LICENSE"><img alt="MIT license" src="https://img.shields.io/badge/license-MIT-0A84FF"></a>
  <img alt="Python 3.9+" src="https://img.shields.io/badge/python-3.9%2B-0A84FF">
  <img alt="No dependencies" src="https://img.shields.io/badge/dependencies-none-0A84FF">
  <a href="https://github.com/afnanpvt/skillsatlas/actions/workflows/test.yml"><img alt="tests" src="https://github.com/afnanpvt/skillsatlas/actions/workflows/test.yml/badge.svg"></a>
</p>

<p align="center">
  <img src="assets/screenshots/search-dark.png" alt="Skill Atlas searching for 'design a screen'" width="900">
</p>

## Why this exists

You write a great Claude Code skill. Two months later you are doing that exact job by hand, because you forgot the skill was ever there.

That is the whole problem, and Skill Atlas is the whole fix. It looks at every skill on your machine, sorts them into clear categories, and lets you search the way you actually think: not "what was that skill called?" but "I'm about to design a screen."

It runs on your computer, reads your own folders, and never phones home.

## What you get

- **Search by the job, not the name.** Type "fix a bug", "make a promo video" or "design an architecture" and the right skills come up first, with the reason they matched. It understands that "screen" and "interface" mean the same thing.
- **Everything sorted for you.** Skills land in categories like Design, Motion and Video, Engineering, Docs, and Business Ops. Don't like where one went? Make your own categories and move skills into them. Nothing on disk changes.
- **Read and edit in place.** Open any skill, see its full text and every file in its folder, change it and save. Your old version is kept every time.
- **Know what is and isn't a skill.** A skill is a folder with a `SKILL.md`. The Atlas tells you when something is missing a description, or looks like a skill but isn't one, and says why.
- **Bring every folder.** Point it at any folder on your machine, such as a project's `.claude/skills`, and those skills join the library.
- **Safe by default.** Removing a skill moves it to Trash and you can undo it. Saving keeps the previous version. The Atlas never deletes your work.
- **Yours to style.** Light, dark or system. Pick an accent colour and a card size. Put your name on it.

<p align="center">
  <img src="assets/screenshots/home-light.png" alt="The library in light mode" width="440">
  <img src="assets/screenshots/settings-light.png" alt="Settings: theme, accent and categories" width="440">
</p>

## Install

You need Python 3.9 or newer. There is nothing else to install; Skill Atlas has no dependencies.

**The easy way (recommended)** uses [pipx](https://pipx.pypa.io), which keeps it tidy and gives you a `skillsatlas` command anywhere:

```bash
pipx install git+https://github.com/afnanpvt/skillsatlas.git
skillsatlas
```

**With pip:**

```bash
pip install git+https://github.com/afnanpvt/skillsatlas.git
skillsatlas
```

**From source, no install at all:**

```bash
git clone https://github.com/afnanpvt/skillsatlas.git
cd skillsatlas
python -m skillsatlas
```

Your browser opens at <http://localhost:4747>. That is it.

To update, run `pipx upgrade skillsatlas`. To remove it, run `pipx uninstall skillsatlas`. Your settings live in one small file, `~/.claude/skill-atlas.json`, which you can delete if you want a clean slate.

### Command line options

| Command | What it does |
|---|---|
| `skillsatlas` | Start the Atlas and open it in your browser |
| `skillsatlas --port 5000` | Use a different port (default 4747) |
| `skillsatlas --no-browser` | Start without opening a browser tab |
| `skillsatlas --export atlas.html` | Write a read-only copy you can share with your team |
| `skillsatlas --version` | Show the version |
