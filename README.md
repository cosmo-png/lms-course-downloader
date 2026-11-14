# LMS Course Downloader

Download your own course files (PDFs, slides, docs) and videos from a Moodle-based
LMS. Built for Miva Open University, but works with any Moodle site via `--base`.

Works on **Windows, Linux and macOS** using your installed Google Chrome.

## Install

You need **Python 3.9+** and **Google Chrome**. No other browser download is needed.

```bash
git clone https://github.com/cosmo-png/lms-course-downloader.git
cd lms-course-downloader
python -m venv venv
```

Activate the virtual environment (pick your system):

| System | Command |
|--------|---------|
| Windows (PowerShell / cmd) | `venv\Scripts\activate` |
| Linux / macOS (bash, zsh) | `source venv/bin/activate` |
| Linux (fish) | `source venv/bin/activate.fish` |

Then:

```bash
pip install -r requirements.txt
```

## Use

```bash
python lms_dl.py
```

1. Enter your LMS username and password (typed locally, never stored or sent anywhere except the LMS).
2. Tick the courses you want.
3. Choose **Files**, **Videos**, or **Both**.
4. Everything lands in `downloads/<course name>/`.

Options:

| Flag | What it does |
|------|--------------|
| `--base URL` | Use a different Moodle site (default: `https://lms.miva.university`) |
| `--out DIR` | Output folder (default: `downloads`) |
| `--manual` | Opens a browser window so you log in yourself. Use this for SSO, OTP or captcha |

Re-running skips files you already have.

## Notes

- Videos on YouTube/Vimeo or direct `.mp4` links are supported. DRM-protected videos are not.
- Moodle themes differ; if a course type is missed, open an issue with the (anonymised) HTML of one activity.
- Use this only for your own account and course material, and follow your institution's rules.

## License

MIT
