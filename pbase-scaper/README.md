# PBase Gallery Scraper

Lightweight command-line helper that logs into a PBase account and downloads the largest available version of each image from the selected galleries.

⚠️ Before using this tool, review PBase's Terms of Service and ensure automated downloads are permitted for your use case. Only scrape content you have the legal right to access (for example your own account or content where you have explicit permission).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

Run the scraper as a module so the package entry point is used:

```bash
python3 -m pbase_scraper --username <USERNAME> --output ./downloads
```

You will be prompted for the password if `--password` is not provided. By default the scraper starts at `<username>/root`, discovers all nested galleries, and saves the largest available image for each entry. Relative paths passed with `--start` (e.g. `--start <username>/gallery/bailey_family_photographs`) restrict the scraper to specific galleries; repeat the flag for multiple starting points.

Available options:

- `--output` controls where files are saved (defaults to `./downloads`).
- `--delay` throttles the request rate (seconds between requests, default `0.5`).
- `--log-level` accepts `DEBUG`, `INFO`, `WARNING`, or `ERROR`.
- `--base-url` allows overriding the PBase host for testing.

## Implementation Notes

- The scraper logs in once with a shared HTTP session (using the same approach as a browser form submission).
- Each gallery is visited once; nested galleries are discovered recursively.
- All photos are saved directly under the output directory. Filenames are built from `<gallery title> - <image caption>` (falling back to the original filename) so everything stays readable and unique.
- For each image page, the tool prefers the `original` size link, falling back to `large`, `medium`, or the currently displayed image if larger variants are not present.
- Saved files keep their original extension. Existing files are not overwritten; duplicates receive a numeric suffix.

## Limitations

- Page structure changes on PBase can require code adjustments; keep the source handy in case selectors need updates.
- The script fetches HTML to discover download links, so it will inherit any rate limiting or CAPTCHA challenges enforced by PBase.
- Network errors are not retried automatically; rerun the scraper if a connection drops.
