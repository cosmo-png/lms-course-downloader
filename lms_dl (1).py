#!/usr/bin/env python3
"""
LMS Course Downloader (Moodle).
Log in through a real Chrome window, pick your courses, download their files and/or videos.
Windows, Linux, macOS.
"""
import argparse
import html as htmllib
import json
import re
import shutil
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlparse

import questionary
import requests
from playwright.sync_api import sync_playwright
from rich.console import Console

console = Console()
STATE_FILE = Path.home() / ".lms-dl" / "session.json"
stats = {"saved": 0, "had": 0, "failed": 0}
FAILS = []
DONE = set()
DEBUG = False

DOC_EXT = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".zip", ".epub", ".txt"}
VID_EXT = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}
EXTERNAL_VIDEO = ("youtube.com", "youtu.be", "vimeo.com", "wistia", "dailymotion.com", "loom.com")
# Moodle activity types that never hold downloadable course material
SKIP_MODS = {"forum", "quiz", "assign", "choice", "choicegroup", "feedback", "survey", "workshop",
             "glossary", "wiki", "data", "chat", "attendance", "bigbluebuttonbn", "zoom", "teams",
             "turnitintooltwo", "questionnaire", "certificate", "customcert", "badge", "scorm", "lesson"}
MOD_RE = re.compile(r"/mod/([a-z0-9_]+)/view\.php")
FILE_RE = re.compile(r"(?:https?://[^\s\"'<>()\\]+)?/pluginfile\.php/[^\s\"'<>()\\?&#]+", re.I)
FILE_EXT_RE = re.compile(
    r"(?:https?://[^\"'<>?&#\\]+?)?/pluginfile\.php/[^\"'<>?&#\\]+?\.(?:pdf|docx?|pptx?|xlsx?|zip|epub|txt|mp4|mkv|webm|mov|m4v)",
    re.I)
MIME_EXT = {
    "application/pdf": ".pdf", "application/zip": ".zip", "video/mp4": ".mp4", "video/webm": ".webm",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
}


def dbg(msg):
    if DEBUG:
        console.print(f"[dim]{msg}[/dim]")


def fail(url, why):
    stats["failed"] += 1
    FAILS.append((url, why))
    console.print(f"    [red]! {why}[/red]")


def ask(question):
    """Run a questionary prompt in its own thread (Playwright already owns the event loop)."""
    with ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(question.ask).result()


def safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", name).strip()[:120] or "unnamed"


def ext_of(url: str) -> str:
    return Path(unquote(urlparse(url).path)).suffix.lower()


def goto(page, url):
    try:
        page.goto(url, wait_until="domcontentloaded")
    except Exception as e:
        dbg(f"goto {url}: {e}")
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass


# -------------------------------------------------------------- browser
def launch_browser(p, headless, path=None):
    """Use the installed Google Chrome (Windows, macOS, Linux). No browser download needed."""
    kw = {"headless": headless}
    if not headless:  # visible login window: look like a normal browser
        kw["args"] = ["--disable-blink-features=AutomationControlled"]
        kw["ignore_default_args"] = ["--enable-automation"]
    if path:
        return p.chromium.launch(executable_path=path, **kw)
    try:
        return p.chromium.launch(channel="chrome", **kw)
    except Exception:
        pass
    names = ("google-chrome-stable", "google-chrome", "chrome", "chromium", "chromium-browser",
             "brave", "microsoft-edge-stable")
    found = next((shutil.which(n) for n in names if shutil.which(n)), None)
    if found:
        return p.chromium.launch(executable_path=found, **kw)
    console.print("[red]Google Chrome not found. Install it from google.com/chrome "
                  "or pass --browser /path/to/chrome[/red]")
    sys.exit(1)


def ua_for(browser) -> str:
    plat = {"win32": "Windows NT 10.0; Win64; x64", "darwin": "Macintosh; Intel Mac OS X 10_15_7"}.get(
        sys.platform, "X11; Linux x86_64")
    return (f"Mozilla/5.0 ({plat}) AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{browser.version} Safari/537.36")


def new_headless_context(browser, state):
    return browser.new_context(storage_state=state, accept_downloads=True, user_agent=ua_for(browser))


# ---------------------------------------------------------------- login
def logged_in(page, base) -> bool:
    goto(page, f"{base}/my/courses.php")
    return "/login" not in page.url and page.locator('input[type="password"]').count() == 0


