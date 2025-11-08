import os
import csv
import time
import requests
import urllib3
from urllib.parse import urljoin, urlsplit, urlunsplit
from concurrent.futures import ThreadPoolExecutor, as_completed

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from tqdm import tqdm

# ========== CONFIG ==========
BASE_URL = "https://qipedc.moet.gov.vn/dictionary"
VIDEO_DIR = "Dataset/Videos"
LABEL_PATH = "Dataset/Text/label.csv"
MAX_THREADS = 5
WAIT_TIME = 25  # generous wait for dynamic content

os.makedirs(VIDEO_DIR, exist_ok=True)
os.makedirs(os.path.dirname(LABEL_PATH), exist_ok=True)

# ========== INIT SELENIUM ==========
options = webdriver.ChromeOptions()
# Toggle headless via env (1 = headless)
if os.getenv("SCRAPER_HEADLESS", "0") == "1":
    options.add_argument("--headless=new")
options.add_argument("--disable-gpu")
options.add_argument("--no-sandbox")
options.add_argument("--window-size=1920,1080")
# Reduce detection of automation
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option('useAutomationExtension', False)
options.add_argument("--disable-blink-features=AutomationControlled")
options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36")
options.add_argument("--ignore-certificate-errors")
options.add_argument("--allow-insecure-localhost")
try:
    options.set_capability('acceptInsecureCerts', True)
except Exception:
    pass

# Prefer local chromedriver.exe if present; else use webdriver-manager
chromedriver_path = os.path.join(os.getcwd(), "chromedriver.exe")
if os.path.exists(chromedriver_path):
    service = Service(chromedriver_path)
else:
    try:
        driver_path = ChromeDriverManager().install()
        service = Service(driver_path)
    except Exception as e:
        print(f"Warning: webdriver-manager failed: {e}")
        service = Service("chromedriver.exe")

driver = webdriver.Chrome(service=service, options=options)
driver.set_page_load_timeout(30)

# Prepare a Requests session with SSL disabled for this host (site has expired cert)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36',
    'Accept': 'video/mp4,application/octet-stream;q=0.9,*/*;q=0.8',
    'Referer': BASE_URL,
    'Connection': 'keep-alive'
})
session.verify = False  # accept expired/invalid certs for the target site


def save_debug_page(driver, filename_prefix="debug_page"):
    """Save the current page HTML and a screenshot to aid debugging."""
    out_dir = os.path.join("scraped_hand_data", "debug")
    os.makedirs(out_dir, exist_ok=True)
    ts = int(time.time())
    html_path = os.path.join(out_dir, f"{filename_prefix}_{ts}.html")
    shot_path = os.path.join(out_dir, f"{filename_prefix}_{ts}.png")
    try:
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(driver.page_source)
    except Exception:
        pass
    try:
        driver.save_screenshot(shot_path)
    except Exception:
        pass
    print(f"🧪 Saved debug artifacts: {html_path} | {shot_path}")


def ensure_on_dictionary_page():
    """Navigate to the dictionary listing page if not already there."""
    try:
        driver.get(BASE_URL)
        WebDriverWait(driver, WAIT_TIME).until(
            lambda d: d.execute_script('return document.readyState') == 'complete'
        )
        # If landing elsewhere, try clicking menu link
        if not driver.find_elements(By.CSS_SELECTOR, "#product a"):
            try:
                link = driver.find_element(By.CSS_SELECTOR, "a[href='/dictionary']")
                driver.execute_script("arguments[0].click();", link)
                time.sleep(1.0)
            except Exception:
                # Fallback by visible text
                try:
                    link = driver.find_element(By.XPATH, "//a[contains(text(),'Video 4000 từ')]")
                    driver.execute_script("arguments[0].click();", link)
                    time.sleep(1.0)
                except Exception:
                    pass
    except Exception:
        pass


def set_items_per_page(count=80):
    """Set number of items per page via the #group select and trigger re-render."""
    try:
        sel = WebDriverWait(driver, WAIT_TIME).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "select#group"))
        )
        driver.execute_script(
            "var s=document.getElementById('group'); if(s){ s.value=arguments[0]; }",
            str(count)
        )
        # Trigger UI update
        try:
            driver.execute_script("if (typeof onSearch === 'function') { onSearch(); }")
        except Exception:
            pass
        # Wait until at least 20 anchors are shown
        for _ in range(20):
            cards = driver.find_elements(By.CSS_SELECTOR, "#product a")
            if len(cards) >= 20:
                break
            time.sleep(0.2)
    except Exception:
        pass


def get_last_page_number():
    """Detect the last page number from pagination buttons."""
    try:
        WebDriverWait(driver, WAIT_TIME).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#pagination-wrapper"))
        )
        # Ensure buttons are rendered
        WebDriverWait(driver, WAIT_TIME).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "#pagination-wrapper button"))
        )
        page_btns = driver.find_elements(By.CSS_SELECTOR, "#pagination-wrapper button.page")
        nums = []
        for b in page_btns:
            v = (b.get_attribute("value") or "").strip()
            if v.isdigit():
                nums.append(int(v))
        if not nums:
            for b in page_btns:
                t = (b.text or "").strip()
                if t.isdigit():
                    nums.append(int(t))
        return max(nums) if nums else 1
    except Exception:
        return 1


