import os
import time
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from datetime import datetime
from pathlib import Path
from PIL import Image
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
TZINFO = ZoneInfo(TZ)

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

# WhatsApp config
TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN")
PHONE_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
RECIPIENTS = [r.strip() for r in os.environ.get("WHATSAPP_RECIPIENTS", "").split(",") if r.strip()]

# Gedrag bij incomplete data:
# - FAIL_IF_INCOMPLETE=1  -> raise error -> GitHub run rood
# - anders               -> netjes stoppen -> GitHub run groen
FAIL_IF_INCOMPLETE = os.environ.get("FAIL_IF_INCOMPLETE", "0") == "1"


# --- HELPER FUNCTIES ---

def expected_hours_for_delivery_date(target_date: pd.Timestamp, tz: str) -> int:
    """
    DST-proof: geeft 23/24/25 afhankelijk van zomertijd-omschakeling.
    target_date is een tz-aware Timestamp in Europe/Amsterdam, genormaliseerd op middernacht.
    """
    start_ts = pd.Timestamp(target_date.date(), tz=tz)
    end_ts = start_ts + pd.Timedelta(days=1)
    hours = len(pd.date_range(start_ts, end_ts, freq="h", inclusive="left", tz=tz))
    return hours

def ensure_96_quarters(data: np.ndarray) -> np.ndarray:
    length = len(data)
    if length == 0:
        return data
    if length == 96:
        return data
    if length == 24:
        return np.repeat(data, 4)
    if length == 48:
        return np.repeat(data, 2)
    return np.interp(np.linspace(0, length - 1, 96), np.arange(length), data)

# --- PANEL 1: NL BAR PLOT ---
def plot_nl(nl_data: np.ndarray, d_trading: str, d_delivery: str):
    if nl_data is None or len(nl_data) == 0:
        return None

    q = ensure_96_quarters(nl_data)
    max_p, min_p = np.max(q), np.min(q)

    colors = []
    for i, p in enumerate(q):
        if p == max_p:
            colors.append("#228B22")  # hoogste groen
        elif p == min_p:
            colors.append("#FF0000")  # laagste rood
        elif 32 <= i < 80:
            colors.append("#87CEEB")  # peak blauw
        else:
            colors.append("#7d7d7d")  # off-peak grijs

    fig, ax = plt.subplots(figsize=(14, 8))
    ax.bar(range(96), q, color=colors, edgecolor="black", linewidth=0.4, width=1.0)
    plt.title(
        f"Netherlands {d_trading} | EPEX Spot DA: {d_delivery}\n"
        f"Baseload: €{np.mean(q):.2f} Peakload: €{np.mean(q[32:80]):.2f}",
        fontsize=14
    )
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
        if arr is None or len(arr) == 0:
            continue

        baseload = np.mean(arr)
        label_text = f"{c} (€{baseload:.2f})"
        q_data = ensure_96_quarters(arr)

        plt.plot(
            np.arange(96),
            q_data,
            label=label_text,
            color=COUNTRIES.get(c, {}).get("color", "black"),
            linewidth=1.5,
            alpha=0.8
        )

    plt.title(f"Day-Ahead Prijsvergelijking Europa (96 Kwartieren) - {d_delivery}", fontsize=15)
    plt.xticks(np.arange(2, 96, 4), [str(i) for i in range(1, 25)])
    plt.ylabel("Prijs (€/MWh)")
    plt.xlabel("Uur van de dag")
    plt.grid(True, linestyle="--", alpha=0.4)
    plt.legend(loc='upper left', bbox_to_anchor=(1.01, 1), fontsize=10, title="Landen (Baseload)")

    plt.tight_layout()
    out = OUTPUT_DIR / f"Multi_Country_{d_delivery}.jpg"
    plt.savefig(out, dpi=150, bbox_inches='tight')
    plt.close()
    return out

def init_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")

    if not os.environ.get("GITHUB_ACTIONS"):
        chrome_options.add_argument("--user-data-dir=/Users/keeskoot/Library/Application Support/Google/Chrome/WhatsAppProfile")

    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

