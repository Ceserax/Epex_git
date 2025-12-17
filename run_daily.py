import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # nodig op headless runners
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from pathlib import Path
from PIL import Image, ImageDraw
import requests
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).with_name(".env"))

from watcher_entsoe import wait_for_day_ahead  # let op: naam moet matchen in watcher_entsoe.py

TZ = "Europe/Amsterdam"

# ENTSO-E bidding zone EIC codes
ZONES = {
    "PL": "10YPL-AREA-----S",
    "NL": "10YNL----------L",
    "DE-LU": "10Y1001A1001A82H",
    "BE": "10YBE----------2",
    "FR": "10YFR-RTE------C",
    "AT": "10YAT-APG------L",
}

COUNTRIES = {
    "PL": {"color": "#1f77b4"},
    "NL": {"color": "#ff7f0e"},
    "DE-LU": {"color": "#2ca02c"},
    "BE": {"color": "#d62728"},
    "FR": {"color": "#9467bd"},
    "AT": {"color": "#8c564b"},
}

BASE_DIR = Path(os.getcwd())
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

load_dotenv()  # lokaal ok; op GitHub komen env vars via Secrets

TOKEN = os.environ.get("WHATSAPP_TOKEN")
PHONE_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
RECIPIENTS = [r.strip() for r in os.environ.get("WHATSAPP_RECIPIENTS", "").split(",") if r.strip()]

def hourly_to_quarters(hourly: np.ndarray) -> np.ndarray:
    return np.repeat(hourly, 4)

def plot_nl(nl_hourly: np.ndarray, d_trading: str, d_delivery: str):
    if nl_hourly is None or len(nl_hourly) < 20:
        return None

    q = hourly_to_quarters(nl_hourly)
    baseload = float(np.mean(q))
    peak = q[32:80] if len(q) >= 80 else q
    peakload = float(np.mean(peak))
    std_dev = float(np.std(q))
    min_p = float(np.min(q))
    max_p = float(np.max(q))

    colors = []
    for i, p in enumerate(q):
        if p == max_p:
            colors.append("red")
        elif p == min_p:
            colors.append("green")
        elif 32 <= i < 80:
            colors.append("#87CEEB")
        else:
            colors.append("gray")

    plt.figure(figsize=(14, 7))
    plt.bar(range(len(q)), q, color=colors, edgecolor="black", linewidth=0.5, width=0.8)

    plt.title(
        f"Netherlands {d_trading} | ENTSO-E DA: {d_delivery}\n"
        f"Baseload: €{baseload:.2f}  Peakload: €{peakload:.2f}  Std Dev: €{std_dev:.2f}",
        fontsize=14
    )
    plt.ylabel("Prijs (€/MWh)", fontsize=12)
    plt.xlabel("Kwartieren (uur)", fontsize=12)
    plt.grid(True, which="both", linestyle="-", linewidth=0.5, color="gray", alpha=0.5)
    plt.minorticks_on()
    plt.grid(which="minor", linestyle=":", linewidth=0.5, alpha=0.3)

    xticks = list(range(0, len(q), 4))
    xlabels = list(range(1, min(25, len(xticks) + 1)))
    plt.xticks(xticks[:24], xlabels[:24])
    plt.tight_layout()

    out = OUTPUT_DIR / f"NL_Price_{d_delivery}.jpg"
    plt.savefig(out, dpi=150, format="jpg")
    plt.close()
    return out

def plot_multi(hourly_map: dict, d_delivery: str):
    plt.figure(figsize=(15, 9))

    stats = []
    all_flat = []
    for c, arr in hourly_map.items():
        if arr is None or len(arr) < 20:
            continue
        x = np.arange(1, len(arr) + 1)
        y = arr.astype(float)

        all_flat.extend(list(y))
        base = float(np.mean(y))
        peak = y[8:20] if len(y) >= 20 else y
        peakv = float(np.mean(peak))

        col = COUNTRIES.get(c, {}).get("color", None)
        plt.plot(x, y, label=c, color=col, linewidth=1.5)
        stats.append((c, base, peakv, col))

    if all_flat:
        y_max = float(np.max(all_flat))
        y_min = float(np.min(all_flat))
        y_range = max(1.0, y_max - y_min)
        x_pos = max(24, int(plt.gca().get_xlim()[1])) - 0.2
        y_start = y_max
        for i, (c, base, peakv, col) in enumerate(stats):
            plt.text(x_pos, y_start - i * (y_range * 0.04),
                     f"{c}: Base €{base:.2f} | Peak €{peakv:.2f}",
                     color=col, fontsize=10, ha="right", va="top")

    plt.title(f"Day-Ahead uurgemiddelden - {d_delivery}", fontsize=14)
    plt.ylabel("Prijs (€/MWh)", fontsize=12)
    plt.xlabel("Uur", fontsize=12)
    plt.grid(True, which="major", linestyle="-", alpha=0.8)
    plt.minorticks_on()
    plt.grid(True, which="minor", linestyle=":", alpha=0.4)
    plt.legend(loc="upper left", frameon=True)
    plt.tight_layout()

    out = OUTPUT_DIR / f"Multi_Country_DA_{d_delivery}.jpg"
    plt.savefig(out, dpi=150, format="jpg")
    plt.close()
    return out

