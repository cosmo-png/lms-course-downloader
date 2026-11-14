# LMS Course Downloader

Download your own course files (PDFs, slides, docs) and videos from a Moodle-based
LMS. Built for Miva Open University, but works with any Moodle site via `--base`.

Works on **Windows, Linux and macOS** using your installed Google Chrome.

## Quick start

You need **Python 3.9+**, **Git** and **Google Chrome**. Then:

```bash
git clone https://github.com/cosmo-png/lms-course-downloader.git
cd lms-course-downloader
python start.py
```

(On Windows, use `py start.py` if `python` isn't found. On Debian/Ubuntu you may first need
`sudo apt install python3-venv`. On Arch, Chrome is `yay -S google-chrome`.)

`start.py` sets up everything on the first run, so there is nothing to activate or install by hand,
whatever shell you use.

## How it works

1. **Login.** A Chrome window opens on your LMS login page. Log in the way you normally do (password,
   captcha, Google/Microsoft sign-in, OTP all work). The tool notices by itself when you're in and
   carries on. Your password is never typed into or seen by this tool.
2. Your login session is saved to `~/.lms-dl/session.json`, so next time Chrome doesn't need to open.
   Treat that file like a password. Remove it with `--forget`, or avoid saving with `--no-save`.
3. Pick courses: arrows to move, **SPACE to tick**, ENTER to confirm. The first option selects all.
4. Choose **Files**, **Videos** or **Both**.
5. Everything lands in `downloads/<course name>/`. Re-running skips files you already have.
   Files are downloaded by Chrome itself, exactly like clicking them yourself.

## Options

| Flag | What it does |
|------|--------------|
| `--base URL` | Use another Moodle site (default `https://lms.miva.university`) |
| `--out DIR` | Output folder (default `downloads`) |
| `--forget` | Delete the saved session and log in again |
| `--no-save` | Do not save the session |
| `--show` | Keep Chrome visible while downloading |
| `--debug` | Print what was found and skipped (useful for bug reports) |
| `--browser PATH` | Use a specific Chrome executable |

## Notes

- Videos on YouTube/Vimeo or direct `.mp4` links are supported. DRM-protected videos are not.
- Moodle themes differ. If a course type is missed, open an issue with the (anonymised) HTML of one activity.
- Use this only for your own account and course material, and follow your institution's rules.

## License

MIT
