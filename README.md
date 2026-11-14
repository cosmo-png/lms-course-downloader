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

1. **Login.** Type your LMS username and password (hidden, never stored). If the site uses a captcha or
   single sign-on, a Chrome window opens so you can log in yourself, then press Enter.
2. Your login session is saved to `~/.lms-dl/session.json` so next time you are not asked again.
   Treat that file like a password. Remove it with `--forget`, or avoid saving with `--no-save`.
3. Pick courses: arrows to move, **SPACE to tick**, ENTER to confirm. The first option selects all.
4. Choose **Files**, **Videos** or **Both**.
5. Everything lands in `downloads/<course name>/`. Re-running skips files you already have.

## Options

| Flag | What it does |
|------|--------------|
| `--base URL` | Use another Moodle site (default `https://lms.miva.university`) |
| `--out DIR` | Output folder (default `downloads`) |
| `--manual` | Skip the password prompt and log in yourself in Chrome |
| `--forget` | Delete the saved session before starting |
| `--no-save` | Do not save the session |
| `--browser PATH` | Use a specific Chrome executable |

## Notes

- Videos on YouTube/Vimeo or direct `.mp4` links are supported. DRM-protected videos are not.
- Moodle themes differ. If a course type is missed, open an issue with the (anonymised) HTML of one activity.
- Use this only for your own account and course material, and follow your institution's rules.

## License

MIT