def capture_external_data():
    p3_path = OUTPUT_DIR / "Tenergy_imbalance.jpg"
    p4_path = OUTPUT_DIR / "ICE_TTF_Gas.jpg"

    driver = None
    try:
        driver = init_driver()

        print("Capturing Tenergy...")
        driver.get('https://services.tenergy.nl/public.aspx/actualimbalanceprices')
        time.sleep(7)
        driver.save_screenshot(str(p3_path).replace(".jpg", ".png"))
        Image.open(str(p3_path).replace(".jpg", ".png")).convert("RGB").save(p3_path)

        print("Capturing ICE Gas...")
        driver.get('https://www.ice.com/products/27996665/Dutch-TTF-Natural-Gas-Futures/data?marketId=5844634')
        time.sleep(8)

        try:
            btn = driver.find_element(By.XPATH, '//button[contains(text(), "Chart")]')
            btn.click()
            time.sleep(3)
        except Exception:
            print("ICE knop niet gevonden of niet nodig.")

        driver.save_screenshot(str(p4_path).replace(".jpg", ".png"))
        Image.open(str(p4_path).replace(".jpg", ".png")).convert("RGB").save(p4_path)

        for p in [p3_path, p4_path]:
            png = str(p).replace(".jpg", ".png")
            if os.path.exists(png):
                os.remove(png)

        return p3_path, p4_path

    except Exception as e:
        print(f"Selenium Error: {e}")
        return None, None
    finally:
        if driver:
            driver.quit()

def create_collage(paths, out_path: Path):
    cell_size = (1200, 900)
    canvas = Image.new("RGB", (2400, 1800), (255, 255, 255))
    positions = [(0, 0), (1200, 0), (0, 900), (1200, 900)]

    for i, p in enumerate(paths):
        if p and p.exists():
            im = Image.open(p)
            im.thumbnail(cell_size, Image.Resampling.LANCZOS)
            x_off = positions[i][0] + (cell_size[0] - im.size[0]) // 2
            y_off = positions[i][1] + (cell_size[1] - im.size[1]) // 2
            canvas.paste(im, (x_off, y_off))

    canvas.save(out_path, quality=90)
    return out_path

def send_whatsapp_image(image_path: Path) -> bool:
    if not TOKEN or not PHONE_ID:
        raise RuntimeError("WHATSAPP_ACCESS_TOKEN of WHATSAPP_PHONE_NUMBER_ID ontbreekt")

    if not RECIPIENTS:
        raise RuntimeError("WHATSAPP_RECIPIENTS is leeg")

    headers = {"Authorization": f"Bearer {TOKEN}"}

    print(f"Media uploaden naar WhatsApp: {image_path.name}...")
    with open(image_path, "rb") as f:
        up = requests.post(
            f"https://graph.facebook.com/v18.0/{PHONE_ID}/media",
            headers=headers,
            files={"file": (image_path.name, f, "image/jpeg")},
            data={"messaging_product": "whatsapp"},
            timeout=60,
        )

    if not up.ok:
        raise RuntimeError(f"Media upload failed {up.status_code}: {up.text[:1500]}")

    media_id = up.json().get("id")
    if not media_id:
        raise RuntimeError(f"Geen media id teruggekregen: {up.text[:1500]}")
    print(f"✅ Media geüpload. Media ID: {media_id}")

    failures = []
    for rcp in RECIPIENTS:
        print(f"Bericht versturen naar {rcp}...")
        payload = {
            "messaging_product": "whatsapp",
            "to": rcp,
            "type": "template",
            "template": {
                "name": "daily_report_nl",
                "language": {"code": "nl"},
                "components": [{
                    "type": "header",
                    "parameters": [{"type": "image", "image": {"id": media_id}}],
                }]
            }
        }

        resp = requests.post(
            f"https://graph.facebook.com/v18.0/{PHONE_ID}/messages",
            headers=headers,
            json=payload,
            timeout=60,
        )

        if resp.ok:
            print(f"✅ Succesvol verzonden naar {rcp}")
        else:
            failures.append((rcp, resp.status_code, resp.text))

    if failures:
        short = "; ".join([f"{r}:{code}" for r, code, _ in failures])
        raise RuntimeError(f"WhatsApp send failures: {short}. Eerste error: {failures[0][2][:800]}")

    return True

