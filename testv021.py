#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bug Notes Assistant — GUI (default) / CLI (--cli)

This build (Aug 2025):
- Header: shorter platform username fields.
- Bugs Written tab:
  * Edit/Save at bottom; edits Bug#, Summary, Report (steps/observed/expected), Username, Build# back into markdown
  * Removed "Clear" bug number; "Set/Update" renamed to "Set"
  * "Build# found on:" → "Build#"
  * Username field now prefers the bug block's **Username:** value; falls back to Header mapping only if empty
- Keeps single-click wrapped list behavior (no Ctrl needed), reflow on resize.

CLI remains (basic), but GUI is the main flow.
"""

import sys
import re
import hashlib
from pathlib import Path
from datetime import datetime
import argparse
import textwrap

# Tk
TK_AVAILABLE = True
try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, simpledialog
    from tkinter import font as tkfont
    import subprocess
except Exception:
    TK_AVAILABLE = False

# ---- Config ----
GEN4_PLATFORMS = {"nx1", "ps4", "xb1"}
GEN5_PLATFORMS = {"nx2", "pc", "xbx", "ps5", "steamdeck", "laptop"}
ALL_PLATFORMS  = sorted(GEN4_PLATFORMS | GEN5_PLATFORMS)

BUGS_HEADERS        = [r"#\s*bugs\s*$", r"#\s*bugs\s*🐛\s*$"]
REPORTS_HEADERS     = [r"#\s*reports\s+written\s*📝\s*$", r"#\s*reports\s+written\s*$"]
ISSUES_HEADERS      = [r"#\s*issues\s+found\s*🕵️‍♂️\s*$", r"#\s*issues\s+found\s*$"]
FOUND_HEADERS       = [r"#\s*found\s*/\s*invalid\s*🗂️\s*$", r"#\s*found\s*/\s*invalid\s*$", r"#\s*found\s*🗂️\s*$", r"#\s*found\s*$"]

# ---- Helpers ----
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
    idx = _find_section_start(lines, header_patterns)
    if idx is None: return None
    start = idx + 1
    if start < len(lines) and lines[start].strip() == "---":
        start += 1
    end = len(lines)
    for j in range(start, len(lines)):
        if re.match(r"^#\s+", lines[j]):
            end = j; break
    return (start, end)

def ensure_section(lines, header_patterns, insert_after_patterns=None, title_line=None):
    b = _section_bounds(lines, header_patterns)
    if b: return lines, b
    insert_at = len(lines)
    if insert_after_patterns:
        after = _section_bounds(lines, insert_after_patterns)
        if after: insert_at = after[1]
    block = [title_line if title_line else "## section", "---", ""]
    lines[insert_at:insert_at] = block
    return lines, _section_bounds(lines, header_patterns)

def find_or_create_sections(text: str) -> str:
    lines = text.splitlines()
    changed = False

    if _section_bounds(lines, ISSUES_HEADERS) is None:
        insert_at = len(lines)
        if lines and lines[0].startswith("# "):
            idx = 1
            if idx < len(lines) and lines[idx].strip() == "---": idx += 1
            while idx < len(lines) and lines[idx].strip() != "": idx += 1
            if idx < len(lines) and lines[idx].strip() == "": idx += 1
            insert_at = idx
        lines[insert_at:insert_at] = ["# issues found 🕵️‍♂️", "---", ""]
        changed = True

    if _section_bounds(lines, FOUND_HEADERS) is None:
        ib = _section_bounds(lines, ISSUES_HEADERS); insert_at = ib[1] if ib else len(lines)
        lines[insert_at:insert_at] = ["# Found / Invalid 🗂️", "---", ""]
        changed = True

    if _section_bounds(lines, REPORTS_HEADERS) is None:
        fb = _section_bounds(lines, FOUND_HEADERS); insert_at = fb[1] if fb else len(lines)
        lines[insert_at:insert_at] = ["# reports written 📝", "---", ""]
        changed = True

    if _section_bounds(lines, BUGS_HEADERS) is None:
        rb = _section_bounds(lines, REPORTS_HEADERS); insert_at = rb[1] if rb else len(lines)
        lines[insert_at:insert_at] = ["# bugs 🐛", "---", ""]
        changed = True

    out = "\n".join(lines)
    if changed and not out.endswith("\n"): out += "\n"
    return out if changed else text

def normalize_time_12h(t: str) -> str:
    t = (t or "").strip()
    if not t: return datetime.now().strftime("%I:%M %p")
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*([AaPp][Mm])?\s*", t)
    if m:
        hh, mm, ampm = m.group(1), m.group(2), m.group(3)
        return f"{int(hh):02d}:{mm} {ampm.upper()}" if ampm else f"{int(hh):02d}:{mm}"
    return datetime.now().strftime("%I:%M %p")

def parse_usernames(text: str):
    usernames = {}
    for m in re.finditer(r"^- \[([a-z0-9]+)\]\[([^\]]+)\]\s*$", text, re.MULTILINE | re.IGNORECASE):
        key = m.group(1).lower(); val = m.group(2).strip()
        if key in {"gen4","gen5"} and re.fullmatch(r"\d+", val): continue
        if key in ALL_PLATFORMS: usernames[key] = val
    return usernames

def parse_builds(text: str):
    gen4 = ""; gen5 = ""
    for m in re.finditer(r"^- \[(gen4|gen5)\]\[(\d+)\]\s*-->\s*build number\s*$", text, re.IGNORECASE|re.MULTILINE):
        if m.group(1).lower() == "gen4": gen4 = m.group(2)
        else: gen5 = m.group(2)
    return gen4, gen5

def header_only_block(date_str: str, usernames: dict, gen4_build: str, gen5_build: str) -> str:
    lines = [f"# {date_str} notes", "---"]
    for p in sorted(ALL_PLATFORMS):
        if p in usernames and usernames[p]:
            lines.append(f"- [{p}][{usernames[p]}]")
    if gen4_build.strip().isdigit(): lines.append(f"- [gen4][{gen4_build.strip()}] --> build number")
    if gen5_build.strip().isdigit(): lines.append(f"- [gen5][{gen5_build.strip()}] --> build number")
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
    if idx < len(lines) and lines[idx].strip() == "---": idx += 1
    while idx < len(lines) and lines[idx].strip() != "": idx += 1
    if idx < len(lines) and lines[idx].strip() == "": idx += 1
    return date_str, idx

def replace_header(text: str, usernames: dict, gen4_build: str, gen5_build: str) -> str:
    date_str, hdr_end = parse_date_and_header_end(text)
    new_header = header_only_block(date_str or datetime.now().strftime("%m-%d-%Y"),
                                   usernames, gen4_build, gen5_build)
    rest = "\n".join(text.splitlines()[hdr_end:])
    out = new_header + rest
    return find_or_create_sections(out)

def header_block(date_str: str, usernames: dict, gen4_build: str, gen5_build: str) -> str:
    lines = [f"# {date_str} notes","---"]
    for p in sorted(ALL_PLATFORMS):
        if p in usernames and usernames[p]: lines.append(f"- [{p}][{usernames[p]}]")
    if gen4_build.strip().isdigit(): lines.append(f"- [gen4][{gen4_build.strip()}] --> build number")
    if gen5_build.strip().isdigit(): lines.append(f"- [gen5][{gen5_build.strip()}] --> build number")
    lines += ["", "# issues found 🕵️‍♂️", "---", "", "# Found / Invalid 🗂️", "---", "", "# reports written 📝", "---", "", "# bugs 🐛", "---", ""]
    out = "\n".join(lines)
    if not out.endswith("\n"): out += "\n"
    return out

def extract_issues_region(text: str) -> str:
    lines = text.splitlines()
    b = _section_bounds(lines, ISSUES_HEADERS)
    if not b: return ""
    start, end = b
    return "\n".join(lines[start:end])

def extract_found_region(text: str) -> str:
    lines = text.splitlines()
    b = _section_bounds(lines, FOUND_HEADERS)
    if not b: return ""
    start, end = b
    return "\n".join(lines[start:end])

def issues_list(text: str):
    region = extract_issues_region(text)
    out = []
    pat = re.compile(r"^- \[(\d{1,2}:\d{2}(?:\s?[AaPp][Mm])?)\]\[([a-z0-9]+)\]\s+(.*)$", re.MULTILINE)
    for m in pat.finditer(region):
        out.append({"time": m.group(1).strip(), "platform": m.group(2).lower(), "desc": m.group(3).strip()})
    return out

FOUND_LINE_RE = re.compile(
    r"^- (?:\[(?P<bug>[^\]]+)\]\s+)?\[(?P<time>\d{1,2}:\d{2}(?:\s?[AaPp][Mm])?)\]\[(?P<plat>[a-z0-9]+)\]\s+(?P<desc>.*)$",
    re.IGNORECASE | re.MULTILINE
)

def found_list(text: str):
    region = extract_found_region(text)
    items = []
    for m in FOUND_LINE_RE.finditer(region):
        items.append({
            "bugnum": (m.group("bug") or "").strip(),
            "time": m.group("time").strip(),
            "platform": m.group("plat").lower(),
            "desc": m.group("desc").strip(),
        })
    return items

def add_issue_line(text: str, time_str: str, platform: str, desc: str) -> str:
    text = find_or_create_sections(text)
    lines = text.splitlines()
    ib = _section_bounds(lines, ISSUES_HEADERS)
    if not ib:
        text = find_or_create_sections(text); lines = text.splitlines(); ib = _section_bounds(lines, ISSUES_HEADERS)
    _, end = ib
    newline = f"- [{normalize_time_12h(time_str)}][{platform.lower()}] {desc.strip()}"
    lines[end:end] = [newline]
    out = "\n".join(lines)
    if not out.endswith("\n"): out += "\n"
    return out

def delete_issue_line(text: str, ev: dict) -> str:
    lines = text.splitlines()
    ib = _section_bounds(lines, ISSUES_HEADERS)
    if not ib: return text
    start, end = ib
    target = f"- [{ev['time']}][{ev['platform']}] {ev['desc']}"
    removed = False
    for i in range(start, end):
        if lines[i].strip() == target:
            del lines[i]; removed = True; break
    if not removed:
        pref = re.compile(rf"^- \[{re.escape(ev['time'])}\]\[{re.escape(ev['platform'])}\]\s+")
        for i in range(start, end):
            if pref.match(lines[i]): del lines[i]; break
    out = "\n".join(lines)
    if not out.endswith("\n"): out += "\n"
    return out

def move_issue_to_found(text: str, ev: dict, bugnum: str = "") -> str:
    text = find_or_create_sections(text)
    lines = text.splitlines()
    ib = _section_bounds(lines, ISSUES_HEADERS)
    lines, fb = ensure_section(lines, FOUND_HEADERS, insert_after_patterns=ISSUES_HEADERS, title_line="# Found / Invalid 🗂️")
    if not ib or not fb:
        return "\n".join(lines) + ("\n" if not text.endswith("\n") else "")

    istart, iend = ib
    issue_line = f"- [{ev['time']}][{ev['platform']}] {ev['desc']}"
    removed = False
    for i in range(istart, iend):
        if lines[i].strip() == issue_line:
            del lines[i]; removed = True; break
    if not removed:
        pref = re.compile(rf"^- \[{re.escape(ev['time'])}\]\[{re.escape(ev['platform'])}\]\s+")
        for i in range(istart, iend):
            if pref.match(lines[i]): del lines[i]; break

    fb2 = _section_bounds(lines, FOUND_HEADERS); fend = fb2[1] if fb2 else len(lines)
    if bugnum.strip():
        new_line = f"- [{bugnum.strip()}] [{ev['time']}][{ev['platform']}] {ev['desc']}"
    else:
        new_line = f"- [{ev['time']}][{ev['platform']}] {ev['desc']}"
    lines[fend:fend] = [new_line]

    out = "\n".join(lines)
    if not out.endswith("\n"): out += "\n"
    return out

def default_plain_steps_lines(platform: str) -> list[str]:
    key = classify_platform(platform) or "gen5"
    base2 = "Enter the City." if key == "gen5" else "Enter the Neighborhood."
    return [
        "Launch the title > create or select build / save.",
        base2
    ]

def build_steps_block_numbered(template_key: str, mode: str, plain_lines: list[str]):
    if mode == "default":
        base2 = "Enter the City." if template_key == "gen5" else "Enter the Neighborhood."
        lines = ["Steps to Reproduce:", "1. Launch the title > create or select build / save.", f"2. {base2}"]
        n = 3
        for ln in plain_lines or []:
            ln = ln.strip()
            if ln: lines.append(f"{n}. {ln}"); n += 1
        if n == 3: lines.append("3. ")
        return "\n".join(lines)
    else:
        lines = ["Steps to Reproduce:"]
        n = 1
        for ln in plain_lines or []:
            ln = ln.strip()
            if ln: lines.append(f"{n}. {ln}"); n += 1
        if n == 1: lines.append("1. ")
        return "\n".join(lines)

def make_bug_block(summary: str, platform: str, username: str,
                   steps_block: str, observed: str, expected: str,
                   build_num: str) -> str:
    tmpl = """## [{bugnum}]
