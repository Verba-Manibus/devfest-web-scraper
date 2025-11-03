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
from tqdm import tqdm
from webdriver_manager.chrome import ChromeDriverManager

# ========== CONFIG ==========
BASE_URL = "https://qipedc.moet.gov.vn/dictionary"
VIDEO_DIR = "Dataset/Videos"
LABEL_PATH = "Dataset/Text/label.csv"
MAX_THREADS = 5
WAIT_TIME = 25  # increase wait for dynamic content

os.makedirs(VIDEO_DIR, exist_ok=True)
os.makedirs(os.path.dirname(LABEL_PATH), exist_ok=True)

# ========== INIT SELENIUM ==========
options = webdriver.ChromeOptions()
# Headless can sometimes cause sites to hide content; allow toggling via env
if os.getenv("SCRAPER_HEADLESS", "1") == "1":
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
# Accept insecure certs explicitly
try:
    options.set_capability('acceptInsecureCerts', True)
except Exception:
    pass
# Try to use a local chromedriver.exe if present; otherwise use webdriver-manager
chromedriver_path = os.path.join(os.getcwd(), "chromedriver.exe")
if os.path.exists(chromedriver_path):
    service = Service(chromedriver_path)
else:
    # webdriver-manager will download a compatible chromedriver into cache
    try:
        driver_path = ChromeDriverManager().install()
        service = Service(driver_path)
    except Exception as e:
        # Fallback: try default executable name (will likely fail and raise later)
        print(f"Warning: webdriver-manager failed: {e}")
        service = Service("chromedriver.exe")  # adjust path if needed

driver = webdriver.Chrome(service=service, options=options)
driver.set_page_load_timeout(30)

# Prepare a Requests session with retries and SSL disabled for this host
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36',
    'Accept': 'video/mp4,application/octet-stream;q=0.9,*/*;q=0.8',
    'Referer': BASE_URL,
    'Connection': 'keep-alive'
})
session.verify = False  # accept expired/invalid certs for the target site
session.timeout = 30

def wait_for_table_or_iframe(driver, timeout=WAIT_TIME):
    """Wait until table rows appear; if the content is inside an iframe, switch into it."""
    # First wait for document ready
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script('return document.readyState') == 'complete'
    )
    
    # Try direct table rows
    try:
        WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody tr"))
        )
        return True
    except Exception:
        pass

    # Try switching into iframes to find the table
    iframes = driver.find_elements(By.TAG_NAME, 'iframe')
    for idx, iframe in enumerate(iframes):
        try:
            driver.switch_to.frame(iframe)
            try:
                WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody tr"))
                )
                return True
            except Exception:
                driver.switch_to.default_content()
                continue
        except Exception:
            continue
    # Back to default
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    return False

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
    """Ensure we are on the dictionary list page that contains the video table."""
    try:
        # If current page doesn't have a table, try clicking the nav link to dictionary
        if not driver.find_elements(By.CSS_SELECTOR, "table tbody tr"):
            # Try direct link first
            try:
                driver.get(BASE_URL)
                time.sleep(1)
            except Exception:
                pass

            if not driver.find_elements(By.CSS_SELECTOR, "table tbody tr"):
                try:
                    link = driver.find_element(By.CSS_SELECTOR, "a[href='/dictionary']")
                    driver.execute_script("arguments[0].click();", link)
                    time.sleep(1.5)
                except Exception:
                    # Try link by visible text
                    try:
                        link = driver.find_element(By.XPATH, "//a[contains(text(),'Video 4000 từ')]")
                        driver.execute_script("arguments[0].click();", link)
                        time.sleep(1.5)
                    except Exception:
                        pass
    except Exception:
        pass

