#!/usr/bin/env python3
"""
Bug Notes Assistant — Hybrid (GUI by default, CLI with --cli)
- Windows & macOS
- GUI: Tkinter wizard + tabs (Header / Issues found / Bugs / Bugs written copier)
- CLI: setup/new-or-existing, Notes mode, Bugs mode
"""
import sys
import re
import hashlib
from pathlib import Path
from datetime import datetime
import argparse

# ----------------- Optional GUI imports (only when needed) -----------------
TK_AVAILABLE = True
try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    import subprocess
except Exception:
    TK_AVAILABLE = False

# ----------------- Config -----------------
GEN4_PLATFORMS = {"nx1", "ps4", "xb1"}
GEN5_PLATFORMS = {"nx2", "pc", "xbx", "ps5"}
ALL_PLATFORMS  = sorted(GEN4_PLATFORMS | GEN5_PLATFORMS)

BUGS_HEADERS     = [r"#\s*bugs\s*$", r"#\s*bugs\s*🐛\s*$"]
REPORTS_HEADERS  = [r"#\s*reports\s+written\s*📝\s*$", r"#\s*reports\s+written\s*$"]
ISSUES_HEADERS   = [r"#\s*issues\s+found\s*🕵️‍♂️\s*$", r"#\s*issues\s+found\s*$"]

# ----------------- Shared helpers -----------------
def classify_platform(p: str):
    p = (p or "").lower()
    if p in GEN4_PLATFORMS: return "gen4"
    if p in GEN5_PLATFORMS: return "gen5"
    return None

def _find_section_start(lines, header_patterns):
    for i, line in enumerate(lines):
        for pat in header_patterns:
            if re.match(pat, line.strip(), re.IGNORECASE):
                return i
    return None

def _section_bounds(lines, header_patterns):
    """Return (content_start, content_end_exclusive) for a section (after header + optional ---)."""
    header_idx = _find_section_start(lines, header_patterns)
    if header_idx is None:
        return None
    start = header_idx + 1
    if start < len(lines) and lines[start].strip() == "---":
        start += 1
    end = len(lines)
    for j in range(start, len(lines)):
        if re.match(r"^#\s+", lines[j]):
            end = j
            break
    return (start, end)

def find_or_create_sections(text: str) -> str:
    lines = text.splitlines()
    changed = False

    if _section_bounds(lines, ISSUES_HEADERS) is None:
        insert_at = len(lines)
        if lines and lines[0].startswith("# "):
            idx = 1
            if idx < len(lines) and lines[idx].strip() == "---":
                idx += 1
            while idx < len(lines) and lines[idx].strip() != "":
                idx += 1
            if idx < len(lines) and lines[idx].strip() == "":
                idx += 1
            insert_at = idx
        block = ["# issues found 🕵️‍♂️", "---", ""]
        lines[insert_at:insert_at] = block
        changed = True

    if _section_bounds(lines, REPORTS_HEADERS) is None:
        ib = _section_bounds(lines, ISSUES_HEADERS)
        insert_at = ib[1] if ib else len(lines)
        block = ["# reports written 📝", "---", ""]
        lines[insert_at:insert_at] = block
        changed = True

    if _section_bounds(lines, BUGS_HEADERS) is None:
        rb = _section_bounds(lines, REPORTS_HEADERS)
        insert_at = rb[1] if rb else len(lines)
        block = ["# bugs 🐛", "---", ""]
        lines[insert_at:insert_at] = block
        changed = True

    out = "\n".join(lines)
    if changed and not out.endswith("\n"):
        out += "\n"
    return out if changed else text

def normalize_time_12h(t: str) -> str:
    t = (t or "").strip()
    if not t:
        return datetime.now().strftime("%I:%M %p")
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*([AaPp][Mm])?\s*", t)
    if m:
        hh, mm, ampm = m.group(1), m.group(2), m.group(3)
        return f"{int(hh):02d}:{mm} {ampm.upper()}" if ampm else f"{int(hh):02d}:{mm}"
    return datetime.now().strftime("%I:%M %p")

def parse_usernames(text: str):
    usernames = {}
    for m in re.finditer(r"^- \[([a-z0-9]+)\]\[([^\]]+)\]\s*$", text, re.MULTILINE | re.IGNORECASE):
        key = m.group(1).lower()
        val = m.group(2).strip()
        if key in {"gen4","gen5"} and re.fullmatch(r"\d+", val):
            continue
        if key in ALL_PLATFORMS:
            usernames[key] = val
    return usernames

def parse_builds(text: str):
    gen4 = ""
    gen5 = ""
    for m in re.finditer(r"^- \[(gen4|gen5)\]\[(\d+)\]\s*-->\s*build number\s*$", text, re.IGNORECASE|re.MULTILINE):
        if m.group(1).lower() == "gen4": gen4 = m.group(2)
        else: gen5 = m.group(2)
    return gen4, gen5

def header_only_block(date_str: str, usernames: dict, gen4_build: str, gen5_build: str) -> str:
    lines = [f"# {date_str} notes", "---"]
    for p in sorted(ALL_PLATFORMS):
        if p in usernames and usernames[p]:
            lines.append(f"- [{p}][{usernames[p]}]")
    if gen4_build.strip().isdigit():
        lines.append(f"- [gen4][{gen4_build.strip()}] --> build number")
    if gen5_build.strip().isdigit():
        lines.append(f"- [gen5][{gen5_build.strip()}] --> build number")
    lines.append("")
    out = "\n".join(lines)
    if not out.endswith("\n"): out += "\n"
    return out