def check_if_already_sent(d_delivery):
    state_dir = Path(".state")
    state_file = state_dir / f"sent_{d_delivery}.txt"

    if state_file.exists():
        print(f">>> [SKIP] Rapport voor {d_delivery} is al eerder verzonden.")
        return True
    return False

def mark_as_sent(d_delivery):
    state_dir = Path(".state")
    state_dir.mkdir(exist_ok=True)
    state_file = state_dir / f"sent_{d_delivery}.txt"
    with open(state_file, "w") as f:
        f.write(f"Verzonden op {datetime.now(TZINFO)}")
    print(f">>> [STATE] Succes opgeslagen in {state_file}")

def main():
    now = datetime.now(TZINFO)

    api_key = os.environ.get("ENTSOE_API_KEY")
    if not api_key:
        raise RuntimeError("ENTSOE_API_KEY ontbreekt")

    # target_date vanuit NL-tijd (minder UTC-verwarring)
    target_date = (pd.Timestamp(now).tz_convert(TZ).normalize() + pd.Timedelta(days=1))
    d_delivery = target_date.strftime("%Y-%m-%d")

    if check_if_already_sent(d_delivery):
        return

    exp_hours = expected_hours_for_delivery_date(target_date, TZ)
    print(f"[INFO] Delivery date: {d_delivery} | expected hours (DST-proof): {exp_hours}")

    # --- Cruciale fix: watcher kan TimeoutError gooien -> afvangen ---
    try:
        series_map = wait_for_day_ahead(
            api_key,
            zones=ZONES,
            target_date=target_date,
            primary_zone="NL"
        )
    except TimeoutError as e:
        msg = f"NL nog niet compleet binnen watcher-timeout: {e}"
        if FAIL_IF_INCOMPLETE:
            raise RuntimeError(msg)
        print("⚠️", msg)
        return

    if not isinstance(series_map, dict):
        msg = f"Onverwachte return van wait_for_day_ahead: {type(series_map)}"
        if FAIL_IF_INCOMPLETE:
            raise RuntimeError(msg)
        print("⚠️", msg)
        return

    nl_series = series_map.get("NL")
    if nl_series is None:
        msg = f"NL series ontbreekt/None voor {d_delivery}"
        if FAIL_IF_INCOMPLETE:
            raise RuntimeError(msg)
        print("⚠️", msg)
        return

    # DST-proof completeness check in jouw script (niet hardcoded 24)
    nl_non_na = int(nl_series.dropna().shape[0])
    if nl_non_na < exp_hours:
        msg = f"NL data nog niet compleet: {nl_non_na}/{exp_hours} uren."
        if FAIL_IF_INCOMPLETE:
            raise RuntimeError(msg)
        print("⚠️", msg)
        return

    hourly_map = {k: (None if v is None else v.astype(float).values) for k, v in series_map.items()}
    ok_countries = [k for k, v in hourly_map.items() if v is not None]
    print(f"[INFO] NL data compleet. Landen met data: {ok_countries}")

    # Plots
    p1 = plot_nl(hourly_map.get("NL"), now.strftime("%Y-%m-%d"), d_delivery)
    p2 = plot_multi(hourly_map, d_delivery)

    # Selenium captures
    print("Starting Selenium captures...")
    p3, p4 = capture_external_data()

    # Collage
    print("Creating collage...")
    final_report = OUTPUT_DIR / f"Market_Report_{d_delivery}.jpg"
    create_collage([p1, p2, p3, p4], final_report)

    # WhatsApp verzending
    ok = send_whatsapp_image(final_report)
    if ok:
        print(f"✅ Succes! Rapport verzonden: {final_report}")
        mark_as_sent(d_delivery)

if __name__ == "__main__":
    main()
