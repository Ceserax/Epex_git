#!/usr/bin/env python
# coding: utf-8

# In[ ]:


import time
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import os
import subprocess
from io import StringIO
from pathlib import Path
import schedule
import requests
import json
from dotenv import load_dotenv

# Afbeeldingsverwerking
from PIL import Image

# Selenium
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# ==========================================
# INSTELLINGEN
# ==========================================
COUNTRIES = {
    'PL': {'color': '#1f77b4', 'name': 'PL'},
    'NL': {'color': '#ff7f0e', 'name': 'NL'},
    'DE-LU': {'color': '#2ca02c', 'name': 'DE-LU'},
    'BE': {'color': '#d62728', 'name': 'BE'},
    'FR': {'color': '#9467bd', 'name': 'FR'},
    'AT': {'color': '#8c564b', 'name': 'AT'}
}

# Paden instellen (Huidige map gebruiken voor eenvoud)
BASE_DIR = Path(os.getcwd())
SCREENSHOT_DIR = BASE_DIR / "screenshots"
OUTPUT_DIR = BASE_DIR / "output"

# Zorg dat mappen bestaan
SCREENSHOT_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# WhatsApp configuratie
ENV_PATH = Path('/Users/keeskoot/EnergyMarket/.env')
load_dotenv(dotenv_path=ENV_PATH)

TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
RECIPIENTS = ["31622801254", "31611199676"]


# ==========================================
# 1. BROWSER SETUP (ROBUUST)
# ==========================================
def init_driver():
    """Initialiseert de Chrome driver met stealth opties en automatische installatie."""
    print("Browser initialiseren...")
    
    try:
        # Optioneel: Oude drivers opruimen (uit jouw snippet)
        chromedriver_wdm = Path.home() / '.wdm' / 'drivers' / 'chromedriver'
        if chromedriver_wdm.exists():
            try:
                # Let op: dit werkt alleen op Mac/Linux, op Windows negeren we fouten
                subprocess.run(['rm', '-rf', str(chromedriver_wdm)], capture_output=True)
            except Exception:
                pass

        options = Options()
        
        # Profiel pad (lokaal houden om permissie-fouten te voorkomen)
        profile_dir = BASE_DIR / "chrome_profile_unified"
        options.add_argument(f"user-data-dir={profile_dir}")
        
        # Stealth & Performance instellingen
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        
        # Automatische installatie van de juiste driver
        service = Service(ChromeDriverManager().install())
        
        driver = webdriver.Chrome(service=service, options=options)
        print("Chrome WebDriver succesvol gestart.")
        return driver

    except Exception as e:
        print(f"FATALE FOUT bij starten browser: {e}")
        return None

# ==========================================
# 2. DATA BESCHIKBAARHEID CHECKEN
# ==========================================
def check_data_availability(driver, country, d_trading, d_delivery, max_retries=3):
    """
    Controleert of er data beschikbaar is op EPEX voor een specifiek land.
    Retourneert True als data beschikbaar is, False zo niet.
    """
    product_id = "15" if country == 'NL' else "60"
    url = f"https://www.epexspot.com/en/market-results?market_area={country}&trading_date={d_trading}&delivery_date={d_delivery}&modality=Auction&sub_modality=DayAhead&product={product_id}&data_mode=table"
    
    for attempt in range(max_retries):
        try:
            driver.get(url)
            
            # Popup killer
            try: 
                driver.execute_script("var b=document.getElementById('onetrust-banner-sdk'); if(b) b.remove();")
            except: 
                pass

            # Wacht op tabel
            try:
                WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "table")))
            except:
                return False

            # Controleer of er daadwerkelijk data is
            dfs = pd.read_html(StringIO(driver.page_source))
            for df in dfs:
                if len(df) > 20:  # Minimaal 20 rijen betekent data
                    return True
            
            return False
            
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            return False
    
    return False

def wait_for_data_availability(driver, d_trading, d_delivery):
    """
    Wacht totdat de EPEX data beschikbaar is voor NL (als referentie land).
    Controleert elke minuut of de data er is.
    """
    print(f"\n{'='*60}")
    print(f"Wachten op data beschikbaarheid voor {d_delivery}")
    print(f"{'='*60}\n")
    
    wait_count = 0
    while True:
        wait_count += 1
        current_time = datetime.now().strftime('%H:%M:%S')
        print(f"[{current_time}] Poging {wait_count}: Data beschikbaarheid controleren...")
        
        # Check of NL data beschikbaar is (als indicator voor alle landen)
        if check_data_availability(driver, 'NL', d_trading, d_delivery):
            print(f"\n✓ Data is beschikbaar! Script wordt voortgezet.\n")
            return True
        
        print(f"   > Data nog niet beschikbaar. Wachten 60 seconden...")
        time.sleep(60)  # 1 minuut wachten