def wait_for_login(page, base, timeout=600) -> bool:
    """Open the login page and wait until the person is logged in. No terminal input needed."""
    host = urlparse(base).netloc
    goto(page, f"{base}/login/index.php")
    console.print("[bold]A Chrome window opened. Log in there as you normally do.[/bold]")
    console.print("I'll continue by myself as soon as you're in.")
    deadline = time.time() + timeout
    while time.time() < deadline:
        page.wait_for_timeout(1500)
        try:
            u = urlparse(page.url)
            if u.netloc == host and "/login" not in u.path and page.locator('input[type="password"]').count() == 0:
                if logged_in(page, base):
                    return True
        except Exception:
            pass
    return False


def authenticate(p, args, base):
    """Return (browser, context, page) with a logged-in session."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if args.forget and STATE_FILE.exists():
        STATE_FILE.unlink()
        console.print("Saved session removed.")

    state = None
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text())
        except Exception:
            state = None

    if state:
        browser = launch_browser(p, not args.show, args.browser)
        ctx = new_headless_context(browser, state)
        page = ctx.new_page()
        if logged_in(page, base):
            console.print("[green]Using your saved session.[/green]")
            return browser, ctx, page
        browser.close()
        console.print("Saved session expired, please log in again.")

    vb = launch_browser(p, False, args.browser)
    vctx = vb.new_context()
    vpage = vctx.new_page()
    if not wait_for_login(vpage, base):
        console.print("[red]Login was not completed in time. Please run it again.[/red]")
        vb.close()
        sys.exit(1)
    state = vctx.storage_state()
    vb.close()
    console.print("[green]Logged in.[/green]")

    if not args.no_save:
        STATE_FILE.write_text(json.dumps(state))
        try:
            STATE_FILE.chmod(0o600)
        except OSError:
            pass
        console.print(f"Session saved to {STATE_FILE} (remove it any time with --forget).")

    browser = launch_browser(p, not args.show, args.browser)
    ctx = new_headless_context(browser, state)
    return browser, ctx, ctx.new_page()


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


# ------------------------------------------------- links to outside sites
URL_RE = re.compile(r"https?://[^\s\"'<>()\\]+")
DRIVE_FILE_RE = re.compile(r"drive\.google\.com/(?:file/d/|open\?id=|uc\?(?:[^\"'\s]*&)?id=)([\w-]{10,})")
GDOC_RE = re.compile(r"docs\.google\.com/(document|presentation|spreadsheets)/d/([\w-]{10,})")


def classify_external(u):
    """For a link that leaves the LMS return ('doc', download_url), ('video', url) or None."""
    if not u or not u.startswith("http"):
        return None
    m = re.search(r"[?&]url=([^&]+)", u)
    if m and any(v in u for v in ("docs.google.com/viewer", "gview", "view.officeapps.live.com")):
        return classify_external(unquote(m.group(1)))  # unwrap online viewers
    m = DRIVE_FILE_RE.search(u)
    if m:
        return ("doc", f"https://drive.google.com/uc?export=download&id={m.group(1)}")
    m = GDOC_RE.search(u)
    if m:
        kind, did = m.groups()
        fmt = "export/pdf" if kind == "presentation" else "export?format=pdf"
        return ("doc", f"https://docs.google.com/{kind}/d/{did}/{fmt}")
    if "dropbox.com" in u and ext_of(u) in DOC_EXT:
        return ("doc", re.sub(r"dl=0", "dl=1", u) if "dl=" in u else u + ("&" if "?" in u else "?") + "dl=1")
    if any(d in u for d in EXTERNAL_VIDEO) or ext_of(u) in VID_EXT | {".m3u8"}:
        return ("video", u)
    if ext_of(u) in DOC_EXT:
        return ("doc", u)
    return None


def fname_from(cd, url) -> str:
    m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", cd or "", re.I)
    return unquote(m.group(1)) if m else unquote(Path(urlparse(url).path).name)


def fetch_external(url, folder: Path, allowed):
    """Download a public file hosted outside the LMS (Google Drive, direct links...)."""
    if url in DONE:
        return
    DONE.add(url)
    try:
        with requests.get(url, stream=True, timeout=60, allow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0"}) as r:
            if r.status_code != 200:
                return fail(url, f"external link answered {r.status_code}")
            ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
            if ctype == "text/html":
                return fail(url, "external link gave a web page, not a file (private file, or needs login?)")
            name = fname_from(r.headers.get("content-disposition", ""), r.url)
            ext = Path(name).suffix.lower() or MIME_EXT.get(ctype, "")
            if ext not in allowed:
                dbg(f"skip external ({ext or ctype}): {name}")
                return
            if not Path(name).suffix:
                name += ext
            folder.mkdir(parents=True, exist_ok=True)
            dest = folder / safe(name)
            if dest.exists():
                console.print(f"    = already have {dest.name}")
                stats["had"] += 1
                return
            part = dest.with_name(dest.name + ".part")
            with open(part, "wb") as f:
                for chunk in r.iter_content(1024 * 256):
                    f.write(chunk)
            part.rename(dest)
            console.print(f"    [green]+ {dest.name}[/green]")
            stats["saved"] += 1
    except Exception as e:
        fail(url, f"{url}: {str(e).splitlines()[0]}")


def url_target(ctx, act):
    """Where does a Moodle 'URL' activity point? Reads the redirect without opening the page."""
    try:
        r = ctx.request.get(act, max_redirects=0)
        loc = r.headers.get("location")
        if 300 <= r.status < 400 and loc:
            return urljoin(act, loc)
        t = r.text()
        for pat in (r'urlworkaround.*?href="([^"]+)"', r'id="resourceobject"[^>]*?(?:src|data)="([^"]+)"'):
            m = re.search(pat, t, re.S)
            if m:
                return urljoin(act, htmllib.unescape(m.group(1)))
    except Exception as e:
        dbg(f"url_target {act}: {str(e).splitlines()[0]}")
    return None


# -------------------------------------------------- finding file links
def extract_files(text, base):
    """Find every Moodle file URL in a chunk of HTML/JS/URL, including ones hidden inside
    escaped strings or wrapped by viewers (Google viewer, PDF.js...)."""
    t = htmllib.unescape(text.replace("\\/", "/"))
    found = set()
    for m in FILE_RE.finditer(t):
        found.add(urljoin(base + "/", m.group(0).rstrip(".,;")))
    if re.search(r"%2f", t, re.I):
        d = unquote(unquote(t))
        for m in FILE_EXT_RE.finditer(d):
            found.add(urljoin(base + "/", quote(m.group(0), safe=":/")))
    return found


def page_files(page, base):
    found = set()
    for fr in page.frames:
        try:
            found |= extract_files(fr.content(), base)
        except Exception:
            pass
    return found


def harvest(page, url, base):
    """Open an activity page, return (lms_files, video_links, external_doc_links)."""
    goto(page, url)
    host = urlparse(base).netloc
    docs, vids = set(), set()

    def add_ext(u):
        if not u or "/pluginfile.php/" in u or urlparse(u).netloc == host:
            return
        c = classify_external(u)
        if c:
            (docs if c[0] == "doc" else vids).add(c[1])

    if urlparse(page.url).netloc != host:  # the activity redirected to an outside site
        add_ext(page.url)
        return set(), vids, docs
    files = page_files(page, base)
    els = page.eval_on_selector_all(
        "iframe[src], embed[src], object[data], video[src], source[src], a[href]",
        "els => els.map(e => e.href || e.src || e.data)",
    )
    for u in filter(None, els):
        files |= extract_files(u, base)
        add_ext(u)
    for fr in page.frames:
        try:
            t = htmllib.unescape(fr.content().replace("\\/", "/"))
        except Exception:
            continue
        for u in URL_RE.findall(t):
            add_ext(u.rstrip(".,;"))
    return files, vids, docs


# ------------------------------------------------------------ downloads
JS_RESOLVE = """async (u) => {
    const r = await fetch(u, {credentials: 'include', redirect: 'follow'});
    const out = {url: r.url, status: r.status,
                 type: r.headers.get('content-type') || '',
                 cd: r.headers.get('content-disposition') || ''};
    if (out.type.includes('text/html')) { out.html = await r.text(); }
    else { try { r.body.cancel(); } catch (e) {} }
    return out;
}"""


def ensure_origin(dl_page, base):
    if urlparse(dl_page.url).netloc != urlparse(base).netloc:
        goto(dl_page, f"{base}/my/")


def resolve(dl_page, url, base):
    """Ask Chrome itself what this URL is (final address, type, filename). Returns dict or None."""
    for _ in range(2):
        try:
            ensure_origin(dl_page, base)
            return dl_page.evaluate(JS_RESOLVE, url)
        except Exception as e:
            dbg(f"resolve failed {url}: {str(e).splitlines()[0]}")
            goto(dl_page, f"{base}/my/")
    return None


def name_from(info) -> str:
    return fname_from(info.get("cd", ""), info["url"])


def browser_save(dl_page, url, dest: Path):
    """Download through Chrome itself (same cookies, same network stack as a human)."""
    target = url if "forcedownload" in url else url + ("&" if "?" in url else "?") + "forcedownload=1"
    try:
        with dl_page.expect_download(timeout=45000) as info:
            try:
                dl_page.goto(target, wait_until="commit")
            except Exception:
                pass  # "Download is starting" is expected
        d = info.value
        dest.parent.mkdir(parents=True, exist_ok=True)
        d.save_as(str(dest))
        return True, ""
    except Exception as e:
        return False, str(e).splitlines()[0]


def download_file(dl_page, url, folder: Path, allowed, base):
    """Returns 'saved' | 'skipped' | 'html' | 'fail' | 'dup'."""
    if url in DONE:
        return "dup"
    DONE.add(url)
    info = resolve(dl_page, url, base)

    if info is None:  # could not inspect it; try a blind download using the name in the URL
        name = unquote(Path(urlparse(url).path).name)
        if Path(name).suffix.lower() not in allowed:
            dbg(f"skip (type {Path(name).suffix}): {url}")
            return "skipped"
        dest = folder / safe(name)
        if dest.exists():
            console.print(f"    = already have {dest.name}")
            stats["had"] += 1
            return "saved"
        ok, why = browser_save(dl_page, url, dest)
        if ok:
            console.print(f"    [green]+ {dest.name}[/green]")
            stats["saved"] += 1
            return "saved"
        fail(url, f"{name}: {why}")
        return "fail"

    ctype = info["type"].split(";")[0].strip().lower()
    if ctype == "text/html":
        if "/pluginfile.php/" in url:
            fail(url, "got a web page instead of the file (session blocked or expired?)")
            return "fail"
        return "html"
    if info["status"] != 200:
        fail(url, f"server answered {info['status']}")
        return "fail"

    name = name_from(info)
    ext = Path(name).suffix.lower() or MIME_EXT.get(ctype, "")
    if ext not in allowed:
        dbg(f"skip ({ext or ctype}): {name}")
        return "skipped"
    if not Path(name).suffix:
        name += ext
    dest = folder / safe(name)
    if dest.exists():
        console.print(f"    = already have {dest.name}")
        stats["had"] += 1
        return "saved"
    ok, why = browser_save(dl_page, info["url"], dest)
    if ok:
        console.print(f"    [green]+ {dest.name}[/green]")
        stats["saved"] += 1
        return "saved"
    fail(url, f"{name}: {why}")
    return "fail"


def ytdlp(url, folder: Path):
    try:
        import yt_dlp
        folder.mkdir(parents=True, exist_ok=True)
        opts = {"outtmpl": str(folder / "%(title)s.%(ext)s"), "quiet": True, "noprogress": True}
        with yt_dlp.YoutubeDL(opts) as y:
            y.download([url])
        console.print(f"    [green]+ video {url}[/green]")
        stats["saved"] += 1
    except Exception as e:
        fail(url, f"video {url}: {str(e).splitlines()[0]}")


def handle_video(url, folder: Path):
    if url in DONE:
        return
    DONE.add(url)
    if ext_of(url) in VID_EXT:  # plain public file on another host
        try:
            folder.mkdir(parents=True, exist_ok=True)
            dest = folder / safe(Path(unquote(urlparse(url).path)).name)
            if dest.exists():
                stats["had"] += 1
                return
            with requests.get(url, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(1024 * 256):
                        f.write(chunk)
            console.print(f"    [green]+ {dest.name}[/green]")
            stats["saved"] += 1
        except Exception as e:
            fail(url, f"video {url}: {str(e).splitlines()[0]}")
    else:
        ytdlp(url, folder)


def is_activity(href, host):
    m = MOD_RE.search(href)
    return bool(m) and m.group(1) not in SKIP_MODS and urlparse(href).netloc == host


def process_course(ctx, page, dl_page, course, out: Path, want_docs, want_vids, base):
    host = urlparse(base).netloc
    folder = out / safe(course["name"])
    allowed = (DOC_EXT if want_docs else set()) | (VID_EXT if want_vids else set())
    console.rule(course["name"])

    goto(page, course["url"])
    hrefs = set(page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)"))
    files = page_files(page, base)
    for s in sorted({h.split("#")[0] for h in hrefs if "/course/section.php" in h}):
        goto(page, s)  # courses that show one section per page
        hrefs |= set(page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)"))
        files |= page_files(page, base)

    acts = sorted({h.split("#")[0] for h in hrefs if is_activity(h, host)})
    kinds = Counter(MOD_RE.search(a).group(1) for a in acts)
    console.print("  activities: " + (", ".join(f"{k} x{v}" for k, v in kinds.items()) or "none")
                  + f" | files on page: {len(files)}")

    for u in sorted(files):
        download_file(dl_page, u, folder, allowed, base)

    def external(c):
        if c[0] == "doc" and want_docs:
            fetch_external(c[1], folder, allowed)
        elif c[0] == "video" and want_vids:
            handle_video(c[1], folder / "videos")

    for i, act in enumerate(acts, 1):
        kind = MOD_RE.search(act).group(1)
        console.print(f"  [{i}/{len(acts)}] {kind}: {act.split('/mod/')[-1]}")
        if kind == "resource":
            if download_file(dl_page, act, folder, allowed, base) != "html":
                continue
        if kind == "url":
            tgt = url_target(ctx, act)
            if tgt and urlparse(tgt).netloc != host:
                c = classify_external(tgt)
                if c:
                    console.print(f"    [dim]link -> {tgt}[/dim]")
                    external(c)
                else:
                    console.print(f"    [dim]link to {tgt} (not a file I can download)[/dim]")
                continue
        found, vids, docs = harvest(page, act, base)
        console.print(f"    [dim]found: {len(found)} files, {len(docs)} outside docs, {len(vids)} videos[/dim]")
        for u in sorted(found):
            download_file(dl_page, u, folder, allowed, base)
        for d in sorted(docs):
            external(("doc", d))
        for v in sorted(vids):
            external(("video", v))


# ----------------------------------------------------------------- main
def main():
    global DEBUG
    ap = argparse.ArgumentParser(description="Download your Moodle course files and videos.")
    ap.add_argument("--base", default="https://lms.miva.university", help="LMS base URL")
    ap.add_argument("--out", default="downloads", help="output folder")
    ap.add_argument("--forget", action="store_true", help="delete the saved login session first")
    ap.add_argument("--no-save", action="store_true", help="do not save the login session")
    ap.add_argument("--show", action="store_true", help="keep Chrome visible while downloading")
    ap.add_argument("--debug", action="store_true", help="print details about everything found/skipped")
    ap.add_argument("--browser", help="path to a Chrome executable (auto-detected if omitted)")
    args = ap.parse_args()
    DEBUG = args.debug
    base, out = args.base.rstrip("/"), Path(args.out)

    with sync_playwright() as p:
        browser, ctx, page = authenticate(p, args, base)

        courses = get_courses(page, base)
        if not courses:
            console.print("[red]No courses found on your classes page.[/red]")
            sys.exit(1)
        console.print(f"Found [bold]{len(courses)}[/bold] courses.")

        choices = [questionary.Choice("*** ALL COURSES ***", value="__all__")]
        choices += [questionary.Choice(c["name"], value=c) for c in courses]
        chosen = ask(questionary.checkbox(
            "Select courses:",
            choices=choices,
            instruction="(arrows move, SPACE ticks, ENTER confirms)",
            validate=lambda sel: True if sel else "Press SPACE to tick at least one course, then ENTER",
        ))
        if not chosen:
            return
        if "__all__" in chosen:
            chosen = courses

        kind = ask(questionary.select(
            "What do you want to download?",
            choices=["Files (PDFs, slides, docs)", "Videos", "Both"],
        ))
        if not kind:
            return
        want_docs, want_vids = kind != "Videos", kind != "Files (PDFs, slides, docs)"

        dl_page = ctx.new_page()
        goto(dl_page, f"{base}/my/")
        for c in chosen:
            process_course(ctx, page, dl_page, c, out, want_docs, want_vids, base)

        console.print(f"\n[bold green]Done.[/bold green] {stats['saved']} new, "
                      f"{stats['had']} already had, {stats['failed']} failed.")
        console.print(f"Saved in: {out.resolve()}")
        if FAILS:
            console.print("\n[yellow]Problems:[/yellow]")
            for u, why in FAILS[:20]:
                console.print(f"  - {why}\n    {u}")
        if stats["saved"] + stats["had"] == 0:
            console.print("[yellow]Nothing was downloaded. Re-run with --debug and send the output "
                          "so the course layout can be supported.[/yellow]")
        browser.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\nStopped.")
