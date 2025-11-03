# QIPEDC Video Scraper

Scrapes video links and labels from the QIPEDC dictionary site and downloads the MP4s to a local dataset folder, saving labels to a CSV.

## What it does

- Navigates through the dictionary pages with Selenium (Chrome)
- Extracts label text and associated video URLs from a modal per card
- Downloads videos in parallel with requests
- Writes a label file: `Dataset/Text/label.csv` with columns: `ID, VIDEO, LABEL`

## Requirements

- Python 3.9+
- Google Chrome installed

Install Python packages (recommended in a virtual environment):

```powershell
# From the repo folder
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
```

If you prefer not to use requirements.txt, install manually:

```powershell
pip install selenium webdriver-manager requests urllib3 tqdm
```

## Configuration

Adjust these constants at the top of `web_scraper.py` if needed:

- `BASE_URL`: Base page for the dictionary (default: `https://qipedc.moet.gov.vn/dictionary`)
- `VIDEO_DIR`: Where downloaded videos are saved (default: `Dataset/Videos`)
- `LABEL_PATH`: Where the label CSV is written (default: `Dataset/Text/label.csv`)
- `MAX_THREADS`: Number of concurrent downloads (default: `5`)
- `WAIT_TIME`: Selenium explicit-wait time in seconds (default: `25`)

Runtime/behavior flags:

- `SCRAPER_HEADLESS` env var: set to `"1"` to run headless (default), `"0"` to show the browser window.

Example (show the browser):

```powershell
$env:SCRAPER_HEADLESS = "0"; python web_scraper.py
```

## How to run

```powershell
# Activate env (if not already)
.\.venv\Scripts\Activate.ps1

# Run the scraper
python web_scraper.py
```

On first run, the script will either use a local `chromedriver.exe` in the current folder or automatically download a matching ChromeDriver via `webdriver-manager`.

## Output

- Videos: `Dataset/Videos/D0001.mp4`, `D0002.mp4`, ...
- Labels CSV: `Dataset/Text/label.csv`

CSV columns:

- `ID`: Sequential ID, e.g. `D0001`
- `VIDEO`: Absolute URL used to download the video
- `LABEL`: Text label shown on the site

Example rows:

```
ID,VIDEO,LABEL
D0001,https://qipedc.moet.gov.vn/path/to/video1.mp4,hello
D0002,https://qipedc.moet.gov.vn/path/to/video2.mp4,world
```

## Troubleshooting

- Import errors for Selenium or webdriver-manager:
  - Ensure the virtual environment is active and run `pip install -r requirements.txt`.
- Chrome/Driver mismatch:
  - Update Chrome to the latest stable, then re-run. `webdriver-manager` will fetch a compatible driver automatically.
  - If you keep a local `chromedriver.exe`, make sure it matches your Chrome version or remove it to let `webdriver-manager` handle it.
- Pages not loading or empty content:
  - Increase `WAIT_TIME` (e.g., 40–60) to allow more time for dynamic content.
  - Set `SCRAPER_HEADLESS = "0"` to watch the browser behavior.
  - Check `scraped_hand_data/debug` for saved HTML and screenshots when errors occur.
- SSL/Certificate warnings:
  - The script disables verification for target downloads to work around site cert issues. Use on trusted networks only.

## Notes and ethics

- Respect the website’s Terms of Service and robots.txt.
- Avoid overloading the site. The script includes small delays and bounded concurrency; tune responsibly.
- Use the dataset only for lawful and ethical purposes.