# ==========================================
# 3. EPEX DATA OPHALEN
# ==========================================
def get_epex_data(driver, country, d_trading, d_delivery):
    product_id = "15" if country == 'NL' else "60"
    
    print(f"--- EPEX {country}: Data ophalen... ---")
    url = f"https://www.epexspot.com/en/market-results?market_area={country}&trading_date={d_trading}&delivery_date={d_delivery}&modality=Auction&sub_modality=DayAhead&product={product_id}&data_mode=table"
    
    try:
        driver.get(url)
        # Popup killer
        try: driver.execute_script("var b=document.getElementById('onetrust-banner-sdk'); if(b) b.remove();")
        except: pass

        try: 
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "table")))
        except: 
            print(f"   > Geen tabel gevonden voor {country}")
            return None

        # Data lezen
        dfs = pd.read_html(StringIO(driver.page_source))
        target_df = None
        for df in dfs:
            if len(df) > 20:
                target_df = df
                break
        
        if target_df is None: return None

        # Opschonen
        df = target_df.copy()
        df.columns = [' '.join(str(c) for c in col).strip() if isinstance(col, tuple) else str(col) for col in df.columns]
        
        col_price = None
        for col in df.columns:
            c_low = col.lower()
            if ('price' in c_low or 'euro' in c_low) and 'volume' not in c_low:
                col_price = col
                break
        if not col_price: col_price = df.columns[-1]

        clean_df = pd.DataFrame()
        clean_df['Prijs'] = df[col_price].astype(str).str.replace(',', '.', regex=False)
        clean_df['Prijs'] = pd.to_numeric(clean_df['Prijs'], errors='coerce')
        clean_df = clean_df.dropna().reset_index(drop=True)
        
        return clean_df

    except Exception as e:
        print(f"   > Fout bij {country}: {e}")
        return None

# ==========================================
# 4. SCREENSHOT FUNCTIE
# ==========================================
def navigate_and_capture(driver, url, folder_path, prefix, delay=3):
    """
    Navigeert naar een URL, wacht een aantal seconden en slaat een screenshot op als JPG.
    """
    print(f"--- Screenshot maken: {prefix} ---")
    try:
        driver.get(url)
        time.sleep(delay)
        
        # Voor Tenergy/Gas futures: soms moeten we scrollen of elementen weghalen
        # Hier houden we het simpel: fullscreen screenshot
        
        folder = Path(folder_path)
        folder.mkdir(parents=True, exist_ok=True)
        
        target_path = folder / f"{prefix}.jpg"
        temp_png_path = folder / f"{prefix}_temp.png"
        
        # Screenshot maken (PNG)
        # We pakken de body voor een full page effect indien mogelijk, anders window
        try:
            # Probeer element te vinden om te focussen of gewoon body
            driver.find_element(By.TAG_NAME, "body")
        except: pass

        success = driver.save_screenshot(str(temp_png_path))
        
        if success:
            # Converteren naar JPG via Pillow
            img_obj = Image.open(temp_png_path)
            # Converteer RGBA naar RGB als nodig
            if img_obj.mode in ("RGBA", "P"):
                img_obj = img_obj.convert('RGB')
                
            img_obj.save(target_path, quality=85)
            
            # Temp verwijderen
            if temp_png_path.exists():
                temp_png_path.unlink()
                
            print(f"   > Opgeslagen: {target_path}")
            return target_path
        else:
            print(f"   > Screenshot mislukt voor {prefix}")
            return None
            
    except Exception as e:
        print(f"   > Fout bij screenshot {prefix}: {e}")
        return None

