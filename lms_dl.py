#!/usr/bin/env python3
"""
LMS Course Downloader (Moodle).
Logs in, lists your enrolled courses, lets you pick some, and downloads
their documents (PDF, slides...) and/or videos. Works on Windows, Linux, macOS.
"""
import argparse
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

import questionary
import requests
from playwright.sync_api import sync_playwright
from rich.console import Console

console = Console()

DOC_EXT = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".zip", ".epub", ".txt"}
VID_EXT = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}
EXTERNAL_VIDEO = ("youtube.com", "youtu.be", "vimeo.com", "wistia", "dailymotion.com", "loom.com")
ACTIVITY_RE = re.compile(r"/mod/(resource|folder|page|url|book|kalvidres|videotime|hvp|lti)/view\.php")


def safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", name).strip()[:120] or "unnamed"


def ext_of(url: str) -> str:
    return Path(unquote(urlparse(url).path)).suffix.lower()


def goto(page, url):
    page.goto(url, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass


# ---------------------------------------------------------------- login
def login(page, base, username, password) -> bool:
    goto(page, f"{base}/login/index.php")
    if page.locator("#username").count() == 0:
        return "login" not in page.url
    page.fill("#username", username)
    page.fill("#password", password)
    page.click("#loginbtn")
    page.wait_for_load_state("networkidle")
    return "/login/" not in page.url


def make_session(ctx) -> requests.Session:
    s = requests.Session()
    for c in ctx.cookies():
        s.cookies.set(c["name"], c["value"], domain=c["domain"], path=c["path"])
    s.headers["User-Agent"] = "Mozilla/5.0 (lms-course-downloader)"
    return s


# -------------------------------------------------------------- courses
def get_courses(page, base):
    goto(page, f"{base}/my/courses.php")
    try:  # Moodle's own AJAX service: returns ALL courses, not just "in progress"
        sesskey = page.evaluate("() => M.cfg.sesskey")
        data = page.evaluate(
            """async (sk) => {
                const m = 'core_course_get_enrolled_courses_by_timeline_classification';
                const r = await fetch('/lib/ajax/service.php?sesskey=' + sk + '&info=' + m, {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify([{index: 0, methodname: m, args: {offset: 0, limit: 0,
                        classification: 'all', sort: 'fullname', customfieldname: '', customfieldvalue: ''}}])
                });
                return await r.json();
            }""",
            sesskey,
        )
        return [{"id": c["id"], "name": c["fullname"], "url": c["viewurl"]} for c in data[0]["data"]["courses"]]
    except Exception:
        pass
    # fallback: scrape the links on the page
    items = page.eval_on_selector_all(
        'a[href*="course/view.php?id="]', "els => els.map(e => [e.href, e.textContent.trim()])"
    )
    seen, out = set(), []
    for href, text in items:
        cid = re.search(r"id=(\d+)", href)
        if cid and cid.group(1) not in seen and text:
            seen.add(cid.group(1))
            out.append({"id": cid.group(1), "name": text, "url": href})
    return out


# ------------------------------------------------------------ downloads
def filename_from(r) -> str:
    cd = r.headers.get("content-disposition", "")
    m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", cd)
    return unquote(m.group(1)) if m else unquote(Path(urlparse(r.url).path).name)


def save_stream(sess, url, folder: Path, allowed):
    """Returns 'saved' | 'skipped' | 'html' | 'fail'."""
    try:
        with sess.get(url, stream=True, allow_redirects=True, timeout=60) as r:
            if r.status_code != 200:
                return "fail"
            if "text/html" in r.headers.get("content-type", ""):
                return "html"
            name = filename_from(r)
            if Path(name).suffix.lower() not in allowed:
                return "skipped"
            folder.mkdir(parents=True, exist_ok=True)
            dest = folder / safe(name)
            if dest.exists():
                console.print(f"    = already have {dest.name}")
                return "saved"
            part = dest.with_name(dest.name + ".part")
            with open(part, "wb") as f:
                for chunk in r.iter_content(1024 * 256):
                    f.write(chunk)
            part.rename(dest)
            console.print(f"    [green]+ {dest.name}[/green]")
            return "saved"
    except Exception as e:
        console.print(f"    [red]! {url} -> {e}[/red]")
        return "fail"


def ytdlp(url, folder: Path):
    try:
        import yt_dlp
        folder.mkdir(parents=True, exist_ok=True)
        opts = {"outtmpl": str(folder / "%(title)s.%(ext)s"), "quiet": True, "noprogress": True}
        with yt_dlp.YoutubeDL(opts) as y:
            y.download([url])
        console.print(f"    [green]+ video {url}[/green]")
    except Exception as e:
        console.print(f"    [red]! video failed {url} -> {e}[/red]")


def harvest(page, url):
    """Open an activity page, return (file_links, video_links)."""
    goto(page, url)
    els = page.eval_on_selector_all(
        "a[href], iframe[src], embed[src], object[data], video[src], source[src]",
        "els => els.map(e => e.href || e.src || e.data)",
    )
    files, vids = set(), set()
    for u in filter(None, els):
        if "/pluginfile.php/" in u:
            files.add(u)
        elif any(d in u for d in EXTERNAL_VIDEO) or ext_of(u) in VID_EXT | {".m3u8"}:
            vids.add(u)
    return files, vids


def handle_file(sess, url, folder, want_docs, want_vids):
    allowed = (DOC_EXT if want_docs else set()) | (VID_EXT if want_vids else set())
    if ext_of(url) in allowed or "/mod/resource/" in url:
        return save_stream(sess, url, folder, allowed)
    return "skipped"


def handle_video(sess, url, folder):
    if ext_of(url) in VID_EXT:
        save_stream(sess, url, folder, VID_EXT)
    else:
        ytdlp(url, folder)


def process_course(page, sess, course, out: Path, want_docs, want_vids):
    folder = out / safe(course["name"])
    console.rule(course["name"])
    goto(page, course["url"])
    hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
    direct = {h for h in hrefs if "/pluginfile.php/" in h}
    acts = sorted({h.split("#")[0] for h in hrefs if ACTIVITY_RE.search(h)})
    console.print(f"  {len(acts)} activities, {len(direct)} direct files")

    for u in direct:
        handle_file(sess, u, folder, want_docs, want_vids)

    for i, act in enumerate(acts, 1):
        console.print(f"  [{i}/{len(acts)}] {act}")
        if "/mod/resource/" in act:
            if handle_file(sess, act, folder, want_docs, want_vids) != "html":
                continue
        files, vids = harvest(page, act)
        for f in files:
            handle_file(sess, f, folder, want_docs, want_vids)
        if want_vids:
            for v in vids:
                handle_video(sess, v, folder / "videos")


# ----------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Download your Moodle course files and videos.")
    ap.add_argument("--base", default="https://lms.miva.university", help="LMS base URL")
    ap.add_argument("--out", default="downloads", help="output folder")
    ap.add_argument("--manual", action="store_true",
                    help="open a browser window and log in yourself (use for SSO / OTP / captcha)")
    args = ap.parse_args()
    base, out = args.base.rstrip("/"), Path(args.out)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.manual)
        ctx = browser.new_context()
        page = ctx.new_page()

        if args.manual:
            goto(page, f"{base}/login/index.php")
            console.print("Log in in the browser window, then come back here.")
            input("Press Enter once you can see your dashboard... ")
        else:
            user = questionary.text("Username / email:").ask()
            pw = questionary.password("Password (hidden, never stored):").ask()
            if not user or not pw or not login(page, base, user, pw):
                console.print("[red]Login failed. Try again with --manual.[/red]")
                sys.exit(1)

        courses = get_courses(page, base)
        if not courses:
            console.print("[red]No courses found.[/red]")
            sys.exit(1)

        chosen = questionary.checkbox(
            "Select courses (space to tick, enter to confirm):",
            choices=[questionary.Choice(c["name"], value=c) for c in courses],
        ).ask()
        if not chosen:
            return
        kind = questionary.select(
            "What do you want to download?",
            choices=["Files (PDFs, slides, docs)", "Videos", "Both"],
        ).ask()
        want_docs, want_vids = kind != "Videos", kind != "Files (PDFs, slides, docs)"

        sess = make_session(ctx)
        for c in chosen:
            process_course(page, sess, c, out, want_docs, want_vids)
        console.print(f"\n[bold green]Done.[/bold green] Saved in: {out.resolve()}")
        browser.close()


if __name__ == "__main__":
    main()