---
**summary:** {summary}

**Platform:** {platform}
**Username:** {username}

{steps_block}

Observed Results:
{observed}

Expected Results:
{expected}
{build_line}
"""
    bugnum = "null"  # initial; header will be updated later when bugnum known
    build_line = f"Build: {build_num}" if build_num else ""
    return tmpl.format(bugnum=bugnum, summary=summary, platform=platform, username=username,
                       steps_block=steps_block, observed=observed, expected=expected,
                       build_line=build_line)

def generate_event_id(ev: dict) -> str:
    raw = f"{ev['time']}|{ev['platform']}|{ev['desc']}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:12]

BUG_META_RE = re.compile(
    r"<!--\s*bug-id:([a-f0-9]{6,})\s+time=([^\s]+(?:\s[AP]M)?)\s+platform=([a-z0-9]+)\s+template=(gen4|gen5)(?:\s+bugnum=([^\s]+))?\s*-->"
)

def list_bugs(text: str):
    lines = text.splitlines()
    bounds = _section_bounds(lines, BUGS_HEADERS)
    if not bounds: return []
    start, end = bounds
    section = "\n".join(lines[start:end])

    def grab_line(block: str, label: str) -> str:
        m = re.search(rf"(?mi)^\*\*{re.escape(label)}:\*\*\s*(.*)$", block)
        return m.group(1).strip() if m else ""

    def grab_between(block: str, start_label: str, end_label: str) -> str:
        m1 = re.search(rf"(?mi)^{re.escape(start_label)}:\s*\n", block)
        if not m1: return ""
        sub = block[m1.start():]
        m2 = re.search(rf"(?mi)^{re.escape(end_label)}:\s*", sub)
        return sub[:m2.start()].rstrip() if m2 else sub.rstrip()

    def grab_after(block: str, start_label: str) -> str:
        m1 = re.search(rf"(?mi)^{re.escape(start_label)}:\s*\n", block)
        return block[m1.end():].strip() if m1 else ""

    def grab_build(block: str) -> str:
        m = re.search(r"(?mi)^\s*Build:\s*(.+?)\s*$", block)
        return m.group(1).strip() if m else ""

    bugs = []
    matches = list(BUG_META_RE.finditer(section))
    for i, m in enumerate(matches):
        bstart = m.end()
        bend = matches[i+1].start() if i+1 < len(matches) else len(section)
        block = section[bstart:bend]

        hm = re.search(r"(?m)^\s*##\s*\[([^\]]+)\]\s*$", block)
        header_bug = hm.group(1).strip() if hm else ""

        bugs.append({
            "id": m.group(1),
            "time": m.group(2),
            "platform": m.group(3).lower(),
            "template": m.group(4),
            "bugnum": (m.group(5) or header_bug or "").strip(),
            "summary": grab_line(block, "summary"),
            "username": grab_line(block, "Username"),
            "steps": grab_between(block, "Steps to Reproduce", "Observed Results"),
            "observed": grab_between(block, "Observed Results", "Expected Results"),
            "expected": grab_after(block, "Expected Results").splitlines()[0] if "Build:" in block else grab_after(block,"Expected Results"),
            "build": grab_build(block),
            "raw": block.strip()
        })
    return bugs

def _update_header_after_meta(text: str, bug_id: str, new_bugnum: str | None) -> str:
    pat = re.compile(
        rf"(<!--\s*bug-id:{re.escape(bug_id)}\b.*?-->)(\s*)(^##\s*\[)([^\]]*)(\]\s*$)",
        re.MULTILINE | re.DOTALL
    )
    def repl(m):
        val = (new_bugnum or "null").strip() or "null"
        return f"{m.group(1)}{m.group(2)}{m.group(3)}{val}{m.group(5)}"
    return re.sub(pat, repl, text)

def write_bug_meta_bugnum(text: str, bug_id: str, new_bugnum: str | None) -> str:
    def meta_repl(m: re.Match):
        if m.group(1) != bug_id:
            return m.group(0)
        bugnum = (new_bugnum or "").strip()
        if bugnum:
            return f"<!-- bug-id:{m.group(1)} time={m.group(2)} platform={m.group(3)} template={m.group(4)} bugnum={bugnum} -->"
        else:
            return f"<!-- bug-id:{m.group(1)} time={m.group(2)} platform={m.group(3)} template={m.group(4)} -->"
    updated = re.sub(BUG_META_RE, meta_repl, text)
    updated = _update_header_after_meta(updated, bug_id, new_bugnum)
    return updated

def _grab_line(block: str, label: str) -> str:
    m = re.search(rf"(?mi)^\*\*{re.escape(label)}:\*\*\s*(.*)$", block)
    return m.group(1).strip() if m else ""

def write_bug_content(text: str, bug_id: str, new_summary: str,
                      new_steps_block: str, new_observed: str,
                      new_expected: str, new_build: str | None,
                      new_username: str | None) -> str:
    """
    Replace the bug content block for bug_id with new values (summary, steps, observed, expected, build, username).
    """
    lines = text.splitlines()
    b = _section_bounds(lines, BUGS_HEADERS)
    if not b: return text
    sec = "\n".join(lines[b[0]:b[1]])
    metas = list(BUG_META_RE.finditer(sec))
    sec_start = len("\n".join(lines[:b[0]])) + (1 if b[0] > 0 else 0)

    for i, m in enumerate(metas):
        if m.group(1) != bug_id: 
            continue
        block_start = m.end()
        block_end = metas[i+1].start() if i+1 < len(metas) else len(sec)
        block = sec[block_start:block_end]

        hm = re.search(r"(?m)^\s*##\s*\[([^\]]*)\]\s*$", block)
        header_bugnum = hm.group(1).strip() if hm else "null"
        platform = _grab_line(block, "Platform")  # keep platform as-is

        build_line_text = f"Build: {new_build}" if (new_build and new_build.strip()) else ""

        # Username: use provided; if None, keep previous; if "", write empty.
        prev_user = _grab_line(block, "Username")
        username_val = (new_username if new_username is not None else prev_user)

        new_block = (
            f"## [{header_bugnum}]\n"
            f"---\n"
            f"**summary:** {new_summary}\n\n"
            f"**Platform:** {platform}\n"
            f"**Username:** {username_val}\n\n"
            f"{new_steps_block}\n\n"
            f"Observed Results:\n{new_observed}\n\n"
            f"Expected Results:\n{new_expected}\n"
            f"{build_line_text}\n"
        )

        abs_start = sec_start + block_start
        abs_end   = sec_start + block_end
        return text[:abs_start] + new_block + text[abs_end:]
    return text

def append_bug_and_move_issue(text: str, ev: dict, summary_prefix: str,
                              steps_mode: str, plain_lines: list,
                              observed: str, expected: str) -> str:
    text = find_or_create_sections(text)
    lines = text.splitlines()

    ib = _section_bounds(lines, ISSUES_HEADERS)
    rb = _section_bounds(lines, REPORTS_HEADERS)
    bb = _section_bounds(lines, BUGS_HEADERS)
    if not (ib and rb and bb):
        text = find_or_create_sections(text); lines = text.splitlines()
        ib = _section_bounds(lines, ISSUES_HEADERS)
        rb = _section_bounds(lines, REPORTS_HEADERS)
        bb = _section_bounds(lines, BUGS_HEADERS)

    ev_id = generate_event_id(ev)
    if f"<!-- bug-id:{ev_id}" in text:
        return text

    template_key = classify_platform(ev["platform"]) or "gen5"
    usernames = parse_usernames(text)
    username = usernames.get(ev["platform"], "")

    g4, g5 = parse_builds(text)
    build_found = g4 if template_key == "gen4" else g5

    summary = f"{summary_prefix}: {ev['desc']}" if summary_prefix else ev['desc']
    # For default mode, auto-fill base steps, then allow user lines from plain_lines
    base_lines = default_plain_steps_lines(ev["platform"]) if steps_mode == "default" else []
    merged_plain = base_lines + [ln for ln in plain_lines if ln not in base_lines]
    steps_block = build_steps_block_numbered(template_key, "default" if steps_mode=="default" else "custom", merged_plain)

    bug_block = make_bug_block(summary, ev["platform"], username, steps_block, observed or "", expected or "", build_found or "")
    meta = f"<!-- bug-id:{ev_id} time={ev['time']} platform={ev['platform']} template={template_key} -->"

    bstart, bend = bb
    lines[bend:bend] = ["", meta, bug_block.strip(), ""]

    istart, iend = ib
    target = f"- [{ev['time']}][{ev['platform']}] {ev['desc']}"
    removed = False
    for i in range(istart, iend):
        if lines[i].strip() == target:
            del lines[i]; removed = True; break
    if not removed:
        pref = re.compile(rf"^- \[{re.escape(ev['time'])}\]\[{re.escape(ev['platform'])}\]\s+")
        for i in range(istart, iend):
            if pref.match(lines[i]): del lines[i]; break

    rstart, rend = _section_bounds(lines, REPORTS_HEADERS)
    lines[rend:rend] = [target]

    out = "\n".join(lines)
    if not out.endswith("\n"): out += "\n"
    return out

# ================= CLI =================
def prompt(msg, default=None):
    sfx = f" [{default}]" if default is not None else ""
    resp = input(f"{msg}{sfx}: ").strip()
    return resp if resp else (default if default is not None else "")

def choose_platform_cli():
    options = list(ALL_PLATFORMS)
    print("\nChoose platform:")
    for i,p in enumerate(options,1): print(f"  {i}) {p}")
    while True:
        s = input("Enter number: ").strip()
        if s.isdigit() and 1 <= int(s) <= len(options):
            return options[int(s)-1]
        print("Invalid selection.")

def cli_setup_or_open():
    today = datetime.now().strftime("%m-%d-%Y")
    date_str = prompt("Notes date (mm-dd-yyyy)", today)
    fname = f"{date_str}-notes.md"
    if Path(fname).exists():
        path = Path(fname).resolve()
        txt = path.read_text(encoding="utf-8")
        upd = find_or_create_sections(txt)
        if upd != txt: path.write_text(upd, encoding="utf-8")
        return path
    usernames = {}
    print("Enter usernames (optional):")
    for p in ALL_PLATFORMS:
        v = input(f"  {p}: ").strip()
        if v: usernames[p] = v
    gen4 = input("gen4 build (digits, optional): ").strip()
    gen5 = input("gen5 build (digits, optional): ").strip()
    text = header_block(date_str, usernames, gen4, gen5)
    Path(fname).write_text(text, encoding="utf-8")
    return Path(fname).resolve()

def cli_notes_mode(path: Path):
    print("\n== Notes Mode ==")
    while True:
        desc = input("Short description (blank to stop): ").strip()
        if not desc: break
        platform = choose_platform_cli()
        time_in = input("Time (hh:mm [AM/PM], blank=now): ").strip()
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
        print("No timestamped issues found.")
        return
    for i, ev in enumerate(events,1):
        print(f"  {i}) [{ev['time']}][{ev['platform']}] {ev['desc']}")
    s = input("Pick one issue number: ").strip()
    if not s.isdigit() or not (1 <= int(s) <= len(events)):
        print("Invalid."); return
    ev = events[int(s)-1]
    prefix = input("Summary prefix (optional): ").strip()
    sm = input("Steps mode 1) Default  2) Custom [1]: ").strip() or "1"
    steps_mode = "default" if sm=="1" else "custom"
    print("Default steps preview:")
    for ln in default_plain_steps_lines(ev["platform"]): print(ln)
    print("Enter extra/custom steps (one per line). '.' ends input:")
    plain = []
    while True:
        ln = input()
        if ln.strip()==".": break
        if ln.strip(): plain.append(ln.strip())
    observed = input("Observed (optional): ").strip()
    expected = input("Expected (optional): ").strip()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.stem}.bak-{stamp}{path.suffix}")
    backup.write_text(txt, encoding="utf-8")
    updated = append_bug_and_move_issue(txt, ev, prefix, steps_mode, plain, observed, expected)
    path.write_text(updated, encoding="utf-8")
    print(f"✓ Bug generated. Backup: {backup.name}")

def run_cli():
    path = cli_setup_or_open()
    while True:
        print("\n1) Notes  2) Bugs  3) Path  4) Quit")
        c = input("> ").strip()
        if c=="1": cli_notes_mode(path)
        elif c=="2": cli_bugs_mode(path)
        elif c=="3": print(path)
        elif c=="4": break

# ================= GUI =================
def copy_to_system(text: str):
    if not TK_AVAILABLE: return
    data = (text or "").encode("utf-8")
    try:
        if sys.platform == "darwin":
            p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            p.communicate(data); return
        elif sys.platform.startswith("win"):
            p = subprocess.Popen(["clip"], stdin=subprocess.PIPE)
            p.communicate((text or "").replace("\n","\r\n").encode("utf-16le")); return
    except Exception:
        pass
    try:
        root = tk._default_root
        if root is not None:
            root.clipboard_clear(); root.clipboard_append(text or ""); root.update()
    except Exception:
        pass

if TK_AVAILABLE:
    class WrappedListboxSingle(ttk.Frame):
        """Single-select Listbox that wraps long items and reflows on resize."""
        def __init__(self, master, wrap_margin_chars=80, **kwargs):
            super().__init__(master)
            self.wrap_margin_chars = wrap_margin_chars
            self.font = tkfont.nametofont("TkTextFont")
            self.listbox = tk.Listbox(self, selectmode="browse", activestyle="none", exportselection=False, **kwargs)
            self.scroll = ttk.Scrollbar(self, orient="vertical", command=self.listbox.yview)
            self.listbox.config(yscrollcommand=self.scroll.set)
            self.listbox.grid(row=0, column=0, sticky="nsew", padx=(0,4))
            self.scroll.grid(row=0, column=1, sticky="ns")
            self.rowconfigure(0, weight=1); self.columnconfigure(0, weight=1)
            self.items = []; self.lines_map = []; self.blank_between = True
            self.listbox.bind("<<ListboxSelect>>", self._on_select)
            self.bind("<Configure>", self._on_resize)
            self.on_change = None

        def _calc_wrap_chars(self):
            try:
                px = self.listbox.winfo_width()
                cw = self.font.measure("0") or 7
                cols = max(20, int(px / cw) - 2)
            except Exception:
                cols = self.wrap_margin_chars
            return cols

        def set_items(self, items):
            self.items = list(items)
            self._render()

        def _render(self):
            cols = self._calc_wrap_chars()
            lb = self.listbox
            lb.delete(0, "end")
            self.lines_map = []
            for idx, text in enumerate(self.items):
                wrapped = textwrap.fill(text, width=cols)
                lines = wrapped.splitlines() if wrapped else [""]
                for _j, line in enumerate(lines):
                    lb.insert("end", line)
                    self.lines_map.append(idx)
                if self.blank_between and idx != len(self.items) - 1:
                    lb.insert("end", "")
                    self.lines_map.append(None)
            if lb.size() > 0: lb.selection_clear(0, "end")

        def _on_resize(self, _evt):
            self.after(50, self._render)

        def _on_select(self, _evt):
            sels = self.listbox.curselection()
            if not sels:
                if self.on_change: self.on_change(None); return
            vis_idx = sels[0]
            item_idx = self._find_item_from_visual(vis_idx)
            if item_idx is None:
                if self.on_change: self.on_change(None); return
            first_vis = self._first_visual_for_item(item_idx)
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(first_vis); self.listbox.activate(first_vis)
            if self.on_change: self.on_change(item_idx)

        def _find_item_from_visual(self, vis_idx):
            if 0 <= vis_idx < len(self.lines_map): return self.lines_map[vis_idx]
            return None

        def _first_visual_for_item(self, item_idx):
            for i, val in enumerate(self.lines_map):
                if val == item_idx: return i
            return 0

        def get_selection(self):
            sels = self.listbox.curselection()
            if not sels: return None
            vis_idx = sels[0]
            return self._find_item_from_visual(vis_idx)

        def get_item(self, idx): return self.items[idx]

    def grid_fill(w, r, c, **kw): w.grid(row=r, column=c, sticky="nsew", **kw)

    class SetupWizard(ttk.Frame):
        def __init__(self, master, on_done):
            super().__init__(master)
            self.on_done = on_done
            self.grid(row=0, column=0, sticky="nsew")
            self.master.rowconfigure(0, weight=1); self.master.columnconfigure(0, weight=1)

            grid_fill(ttk.Label(self, text="Bug Notes Assistant — Setup", font=("TkDefaultFont",14,"bold")), 0, 0, padx=12, pady=(12,8))
            btns = ttk.Frame(self); grid_fill(btns, 1, 0, padx=12, pady=(0,10))
            ttk.Button(btns, text="📄 New Notes File", command=self.new_file_flow).pack(side="left")
            ttk.Button(btns, text="📂 Open Existing File…", command=self.open_existing).pack(side="left", padx=8)
            self.status = tk.StringVar(value="Create a new file for today or open an existing one.")
            grid_fill(ttk.Label(self, textvariable=self.status), 2, 0, padx=12, pady=(6,12))
            self.rowconfigure(3, weight=1)

        def open_existing(self):
            p = filedialog.askopenfilename(title="Open notes file", filetypes=[("Markdown","*.md"),("All files","*.*")])
            if not p: return
            path = Path(p).expanduser().resolve()
            if not path.exists(): messagebox.showerror("Not found", f"{path} does not exist."); return
            txt = path.read_text(encoding="utf-8")
            upd = find_or_create_sections(txt)
            if upd != txt: path.write_text(upd, encoding="utf-8")
            self.on_done(path)

        def new_file_flow(self):
            NewFileDialog(self, self.on_done)

    class NewFileDialog(tk.Toplevel):
        def __init__(self, master, on_done):
            super().__init__(master)
            self.title("New Notes File"); self.resizable(True, True); self.grab_set()
            self.on_done = on_done
            frm = ttk.Frame(self); frm.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
            self.rowconfigure(0, weight=1); self.columnconfigure(0, weight=1)

            self.date_var = tk.StringVar(value=datetime.now().strftime("%m-%d-%Y"))
            self.dir_var = tk.StringVar(value=str(Path(".").resolve()))
            row=0
            ttk.Label(frm, text="Date (mm-dd-yyyy):").grid(row=row, column=0, sticky="e")
            ttk.Entry(frm, textvariable=self.date_var, width=14).grid(row=row, column=1, sticky="w", padx=6)
            ttk.Button(frm, text="Choose Folder…", command=self._choose).grid(row=row, column=2, sticky="w")
            ttk.Label(frm, textvariable=self.dir_var).grid(row=row, column=3, sticky="w", padx=6); row+=1

            ttk.Label(frm, text="Usernames (optional):", font=("TkDefaultFont",10,"bold")).grid(row=row, column=0, columnspan=4, sticky="w", pady=(8,2)); row+=1
            self.user_vars = {}
            for p in ALL_PLATFORMS:
                ttk.Label(frm, text=f"{p}:").grid(row=row, column=0, sticky="e")
                v=tk.StringVar(value="")
                ttk.Entry(frm, textvariable=v, width=14).grid(row=row, column=1, sticky="w", padx=6, pady=1)  # narrower
                self.user_vars[p]=v; row+=1

            ttk.Label(frm, text="Build numbers (digits):", font=("TkDefaultFont",10,"bold")).grid(row=row, column=0, columnspan=4, sticky="w", pady=(8,2)); row+=1
            self.gen4_var=tk.StringVar(value=""); self.gen5_var=tk.StringVar(value="")
            ttk.Label(frm, text="gen4:").grid(row=row, column=0, sticky="e")
            ttk.Entry(frm, textvariable=self.gen4_var, width=10).grid(row=row, column=1, sticky="w", padx=6)
            ttk.Label(frm, text="gen5:").grid(row=row, column=2, sticky="e")
            ttk.Entry(frm, textvariable=self.gen5_var, width=10).grid(row=row, column=3, sticky="w", padx=6); row+=1

            btns=ttk.Frame(frm); btns.grid(row=row, column=0, columnspan=4, sticky="e", pady=(10,0))
            ttk.Button(btns, text="Create", command=self._create).pack(side="right", padx=6)
            ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right")

        def _choose(self):
            d = filedialog.askdirectory(initialdir=self.dir_var.get())
            if d: self.dir_var.set(d)

        def _create(self):
            try:
                date_str = (self.date_var.get() or datetime.now().strftime("%m-%d-%Y")).strip()
                base = Path(self.dir_var.get()).expanduser().resolve() / f"{date_str}-notes.md"
                base.parent.mkdir(parents=True, exist_ok=True)
                usernames = {p:v.get().strip() for p,v in self.user_vars.items() if v.get().strip()}
                txt = header_block(date_str, usernames, self.gen4_var.get(), self.gen5_var.get())
                base.write_text(txt, encoding="utf-8")
                self.on_done(base); self.destroy()
            except Exception as e:
                messagebox.showerror("Error", str(e))

    class MainApp(ttk.Frame):
        def __init__(self, master, notes_path: Path):
            super().__init__(master); self.grid(row=0, column=0, sticky="nsew")
            master.rowconfigure(0, weight=1); master.columnconfigure(0, weight=1)
            self.notes_path = notes_path

            hdr=ttk.Frame(self); grid_fill(hdr, 0,0, padx=10, pady=8)
            ttk.Label(hdr, text=f"File: {notes_path.name}", font=("TkDefaultFont",12,"bold")).pack(side="left")
            ttk.Button(hdr, text="Open Different File…", command=self.change_file).pack(side="right")

            self.nb = ttk.Notebook(self); grid_fill(self.nb, 1,0, padx=10, pady=(0,10))
            self.rowconfigure(1, weight=1); self.columnconfigure(0, weight=1)

            self.header_tab = HeaderTab(self.nb, self); self.nb.add(self.header_tab, text="Header ✏️")
            self.issues_tab = IssuesTab(self.nb, self); self.nb.add(self.issues_tab, text="Issues found 🕵️‍♂️")
            self.found_tab  = FoundTab(self.nb, self);  self.nb.add(self.found_tab,  text="Found / Invalid 🗂️")
            self.bugs_tab   = BugsTab(self.nb, self);   self.nb.add(self.bugs_tab,   text="Bugs 🐛")
            self.copier_tab = BugsWrittenTab(self.nb, self); self.nb.add(self.copier_tab, text="Bugs written 🧾")

        def change_file(self):
            p = filedialog.askopenfilename(title="Open notes file", filetypes=[("Markdown","*.md"),("All files","*.*")])
            if not p: return
            path = Path(p).expanduser().resolve()
            if not path.exists(): messagebox.showerror("Not found", f"{path} does not exist."); return
            txt = path.read_text(encoding="utf-8"); upd = find_or_create_sections(txt)
            if upd != txt: path.write_text(upd, encoding="utf-8")
            self.notes_path = path
            self.header_tab.refresh(); self.issues_tab.refresh(); self.found_tab.refresh(); self.bugs_tab.refresh(); self.copier_tab.refresh()

    class HeaderTab(ttk.Frame):
        def __init__(self, master, app: MainApp):
            super().__init__(master); self.app = app
            self.grid_columnconfigure(0, weight=1); self.grid_rowconfigure(1, weight=1)
            frm=ttk.Frame(self); grid_fill(frm,0,0, padx=10, pady=10)
            ttk.Label(frm, text="Date:").grid(row=0,column=0,sticky="e")
            self.date_var=tk.StringVar(value=""); ttk.Entry(frm,textvariable=self.date_var,width=14,state="readonly").grid(row=0,column=1,sticky="w",padx=6)
            ttk.Label(frm, text="gen4 build:").grid(row=0,column=2,sticky="e"); self.gen4_var=tk.StringVar(value="")
            ttk.Entry(frm,textvariable=self.gen4_var,width=10).grid(row=0,column=3,sticky="w",padx=6)
            ttk.Label(frm, text="gen5 build:").grid(row=0,column=4,sticky="e"); self.gen5_var=tk.StringVar(value="")
            ttk.Entry(frm,textvariable=self.gen5_var,width=10).grid(row=0,column=5,sticky="w",padx=6)

            grid=ttk.Frame(self); grid_fill(grid,1,0, padx=10, pady=(0,10))
            self.user_vars={}; r=0
            for p in ALL_PLATFORMS:
                ttk.Label(grid, text=f"{p}:").grid(row=r,column=0,sticky="e")
                v=tk.StringVar(value="")
                ttk.Entry(grid,textvariable=v,width=14).grid(row=r,column=1,sticky="w",padx=6,pady=2)  # narrower inputs
                self.user_vars[p]=v; r+=1

            btns=ttk.Frame(self); grid_fill(btns,2,0, padx=10, pady=(0,10))
            ttk.Button(btns, text="Reload", command=self.refresh).pack(side="left")
            ttk.Button(btns, text="Save Header", command=self.save_header).pack(side="right")
            self.refresh()

        def refresh(self):
            if not self.app.notes_path.exists(): return
            text=self.app.notes_path.read_text(encoding="utf-8")
            date_str,_=parse_date_and_header_end(text); self.date_var.set(date_str or "")
            g4,g5=parse_builds(text); self.gen4_var.set(g4); self.gen5_var.set(g5)
            un=parse_usernames(text)
            for p in ALL_PLATFORMS: self.user_vars[p].set(un.get(p,""))

        def save_header(self):
            try:
                text=self.app.notes_path.read_text(encoding="utf-8")
                usernames={p:v.get().strip() for p,v in self.user_vars.items() if v.get().strip()}
                new_text=replace_header(text, usernames, self.gen4_var.get().strip(), self.gen5_var.get().strip())
                self.app.notes_path.write_text(new_text, encoding="utf-8")
                messagebox.showinfo("Saved","Header updated.")
                self.app.issues_tab.refresh(); self.app.found_tab.refresh(); self.app.bugs_tab.refresh(); self.app.copier_tab.refresh()
            except Exception as e:
                messagebox.showerror("Error", str(e))

    class IssuesTab(ttk.Frame):
        def __init__(self, master, app: MainApp):
            super().__init__(master); self.app=app
            self.grid_columnconfigure(0, weight=1); self.grid_rowconfigure(0, weight=1)

            pan=ttk.PanedWindow(self, orient="horizontal"); grid_fill(pan,0,0, padx=8, pady=8)
            left=ttk.Frame(pan); right=ttk.LabelFrame(pan, text="Add issue")
            pan.add(left, weight=3); pan.add(right, weight=2)

            left.grid_columnconfigure(0, weight=1); left.grid_rowconfigure(1, weight=1)
            ttk.Label(left, text="Issues").grid(row=0,column=0,sticky="w")
            self.wlist=WrappedListboxSingle(left)
            self.wlist.grid(row=1,column=0,sticky="nsew", padx=(0,2), pady=(4,6))
            self.wlist.on_change = lambda idx: None

            btns=ttk.Frame(left); btns.grid(row=2,column=0,sticky="w", pady=(0,4))
            ttk.Button(btns, text="Refresh", command=self.refresh).pack(side="left")
            ttk.Button(btns, text="Copy", command=self.copy_desc_only).pack(side="left", padx=8)
            ttk.Button(btns, text="Found / Invalid", command=self.move_to_found).pack(side="left")
            ttk.Button(btns, text="Remove", command=self.remove_issue).pack(side="left", padx=8)

            right.grid_columnconfigure(1, weight=1)
            ttk.Label(right, text="Platform:").grid(row=0,column=0,sticky="w",padx=8,pady=(8,2))
            self.platform_var=tk.StringVar(value="ps5")
            ttk.Combobox(right,textvariable=self.platform_var,values=ALL_PLATFORMS,state="readonly",width=12)\
                .grid(row=0,column=1,sticky="we",padx=8,pady=(8,2))
            ttk.Label(right, text="Time (optional):").grid(row=1,column=0,sticky="w",padx=8,pady=2)
            self.time_var=tk.StringVar(value="")
            ttk.Entry(right,textvariable=self.time_var,width=12).grid(row=1,column=1,sticky="w",padx=8,pady=2)
            ttk.Label(right, text="Short description:").grid(row=2,column=0,sticky="nw",padx=8,pady=(8,2))
            self.desc_txt=tk.Text(right,height=8,wrap="word"); self.desc_txt.grid(row=2,column=1,sticky="nsew",padx=8,pady=(8,2))
            right.grid_rowconfigure(2, weight=1)
            ttk.Button(right, text="Add to 'issues found'",command=self.add_issue).grid(row=3,column=1,sticky="e",padx=8,pady=(8,10))
            self.refresh()

        def refresh(self):
            if not self.app.notes_path.exists(): return
            text=self.app.notes_path.read_text(encoding="utf-8"); text=find_or_create_sections(text)
            self.events=issues_list(text)
            self.wlist.set_items([f"[{e['time']}][{e['platform']}] {e['desc']}" for e in self.events])

        def _current_event(self):
            idx=self.wlist.get_selection()
            if idx is None: return None
            return self.events[idx]

        def copy_desc_only(self):
            ev=self._current_event()
            if not ev: return
            copy_to_system(f"[{ev['platform']}] {ev['desc']}")

        def move_to_found(self):
            ev=self._current_event()
            if not ev: return
            try:
                text=self.app.notes_path.read_text(encoding="utf-8"); text=find_or_create_sections(text)
                bugnum=simpledialog.askstring("Optional Bug Number","Enter bug number (leave blank if none):")
                new_text=move_issue_to_found(text, ev, bugnum or "")
                self.app.notes_path.write_text(new_text, encoding="utf-8")
                self.refresh(); self.master.master.found_tab.refresh()
            except Exception as e:
                messagebox.showerror("Error", str(e))

        def remove_issue(self):
            ev=self._current_event()
            if not ev: return
            if not messagebox.askyesno("Remove", "Delete this issue from 'issues found'?"): return
            try:
                text=self.app.notes_path.read_text(encoding="utf-8")
                new_text=delete_issue_line(text, ev)
                self.app.notes_path.write_text(new_text, encoding="utf-8")
                self.refresh()
            except Exception as e:
                messagebox.showerror("Error", str(e))

        def add_issue(self):
            desc=self.desc_txt.get("1.0","end").strip()
            if not desc: messagebox.showwarning("Missing","Enter a short description."); return
            platform=self.platform_var.get().strip().lower()
            time_str=self.time_var.get().strip()
            try:
                txt=self.app.notes_path.read_text(encoding="utf-8")
                new_txt=add_issue_line(txt, time_str, platform, desc)
                self.app.notes_path.write_text(new_txt, encoding="utf-8")
                self.desc_txt.delete("1.0","end"); self.time_var.set("")
                self.refresh()
            except Exception as e:
                messagebox.showerror("Error", str(e))

    class FoundTab(ttk.Frame):
        def __init__(self, master, app: MainApp):
            super().__init__(master); self.app=app
            self.grid_columnconfigure(0, weight=1); self.grid_rowconfigure(0, weight=1)

            pan=ttk.PanedWindow(self, orient="horizontal"); grid_fill(pan,0,0, padx=8, pady=8)
            left=ttk.Frame(pan); right=ttk.LabelFrame(pan, text="Tag / Copy")
            pan.add(left, weight=3); pan.add(right, weight=2)

            left.grid_columnconfigure(0, weight=1); left.grid_rowconfigure(1, weight=1)
            ttk.Label(left, text="Found / Invalid issues:").grid(row=0,column=0,sticky="w")
            self.wlist = WrappedListboxSingle(left)
            self.wlist.grid(row=1,column=0,sticky="nsew", padx=6, pady=(4,8))
            ttk.Button(left, text="Refresh", command=self.refresh).grid(row=2,column=0,sticky="w")
            self.wlist.on_change = lambda idx: self.on_select(idx)

            right.grid_columnconfigure(1, weight=1)
            r=0
            ttk.Label(right, text="Selected:").grid(row=r,column=0,sticky="w",padx=8,pady=(8,2))
            self.sel_var=tk.StringVar(value=""); ttk.Entry(right,textvariable=self.sel_var,state="readonly").grid(row=r,column=1,sticky="we",padx=8,pady=(8,2)); r+=1

            ttk.Label(right, text="Bug number tag:").grid(row=r,column=0,sticky="w",padx=8,pady=(8,2))
            self.bugnum_var=tk.StringVar(value=""); ttk.Entry(right,textvariable=self.bugnum_var).grid(row=r,column=1,sticky="we",padx=8,pady=(8,2)); r+=1

            rowbtns=ttk.Frame(right); rowbtns.grid(row=r,column=1,sticky="w",padx=8,pady=(8,4))
            ttk.Button(rowbtns,text="Set",command=self.set_tag).pack(side="left",padx=4)
            r+=1

            ttk.Button(right, text="Copy (strike summary)", command=self.copy_markdown_strike).grid(row=r,column=1,sticky="w",padx=8,pady=(0,10))

            self.items=[]; self.refresh()

        def refresh(self):
            self.items=[]
            if not self.app.notes_path.exists():
                self.sel_var.set(""); self.bugnum_var.set(""); self.wlist.set_items([]); return
            text=self.app.notes_path.read_text(encoding="utf-8"); text=find_or_create_sections(text)
            self.items=found_list(text)
            labels=[]
            for it in self.items:
                left=(f"[{it['bugnum']}] " if it["bugnum"] else "")
                labels.append(f"{left}[{it['time']}][{it['platform']}] {it['desc']}")
            self.wlist.set_items(labels)
            self.sel_var.set(""); self.bugnum_var.set("")

        def on_select(self, idx):
            if idx is None: self.sel_var.set(""); self.bugnum_var.set(""); return
            it=self.items[idx]
            self.sel_var.set((f"[{it['bugnum']}] " if it["bugnum"] else "") + f"[{it['time']}][{it['platform']}] {it['desc']}")
            self.bugnum_var.set(it["bugnum"])

        def _rewrite_found_line(self, text: str, item: dict, new_bugnum: str | None):
            lines=text.splitlines(); b=_section_bounds(lines, FOUND_HEADERS)
            if not b: return text
            start,end=b
            target_re = re.compile(
                rf"^\- (?:\[(?P<num>[^\]]+)\]\s+)?\[{re.escape(item['time'])}\]\[{re.escape(item['platform'])}\]\s+{re.escape(item['desc'])}\s*$",
                re.IGNORECASE
            )
            for i in range(start,end):
                m=target_re.match(lines[i].strip())
                if m:
                    base=f"- [{item['time']}][{item['platform']}] {item['desc']}"
                    if new_bugnum and new_bugnum.strip():
                        lines[i] = f"- [{new_bugnum.strip()}] {base[2:]}"
                    else:
                        lines[i] = base
                    break
            out="\n".join(lines)
            if not out.endswith("\n"): out+="\n"
            return out

        def set_tag(self):
            idx=self.wlist.get_selection()
            if idx is None: return
            it=self.items[idx]
            new_tag=self.bugnum_var.get().strip()
            try:
                text=self.app.notes_path.read_text(encoding="utf-8")
                new_text=self._rewrite_found_line(text, it, new_tag)
                self.app.notes_path.write_text(new_text, encoding="utf-8")
                self.refresh()
            except Exception as e:
                messagebox.showerror("Error", str(e))

        def copy_markdown_strike(self):
            idx=self.wlist.get_selection()
            if idx is None: return
            it=self.items[idx]
            tag=f"[{it['bugnum']}]" if it["bugnum"] else "[]"
            copy_to_system(f"{tag} ~~{it['desc']}~~")

    class BugsTab(ttk.Frame):
        def __init__(self, master, app: MainApp):
            super().__init__(master); self.app=app
            self.grid_columnconfigure(0, weight=1); self.grid_rowconfigure(0, weight=1)
            self._last_autofill=""

            pan=ttk.PanedWindow(self, orient="horizontal"); grid_fill(pan,0,0, padx=8, pady=8)
            left=ttk.Frame(pan); right=ttk.LabelFrame(pan, text="Bug details")
            pan.add(left, weight=3); pan.add(right, weight=2)

            left.grid_columnconfigure(0, weight=1); left.grid_rowconfigure(1, weight=1)
            ttk.Label(left, text="Select issue to convert:").grid(row=0,column=0,sticky="w")
            self.wlist=WrappedListboxSingle(left)
            self.wlist.grid(row=1,column=0,sticky="nsew", padx=(0,2), pady=(4,4))
            self.wlist.on_change = lambda idx: self._post_select(idx)
            ttk.Button(left,text="Refresh",command=self.refresh).grid(row=2,column=0,sticky="w",pady=(0,8))

            right.grid_columnconfigure(1, weight=1)
            r=0
            ttk.Label(right, text="Summary prefix (optional):").grid(row=r,column=0,sticky="w",padx=8,pady=(8,2))
            self.prefix_var=tk.StringVar(value=""); ttk.Entry(right,textvariable=self.prefix_var).grid(row=r,column=1,sticky="we",padx=8,pady=(8,2)); r+=1

            ttk.Label(right, text="Steps mode:").grid(row=r,column=0,sticky="w",padx=8)
            self.steps_mode=tk.StringVar(value="default")
            self.rb_default=ttk.Radiobutton(right,text="Default steps (base + your lines)",variable=self.steps_mode,value="default")
            self.rb_custom =ttk.Radiobutton(right,text="Custom steps (start from step 1)",variable=self.steps_mode,value="custom",command=self._on_custom_selected)
            self.rb_default.grid(row=r,column=1,sticky="w",padx=8); r+=1
            self.rb_custom.grid(row=r,column=1,sticky="w",padx=8);  r+=1

            ttk.Label(right, text="Steps").grid(row=r,column=0,sticky="nw",padx=8,pady=(8,2))
            self.steps_txt=tk.Text(right,height=8,wrap="word"); self.steps_txt.grid(row=r,column=1,sticky="nsew",padx=8,pady=(8,2))
            right.grid_rowconfigure(r, weight=1); self.steps_txt.bind("<KeyRelease>", self._on_steps_key); r+=1

            ttk.Label(right, text="Observed Results (optional):").grid(row=r,column=0,sticky="nw",padx=8,pady=(8,2))
            self.obs_txt=tk.Text(right,height=4,wrap="word"); self.obs_txt.grid(row=r,column=1,sticky="nsew",padx=8,pady=(8,2)); r+=1

            ttk.Label(right, text="Expected Results (optional):").grid(row=r,column=0,sticky="nw",padx=8,pady=(8,2))
            self.exp_txt=tk.Text(right,height=4,wrap="word"); self.exp_txt.grid(row=r,column=1,sticky="nsew",padx=8,pady=(8,2)); r+=1

            ttk.Button(right,text="Generate Bug",command=self.generate_bug).grid(row=r,column=1,sticky="e",padx=8,pady=(8,10))
            self.refresh()

        def _on_custom_selected(self):
            self.steps_txt.delete("1.0","end"); self._last_autofill=""

        def _autofill_default_steps_if_empty(self, platform: str):
            if self.steps_txt.get("1.0","end").strip(): return
            lines=default_plain_steps_lines(platform); default_text="\n".join(lines)
            self._last_autofill=default_text.strip(); self.steps_mode.set("default")
            self.steps_txt.delete("1.0","end"); self.steps_txt.insert("1.0", default_text)

        def _on_steps_key(self,_=None):
            current=self.steps_txt.get("1.0","end").strip()
            if self.steps_mode.get()=="default" and self._last_autofill and current != self._last_autofill:
                self.steps_mode.set("custom")

        def refresh(self):
            if not self.app.notes_path.exists(): return
            text=self.app.notes_path.read_text(encoding="utf-8"); text=find_or_create_sections(text)
            self.events=issues_list(text)
            self.wlist.set_items([f"[{e['time']}][{e['platform']}] {e['desc']}" for e in self.events])

        def _post_select(self, idx):
            if idx is None: return
            ev=self.events[idx]
            self._autofill_default_steps_if_empty(ev["platform"])

        def generate_bug(self):
            idx=self.wlist.get_selection()
            if idx is None:
                messagebox.showinfo("Pick issue", "Select one issue to convert."); return
            ev=self.events[idx]
            prefix=self.prefix_var.get().strip()
            steps_mode=self.steps_mode.get()
            plain_lines=[ln.strip() for ln in self.steps_txt.get("1.0","end").splitlines() if ln.strip()]
            observed=self.obs_txt.get("1.0","end").strip()
            expected=self.exp_txt.get("1.0","end").strip()
            try:
                original=self.app.notes_path.read_text(encoding="utf-8")
                stamp=datetime.now().strftime("%Y%m%d-%H%M%S")
                backup=self.app.notes_path.with_name(f"{self.app.notes_path.stem}.bak-{stamp}{self.app.notes_path.suffix}")
                backup.write_text(original, encoding="utf-8")
                updated=append_bug_and_move_issue(original, ev, prefix, steps_mode, plain_lines, observed, expected)
                self.app.notes_path.write_text(updated, encoding="utf-8")
                messagebox.showinfo("Done", f"Generated 1 bug. Backup: {backup.name}")
                # Clear fields after generate
                self.prefix_var.set("")
                self.steps_txt.delete("1.0","end"); self._last_autofill=""
                self.obs_txt.delete("1.0","end"); self.exp_txt.delete("1.0","end")
                self.refresh(); self.master.master.issues_tab.refresh(); self.master.master.copier_tab.refresh()
            except Exception as e:
                messagebox.showerror("Error", str(e))

    class BugsWrittenTab(ttk.Frame):
        def __init__(self, master, app: MainApp):
            super().__init__(master); self.app=app
            self.grid_columnconfigure(0, weight=1); self.grid_rowconfigure(0, weight=1)

            pan = ttk.PanedWindow(self, orient="horizontal")
            grid_fill(pan, 0, 0, padx=10, pady=10)

            # Left: wrapped single-select list
            left = ttk.Frame(pan)
            left.grid_columnconfigure(0, weight=1); left.grid_rowconfigure(1, weight=1)
            ttk.Label(left, text="Bugs written (from 'Bugs 🐛' section):").grid(row=0, column=0, sticky="w")
            self.wlist = WrappedListboxSingle(left)
            self.wlist.grid(row=1, column=0, sticky="nsew", pady=(4, 8))
            lbbtns = ttk.Frame(left); lbbtns.grid(row=2, column=0, sticky="w")
            ttk.Button(lbbtns, text="Refresh", command=self.refresh).pack(side="left")
            self.wlist.on_change = lambda idx: self._update_selection(idx)
            pan.add(left, weight=3)

            # Right: Copy / Tag area
            right = ttk.LabelFrame(pan, text="Copy / Tag")
            for c in (0, 1, 2):
                right.grid_columnconfigure(c, weight=1 if c == 1 else 0)

            r = 0
            # 1) Bug number row
            ttk.Label(right, text="Bug number:").grid(row=r, column=0, sticky="w", padx=6, pady=(8, 2))
            self.bugnum_var = tk.StringVar(value="")
            self.bugnum_entry = ttk.Entry(right, textvariable=self.bugnum_var, width=20)
            self.bugnum_entry.grid(row=r, column=1, sticky="w", padx=6, pady=(8, 2))
            rowbtns = ttk.Frame(right); rowbtns.grid(row=r, column=2, sticky="w", padx=6)
            ttk.Button(rowbtns, text="Set", command=self.set_bugnum).pack(side="left", padx=(0, 6))
            r += 1

            # 2) Summary row + copy buttons
            ttk.Label(right, text="Summary:").grid(row=r, column=0, sticky="w", padx=6, pady=(6, 2))
            self.summary_var = tk.StringVar(value="")
            self.summary_entry = ttk.Entry(right, textvariable=self.summary_var, state="readonly", width=70, exportselection=False)
            self.summary_entry.grid(row=r, column=1, sticky="we", padx=6, pady=(6, 2))
            sum_btns = ttk.Frame(right); sum_btns.grid(row=r, column=2, sticky="w", padx=6)
            ttk.Button(sum_btns, text="Copy", command=self.copy_summary_no_empty_brackets).pack(side="left", padx=(0,6))
            ttk.Button(sum_btns, text="Copy #+Summary", command=self.copy_bugnum_and_summary).pack(side="left")
            r += 1

            # 3) Report block + copy
            ttk.Label(right, text="Report:").grid(row=r, column=0, sticky="nw", padx=6, pady=(8, 2))
            self.report_txt = tk.Text(right, width=70, height=16, state="disabled", exportselection=False, wrap="word")
            self.report_txt.grid(row=r, column=1, sticky="nsew", padx=6, pady=(8, 2))
            rep_btns = ttk.Frame(right); rep_btns.grid(row=r, column=2, sticky="nw", padx=6, pady=(8, 2))
            ttk.Button(rep_btns, text="Copy", command=lambda: copy_to_system(self.report_txt.get("1.0", "end").strip())).pack(side="top", anchor="w")
            r += 1

            # 4) Username row
            ttk.Label(right, text="Username:").grid(row=r, column=0, sticky="w", padx=6, pady=(6, 2))
            self.user_val = tk.StringVar(value="")
            self.user_entry = ttk.Entry(right, textvariable=self.user_val, state="readonly", width=30)
            self.user_entry.grid(row=r, column=1, sticky="w", padx=6, pady=(6, 2))
            user_btns = ttk.Frame(right); user_btns.grid(row=r, column=2, sticky="w", padx=6)
            ttk.Button(user_btns, text="Copy", command=lambda: copy_to_system(self.user_val.get().strip())).pack(side="left")
            r += 1

            # 5) Build row
            ttk.Label(right, text="Build#:").grid(row=r, column=0, sticky="w", padx=6, pady=(6, 10))
            self.build_val = tk.StringVar(value="")
            self.build_entry = ttk.Entry(right, textvariable=self.build_val, state="readonly", width=20)
            self.build_entry.grid(row=r, column=1, sticky="w", padx=6, pady=(6, 10))
            build_btns = ttk.Frame(right); build_btns.grid(row=r, column=2, sticky="w", padx=6)
            ttk.Button(build_btns, text="Copy", command=lambda: copy_to_system(self.build_val.get().strip())).pack(side="left")
            r += 1

            # 6) Edit/Save at the bottom (affects all fields)
            self.edit_btn = ttk.Button(right, text="Edit / Save", command=self.toggle_edit)
            self.edit_btn.grid(row=r, column=1, sticky="e", padx=6, pady=(8, 10))
            r += 1

            pan.add(right, weight=4)

            self.bugs=[]; self.selected_idx=None
            self.refresh()

        def refresh(self):
            self.wlist.set_items([])
            self.bugs=[]
            if not self.app.notes_path.exists():
                self._clear_fields(); return
            text=self.app.notes_path.read_text(encoding="utf-8"); text=find_or_create_sections(text)
            self.bugs=list_bugs(text)
            labels=[]
            for b in self.bugs:
                time_tag = f"[{b['time']}]"
                bug_tag  = f"[{b['bugnum']}]" if b["bugnum"] else ""
                plat_tag = f"[{b['platform']}]"
                labels.append(f"{time_tag}{bug_tag}{plat_tag} {b['summary'] or '(no summary)'}")
            self.wlist.set_items(labels)
            self.selected_idx=None; self._clear_fields()

        def _clear_fields(self):
            self.summary_var.set(""); self._set_report(""); self.bugnum_var.set(""); self.user_val.set(""); self.build_val.set("")
            self._set_report_state(False)

        def _update_selection(self, idx):
            self.selected_idx=idx
            if idx is None: self._clear_fields(); return
            bug=self.bugs[idx]
            self.summary_var.set(bug["summary"])
            self._set_report(self._compose_report(bug))
            self.bugnum_var.set(bug["bugnum"])

            # Username: prefer bug block's value; fallback to Header mapping if empty
            full = self.app.notes_path.read_text(encoding="utf-8")
            header_users = parse_usernames(full)
            bug_username = (bug.get("username") or "").strip()
            if bug_username:
                self.user_val.set(bug_username)
            else:
                self.user_val.set(header_users.get(bug["platform"], ""))

            # Build line from bug block (already parsed)
            self.build_val.set(bug.get("build",""))

        def _compose_report(self, bug):
            def ensure_label(text,label):
                t=(text or "").lstrip()
                if not t: return f"{label}:\n"
                if re.match(rf"(?i)^{re.escape(label)}\s*:", t): return t
                return f"{label}:\n{t}"
            parts=[]
            if bug["steps"]: parts.append(bug["steps"])
            parts.append(ensure_label(bug["observed"],"Observed Results"))
            parts.append(ensure_label(bug["expected"],"Expected Results"))
            return "\n\n".join(parts).strip()

        def _set_report(self,text):
            self.report_txt.config(state="normal"); self.report_txt.delete("1.0","end"); self.report_txt.insert("1.0",text); self.report_txt.config(state="disabled")

        def _set_report_state(self, editing: bool):
            self.editing = editing
            state = "normal" if editing else "readonly"
            self.summary_entry.config(state=state)
            self.user_entry.config(state=state)
            self.build_entry.config(state=state)
            self.report_txt.config(state=("normal" if editing else "disabled"))

        def toggle_edit(self):
            if self.selected_idx is None: return
            if not getattr(self, "editing", False):
                self._set_report_state(True)
                self.edit_btn.config(text="Save")
            else:
                # Save changes back to markdown
                bug=self.bugs[self.selected_idx]
                new_summary = self.summary_var.get().strip()

                # Parse the report text into steps/observed/expected
                txt = self.report_txt.get("1.0","end").strip()
                steps = ""
                observed = ""
                expected = ""
                m_obs = re.search(r"(?mi)^Observed Results:\s*", txt)
                m_exp = re.search(r"(?mi)^Expected Results:\s*", txt)
                if m_obs and m_exp:
                    steps = txt[:m_obs.start()].rstrip()
                    observed = txt[m_obs.end():m_exp.start()].strip()
                    expected = txt[m_exp.end():].strip()
                else:
                    # Fallback: treat all as observed if split fails
                    observed = txt

                # Ensure steps block header is present + numbered
                if not re.search(r"(?mi)^Steps to Reproduce:\s*", steps):
                    lines = [ln.strip() for ln in steps.splitlines() if ln.strip()]
                    nlines = ["Steps to Reproduce:"]
                    for i, ln in enumerate(lines, start=1):
                        nlines.append(f"{i}. {ln}")
                    if len(nlines) == 1: nlines.append("1. ")
                    steps_block = "\n".join(nlines)
                else:
                    steps_block = steps

                # Build & Username fields (username may be empty)
                new_build = self.build_val.get().strip() or None
                new_username = self.user_val.get().strip()

                try:
                    full = self.app.notes_path.read_text(encoding="utf-8")
                    new_text = write_bug_content(full, bug["id"], new_summary, steps_block, observed, expected, new_build, new_username)
                    # Also set bug number in meta/header if changed:
                    new_bugnum = (self.bugnum_var.get() or "").strip()
                    if new_bugnum != bug["bugnum"]:
                        new_text = write_bug_meta_bugnum(new_text, bug["id"], new_bugnum if new_bugnum else None)
                    self.app.notes_path.write_text(new_text, encoding="utf-8")
                    self._set_report_state(False)
                    self.edit_btn.config(text="Edit / Save")
                    self.refresh()
                except Exception as e:
                    messagebox.showerror("Error", str(e))

        def set_bugnum(self):
            if self.selected_idx is None: return
            bug=self.bugs[self.selected_idx]
            new=self.bugnum_var.get().strip()
            try:
                txt=self.app.notes_path.read_text(encoding="utf-8")
                new_txt=write_bug_meta_bugnum(txt, bug["id"], new if new else None)
                self.app.notes_path.write_text(new_txt, encoding="utf-8")
                self.refresh()
            except Exception as e:
                messagebox.showerror("Error", str(e))

        def copy_summary_no_empty_brackets(self):
            if self.selected_idx is None: return
            bug=self.bugs[self.selected_idx]
            if bug["bugnum"]:
                copy_to_system(f"[{bug['bugnum']}] {bug['summary']}")
            else:
                copy_to_system(bug["summary"])

        def copy_bugnum_and_summary(self):
            if self.selected_idx is None: return
            bug=self.bugs[self.selected_idx]
            tag=f"[{bug['bugnum']}]" if bug["bugnum"] else "[]"
            copy_to_system(f"{tag} {bug['summary']}")

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title("Bug Notes Assistant")
            self.geometry("1180x780"); self.minsize(860, 580)
            self.rowconfigure(0, weight=1); self.columnconfigure(0, weight=1)
            self.show_wizard()
            m=tk.Menu(self); filem=tk.Menu(m, tearoff=0)
            filem.add_command(label="New (Wizard)…", command=self.show_wizard)
            filem.add_separator(); filem.add_command(label="Quit", command=self.destroy)
            m.add_cascade(label="File", menu=filem); self.config(menu=m)

        def show_wizard(self):
            for w in self.winfo_children(): w.destroy()
            SetupWizard(self, self.on_setup_done)

        def on_setup_done(self, path: Path):
            for w in self.winfo_children(): w.destroy()
            MainApp(self, path)

def run_gui():
    if not TK_AVAILABLE:
        print("Tkinter is not available in this environment. Use --cli to run the CLI."); sys.exit(1)
    app=App()
    try: app.tk.call("tk","scaling",1.2)
    except Exception: pass
    app.mainloop()

def main():
    ap=argparse.ArgumentParser(description="Bug Notes Assistant (GUI default, CLI with --cli)")
    ap.add_argument("--cli", action="store_true", help="Run CLI mode")
    args=ap.parse_args()
    if args.cli: run_cli()
    else: run_gui()

if __name__ == "__main__":
    main()