# ==========================================
# 5. GRAFIEK FUNCTIES (EPEX)
# ==========================================
def plot_nl_exact_style(df, date_trading, date_delivery):
    if df is None or len(df) < 90: return None

    prices = df['Prijs'].values
    n_quarters = len(prices)
    
    baseload = np.mean(prices)
    # Peakload (08:00 - 20:00) -> kwartier 32 t/m 80
    if n_quarters >= 80:
        peak_prices = prices[32:80]
        peakload = np.mean(peak_prices)
    else:
        peakload = 0
    
    std_dev = np.std(prices)
    min_price = np.min(prices)
    max_price = np.max(prices)
    
    bar_colors = []
    for i, p in enumerate(prices):
        if p == max_price: bar_colors.append('red')
        elif p == min_price: bar_colors.append('green')
        elif 32 <= i < 80: bar_colors.append('#87CEEB')
        else: bar_colors.append('gray')

    plt.figure(figsize=(14, 7))
    plt.bar(range(n_quarters), prices, color=bar_colors, edgecolor='black', linewidth=0.5, width=0.8)
    
    title = f"Netherlands {date_trading} | Epexspot DA: {date_delivery}\nBaseload: €{baseload:.2f}  Peakload: €{peakload:.2f}  Std Dev: €{std_dev:.2f}"
    plt.title(title, fontsize=14)
    plt.ylabel("Prijs (€ per MWh)", fontsize=12)
    plt.xlabel("Kwartieren van de dag (Uur)", fontsize=12)
    
    plt.grid(True, which='both', linestyle='-', linewidth=0.5, color='gray', alpha=0.5)
    plt.minorticks_on()
    plt.grid(which='minor', linestyle=':', linewidth=0.5, alpha=0.3)
    
    plt.xticks(range(0, 96, 4), range(1, 25))
    plt.xlim(-1, 96)
    plt.tight_layout()
    
    filename = OUTPUT_DIR / f"NL_Price_{date_delivery}.jpg" # Opslaan als JPG voor collage
    plt.savefig(filename, dpi=150, format='jpg')
    plt.close()
    return filename

