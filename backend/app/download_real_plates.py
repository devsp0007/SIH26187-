import urllib.request
import urllib.error
import ssl
from pathlib import Path

# Create directory for real license plate test photos
test_dir = Path("backend/test_data/real_plates")
test_dir.mkdir(parents=True, exist_ok=True)

# List of real Wikimedia Commons photographs with license plates
urls = {
    "real_car_1_baleno.jpg": "https://upload.wikimedia.org/wikipedia/commons/d/d8/2022_Maruti_Suzuki_Baleno_Alpha_%28India%29_front_view_02.jpg",
    "real_car_2_creta.jpg": "https://upload.wikimedia.org/wikipedia/commons/7/7f/2021_Hyundai_Creta_SX%28O%29_CRDi_%28India%29_front_view.jpg",
    "real_car_3_vitara.jpg": "https://upload.wikimedia.org/wikipedia/commons/c/c0/2022_Maruti_Suzuki_Grand_Vitara_Zeta_Smart_Hybrid_%28India%29_front_view.jpg",
    "real_plate_1_kerala.jpg": "https://upload.wikimedia.org/wikipedia/commons/f/f3/License_plate_of_Kerala%2C_India.jpg",
    "real_plate_2_indian_reg.jpg": "https://upload.wikimedia.org/wikipedia/commons/8/8b/Indian_registration_2313.jpg",
    "real_plate_3_autorickshaw.jpg": "https://upload.wikimedia.org/wikipedia/commons/d/d6/India_license_plate_of_an_Auto_Rickshaw_at_Nizampet.jpg",
    "real_plate_5_diplomatic.jpg": "https://upload.wikimedia.org/wikipedia/commons/b/b9/Diplomatic_Vehicle_Registration_Plate_India.jpg",
    "real_plate_6_military.jpg": "https://upload.wikimedia.org/wikipedia/commons/c/c2/Military_Vehicle_Registration_plate-India.jpg",
}

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

import time

headers = {
    "User-Agent": "IBVAP_Surveillance_Academic_Evaluator/1.0 (https://github.com/ibvap; evaluation@ibvap.org) Python-urllib/3.13"
}

downloaded = []
for filename, url in urls.items():
    dst = test_dir / filename
    if dst.exists() and dst.stat().st_size > 1000:
        print(f"[+] Already downloaded {filename} ({dst.stat().st_size} bytes)")
        downloaded.append(dst)
        continue

    try:
        time.sleep(2.0)  # Rate limiting compliance
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
            data = resp.read()
            with open(dst, "wb") as f:
                f.write(data)
            print(f"[+] Successfully downloaded {filename} ({len(data)} bytes)")
            downloaded.append(dst)
    except Exception as e:
        print(f"[!] Failed downloading {filename} from {url}: {e}")

print(f"\nTotal real plate images downloaded: {len(downloaded)}/{len(urls)}")