def parse_date_and_header_end(text: str):
    lines = text.splitlines()
    date_str = ""
    if lines and lines[0].startswith("# "):
        date_str = lines[0][2:].strip().replace(" notes","")
    idx = 1
    if idx < len(lines) and lines[idx].strip() == "---":
        idx += 1
    while idx < len(lines) and lines[idx].strip() != "":
        idx += 1
    if idx < len(lines) and lines[idx].strip() == "":
        idx += 1
    return date_str, idx

def replace_header(text: str, usernames: dict, gen4_build: str, gen5_build: str) -> str:
    date_str, hdr_end = parse_date_and_header_end(text)
    new_header = header_only_block(date_str or datetime.now().strftime("%m-%d-%Y"),
                                   usernames, gen4_build, gen5_build)
    rest = "\n".join(text.splitlines()[hdr_end:])
    out = new_header + rest
    out = find_or_create_sections(out)
    return out

def header_block(date_str: str, usernames: dict, gen4_build: str, gen5_build: str) -> str:
    lines = []
    lines.append(f"# {date_str} notes")
    lines.append("---")
    for p in sorted(ALL_PLATFORMS):
        if p in usernames and usernames[p]:
            lines.append(f"- [{p}][{usernames[p]}]")
    if gen4_build.strip().isdigit():
        lines.append(f"- [gen4][{gen4_build.strip()}] --> build number")
    if gen5_build.strip().isdigit():
        lines.append(f"- [gen5][{gen5_build.strip()}] --> build number")
    lines.append("")
    lines += ["# issues found 🕵️‍♂️", "---", ""]
    lines += ["# reports written 📝", "---", ""]
    lines += ["# bugs 🐛", "---", ""]
    out = "\n".join(lines)
    if not out.endswith("\n"):
        out += "\n"
    return out

def extract_issues_region(text: str) -> str:
    lines = text.splitlines()
    b = _section_bounds(lines, ISSUES_HEADERS)
    if not b: return ""
    start, end = b
    return "\n".join(lines[start:end])

def issues_list(text: str):
    region = extract_issues_region(text)
    events = []
    pattern = re.compile(r"^- \[(\d{1,2}:\d{2}(?:\s?[AaPp][Mm])?)\]\[([a-z0-9]+)\]\s+(.*)$", re.MULTILINE)
    for m in pattern.finditer(region):
        events.append({"time": m.group(1).strip(), "platform": m.group(2).lower(), "desc": m.group(3).strip()})
    return events

def add_issue_line(text: str, time_str: str, platform: str, desc: str) -> str:
    text = find_or_create_sections(text)
    lines = text.splitlines()
    ib = _section_bounds(lines, ISSUES_HEADERS)
    if not ib:
        text = find_or_create_sections(text)
        lines = text.splitlines()
        ib = _section_bounds(lines, ISSUES_HEADERS)
    start, end = ib
    newline = f"- [{normalize_time_12h(time_str)}][{platform.lower()}] {desc.strip()}"
    lines[end:end] = [newline]
    out = "\n".join(lines)
    if not out.endswith("\n"):
        out += "\n"
    return out

def build_steps_block(template_key: str, mode: str, extra_lines: list):
    if mode == "default":
        base2 = "2. Enter the City." if template_key == "gen5" else "2. Enter the Neighborhood."
        lines = [
            "Steps to Reproduce:",
            "1. Launch the title > create or select build / save.",
            base2
        ]
        n = 3
        for ln in extra_lines or []:
            ln = ln.strip()
            if ln:
                lines.append(f"{n}. {ln}")
                n += 1
        if n == 3:
            lines.append("3. ")
        return "\n".join(lines)
    else:
        lines = ["Steps to Reproduce:"]
        n = 1
        for ln in extra_lines or []:
            ln = ln.strip()
            if ln:
                lines.append(f"{n}. {ln}")
                n += 1
        if n == 1:
            lines.append("1. ")
        return "\n".join(lines)

def make_bug_block(summary: str, platform: str, username: str,
                   steps_block: str, observed: str, expected: str) -> str:
    tmpl = """## [null]
---
**summary:** {summary}

**Platform:** {platform}
**Username:** {username}

{steps_block}

Observed Results:
{observed}

Expected Results:
{expected}
"""
    return tmpl.format(summary=summary, platform=platform, username=username,
                       steps_block=steps_block, observed=observed, expected=expected)

def generate_event_id(ev: dict) -> str:
    raw = f"{ev['time']}|{ev['platform']}|{ev['desc']}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:12]

