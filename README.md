# PBase Gallery Scraper

<div align="center">
  <p><strong>Mirror your PBase galleries in full resolution with a single command-line helper.</strong></p>
  <p>
    <a href="https://img.shields.io/badge/status-stable-brightgreen"><img alt="Status" src="https://img.shields.io/badge/status-stable-brightgreen"></a>
    <a href="https://img.shields.io/badge/python-3.9%2B-blue"><img alt="Python" src="https://img.shields.io/badge/python-3.9%2B-blue"></a>
    <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-lightgrey"></a>
  </p>
</div>

> ⚠️ Review PBase's Terms of Service before scraping. Only download content you are authorized to access.

---

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python3 -m pbase_scraper --username <USERNAME> --output ./downloads
```

## Basic Workflow

1. Activate your virtual environment and install dependencies.
2. Run the module with your PBase credentials; you will be prompted for the password if omitted.
3. The scraper logs in once, discovers nested galleries, and downloads the largest available image for each entry.
4. Files land in the output directory with readable names that combine gallery title and image caption.

## Command Options

| Option | Description |
| --- | --- |
| `--username <USERNAME>` | PBase account owner (required). |
| `--password <PASSWORD>` | Account password; prompt appears if omitted. |
| `--output <DIR>` | Destination directory (default: `./downloads`). |
| `--start <PATH or URL>` | Start point(s); repeat the flag to target specific galleries. Defaults to `<username>/root`. |
| `--base-url <URL>` | Override the PBase host for testing. |
| `--delay <SECONDS>` | Throttle between HTTP requests (default: `0.5`). |
| `--log-level <LEVEL>` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |

## Features

- ✅ Single login session with polite throttling keeps you in good standing with PBase.
- ✅ Recursively discovers nested galleries and grabs the highest-resolution asset available.
- ✅ Cleans file names for readability, preserves extensions, and avoids overwriting existing files.
- ✅ Skips known placeholder assets so your archive stays tidy.

## Limitations

- ⚠️ Changes to PBase's HTML may require selector updates in the scraper.
- ⚠️ The scraper inherits any rate limits or CAPTCHA walls enforced by the site.
- ⚠️ Transient network failures currently require rerunning the command.

## Visual Overview

<div align="center">
  <em>Add a gallery screenshot or flow diagram here for a quick visual cue.</em>
  <!-- Example: <img src="docs/images/scraper-overview.png" alt="Scraper overview" width="600"> -->
</div>

## Implementation Notes

- Authenticates using a shared `requests.Session` that mimics a standard browser form submission.
- Each gallery is normalized and visited once; recursion prevents revisiting branches already scraped.
- Image size links are prioritized (`original` → `large` → `medium` → displayed image) to ensure the best available quality.
- Downloaded files are written in streaming chunks and appended with numeric suffixes when duplicates appear.

### File Naming Details

- Captions become the base filename, cleaned for filesystem safety and trimmed to fit common path limits.
- If the gallery has a title, it is prefixed as `<Gallery Title> - <Caption>` so multi-gallery runs stay organized.
- When captions are missing, the scraper falls back to the original asset name supplied by PBase.
- Existing files are never overwritten; `_1`, `_2`, … suffixes are added when duplicates are encountered.
- Known placeholder assets (`m_pbase*`, `pixel.gif`, `blank.gif`) are ignored entirely to keep the archive noise-free.