def plot_multi_exact_style(all_data, date_delivery):
    if not all_data: return None

    plt.figure(figsize=(15, 9))
    hours_range = range(1, 25)
    stats_text = []
    all_prices_flat = []
    
    for country, prices in all_data.items():
        # Converteren naar uren indien nodig
        if len(prices) > 90:
            prices = pd.Series(prices).groupby(np.arange(len(prices)) // 4).mean().values
            
        plot_prices = prices[:24]
        if len(plot_prices) == 0: continue
        
        current_x = hours_range[:len(plot_prices)]
        all_prices_flat.extend(plot_prices)
        
        baseload = np.mean(plot_prices)
        peak_prices = plot_prices[8:20] if len(plot_prices) >= 20 else [0]
        peakload = np.mean(peak_prices)
            
        color = COUNTRIES[country]['color']
        
        plt.plot(current_x, plot_prices, label=country, color=color, linewidth=1.5)
        stats_line = f"{country}: Base €{baseload:.2f} €, Peak €{peakload:.2f} €"
        stats_text.append({'text': stats_line, 'color': color})

    if all_prices_flat:
        y_max = np.max(all_prices_flat)
        y_min = np.min(all_prices_flat)
        y_range = y_max - y_min
        x_pos = 23.8
        y_start = y_max 
        for i, item in enumerate(stats_text):
            y_pos = y_start - (i * (y_range * 0.04)) 
            plt.text(x_pos, y_pos, item['text'], color=item['color'], 
                     fontsize=10, ha='right', va='top', weight='normal')

    plt.title(f"Day-Ahead Uurgemiddelden voor {', '.join(all_data.keys())} - {date_delivery}", fontsize=14)
    plt.ylabel("Gemiddelde Prijs (€/MWh)", fontsize=12)
    plt.xlabel("Uur", fontsize=12)
    plt.grid(True, which='major', linestyle='-', alpha=0.8)
    plt.minorticks_on()
    plt.grid(True, which='minor', linestyle=':', alpha=0.4)
    plt.xticks(range(2, 25, 2))
    plt.xlim(1, 24)
    plt.legend(loc='upper left', title="Market Area", frameon=True, facecolor='white', framealpha=0.9)
    plt.tight_layout()
    
    filename = OUTPUT_DIR / f"Multi_Country_DA_{date_delivery}.jpg"
    plt.savefig(filename, dpi=150, format='jpg')
    plt.close()
    return filename

# ==========================================
# 6. COLLAGE MAKEN
# ==========================================
def create_collage(image_paths, collage_path, grid=(2, 2), cell_size=(1000, 800)):
    """
    Maakt een collage.
    """
    print("--- Collage genereren ---")
    valid_images = []
    
    # Filter None waarden (mislukte screenshots)
    safe_paths = [p for p in image_paths if p is not None]
    
    for path in safe_paths:
        try:
            img = Image.open(path)
            # Resize met behoud van aspect ratio zodat het in de cell past
            img.thumbnail(cell_size, Image.Resampling.LANCZOS)
            
            # Witte achtergrond cel maken
            cell = Image.new('RGB', cell_size, (255, 255, 255))
            
            # Centreren
            left = (cell_size[0] - img.size[0]) // 2
            top = (cell_size[1] - img.size[1]) // 2
            cell.paste(img, (left, top))
            
            valid_images.append(cell)
        except Exception as e:
            print(f"   > Kon afbeelding {path} niet verwerken: {e}")

    if not valid_images:
        print("   > Geen afbeeldingen om samen te voegen.")
        return

    # Collage canvas maken
    collage_width = grid[0] * cell_size[0]
    collage_height = grid[1] * cell_size[1]
    collage_image = Image.new('RGB', (collage_width, collage_height), (255, 255, 255))
    
    for index, img in enumerate(valid_images):
        if index >= grid[0] * grid[1]: break # Niet meer plaatsen dan grid grootte
        
        x = (index % grid[0]) * cell_size[0]
        y = (index // grid[0]) * cell_size[1]
        collage_image.paste(img, (x, y))
    
    collage_image.save(collage_path)
    print(f"Collage succesvol opgeslagen: {collage_path}")

# ==========================================
# 7. WHATSAPP VERSTUREN
# ==========================================
def send_whatsapp_collage(collage_path):
    """
    Verstuurt collage via WhatsApp Business API naar meerdere ontvangers.
    Gebruikt template 'daily_report_nl'.
    """
    if not TOKEN or not PHONE_ID:
        print("ERROR: Missing environment variables (TOKEN or PHONE_ID) in .env")
        return False

    if not os.path.exists(collage_path):
        print(f"ERROR: Collage niet gevonden op {collage_path}")
        return False

    print(f"\n{'='*60}")
    print("WhatsApp Verzenden")
    print(f"{'='*60}\n")
    print(f"Collage gevonden: {collage_path}")

    # 1. Upload Image (Eén keer uploaden is genoeg)
    print("Uploaden naar Meta...")
    upload_url = f"https://graph.facebook.com/v18.0/{PHONE_ID}/media"
    headers = {"Authorization": f"Bearer {TOKEN}"}
    
    try:
        with open(collage_path, 'rb') as f:
            files = {
                'file': (os.path.basename(collage_path), f, 'image/jpeg'),
                'messaging_product': (None, 'whatsapp')
            }
            upload_response = requests.post(upload_url, headers=headers, files=files)
        
        if upload_response.status_code != 200:
            print(f"Upload mislukt: {upload_response.text}")
            return False
            
        media_id = upload_response.json()['id']
        print(f"✓ Upload geslaagd! Media ID: {media_id}")

        # 2. Send Template to ALL recipients
        send_url = f"https://graph.facebook.com/v18.0/{PHONE_ID}/messages"
        send_headers = {
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json"
        }
        
        success_count = 0
        for recipient in RECIPIENTS:
            print(f"Versturen naar {recipient}...")
            payload = {
                "messaging_product": "whatsapp",
                "to": recipient,
                "type": "template",
                "template": {
                    "name": "daily_report_nl",
                    "language": {"code": "nl"},
                    "components": [
                        {
                            "type": "header",
                            "parameters": [
                                {
                                    "type": "image",
                                    "image": {"id": media_id}
                                }
                            ]
                        }
                    ]
                }
            }
            
            send_response = requests.post(send_url, headers=send_headers, json=payload)
            
            if send_response.status_code == 200:
                print(f"✓ Bericht succesvol verzonden naar {recipient}!")
                success_count += 1
            else:
                print(f"✗ Verzenden naar {recipient} mislukt: {send_response.text}")

        print(f"\n{'='*60}")
        print(f"✓ WhatsApp verzending compleet: {success_count}/{len(RECIPIENTS)} succesvol")
        print(f"{'='*60}\n")
        return success_count > 0

    except Exception as e:
        print(f"Fout opgetreden bij WhatsApp verzending: {e}")
        return False

# ==========================================
# 8. HOOFD PROGRAMMA
# ==========================================
def run_daily_job():
    """
    Hoofdfunctie die dagelijks om 13:00 wordt uitgevoerd.
    Wacht op data beschikbaarheid en maakt dan de collage.
    """
    # Datums
    today = datetime.now()
    target_date = today + timedelta(days=1)
    d_trading = today.strftime('%Y-%m-%d')
    d_delivery = target_date.strftime('%Y-%m-%d')
    
    print(f"\n{'='*60}")
    print(f"Start dagelijkse job om {datetime.now().strftime('%H:%M:%S')}")
    print(f"Trading datum: {d_trading}")
    print(f"Levering datum: {d_delivery}")
    print(f"{'='*60}\n")
    
    driver = init_driver()
    if not driver:
        print("Kan browser niet starten. Script wordt afgebroken.")
        return

    # Lijsten om resultaten bij te houden
    collected_epex_data = {}
    path_nl_graph = None
    path_multi_graph = None
    path_tenergy = None
    path_gas = None
    collage_filename = None

    try:
        # STAP 1: Wacht tot data beschikbaar is
        wait_for_data_availability(driver, d_trading, d_delivery)
        
        # STAP 2: EPEX Data & Grafieken
        print("\n--- EPEX Data verzamelen voor alle landen ---\n")
        for country in COUNTRIES.keys():
            df = get_epex_data(driver, country, d_trading, d_delivery)
            if df is not None and not df.empty:
                collected_epex_data[country] = df['Prijs'].values
            time.sleep(2)

        # Genereer EPEX Grafieken als data aanwezig is
        if collected_epex_data:
            print("\n--- EPEX Grafieken genereren ---\n")
            # Grafiek 1: NL Detail
            if 'NL' in collected_epex_data:
                nl_df = pd.DataFrame({'Prijs': collected_epex_data['NL']})
                path_nl_graph = plot_nl_exact_style(nl_df, d_trading, d_delivery)
            
            # Grafiek 2: Multi Country
            path_multi_graph = plot_multi_exact_style(collected_epex_data, d_delivery)

        # STAP 3: Screenshots
        print("\n--- Screenshots maken ---\n")
        
        # Tenergy
        path_tenergy = navigate_and_capture(
            driver,
            'https://services.tenergy.nl/public.aspx/actualimbalanceprices',
            str(SCREENSHOT_DIR),
            f"Tenergy_{d_trading}",
            delay=5
        )
        
        # Gas Futures
        path_gas = navigate_and_capture(
            driver,
            'https://www.ice.com/products/27996665/Dutch-TTF-Natural-Gas-Futures/data?marketId=5844634',
            str(SCREENSHOT_DIR),
            f"Gas_Futures_{d_trading}",
            delay=10
        )

    except Exception as e:
        print(f"\n❌ Fout tijdens uitvoering: {e}")
    finally:
        driver.quit()
        print("\nBrowser afgesloten.")

    # STAP 4: Collage Maken
    print("\n--- Collage maken ---\n")
    images_to_collage = [path_nl_graph, path_multi_graph, path_tenergy, path_gas]
    
    collage_filename = OUTPUT_DIR / f"Energy_Collage_{d_delivery}.jpg"
    
    # Controleer of we iets hebben om te collagen
    if any(images_to_collage):
        create_collage(
            images_to_collage, 
            str(collage_filename), 
            grid=(2, 2), 
            cell_size=(1000, 800)
        )
        
        print(f"\n{'='*60}")
        print(f"✓ Collage succesvol gemaakt!")
        print(f"✓ Collage opgeslagen: {collage_filename}")
        print(f"{'='*60}\n")
        
        # STAP 5: Verstuur via WhatsApp
        send_whatsapp_collage(str(collage_filename))
        
        # Opruimen losse bestanden (optioneel)
        # for p in images_to_collage:
        #     if p and os.path.exists(p): os.remove(p)
    else:
        print("\n❌ Geen afbeeldingen gegenereerd, collage overgeslagen.\n")

def main():
    """
    Start de scheduler die elke dag om 13:00 uur de job uitvoert.
    """
    print(f"\n{'='*60}")
    print("Energy Data Collage Generator + WhatsApp")
    print(f"{'='*60}")
    print(f"Script gestart om {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("Scheduler ingesteld voor dagelijks 13:00 uur")
    print(f"Ontvangers: {', '.join(RECIPIENTS)}")
    print(f"{'='*60}\n")
    
    # Schedule de dagelijkse job om 13:00
    schedule.every().day.at("13:15").do(run_daily_job)
    
    print("Wachten tot 13:15 uur voor de eerste run...")
    print(f"Huidige tijd: {datetime.now().strftime('%H:%M:%S')}\n")
    
    # Blijf draaien en check elke minuut of er een job moet worden uitgevoerd
    while True:
        schedule.run_pending()
        time.sleep(60)  # Check elke minuut

if __name__ == "__main__":
    main()