def append_bug_and_move_issue(text: str, ev: dict, summary_prefix: str,
                              steps_mode: str, extra_steps: list,
                              observed: str, expected: str) -> str:
    text = find_or_create_sections(text)
    lines = text.splitlines()

    ib = _section_bounds(lines, ISSUES_HEADERS)
    rb = _section_bounds(lines, REPORTS_HEADERS)
    bb = _section_bounds(lines, BUGS_HEADERS)
    if not (ib and rb and bb):
        text = find_or_create_sections(text)
        lines = text.splitlines()
        ib = _section_bounds(lines, ISSUES_HEADERS)
        rb = _section_bounds(lines, REPORTS_HEADERS)
        bb = _section_bounds(lines, BUGS_HEADERS)

    ev_id = generate_event_id(ev)
    if f"<!-- bug-id:{ev_id}" in text:
        return text  # already added

    template_key = classify_platform(ev["platform"]) or "gen5"
    usernames = parse_usernames(text)
    username = usernames.get(ev["platform"], "")

    summary = f"{summary_prefix}: {ev['desc']}" if summary_prefix else ev['desc']
    steps_block = build_steps_block(template_key, steps_mode, extra_steps)

    bug_block = make_bug_block(summary, ev["platform"], username, steps_block,
                               observed or "", expected or "")
    meta = f"<!-- bug-id:{ev_id} time={ev['time']} platform={ev['platform']} template={template_key} -->"

    # Append to Bugs
    bstart, bend = bb
    lines[bend:bend] = ["", meta, bug_block.strip(), ""]

    # Remove issue from Issues, append to Reports
    istart, iend = ib
    issue_line = f"- [{ev['time']}][{ev['platform']}] {ev['desc']}"
    removed = False
    for i in range(istart, iend):
        if lines[i].strip() == issue_line:
            del lines[i]
            removed = True
            break
    if not removed:
        pref = re.compile(rf"^- \[{re.escape(ev['time'])}\]\[{re.escape(ev['platform'])}\]\s+")
        for i in range(istart, iend):
            if pref.match(lines[i]):
                issue_line = lines[i].strip()
                del lines[i]
                removed = True
                break

    rstart, rend = _section_bounds(lines, REPORTS_HEADERS)
    lines[rend:rend] = [issue_line]

    out = "\n".join(lines)
    if not out.endswith("\n"):
        out += "\n"
    return out

# -------- Parse bugs from the Bugs section (for GUI copier) --------
BUG_META_RE = re.compile(r"<!--\s*bug-id:([a-f0-9]{6,})\s+time=([^\s]+(?:\s[AP]M)?)\s+platform=([a-z0-9]+)\s+template=(gen4|gen5)\s*-->")

def list_bugs(text: str):
    """Parse the Bugs section into structured fields with line-accurate extraction."""
    lines = text.splitlines()
    bounds = _section_bounds(lines, BUGS_HEADERS)
    if not bounds:
        return []
    start, end = bounds
    section = "\n".join(lines[start:end])

    def grab_line(block: str, label: str) -> str:
        pat = rf"(?mi)^\*\*{re.escape(label)}:\*\*\s*(.*)$"
        m = re.search(pat, block)
        return m.group(1).strip() if m else ""

    def grab_block_between(block: str, start_label: str, end_label: str) -> str:
        sp = rf"(?mi)^{re.escape(start_label)}:\s*\n"
        ep = rf"(?mi)^{re.escape(end_label)}:\s*"
        m1 = re.search(sp, block)
        if not m1:
            return ""
        sub = block[m1.start():]
        m2 = re.search(ep, sub)
        return sub[:m2.start()].rstrip() if m2 else sub.rstrip()

    def grab_after(block: str, start_label: str) -> str:
        sp = rf"(?mi)^{re.escape(start_label)}:\s*\n"
        m1 = re.search(sp, block)
        return block[m1.end():].strip() if m1 else ""

    bugs = []
    matches = list(BUG_META_RE.finditer(section))
    for i, m in enumerate(matches):
        bstart = m.end()
        bend = matches[i+1].start() if i+1 < len(matches) else len(section)
        block = section[bstart:bend]

        summary   = grab_line(block, "summary")
        platform  = grab_line(block, "Platform")
        username  = grab_line(block, "Username")

        steps     = grab_block_between(block, "Steps to Reproduce", "Observed Results")
        observed  = grab_block_between(block, "Observed Results", "Expected Results")
        expected  = grab_after(block, "Expected Results")

        bugs.append({
            "id": m.group(1),
            "time": m.group(2),
            "platform": m.group(3).lower(),
            "template": m.group(4),
            "summary": (summary or "").strip(),
            "username": (username or "").strip(),
            "steps": (steps or "").strip(),
            "observed": (observed or "").strip(),
            "expected": (expected or "").strip(),
            "raw": block.strip()
        })
    return bugs

# ============================== CLI MODE ==============================
def prompt(msg, default=None):
    sfx = f" [{default}]" if default is not None else ""
    resp = input(f"{msg}{sfx}: ").strip()
    return resp if resp else (default if default is not None else "")

def choose_platform_cli():
    options = list(ALL_PLATFORMS)
    print("\nChoose platform:")
    for idx, p in enumerate(options, 1):
        print(f"  {idx}) {p}")
    while True:
        sel = input("Enter number: ").strip()
        if sel.isdigit() and 1 <= int(sel) <= len(options):
            return options[int(sel)-1]
        print("Invalid selection.")

def cli_setup_or_open():
    today = datetime.now().strftime("%m-%d-%Y")
    date_str = prompt("Notes date (mm-dd-yyyy)", today)
    fname = f"{date_str}-notes.md"

    existing = Path(fname).exists()
    print(f"\nFile for {date_str}: {fname}")
    if existing:
        print("Found existing file. Continue using it.")
        path = Path(fname).resolve()
        txt = path.read_text(encoding="utf-8")
        updated = find_or_create_sections(txt)
        if updated != txt:
            path.write_text(updated, encoding="utf-8")
        return path

    print("No file found. Creating a new one…")
    usernames = {}
    print("Enter usernames (optional, leave blank to skip):")
    for p in ALL_PLATFORMS:
        v = input(f"  {p}: ").strip()
        if v:
            usernames[p] = v
    gen4 = input("gen4 build (digits, optional): ").strip()
    gen5 = input("gen5 build (digits, optional): ").strip()
    text = header_block(date_str, usernames, gen4, gen5)
    Path(fname).write_text(text, encoding="utf-8")
    return Path(fname).resolve()

