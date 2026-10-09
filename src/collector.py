"""Data Collector for UK Petrol & Diesel Prices.

Fetches data in parallel from the official UK Government Fuel Finder scheme
and CMA retailer open data feeds, saving raw files to data/raw/.
"""

import concurrent.futures
import json
import logging
import os
import ssl
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Collector")

USER_AGENT = "UKFuelPriceTracker/1.0 (OpenDataProject; +https://github.com/)"

FEEDS = [
    {
        "name": "fuel_finder",
        "label": "UK Government Fuel Finder (Statutory Scheme)",
        "url": "https://www.fuel-finder.service.gov.uk/internal/v1.0.2/csv/get-latest-fuel-prices-csv",
        "filename": "fuel_finder.csv",
        "format": "csv",
        "primary": True,
    },
    {
        "name": "asda",
        "label": "Asda Stores Ltd",
        "url": "https://storelocator.asda.com/fuel_prices_data.json",
        "filename": "asda.json",
        "format": "json",
        "primary": False,
    },
    {
        "name": "mfg",
        "label": "Motor Fuel Group (MFG - BP/Shell/Esso/Texaco)",
        "url": "https://fuel.motorfuelgroup.com/fuel_prices_data.json",
        "filename": "mfg.json",
        "format": "json",
        "primary": False,
    },
    {
        "name": "applegreen",
        "label": "Applegreen Stores",
        "url": "https://www.applegreenstores.com/fuel-prices/data.json",
        "filename": "applegreen.json",
        "format": "json",
        "primary": False,
    },
    {
        "name": "tesco",
        "label": "Tesco Stores (Standalone CMA Feed)",
        "url": "https://www.tesco.com/fuel_prices/fuel_prices_data.json",
        "filename": "tesco.json",
        "format": "json",
        "primary": False,
    },
    {
        "name": "bp",
        "label": "BP UK (Standalone CMA Feed)",
        "url": "https://www.bp.com/en_gb/united-kingdom/home/fuelprices/fuel_prices_data.json",
        "filename": "bp.json",
        "format": "json",
        "primary": False,
    },
    {
        "name": "shell",
        "label": "Shell UK (Standalone CMA Feed)",
        "url": "https://www.shell.co.uk/fuel-prices-data.json",
        "filename": "shell.json",
        "format": "json",
        "primary": False,
    },
    {
        "name": "morrisons",
        "label": "Morrisons (Standalone CMA Feed)",
        "url": "https://service.morrisons.com/fuel-prices/fuel_prices_data.json",
        "filename": "morrisons.json",
        "format": "json",
        "primary": False,
    },
    {
        "name": "sainsburys",
        "label": "Sainsbury's (Standalone CMA Feed)",
        "url": "https://api.sainsburys.co.uk/v1/exports/latest/fuel_prices_data.json",
        "filename": "sainsburys.json",
        "format": "json",
        "primary": False,
    },
]


def fetch_single_feed(feed: Dict[str, Any], output_dir: str, timeout: int = 25) -> Dict[str, Any]:
    """Fetch a single feed and save to disk."""
    name = feed["name"]
    url = feed["url"]
    filename = feed["filename"]
    filepath = os.path.join(output_dir, filename)

    result = {
        "name": name,
        "label": feed["label"],
        "url": url,
        "format": feed["format"],
        "primary": feed.get("primary", False),
        "filepath": filepath,
        "success": False,
        "status_code": None,
        "bytes_fetched": 0,
        "error": None,
        "duration_sec": 0.0,
    }

    t0 = time.time()
    ctx = ssl.create_default_context()

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/csv,application/json,*/*",
        },
    )

    try:
        logger.info("Fetching %s from %s...", name, url)
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as response:
            status = response.status
            content = response.read()

            result["status_code"] = status
            result["bytes_fetched"] = len(content)

            # Sanity check content
            if len(content) < 50:
                raise ValueError("Response too short (less than 50 bytes)")

            # Check format basic validity
            if feed["format"] == "json":
                try:
                    json.loads(content.decode("utf-8", errors="replace"))
                except Exception as je:
                    raise ValueError(f"Invalid JSON payload: {je}")

            with open(filepath, "wb") as f:
                f.write(content)

            result["success"] = True
            logger.info("Successfully fetched %s (%d bytes)", name, len(content))

    except urllib.error.HTTPError as e:
        result["status_code"] = e.code
        result["error"] = f"HTTP {e.code}: {e.reason}"
        logger.warning("Feed %s failed: HTTP %s", name, e.code)
    except urllib.error.URLError as e:
        result["error"] = f"Network error: {e.reason}"
        logger.warning("Feed %s failed: Network error %s", name, e.reason)
    except Exception as e:
        result["error"] = str(e)
        logger.warning("Feed %s failed: %s", name, str(e))
    finally:
        result["duration_sec"] = round(time.time() - t0, 2)

    return result


def collect_all_feeds(output_dir: str = "data/raw", max_workers: int = 6) -> List[Dict[str, Any]]:
    """Fetch all feeds in parallel with one worker per feed."""
    os.makedirs(output_dir, exist_ok=True)
    results = []

    logger.info("Starting parallel collection for %d feeds...", len(FEEDS))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_feed = {
            executor.submit(fetch_single_feed, feed, output_dir): feed for feed in FEEDS
        }
        for future in concurrent.futures.as_completed(future_to_feed):
            res = future.result()
            results.append(res)

    return sorted(results, key=lambda r: (not r["primary"], r["name"]))


if __name__ == "__main__":
    results = collect_all_feeds()
    print("\n--- Collection Summary ---")
    for r in results:
        status = "SUCCESS" if r["success"] else f"FAILED ({r['error']})"
        print(f"[{r['name']}] {status} - {r['bytes_fetched']} bytes in {r['duration_sec']}s")