def go_to_page(page_num):
    """Click the pagination button with given value and wait for content to change."""
    try:
        prev_first = None
        try:
            prev_first = driver.find_element(By.CSS_SELECTOR, "#product a p").text
        except Exception:
            pass
        btn = WebDriverWait(driver, WAIT_TIME).until(
            EC.presence_of_element_located((By.XPATH, f"//div[@id='pagination-wrapper']//button[@value='{page_num}']"))
        )
        driver.execute_script("arguments[0].click();", btn)
        # Wait for change in first card label
        for _ in range(30):
            try:
                cur_first = driver.find_element(By.CSS_SELECTOR, "#product a p").text
                if prev_first is None or cur_first != prev_first:
                    break
            except Exception:
                pass
            time.sleep(0.2)
        return True
    except Exception:
        return False


def crawl_page():
    """Extract video URLs and labels from the card grid without opening modals."""
    page_data = []
    WebDriverWait(driver, WAIT_TIME).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "#product a"))
    )
    # Wait for typical page size to be present
    for _ in range(20):
        cards = driver.find_elements(By.CSS_SELECTOR, "#product a")
        if len(cards) >= 20:
            break
        time.sleep(0.2)
    cards = driver.find_elements(By.CSS_SELECTOR, "#product a")

    for card in cards:
        try:
            vid_code = None
            label = ""
            onclick = card.get_attribute("onclick") or ""
            if "modalData" in onclick:
                # modalData('D0001B','địa chỉ','desc','false' ) → take first two args
                parts = onclick.split("modalData(")[-1].split(")")[0]
                raw = parts.split(",")
                cleaned = [p.strip().strip("'\"") for p in raw]
                if len(cleaned) >= 2:
                    vid_code = cleaned[0]
                    label = cleaned[1]
            if not vid_code:
                # Fallback derive from image thumb filename
                try:
                    img = card.find_element(By.TAG_NAME, "img")
                    src = img.get_attribute("src")
                    vid_code = os.path.splitext(os.path.basename(src))[0]
                except Exception:
                    continue
                try:
                    label = card.find_element(By.TAG_NAME, "p").text.strip()
                except Exception:
                    label = ""
            if not vid_code:
                continue
            video_url = f"https://qipedc.moet.gov.vn/videos/{vid_code}.mp4"
            page_data.append((label or vid_code, video_url))
        except Exception:
            continue

    return page_data


print("🔍 Opening QIPEDC page...")
ensure_on_dictionary_page()

# Prefer to render more items per page to reduce clicks
set_items_per_page(80)

all_data = []
last_page = get_last_page_number()
print(f"🔢 Total pages detected: {last_page}")

for page in range(1, last_page + 1):
    print(f"📄 Processing page {page}/{last_page} ...")
    if page > 1:
        if not go_to_page(page):
            print(f"⚠️ Cannot navigate to page {page}, skipping.")
            continue
    try:
        data = crawl_page()
        all_data.extend(data)
        print(f"   ➕ Collected {len(data)} items on page {page}")
    except Exception as e:
        print(f"⚠️ Error while crawling page {page}: {e}")
        save_debug_page(driver, filename_prefix=f"page_{page}_error")

driver.quit()
print(f"✅ Collected {len(all_data)} video links.")

# ========== ASSIGN IDS & FILENAMES ==========
entries = []
for i, (label, link) in enumerate(all_data, start=1):
    vid_id = f"D{i:04d}"
    filename = f"{vid_id}.mp4"
    full_link = link if link.startswith("http") else urljoin(BASE_URL, link)
    entries.append((vid_id, full_link, label, filename))


# ========== VIDEO DOWNLOAD FUNCTION ==========
def download_video(entry):
    vid_id, url, label, filename = entry
    save_path = os.path.join(VIDEO_DIR, filename)
    try:
        r = session.get(url, stream=True, allow_redirects=True, verify=False)
        r.raise_for_status()
        with open(save_path, "wb") as f:
            for chunk in r.iter_content(8192):
                if chunk:
                    f.write(chunk)
        return (vid_id, filename, label)
    except Exception as e:
        print(f"Failed to download {filename}: {e}")
        return None


# ========== PARALLEL DOWNLOAD ==========
results = []
with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
    futures = [executor.submit(download_video, e) for e in entries]
    for future in tqdm(as_completed(futures), total=len(futures), desc="Downloading videos"):
        res = future.result()
        if res:
            results.append(res)


# ========== WRITE CSV ==========
with open(LABEL_PATH, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["ID", "VIDEO", "LABEL"])
    writer.writerows(results)

print(f"\n🎉 Done! Saved {len(results)} videos to {LABEL_PATH}")