def cli_notes_mode(path: Path):
    print("\n== Notes Mode ==")
    while True:
        desc = input("Short description (leave blank to stop): ").strip()
        if not desc:
            break
        platform = choose_platform_cli()
        time_in = input("Time (hh:mm [AM/PM], optional; blank = now): ").strip()
        try:
            txt = path.read_text(encoding="utf-8")
            new_txt = add_issue_line(txt, time_in, platform, desc)
            path.write_text(new_txt, encoding="utf-8")
            print("  ✓ Added.")
        except Exception as e:
            print(f"  ! Error: {e}")

def cli_bugs_mode(path: Path):
    print("\n== Bugs Mode ==")
    txt = path.read_text(encoding="utf-8")
    txt = find_or_create_sections(txt)
    events = issues_list(txt)
    if not events:
        print("No timestamped issues found in 'issues found' section.")
        return

    print("\nSelect issues to convert (e.g., 1,3,4 or 2-5):")
    for i, ev in enumerate(events, 1):
        print(f"  {i}) [{ev['time']}][{ev['platform']}] {ev['desc']}")

    def parse_selection(s, nmax):
        chosen = set()
        for chunk in s.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            if "-" in chunk:
                a, b = chunk.split("-", 1)
                if a.strip().isdigit() and b.strip().isdigit():
                    a, b = int(a), int(b)
                    for k in range(min(a,b), max(a,b)+1):
                        if 1 <= k <= nmax:
                            chosen.add(k-1)
            elif chunk.isdigit():
                k = int(chunk)
                if 1 <= k <= nmax:
                    chosen.add(k-1)
        return sorted(chosen)

    sels_raw = input("Enter selection: ").strip()
    sels = parse_selection(sels_raw, len(events))
    if not sels:
        print("No valid selection.")
        return

    prefix = input("Summary prefix (game mode, optional): ").strip()

    print("Steps mode: 1) Default (continue from step 3)  2) Custom (start at step 1)")
    sm = input("Choose 1/2 [1]: ").strip() or "1"
    steps_mode = "default" if sm == "1" else "custom"

    print("Enter extra/custom steps (one per line). Finish with a single '.' on its own line:")
    extra_lines = []
    while True:
        ln = input()
        if ln.strip() == ".":
            break
        extra_lines.append(ln)

    observed = input("Observed Results (optional; finish with Enter): ").strip()
    expected = input("Expected Results (optional; finish with Enter): ").strip()

    # Backup
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.stem}.bak-{stamp}{path.suffix}")
    backup.write_text(txt, encoding="utf-8")

    updated = txt
    for idx in sels:
        ev = events[idx]
        updated = append_bug_and_move_issue(updated, ev, prefix, steps_mode, extra_lines, observed, expected)

    path.write_text(updated, encoding="utf-8")
    print(f"✓ Generated {len(sels)} bug(s). Backup written to {backup.name}")

def run_cli():
    path = cli_setup_or_open()
    while True:
        print("\nChoose mode:")
        print("  1) Notes mode (enter timestamped issues)")
        print("  2) Bugs mode (generate bug reports from notes)")
        print("  3) Show file path")
        print("  4) Quit")
        choice = input("Enter 1/2/3/4: ").strip()
        if choice == "1":
            cli_notes_mode(path)
        elif choice == "2":
            cli_bugs_mode(path)
        elif choice == "3":
            print(path)
        elif choice == "4":
            break
        else:
            print("Invalid choice.")

# ============================== GUI MODE ==============================
def copy_to_system(text: str):
    if not TK_AVAILABLE:
        return
    data = (text or "").encode("utf-8")
    try:
        if sys.platform == "darwin":
            p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            p.communicate(data); return
        elif sys.platform.startswith("win"):
            data_win = (text or "").replace("\n", "\r\n").encode("utf-16le")
            p = subprocess.Popen(["clip"], stdin=subprocess.PIPE)
            p.communicate(data_win); return
    except Exception:
        pass
    try:
        root = tk._default_root
        if root is not None:
            root.clipboard_clear()
            root.clipboard_append(text or "")
            root.update()
    except Exception:
        pass