def crawl_page():
    """Crawl the video URL and label from a single page (card grid with a video modal)."""
    page_data = []
    # Ensure the product grid is present
    WebDriverWait(driver, WAIT_TIME).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "#product a"))
    )
    cards = driver.find_elements(By.CSS_SELECTOR, "#product a")
    for idx, card in enumerate(cards):
        try:
            # Get the label from the <p> tag
            label_el = card.find_element(By.TAG_NAME, "p")
            label = (label_el.text or "").strip()

            # Click to open the modal
            driver.execute_script("arguments[0].click();", card)
            # Wait for the iframe video element to be assigned a src
            WebDriverWait(driver, WAIT_TIME).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#video-modal.show, #video-modal.in"))
            )
            iframe = WebDriverWait(driver, WAIT_TIME).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#s_expert"))
            )
            # Wait for a non-empty src
            def iframe_has_src(drv):
                src = drv.find_element(By.CSS_SELECTOR, "#s_expert").get_attribute("src")
                return src if src else False
            src = WebDriverWait(driver, WAIT_TIME).until(iframe_has_src)

            # Save data
            if src:
                # Remove autoplay or any query params to get direct .mp4
                parts = urlsplit(src)
                clean_src = urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))
                page_data.append((label, clean_src))

            # Close the modal
            try:
                driver.execute_script("$('#video-modal').modal('hide');")
            except Exception:
                # Fallback: click the "Đóng" (Close) button (site text is Vietnamese)
                try:
                    close_btn = driver.find_element(By.XPATH, "//div[@id='video-modal']//button[contains(text(),'Đóng')]")
                    close_btn.click()
                except Exception:
                    pass

            # Small delay to avoid going too fast
            time.sleep(0.1)

        except Exception:
            # If there's an error with this card, skip it
            try:
                driver.execute_script("$('#video-modal').modal('hide');")
            except Exception:
                pass
            continue

    return page_data

def get_last_page_number():
    """Read the last page number from a 'Last »' button if present; otherwise, infer from visible buttons."""
    try:
        # Wait for pagination to appear
        WebDriverWait(driver, WAIT_TIME).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#pagination-wrapper"))
        )
        # Look for a Last » button
        last_btns = driver.find_elements(By.XPATH, "//div[@id='pagination-wrapper']//button[contains(text(),'Last')] | //div[@id='pagination-wrapper']//button[contains(text(),'»')]")
        for btn in last_btns:
            val = btn.get_attribute("value")
            if val and val.isdigit():
                return int(val)
        # If no Last button, take the largest visible page button
        page_btns = driver.find_elements(By.CSS_SELECTOR, "#pagination-wrapper button.page")
        nums = []
        for b in page_btns:
            try:
                v = b.get_attribute("value")
                if v and v.isdigit():
                    nums.append(int(v))
            except Exception:
                pass
        return max(nums) if nums else 1
    except Exception:
        return 1

def go_to_page(page_num):
    """Navigate to a specific page by clicking the button with value=page_num."""
    try:
        btn = WebDriverWait(driver, WAIT_TIME).until(
            EC.presence_of_element_located((By.XPATH, f"//div[@id='pagination-wrapper']//button[@value='{page_num}']"))
        )
        driver.execute_script("arguments[0].click();", btn)
        # Wait for #product content to change by waiting for the first anchor to be present
        WebDriverWait(driver, WAIT_TIME).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#product a"))
        )
        time.sleep(0.5)
        return True
    except Exception:
        return False

print("🔍 Opening QIPEDC page...")
driver.get(BASE_URL)
time.sleep(2)

# Ensure we are on the dictionary listing page
ensure_on_dictionary_page()

all_data = []

# Xác định tổng số trang
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
    full_link = urljoin(BASE_URL, link)
    entries.append((vid_id, full_link, label, filename))

# ========== VIDEO DOWNLOAD FUNCTION ==========
def download_video(entry):
    vid_id, url, label, filename = entry
    save_path = os.path.join(VIDEO_DIR, filename)
    try:
        # Use prepared session with SSL verify disabled
        r = session.get(url, stream=True, allow_redirects=True)
        r.raise_for_status()
        with open(save_path, "wb") as f:
            for chunk in r.iter_content(8192):
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
