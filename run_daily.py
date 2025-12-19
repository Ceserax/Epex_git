import os
import time
import subprocess
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageDraw
import requests
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

# Selenium imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# ENTSO-E Watcher
from watcher_entsoe import wait_for_day_ahead 

load_dotenv(Path(__file__).with_name(".env"))

TZ = "Europe/Amsterdam"

# Configuratie
ZONES = {
    "NL": "10YNL----------L", "BE": "10YBE----------2", "DE-LU": "10Y1001A1001A82H",
    "FR": "10YFR-RTE------C", "AT": "10YAT-APG------L", "PL": "10YPL-AREA-----S",
    "DK1": "10YDK-1--------W", "DK2": "10YDK-2--------M", "NO1": "10YNO-1--------2",
    "SE3": "10Y1001A1001A46L", "IT-N": "10Y1001A1001A73I", "ES": "10YES-REE------0",
    "CH": "10YCH-SWISSGRIDZ", "CZ": "10YCZ-CEPS-----N", "HU": "10YHU-MAVIR----U",
}

COUNTRIES = {
    "NL": {"color": "#ff7f0e"}, "BE": {"color": "#d62728"}, "DE-LU": {"color": "#2ca02c"},
    "FR": {"color": "#9467bd"}, "AT": {"color": "#8c564b"}, "PL": {"color": "#1f77b4"},
    "DK1": {"color": "#e377c2"}, "DK2": {"color": "#f7b6d2"}, "NO1": {"color": "#bcbd22"},
    "SE3": {"color": "#17becf"}, "IT-N": {"color": "#aec7e8"}, "ES": {"color": "#ffbb78"},
    "CH": {"color": "#ff9896"}, "CZ": {"color": "#c5b0d5"}, "HU": {"color": "#c49c94"},
}

BASE_DIR = Path(os.getcwd())
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

TOKEN = os.environ.get("WHATSAPP_TOKEN")
PHONE_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
RECIPIENTS = [r.strip() for r in os.environ.get("WHATSAPP_RECIPIENTS", "").split(",") if r.strip()]

# --- HELPER FUNCTIES ---

def ensure_96_quarters(data: np.ndarray) -> np.ndarray:
    length = len(data)
    if length == 96: return data
    if length == 24: return np.repeat(data, 4)
    if length == 48: return np.repeat(data, 2)
    return np.interp(np.linspace(0, length, 96), np.arange(length), data)

# --- PANEL 1: NL BAR PLOT ---
def plot_nl(nl_data: np.ndarray, d_trading: str, d_delivery: str):
    if nl_data is None or len(nl_data) == 0: return None
    q = ensure_96_quarters(nl_data)
    max_p, min_p = np.max(q), np.min(q)
    
    colors = []
    for i, p in enumerate(q):
        if p == max_p: colors.append("#228B22") # HOOGSTE = GROEN
        elif p == min_p: colors.append("#FF0000") # LAAGSTE = ROOD
        elif 32 <= i < 80: colors.append("#87CEEB") # PEAK = BLAUW
        else: colors.append("#7d7d7d") # OFF-PEAK = GRIJS

    fig, ax = plt.subplots(figsize=(14, 8))
    ax.bar(range(96), q, color=colors, edgecolor="black", linewidth=0.4, width=1.0)
    plt.title(f"Netherlands {d_trading} | EPEX Spot DA: {d_delivery}\nBaseload: €{np.mean(q):.2f} Peakload: €{np.mean(q[32:80]):.2f}", fontsize=14)
    ax.set_xticks(np.arange(2, 96, 4))
    ax.set_xticklabels([str(i) for i in range(1, 25)])
    ax.grid(which='both', axis='both', linestyle='-', color='black', alpha=0.1)
    plt.ylim(min(0, min_p - 10), max(130, max_p + 10))
    plt.tight_layout()
    out = OUTPUT_DIR / f"NL_Price_{d_delivery}.jpg"
    plt.savefig(out, dpi=150)
    plt.close()
    return out

# --- PANEL 2: MULTI COUNTRY ---
def plot_multi(hourly_map: dict, d_delivery: str):
    plt.figure(figsize=(15, 9))
    for c in sorted(hourly_map.keys()):
        arr = hourly_map[c]
        if arr is None or len(arr) == 0: continue
        q_data = ensure_96_quarters(arr)
        plt.plot(np.arange(96), q_data, label=c, color=COUNTRIES.get(c, {}).get("color", "black"), linewidth=1.5, alpha=0.8)
    plt.title(f"Day-Ahead Prijsvergelijking Europa (96 Kwartieren) - {d_delivery}", fontsize=15)
    plt.xticks(np.arange(2, 96, 4), [str(i) for i in range(1, 25)])
    plt.grid(True, linestyle="--", alpha=0.4)
    plt.legend(loc='upper left', bbox_to_anchor=(1.01, 1), fontsize=10)
    plt.tight_layout()
    out = OUTPUT_DIR / f"Multi_Country_{d_delivery}.jpg"
    plt.savefig(out, dpi=150, bbox_inches='tight')
    plt.close()
    return out