if TK_AVAILABLE:
    class SetupWizard(ttk.Frame):
        def __init__(self, master, on_done):
            super().__init__(master)
            self.on_done = on_done
            self.pack(fill="both", expand=True, padx=12, pady=12)

            ttk.Label(self, text="Bug Notes Assistant — Setup", font=("TkDefaultFont", 14, "bold")).pack(anchor="w", pady=(0,8))

            btns = ttk.Frame(self)
            btns.pack(fill="x", pady=(0,10))
            ttk.Button(btns, text="📄 New Notes File", command=self.new_file_flow).pack(side="left")
            ttk.Button(btns, text="📂 Open Existing File…", command=self.open_existing).pack(side="left", padx=8)

            self.status = tk.StringVar(value="Start by creating a new file for today or open an existing one.")
            ttk.Label(self, textvariable=self.status).pack(anchor="w", pady=(6,0))

        def open_existing(self):
            p = filedialog.askopenfilename(title="Open notes file", filetypes=[("Markdown","*.md"),("All files","*.*")])
            if not p:
                return
            path = Path(p).expanduser().resolve()
            if not path.exists():
                messagebox.showerror("Not found", f"{path} does not exist.")
                return
            txt = path.read_text(encoding="utf-8")
            updated = find_or_create_sections(txt)
            if updated != txt:
                path.write_text(updated, encoding="utf-8")
            self.on_done(path)

        def new_file_flow(self):
            NewFileDialog(self, self.on_done)

    class NewFileDialog(tk.Toplevel):
        def __init__(self, master, on_done):
            super().__init__(master)
            self.title("New Notes File")
            self.resizable(False, False)
            self.grab_set()
            self.on_done = on_done

            frm = ttk.Frame(self)
            frm.pack(padx=12, pady=12, fill="both", expand=True)

            self.date_var = tk.StringVar(value=datetime.now().strftime("%m-%d-%Y"))
            self.dir_var = tk.StringVar(value=str(Path(".").resolve()))
            row = 0
            ttk.Label(frm, text="Date (mm-dd-yyyy):").grid(row=row, column=0, sticky="w")
            ttk.Entry(frm, textvariable=self.date_var, width=14).grid(row=row, column=1, sticky="w", padx=6)
            ttk.Button(frm, text="Choose Folder…", command=self.choose_folder).grid(row=row, column=2, sticky="w")
            ttk.Label(frm, textvariable=self.dir_var).grid(row=row, column=3, sticky="w", padx=6)
            row += 1

            ttk.Label(frm, text="Usernames (optional):", font=("TkDefaultFont", 10, "bold")).grid(row=row, column=0, columnspan=4, sticky="w", pady=(8,2))
            row += 1

            self.user_vars = {}
            for p in ALL_PLATFORMS:
                ttk.Label(frm, text=f"{p}:").grid(row=row, column=0, sticky="e")
                v = tk.StringVar(value="")
                ttk.Entry(frm, textvariable=v, width=20).grid(row=row, column=1, sticky="w", padx=6, pady=1)
                self.user_vars[p] = v
                row += 1

            ttk.Label(frm, text="Build numbers (digits):", font=("TkDefaultFont", 10, "bold")).grid(row=row, column=0, columnspan=4, sticky="w", pady=(8,2))
            row += 1
            self.gen4_var = tk.StringVar(value="")
            self.gen5_var = tk.StringVar(value="")
            ttk.Label(frm, text="gen4:").grid(row=row, column=0, sticky="e")
            ttk.Entry(frm, textvariable=self.gen4_var, width=10).grid(row=row, column=1, sticky="w", padx=6)
            ttk.Label(frm, text="gen5:").grid(row=row, column=2, sticky="e")
            ttk.Entry(frm, textvariable=self.gen5_var, width=10).grid(row=row, column=3, sticky="w", padx=6)
            row += 1

            btns = ttk.Frame(frm)
            btns.grid(row=row, column=0, columnspan=4, sticky="e", pady=(10,0))
            ttk.Button(btns, text="Create", command=self.create_file).pack(side="right", padx=6)
            ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right")

        def choose_folder(self):
            d = filedialog.askdirectory(initialdir=self.dir_var.get())
            if d:
                self.dir_var.set(d)

        def create_file(self):
            try:
                date_str = (self.date_var.get() or datetime.now().strftime("%m-%d-%Y")).strip()
                base = Path(self.dir_var.get()).expanduser().resolve() / f"{date_str}-notes.md"
                base.parent.mkdir(parents=True, exist_ok=True)
                usernames = {p: self.user_vars[p].get().strip() for p in ALL_PLATFORMS if self.user_vars[p].get().strip()}
                txt = header_block(date_str, usernames, self.gen4_var.get(), self.gen5_var.get())
                base.write_text(txt, encoding="utf-8")
                self.on_done(base)
                self.destroy()
            except Exception as e:
                messagebox.showerror("Error", str(e))

    class MainApp(ttk.Frame):
        def __init__(self, master, notes_path: Path):
            super().__init__(master)
            self.notes_path = notes_path
            self.pack(fill="both", expand=True)

            hdr = ttk.Frame(self)
            hdr.pack(fill="x", padx=10, pady=8)
            ttk.Label(hdr, text=f"File: {notes_path.name}", font=("TkDefaultFont", 12, "bold")).pack(side="left")
            ttk.Button(hdr, text="Open Different File…", command=self.change_file).pack(side="right")

            self.nb = ttk.Notebook(self)
            self.nb.pack(fill="both", expand=True, padx=10, pady=(0,10))

            self.header_tab = HeaderTab(self.nb, self)
            self.nb.add(self.header_tab, text="Header ✏️")

            self.issues_tab = IssuesTab(self.nb, self)
            self.nb.add(self.issues_tab, text="Issues found 🕵️‍♂️")

            self.bugs_tab = BugsTab(self.nb, self)
            self.nb.add(self.bugs_tab, text="Bugs 🐛")

            self.copier_tab = BugsWrittenTab(self.nb, self)
            self.nb.add(self.copier_tab, text="Bugs written 🧾")

        def change_file(self):
            p = filedialog.askopenfilename(title="Open notes file", filetypes=[("Markdown","*.md"),("All files","*.*")])
            if not p:
                return
            path = Path(p).expanduser().resolve()
            if not path.exists():
                messagebox.showerror("Not found", f"{path} does not exist.")
                return
            txt = path.read_text(encoding="utf-8")
            updated = find_or_create_sections(txt)
            if updated != txt:
                path.write_text(updated, encoding="utf-8")
            self.notes_path = path
            self.header_tab.refresh()
            self.issues_tab.refresh()
            self.bugs_tab.refresh()
            self.copier_tab.refresh()

    class HeaderTab(ttk.Frame):
        def __init__(self, master, app: MainApp):
            super().__init__(master)
            self.app = app

            frm = ttk.Frame(self)
            frm.pack(fill="x", padx=10, pady=10)

            ttk.Label(frm, text="Date:").grid(row=0, column=0, sticky="e")
            self.date_var = tk.StringVar(value="")
            ttk.Entry(frm, textvariable=self.date_var, width=14, state="readonly").grid(row=0, column=1, sticky="w", padx=6)

            ttk.Label(frm, text="gen4 build:").grid(row=0, column=2, sticky="e")
            self.gen4_var = tk.StringVar(value="")
            ttk.Entry(frm, textvariable=self.gen4_var, width=10).grid(row=0, column=3, sticky="w", padx=6)
            ttk.Label(frm, text="gen5 build:").grid(row=0, column=4, sticky="e")
            self.gen5_var = tk.StringVar(value="")
            ttk.Entry(frm, textvariable=self.gen5_var, width=10).grid(row=0, column=5, sticky="w", padx=6)

            grid = ttk.Frame(self)
            grid.pack(fill="x", padx=10, pady=(0,10))
            self.user_vars = {}
            r = 0
            for p in ALL_PLATFORMS:
                ttk.Label(grid, text=f"{p}:").grid(row=r, column=0, sticky="e")
                v = tk.StringVar(value="")
                ttk.Entry(grid, textvariable=v, width=20).grid(row=r, column=1, sticky="w", padx=6, pady=2)
                self.user_vars[p] = v
                r += 1

            btns = ttk.Frame(self)
            btns.pack(fill="x", padx=10, pady=(0,10))
            ttk.Button(btns, text="Reload", command=self.refresh).pack(side="left")
            ttk.Button(btns, text="Save Header", command=self.save_header).pack(side="right")

            self.refresh()

        def refresh(self):
            if not self.app.notes_path.exists():
                return
            text = self.app.notes_path.read_text(encoding="utf-8")
            date_str, _ = parse_date_and_header_end(text)
            self.date_var.set(date_str or "")
            g4, g5 = parse_builds(text)
            self.gen4_var.set(g4)
            self.gen5_var.set(g5)
            un = parse_usernames(text)
            for p in ALL_PLATFORMS:
                self.user_vars[p].set(un.get(p, ""))

        def save_header(self):
            try:
                text = self.app.notes_path.read_text(encoding="utf-8")
                usernames = {p: self.user_vars[p].get().strip() for p in ALL_PLATFORMS if self.user_vars[p].get().strip()}
                new_text = replace_header(text, usernames, self.gen4_var.get().strip(), self.gen5_var.get().strip())
                self.app.notes_path.write_text(new_text, encoding="utf-8")
                messagebox.showinfo("Saved", "Header updated.")
                self.app.issues_tab.refresh()
                self.app.bugs_tab.refresh()
                self.app.copier_tab.refresh()
            except Exception as e:
                messagebox.showerror("Error", str(e))

    class IssuesTab(ttk.Frame):
        def __init__(self, master, app: MainApp):
            super().__init__(master)
            self.app = app

            left = ttk.Frame(self)
            left.pack(side="left", fill="both", expand=True)
            ttk.Label(left, text="Issues (timestamped notes inside 'issues found 🕵️‍♂️')").pack(anchor="w")
            self.listbox = tk.Listbox(left, selectmode="browse")
            self.listbox.pack(fill="both", expand=True, pady=(4,8))
            btns = ttk.Frame(left)
            btns.pack(fill="x")
            ttk.Button(btns, text="Refresh", command=self.refresh).pack(side="left")

            right = ttk.LabelFrame(self, text="Add issue")
            right.pack(side="left", fill="y", padx=(12,0))
            ttk.Label(right, text="Platform:").grid(row=0, column=0, sticky="w", padx=8, pady=(8,2))
            self.platform_var = tk.StringVar(value="ps5")
            ttk.Combobox(right, textvariable=self.platform_var, values=ALL_PLATFORMS, state="readonly", width=10)\
                .grid(row=0, column=1, sticky="w", padx=8, pady=(8,2))

            ttk.Label(right, text="Time (optional):").grid(row=1, column=0, sticky="w", padx=8, pady=2)
            self.time_var = tk.StringVar(value="")
            ttk.Entry(right, textvariable=self.time_var, width=12).grid(row=1, column=1, sticky="w", padx=8, pady=2)

            ttk.Label(right, text="Short description:").grid(row=2, column=0, sticky="nw", padx=8, pady=(8,2))
            self.desc_txt = tk.Text(right, width=40, height=7)
            self.desc_txt.grid(row=2, column=1, sticky="w", padx=8, pady=(8,2))

            ttk.Button(right, text="Add to 'issues found'", command=self.add_issue).grid(row=3, column=1, sticky="e", padx=8, pady=(8,10))

            for i in range(4):
                right.grid_rowconfigure(i, weight=0)
            right.grid_columnconfigure(1, weight=1)

            self.refresh()

        def refresh(self):
            self.listbox.delete(0, "end")
            if not self.app.notes_path.exists():
                return
            text = self.app.notes_path.read_text(encoding="utf-8")
            text = find_or_create_sections(text)
            events = issues_list(text)
            for ev in events:
                self.listbox.insert("end", f"[{ev['time']}][{ev['platform']}] {ev['desc']}")

        def add_issue(self):
            desc = self.desc_txt.get("1.0", "end").strip()
            if not desc:
                messagebox.showwarning("Missing", "Enter a short description.")
                return
            platform = self.platform_var.get().strip().lower()
            time_str = self.time_var.get().strip()
            try:
                txt = self.app.notes_path.read_text(encoding="utf-8")
                new_txt = add_issue_line(txt, time_str, platform, desc)
                self.app.notes_path.write_text(new_txt, encoding="utf-8")
                self.desc_txt.delete("1.0", "end")
                self.time_var.set("")
                self.refresh()
            except Exception as e:
                messagebox.showerror("Error", str(e))

    class BugsTab(ttk.Frame):
        def __init__(self, master, app: MainApp):
            super().__init__(master)
            self.app = app

            container = ttk.Frame(self)
            container.pack(fill="both", expand=True)

            left = ttk.Frame(container)
            left.pack(side="left", fill="both", expand=True)
            ttk.Label(left, text="Select issue(s) to convert:").pack(anchor="w")
            self.listbox = tk.Listbox(left, selectmode="extended")
            self.listbox.pack(fill="both", expand=True, pady=(4,8))
            ttk.Button(left, text="Refresh", command=self.refresh).pack(anchor="w")

            right = ttk.LabelFrame(container, text="Bug details (applied to all selected)")
            right.pack(side="left", fill="both", expand=True, padx=(12,0))

            r = 0
            ttk.Label(right, text="Summary prefix (game mode, optional):").grid(row=r, column=0, sticky="w", padx=8, pady=(8,2))
            self.prefix_var = tk.StringVar(value="")
            ttk.Entry(right, textvariable=self.prefix_var, width=40).grid(row=r, column=1, sticky="we", padx=8, pady=(8,2))
            r += 1

            ttk.Label(right, text="Steps mode:").grid(row=r, column=0, sticky="w", padx=8)
            self.steps_mode = tk.StringVar(value="default")
            ttk.Radiobutton(right, text="Default steps (continue from step 3)", variable=self.steps_mode, value="default")\
                .grid(row=r, column=1, sticky="w", padx=8)
            r += 1
            ttk.Radiobutton(right, text="Custom steps (start at step 1)", variable=self.steps_mode, value="custom")\
                .grid(row=r, column=1, sticky="w", padx=8)
            r += 1

            ttk.Label(right, text="Extra/Custom steps (one per line):").grid(row=r, column=0, sticky="nw", padx=8, pady=(8,2))
            self.steps_txt = tk.Text(right, width=50, height=8)
            self.steps_txt.grid(row=r, column=1, sticky="we", padx=8, pady=(8,2))
            r += 1

            ttk.Label(right, text="Observed Results (optional):").grid(row=r, column=0, sticky="nw", padx=8, pady=(8,2))
            self.obs_txt = tk.Text(right, width=50, height=4)
            self.obs_txt.grid(row=r, column=1, sticky="we", padx=8, pady=(8,2))
            r += 1

            ttk.Label(right, text="Expected Results (optional):").grid(row=r, column=0, sticky="nw", padx=8, pady=(8,2))
            self.exp_txt = tk.Text(right, width=50, height=4)
            self.exp_txt.grid(row=r, column=1, sticky="we", padx=8, pady=(8,2))
            r += 1

            ttk.Button(right, text="Generate Bug(s)", command=self.generate_bugs).grid(row=r, column=1, sticky="e", padx=8, pady=(8,10))
            for c in range(2):
                right.grid_columnconfigure(c, weight=1)

            self.refresh()

        def refresh(self):
            self.listbox.delete(0, "end")
            if not self.app.notes_path.exists():
                return
            text = self.app.notes_path.read_text(encoding="utf-8")
            text = find_or_create_sections(text)
            self.events = issues_list(text)
            for ev in self.events:
                self.listbox.insert("end", f"[{ev['time']}][{ev['platform']}] {ev['desc']}")

        def generate_bugs(self):
            sels = self.listbox.curselection()
            if not sels:
                messagebox.showinfo("Pick issue(s)", "Select one or more issues to convert.")
                return
            selected_events = [self.events[i] for i in sels]

            prefix = self.prefix_var.get().strip()
            steps_mode = self.steps_mode.get()
            steps_lines = [ln for ln in self.steps_txt.get("1.0","end").splitlines() if ln.strip()]
            observed = self.obs_txt.get("1.0","end").strip()
            expected = self.exp_txt.get("1.0","end").strip()

            try:
                original = self.app.notes_path.read_text(encoding="utf-8")
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                backup = self.app.notes_path.with_name(f"{self.app.notes_path.stem}.bak-{stamp}{self.app.notes_path.suffix}")
                backup.write_text(original, encoding="utf-8")

                updated = original
                for ev in selected_events:
                    updated = append_bug_and_move_issue(updated, ev, prefix, steps_mode, steps_lines, observed, expected)

                self.app.notes_path.write_text(updated, encoding="utf-8")

                messagebox.showinfo("Done", f"Generated {len(selected_events)} bug(s). Backup: {backup.name}")
                self.obs_txt.delete("1.0","end")
                self.exp_txt.delete("1.0","end")
                self.refresh()
                self.master.master.issues_tab.refresh()
                self.master.master.copier_tab.refresh()
            except Exception as e:
                messagebox.showerror("Error", str(e))

    class BugsWrittenTab(ttk.Frame):
        def __init__(self, master, app: MainApp):
            super().__init__(master)
            self.app = app

            container = ttk.Frame(self)
            container.pack(fill="both", expand=True, padx=10, pady=10)

            left = ttk.Frame(container)
            left.pack(side="left", fill="both", expand=True)
            ttk.Label(left, text="Bugs written (from 'Bugs 🐛' section):").pack(anchor="w")
            self.listbox = tk.Listbox(left, selectmode="browse", exportselection=False)
            self.listbox.pack(fill="both", expand=True, pady=(4,8))
            lbbtns = ttk.Frame(left)
            lbbtns.pack(fill="x")
            ttk.Button(lbbtns, text="Refresh", command=self.refresh).pack(side="left")
            self.listbox.bind("<<ListboxSelect>>", self.on_select)

            right = ttk.LabelFrame(container, text="Copy fields")
            right.pack(side="left", fill="both", expand=True, padx=(12,0))

            r = 0
            ttk.Label(right, text="Summary:").grid(row=r, column=0, sticky="w", padx=6, pady=(6,2))
            self.summary_var = tk.StringVar(value="")
            self.summary_entry = ttk.Entry(right, textvariable=self.summary_var, state="readonly", width=70, exportselection=False)
            self.summary_entry.grid(row=r, column=1, sticky="we", padx=6, pady=(6,2))
            ttk.Button(right, text="Copy", command=lambda: copy_to_system(self.summary_var.get())).grid(row=r, column=2, padx=6)
            r += 1

            ttk.Label(right, text="Steps + Observed + Expected:").grid(row=r, column=0, sticky="nw", padx=6, pady=(8,2))
            self.soe_txt = tk.Text(right, width=70, height=16, state="disabled", exportselection=False)
            self.soe_txt.grid(row=r, column=1, sticky="we", padx=6, pady=(8,2))
            ttk.Button(right, text="Copy", command=lambda: copy_to_system(self.soe_txt.get("1.0", "end").strip())).grid(row=r, column=2, padx=6, sticky="n")
            r += 1

            ttk.Label(right, text="Username:").grid(row=r, column=0, sticky="w", padx=6, pady=(8,2))
            self.username_var = tk.StringVar(value="")
            self.username_entry = ttk.Entry(right, textvariable=self.username_var, state="readonly", width=30, exportselection=False)
            self.username_entry.grid(row=r, column=1, sticky="w", padx=6, pady=(8,2))
            ttk.Button(right, text="Copy", command=lambda: copy_to_system(self.username_var.get())).grid(row=r, column=2, padx=6)
            r += 1

            ttk.Label(right, text="Build #:").grid(row=r, column=0, sticky="w", padx=6, pady=(8,2))
            self.build_var = tk.StringVar(value="")
            self.build_entry = ttk.Entry(right, textvariable=self.build_var, state="readonly", width=20, exportselection=False)
            self.build_entry.grid(row=r, column=1, sticky="w", padx=6, pady=(8,2))
            ttk.Button(right, text="Copy", command=lambda: copy_to_system(self.build_var.get())).grid(row=r, column=2, padx=6)
            r += 1

            for c in range(3):
                right.grid_columnconfigure(c, weight=(1 if c == 1 else 0))

            self.bugs = []
            self.refresh()

        def refresh(self):
            self.listbox.delete(0, "end")
            self.bugs = []
            if not self.app.notes_path.exists():
                self._clear_fields()
                return
            text = self.app.notes_path.read_text(encoding="utf-8")
            text = find_or_create_sections(text)
            self.bugs = list_bugs(text)
            for b in self.bugs:
                label = f"[{b['time']}][{b['platform']}] {b['summary'] or '(no summary)'}"
                self.listbox.insert("end", label)
            self._clear_fields()

        def _clear_fields(self):
            self.summary_var.set("")
            self.set_soe("")
            self.username_var.set("")
            self.build_var.set("")

        def on_select(self, _evt=None):
            sels = self.listbox.curselection()
            if not sels:
                self._clear_fields()
                return
            bug = self.bugs[sels[0]]
            self.summary_var.set(bug["summary"])
            self.set_soe(self.compose_soe(bug))
            self.username_var.set(bug["username"])
            g4, g5 = parse_builds(self.app.notes_path.read_text(encoding="utf-8"))
            bnum = g4 if bug["platform"] in GEN4_PLATFORMS else g5
            self.build_var.set(bnum)

        def compose_soe(self, bug):
            # Avoid double-adding labels if the parsed text already includes them
            def ensure_label(text, label):
                t = (text or "").lstrip()
                if not t:
                    return f"{label}:\n"
                if re.match(rf"(?i)^{re.escape(label)}\s*:", t):
                    return t
                return f"{label}:\n{t}"

            parts = []
            if bug["steps"]:
                parts.append(bug["steps"])  # includes "Steps to Reproduce:" from parser
            parts.append(ensure_label(bug["observed"], "Observed Results"))
            parts.append(ensure_label(bug["expected"], "Expected Results"))
            return "\n\n".join(parts).strip()

        def set_soe(self, text):
            self.soe_txt.config(state="normal")
            self.soe_txt.delete("1.0", "end")
            self.soe_txt.insert("1.0", text)
            self.soe_txt.config(state="disabled")

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title("Bug Notes Assistant")
            self.geometry("1120x720")
            self.resizable(True, True)
            self.show_wizard()

            m = tk.Menu(self)
            filem = tk.Menu(m, tearoff=0)
            filem.add_command(label="New (Wizard)…", command=self.show_wizard)
            filem.add_separator()
            filem.add_command(label="Quit", command=self.destroy)
            self.config(menu=m)

        def show_wizard(self):
            for w in self.winfo_children():
                w.destroy()
            SetupWizard(self, self.on_setup_done)

        def on_setup_done(self, notes_path: Path):
            for w in self.winfo_children():
                w.destroy()
            MainApp(self, notes_path)

def run_gui():
    if not TK_AVAILABLE:
        print("Tkinter is not available in this environment. Use --cli to run the CLI.")
        sys.exit(1)
    app = App()
    try:
        app.tk.call("tk", "scaling", 1.2)
    except Exception:
        pass
    app.mainloop()

# ============================== ENTRY ==============================
def main():
    ap = argparse.ArgumentParser(description="Bug Notes Assistant (GUI by default, CLI with --cli)")
    ap.add_argument("--cli", action="store_true", help="Run in CLI mode")
    args = ap.parse_args()

    if args.cli:
        run_cli()
    else:
        run_gui()

if __name__ == "__main__":
    main()