def placeholder(text: str, out: Path, size=(1000, 800)):
    img = Image.new("RGB", size, (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([20, 20, size[0]-20, size[1]-20], outline=(0, 0, 0), width=3)
    d.text((50, 60), text, fill=(0, 0, 0))
    img.save(out, quality=90)
    return out

def create_collage(paths, out_path: Path, grid=(2, 2), cell_size=(1000, 800)):
    imgs = []
    for p in [p for p in paths if p is not None]:
        im = Image.open(p)
        im.thumbnail(cell_size, Image.Resampling.LANCZOS)
        cell = Image.new("RGB", cell_size, (255, 255, 255))
        cell.paste(im, ((cell_size[0] - im.size[0]) // 2, (cell_size[1] - im.size[1]) // 2))
        imgs.append(cell)

    canvas = Image.new("RGB", (grid[0]*cell_size[0], grid[1]*cell_size[1]), (255, 255, 255))
    for i, im in enumerate(imgs[: grid[0]*grid[1]]):
        x = (i % grid[0]) * cell_size[0]
        y = (i // grid[0]) * cell_size[1]
        canvas.paste(im, (x, y))

    canvas.save(out_path, quality=90)
    print("[debug] collage gemaakt:", out_path)
    return out_path
    print("[debug] collage gemaakt:", collage)

    print("[debug] token_len:", len(TOKEN or ""))
    print("[debug] phone_id:", PHONE_ID)
    print("[debug] recipients:", RECIPIENTS)

    print("[debug] collage:", collage)
    send_whatsapp_image(collage)   # of jouw send_whatsapp_collage(...)
    print("[debug] whatsapp send klaar")

def send_whatsapp_image(image_path: Path):
    if not TOKEN or not PHONE_ID:
        raise RuntimeError("WHATSAPP_TOKEN / WHATSAPP_PHONE_NUMBER_ID ontbreken.")
    if not RECIPIENTS:
        raise RuntimeError("WHATSAPP_RECIPIENTS ontbreekt (comma-separated).")

    upload_url = f"https://graph.facebook.com/v18.0/{PHONE_ID}/media"
    headers = {"Authorization": f"Bearer {TOKEN}"}

    with open(image_path, "rb") as f:
        files = {
            "file": (image_path.name, f, "image/jpeg"),
            "messaging_product": (None, "whatsapp"),
        }
        up = requests.post(upload_url, headers=headers, files=files)
    up.raise_for_status()
    media_id = up.json()["id"]

    send_url = f"https://graph.facebook.com/v18.0/{PHONE_ID}/messages"
    send_headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

    ok = 0
    for rcp in RECIPIENTS:
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
                }],
            },
        }
        resp = requests.post(send_url, headers=send_headers, json=payload)
        if resp.status_code == 200:
            ok += 1
        else:
            print(f"[whatsapp] fail {rcp}: {resp.status_code} {resp.text}")
    print(f"[whatsapp] sent {ok}/{len(RECIPIENTS)}")
from zoneinfo import ZoneInfo
from pathlib import Path
from datetime import datetime


def main():
    now = datetime.now(ZoneInfo("Europe/Amsterdam"))

    if now.hour < 13:
        print("[guard] vóór 13:00 NL, stop.")
        return

    state_dir = Path(".state")
    state_dir.mkdir(exist_ok=True)
    sent_flag = state_dir / f"sent_{now.date().isoformat()}.txt"
    if sent_flag.exists():
        print("[guard] vandaag al verstuurd, stop.")
        return

    api_key = os.environ["ENTSOE_API_KEY"]

    today = datetime.now()
    target_date = today + timedelta(days=1)
    d_trading = today.strftime("%Y-%m-%d")
    d_delivery = target_date.strftime("%Y-%m-%d")

    target = (pd.Timestamp.now(tz=TZ) + pd.Timedelta(days=1)).normalize()
    series_map = wait_for_day_ahead(api_key, zones=ZONES, target_date=target, poll_seconds=60, timeout_minutes=90)

    hourly_map = {k: (None if v is None else v.astype(float).values) for k, v in series_map.items()}

    p1 = plot_nl(hourly_map.get("NL"), d_trading, d_delivery)
    p2 = plot_multi(hourly_map, d_delivery)
    p3 = placeholder("Panel 3 (later): TenneT/Tenergy imbalance", OUTPUT_DIR / f"Panel3_{d_trading}.jpg")
    p4 = placeholder("Panel 4 (later): ICE TTF / gas", OUTPUT_DIR / f"Panel4_{d_trading}.jpg")

    collage = OUTPUT_DIR / f"Energy_Collage_{d_delivery}.jpg"
    create_collage([p1, p2, p3, p4], collage)

    try:
        print("[whatsapp] sending...")
        send_whatsapp_image(collage)
        print("[whatsapp] sent OK")
    except Exception as e:
        print("[whatsapp] ERROR:", type(e).__name__, e)
        raise

    sent_flag.write_text(f"sent at {now.isoformat()}\n", encoding="utf-8")
    print("[guard] sent flag written:", sent_flag)


if __name__ == "__main__":
    main()