# --- PANEL 3 & 4: SELENIUM SCREENSHOTS ---
def capture_external_data():
    """
    Maakt screenshots van Tenergy en ICE TTF Gas.
    """
    p3_path = OUTPUT_DIR / "Tenergy_imbalance.jpg"
    p4_path = OUTPUT_DIR / "ICE_TTF_Gas.jpg"
    
    chrome_options = Options()
    # Behoud jouw specifieke profiel-pad
    chrome_options.add_argument("--user-data-dir=/Users/keeskoot/Library/Application Support/Google/Chrome/WhatsAppProfile")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.binary_location = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        # Screenshot Tenergy (Panel 3)
        print("Capturing Tenergy...")
        driver.get('https://services.tenergy.nl/public.aspx/actualimbalanceprices')
        time.sleep(5)
        driver.save_screenshot(str(p3_path).replace(".jpg", ".png"))
        Image.open(str(p3_path).replace(".jpg", ".png")).convert("RGB").save(p3_path)
        
        # Screenshot ICE Gas (Panel 4)
        print("Capturing ICE Gas...")
        driver.get('https://www.ice.com/products/27996665/Dutch-TTF-Natural-Gas-Futures/data?marketId=5844634')
        time.sleep(5)
        try:
            # Klik op de grafiek/data knop zoals in jouw script
            btn = driver.find_element(By.XPATH, '/html/body/div[9]/div[3]/div/div[1]/div/div[2]/div/button[3]')
            btn.click()
            time.sleep(3)
        except: pass
        
        driver.save_screenshot(str(p4_path).replace(".jpg", ".png"))
        Image.open(str(p4_path).replace(".jpg", ".png")).convert("RGB").save(p4_path)
        
        driver.quit()
        return p3_path, p4_path
    except Exception as e:
        print(f"Selenium Error: {e}")
        return None, None

# --- COLLAGE & SEND ---
def create_collage(paths, out_path: Path):
    cell_size = (1200, 900)
    canvas = Image.new("RGB", (2400, 1800), (255, 255, 255))
    positions = [(0, 0), (1200, 0), (0, 900), (1200, 900)]
    
    for i, p in enumerate(paths):
        if p and p.exists():
            im = Image.open(p)
            im.thumbnail(cell_size, Image.Resampling.LANCZOS)
            # Center in cell
            x_off = positions[i][0] + (cell_size[0] - im.size[0]) // 2
            y_off = positions[i][1] + (cell_size[1] - im.size[1]) // 2
            canvas.paste(im, (x_off, y_off))
            
    canvas.save(out_path, quality=90)
    return out_path

def send_whatsapp_image(image_path: Path):
    if not TOKEN or not PHONE_ID: return
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with open(image_path, "rb") as f:
        up = requests.post(f"https://graph.facebook.com/v18.0/{PHONE_ID}/media", 
                           headers=headers, files={"file": (image_path.name, f, "image/jpeg"), "messaging_product": (None, "whatsapp")})
    if up.status_code != 200: return
    media_id = up.json()["id"]
    for rcp in RECIPIENTS:
        payload = {"messaging_product": "whatsapp", "to": rcp, "type": "template", 
                   "template": {"name": "daily_report_nl", "language": {"code": "nl"},
                   "components": [{"type": "header", "parameters": [{"type": "image", "image": {"id": media_id}}]} ]}}
        requests.post(f"https://graph.facebook.com/v18.0/{PHONE_ID}/messages", headers=headers, json=payload)

# --- MAIN ---
def main():
    now = datetime.now(ZoneInfo(TZ))
    api_key = os.environ.get("ENTSOE_API_KEY")
    target_date = (pd.Timestamp.now(tz=TZ) + pd.Timedelta(days=1)).normalize()
    d_delivery = target_date.strftime("%Y-%m-%d")

    # 1. ENTSO-E Data
    print("Fetching ENTSO-E data...")
    series_map = wait_for_day_ahead(api_key, zones=ZONES, target_date=target_date)
    hourly_map = {k: (None if v is None else v.astype(float).values) for k, v in series_map.items()}

    # 2. Plots maken (Panel 1 & 2)
    p1 = plot_nl(hourly_map.get("NL"), now.strftime("%Y-%m-%d"), d_delivery)
    p2 = plot_multi(hourly_map, d_delivery)

    # 3. Selenium Screenshots (Panel 3 & 4)
    print("Starting Selenium captures...")
    p3, p4 = capture_external_data()

    # 4. Collage
    print("Creating collage...")
    final_report = OUTPUT_DIR / f"Market_Report_{d_delivery}.jpg"
    create_collage([p1, p2, p3, p4], final_report)

    # 5. Send
    try:
        send_whatsapp_image(final_report)
        print(f"Succes! Rapport verzonden: {final_report}")
    except Exception as e:
        print(f"Fout bij verzenden: {e}")

if __name__ == "__main__":
    main()