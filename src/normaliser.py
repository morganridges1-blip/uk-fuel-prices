"""Data Normaliser for UK Fuel Price Tracker.

Reads raw CSV and JSON feeds, normalises forecourts into a unified schema,
cleans addresses, deduplicates across sources, filters implausible prices,
flags stale data, and writes the compact production prices.json.
"""

import csv
import datetime
import io
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Normaliser")

MIN_PLAUSIBLE_PRICE = 100.0  # 100p per litre
MAX_PLAUSIBLE_PRICE = 250.0  # 250p per litre
STALE_DAYS_THRESHOLD = 7

# Canonical brand name mapping
BRAND_MAP = {
    "TESCO": "Tesco",
    "SAINSBURYS": "Sainsbury's",
    "SAINSBURY'S": "Sainsbury's",
    "ASDA": "Asda",
    "MORRISONS": "Morrisons",
    "BP": "BP",
    "SHELL": "Shell",
    "ESSO": "Esso",
    "TEXACO": "Texaco",
    "JET": "Jet",
    "GULF": "Gulf",
    "APPLEGREEN": "Applegreen",
    "APPLEGREEEN": "Applegreen",
    "CO-OP": "Co-op",
    "COOP": "Co-op",
    "RONTEC": "Rontec",
    "HARVEST ENERGY": "Harvest Energy",
    "PACE": "Pace",
    "MURCO": "Murco",
    "MAXOL": "Maxol",
    "MOTO": "Moto",
    "WELCOME BREAK": "Welcome Break",
    "ROADCHEF": "Roadchef",
}

# Kent and South East postcode prefixes
KENT_POSTCODES = {"CT", "DA", "ME", "TN", "BR"}
SOUTH_EAST_POSTCODES = {
    "CT", "DA", "ME", "TN", "BR",  # Kent & borders
    "BN", "RH",  # Sussex
    "GU", "KT", "SM", "CR",  # Surrey
    "PO", "SO", "RG",  # Hampshire / Berkshire
    "OX", "HP", "SL", "MK",  # Oxfordshire / Bucks / Berks
}


def clean_brand(raw_brand: Optional[str]) -> str:
    """Standardise brand name to clean display format."""
    if not raw_brand:
        return "Independent"
    b_upper = raw_brand.strip().upper()
    if b_upper in BRAND_MAP:
        return BRAND_MAP[b_upper]
    # Default title casing
    return raw_brand.strip().title()


def clean_postcode(raw_postcode: Optional[str]) -> str:
    """Format UK postcode with canonical single space."""
    if not raw_postcode:
        return ""
    p = raw_postcode.strip().upper()
    p = re.sub(r"\s+", "", p)
    if len(p) >= 5:
        return f"{p[:-3]} {p[-3:]}"
    return p


def get_postcode_area(postcode: str) -> str:
    """Extract outward postcode area code (e.g. 'ME14' -> 'ME')."""
    match = re.match(r"^([A-Z]{1,2})", postcode.upper())
    return match.group(1) if match else ""


def parse_timestamp(ts_raw: Optional[str]) -> Optional[datetime.datetime]:
    """Parse various datetime string formats into UTC datetime object."""
    if not ts_raw or str(ts_raw).lower() in ("null", "none", ""):
        return None

    s = str(ts_raw).strip()

    # Format 1: 'Fri Oct 02 2026 15:30:27 GMT+0000 (Coordinated Universal Time)'
    # Or 'Thu Oct 08 2026 21:07:34 GMT+0100 (British Summer Time)'
    match = re.match(r"^[A-Za-z]{3}\s+([A-Za-z]{3})\s+(\d{1,2})\s+(\d{4})\s+(\d{2}:\d{2}:\d{2})", s)
    if match:
        month_str, day_str, year_str, time_str = match.groups()
        try:
            dt = datetime.datetime.strptime(f"{day_str} {month_str} {year_str} {time_str}", "%d %b %Y %H:%M:%S")
            return dt.replace(tzinfo=datetime.timezone.utc)
        except Exception:
            pass

    # Format 2: '09/10/2026 11:00:00' or '26/02/2025 11:45:37'
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.datetime.strptime(s, fmt)
            return dt.replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            continue

    # ISO fallback with regex
    iso_match = re.match(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})", s)
    if iso_match:
        try:
            y, m, d, hh, mm, ss = map(int, iso_match.groups())
            return datetime.datetime(y, m, d, hh, mm, ss, tzinfo=datetime.timezone.utc)
        except Exception:
            pass

    return None


def validate_price(val: Any) -> Tuple[Optional[float], Optional[float]]:
    """Validate and round price in pence per litre.

    Returns (valid_price, rejected_raw_price).
    """
    if val is None or val == "" or str(val).lower() in ("null", "none"):
        return None, None
    try:
        p = float(val)
        if MIN_PLAUSIBLE_PRICE <= p <= MAX_PLAUSIBLE_PRICE:
            return round(p, 1), None
        else:
            return None, p  # Flagged as implausible
    except (ValueError, TypeError):
        return None, None


class Normaliser:
    """Normalises raw fuel price files into unified JSON dataset."""

    def __init__(self, now: Optional[datetime.datetime] = None):
        self.now = now or datetime.datetime.now(datetime.timezone.utc)
        self.stations: Dict[str, Dict[str, Any]] = {}
        self.rejected_prices: List[Dict[str, Any]] = []
        self.raw_station_counts: Dict[str, int] = {}
        self.stats: Dict[str, Any] = {
            "total_raw_records": 0,
            "deduplicated_stations": 0,
            "e10_count": 0,
            "e5_count": 0,
            "b7_standard_count": 0,
            "b7_premium_count": 0,
            "stale_count": 0,
            "rejected_price_count": 0,
            "kent_count": 0,
            "south_east_count": 0,
            "brand_counts": {},
        }

    def process_fuel_finder_csv(self, filepath: str) -> None:
        """Process official UK Government Fuel Finder CSV."""
        if not os.path.exists(filepath):
            logger.warning("Fuel Finder CSV not found: %s", filepath)
            return

        logger.info("Normalising Fuel Finder CSV: %s", filepath)
        count = 0
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                count += 1

                # Check closures
                if row.get("forecourts.permanent_closure", "").lower() == "true":
                    continue
                if row.get("forecourts.temporary_closure", "").lower() == "true":
                    continue

                lat_str = row.get("forecourts.location.latitude", "").strip()
                lon_str = row.get("forecourts.location.longitude", "").strip()
                try:
                    lat = float(lat_str)
                    lon = float(lon_str)
                    if not (49.0 <= lat <= 61.5 and -9.0 <= lon <= 2.5):
                        continue
                except (ValueError, TypeError):
                    continue

                postcode = clean_postcode(row.get("forecourts.location.postcode", ""))
                brand = clean_brand(row.get("forecourts.brand_name", ""))
                trading_name = (row.get("forecourts.trading_name") or f"{brand} PFS").strip().title()

                addr_parts = [
                    row.get("forecourts.location.address_line_1", "").strip().title(),
                    row.get("forecourts.location.address_line_2", "").strip().title(),
                    row.get("forecourts.location.city", "").strip().title(),
                ]
                address = ", ".join([p for p in addr_parts if p])

                county = (row.get("forecourts.location.county") or "").strip().title()
                country = (row.get("forecourts.location.country") or "").strip().title()

                # Parse prices
                e10, rej_e10 = validate_price(row.get("forecourts.fuel_price.E10"))
                e5, rej_e5 = validate_price(row.get("forecourts.fuel_price.E5"))
                b7_s, rej_b7s = validate_price(row.get("forecourts.fuel_price.B7S"))
                b7_p, rej_b7p = validate_price(row.get("forecourts.fuel_price.B7P"))

                for fuel_name, rej in [("E10", rej_e10), ("E5", rej_e5), ("B7 Standard", rej_b7s), ("B7 Premium", rej_b7p)]:
                    if rej is not None:
                        self.rejected_prices.append({
                            "station": trading_name,
                            "brand": brand,
                            "postcode": postcode,
                            "fuel": fuel_name,
                            "price": rej,
                            "source": "Fuel Finder",
                        })

                # Timestamps
                updated_dt = parse_timestamp(row.get("forecourt_update_timestamp"))
                # Fall back to fuel price submission timestamp if needed
                if not updated_dt:
                    for ts_field in ("forecourts.price_submission_timestamp.E10", "forecourts.price_submission_timestamp.B7S"):
                        updated_dt = parse_timestamp(row.get(ts_field))
                        if updated_dt:
                            break

                # Create station record
                station_record = {
                    "node_id": row.get("forecourts.node_id", ""),
                    "name": trading_name,
                    "brand": brand,
                    "address": address,
                    "postcode": postcode,
                    "county": county,
                    "country": country,
                    "lat": round(lat, 6),
                    "lon": round(lon, 6),
                    "prices": {
                        "e10": e10,
                        "e5": e5,
                        "b7": b7_s,
                        "b7_prem": b7_p,
                    },
                    "updated_at": updated_dt.isoformat() if updated_dt else None,
                    "updated_dt": updated_dt,
                    "source": "Fuel Finder (GOV.UK)",
                }

                self._upsert_station(station_record)

        self.raw_station_counts["fuel_finder"] = count
        logger.info("Processed %d stations from Fuel Finder CSV", count)

    def process_cma_json(self, filepath: str, source_name: str) -> None:
        """Process a CMA retailer JSON feed (Asda, MFG, Applegreen, etc.)."""
        if not os.path.exists(filepath):
            return

        logger.info("Normalising CMA JSON (%s): %s", source_name, filepath)
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
        except Exception as e:
            logger.error("Failed to parse JSON file %s: %s", filepath, e)
            return

        raw_stations = data.get("stations", [])
        feed_last_updated = parse_timestamp(data.get("last_updated"))
        count = 0

        for s in raw_stations:
            count += 1
            loc = s.get("location", {})
            try:
                lat = float(loc.get("latitude"))
                lon = float(loc.get("longitude"))
                if not (49.0 <= lat <= 61.5 and -9.0 <= lon <= 2.5):
                    continue
            except (ValueError, TypeError):
                continue

            postcode = clean_postcode(s.get("postcode", ""))
            brand = clean_brand(s.get("brand", ""))
            address = (s.get("address") or "").strip()
            name = s.get("site_name") or f"{brand} {s.get('address', '').split(',')[0]}" or f"{brand} PFS"

            raw_prices = s.get("prices", {})
            e10, rej_e10 = validate_price(raw_prices.get("E10"))
            e5, rej_e5 = validate_price(raw_prices.get("E5"))
            b7, rej_b7 = validate_price(raw_prices.get("B7"))
            sdv, rej_sdv = validate_price(raw_prices.get("SDV") or raw_prices.get("Premium Diesel"))

            for fuel_name, rej in [("E10", rej_e10), ("E5", rej_e5), ("B7", rej_b7), ("Premium Diesel", rej_sdv)]:
                if rej is not None:
                    self.rejected_prices.append({
                        "station": name,
                        "brand": brand,
                        "postcode": postcode,
                        "fuel": fuel_name,
                        "price": rej,
                        "source": source_name,
                    })

            station_record = {
                "node_id": s.get("site_id", ""),
                "name": name.strip().title(),
                "brand": brand,
                "address": address,
                "postcode": postcode,
                "county": "",
                "country": "UK",
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "prices": {
                    "e10": e10,
                    "e5": e5,
                    "b7": b7,
                    "b7_prem": sdv,
                },
                "updated_at": feed_last_updated.isoformat() if feed_last_updated else None,
                "updated_dt": feed_last_updated,
                "source": f"{source_name.upper()} Direct Feed",
            }

            self._upsert_station(station_record)

        self.raw_station_counts[source_name] = count
        logger.info("Processed %d stations from %s JSON", count, source_name)

    def _upsert_station(self, new_rec: Dict[str, Any]) -> None:
        """Deduplicate stations using normalised postcode + brand or coordinates."""
        postcode = new_rec["postcode"]
        # Primary key: postcode + brand (or rounded lat/lon if postcode missing)
        if postcode:
            dedup_key = f"{postcode}_{new_rec['brand'].lower()}"
        else:
            dedup_key = f"{round(new_rec['lat'], 3)}_{round(new_rec['lon'], 3)}"

        if dedup_key in self.stations:
            existing = self.stations[dedup_key]
            # Keep whichever is newer
            new_dt = new_rec.get("updated_dt")
            old_dt = existing.get("updated_dt")

            if new_dt and (not old_dt or new_dt > old_dt):
                # New record is more recent; update prices and timestamp
                for k, v in new_rec["prices"].items():
                    if v is not None:
                        existing["prices"][k] = v
                existing["updated_at"] = new_rec["updated_at"]
                existing["updated_dt"] = new_dt
                existing["source"] = new_rec["source"]
            else:
                # Merge any missing prices from new record into existing
                for k, v in new_rec["prices"].items():
                    if existing["prices"].get(k) is None and v is not None:
                        existing["prices"][k] = v
        else:
            self.stations[dedup_key] = new_rec

    def build_output_dataset(self) -> Dict[str, Any]:
        """Compile final dataset, flag staleness, compute metrics and regional tags."""
        stale_cutoff = self.now - datetime.timedelta(days=STALE_DAYS_THRESHOLD)
        cleaned_stations: List[Dict[str, Any]] = []

        brand_counter: Dict[str, int] = {}
        e10_cnt = 0
        e5_cnt = 0
        b7_cnt = 0
        b7_prem_cnt = 0
        stale_cnt = 0
        kent_cnt = 0
        se_cnt = 0

        for key, s in self.stations.items():
            # Check staleness
            dt = s.get("updated_dt")
            is_stale = False
            if dt and dt < stale_cutoff:
                is_stale = True
                stale_cnt += 1

            # Count fuels
            prices = s["prices"]
            has_any_price = False
            if prices.get("e10") is not None:
                e10_cnt += 1
                has_any_price = True
            if prices.get("e5") is not None:
                e5_cnt += 1
                has_any_price = True
            if prices.get("b7") is not None:
                b7_cnt += 1
                has_any_price = True
            if prices.get("b7_prem") is not None:
                b7_prem_cnt += 1
                has_any_price = True

            # Skip stations with zero fuel prices listed
            if not has_any_price:
                continue

            # Region tagging
            pc_area = get_postcode_area(s["postcode"])
            is_kent = pc_area in KENT_POSTCODES or "Kent" in s["county"]
            is_se = pc_area in SOUTH_EAST_POSTCODES or is_kent or "Sussex" in s["county"] or "Surrey" in s["county"]

            if is_kent:
                kent_cnt += 1
            if is_se:
                se_cnt += 1

            brand = s["brand"]
            brand_counter[brand] = brand_counter.get(brand, 0) + 1

            # Clean station item for compact output
            clean_item = {
                "id": s.get("node_id") or key,
                "name": s["name"],
                "brand": brand,
                "address": s["address"],
                "postcode": s["postcode"],
                "lat": s["lat"],
                "lon": s["lon"],
                "prices": prices,
                "updated_at": s["updated_at"],
                "stale": is_stale,
                "source": s["source"],
                "is_kent": is_kent,
                "is_se": is_se,
            }
            cleaned_stations.append(clean_item)

        # Sort stations deterministically (Kent & SE first, then by brand and postcode)
        cleaned_stations.sort(key=lambda x: (not x["is_se"], x["brand"], x["postcode"]))

        self.stats = {
            "generated_at": self.now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "total_raw_records": sum(self.raw_station_counts.values()),
            "total_stations": len(cleaned_stations),
            "e10_count": e10_cnt,
            "e5_count": e5_cnt,
            "b7_standard_count": b7_cnt,
            "b7_premium_count": b7_prem_cnt,
            "stale_count": stale_cnt,
            "rejected_price_count": len(self.rejected_prices),
            "kent_count": kent_cnt,
            "south_east_count": se_cnt,
            "brand_counts": dict(sorted(brand_counter.items(), key=lambda i: i[1], reverse=True)),
            "sources": self.raw_station_counts,
        }

        return {
            "generated_at": self.now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "stats": self.stats,
            "stations": cleaned_stations,
        }


def normalise_all(raw_dir: str = "data/raw", output_file: str = "public/data/prices.json") -> Dict[str, Any]:
    """Execute complete normalisation pipeline."""
    normaliser = Normaliser()

    # 1. Primary: UK Fuel Finder CSV
    fuel_finder_path = os.path.join(raw_dir, "fuel_finder.csv")
    normaliser.process_fuel_finder_csv(fuel_finder_path)

    # 2. Secondary CMA feeds
    for json_file in ("asda.json", "mfg.json", "applegreen.json"):
        source_name = json_file.split(".")[0]
        json_path = os.path.join(raw_dir, json_file)
        normaliser.process_cma_json(json_path, source_name)

    dataset = normaliser.build_output_dataset()

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        # Compact separators for minimal JSON payload
        json.dump(dataset, f, separators=(",", ":"))

    logger.info("Wrote %d normalised stations to %s (%.2f MB)",
                len(dataset["stations"]),
                output_file,
                os.path.getsize(output_file) / (1024 * 1024))

    return {
        "dataset": dataset,
        "rejected_prices": normaliser.rejected_prices,
    }


if __name__ == "__main__":
    result = normalise_all()
    stats = result["dataset"]["stats"]
    print("\n--- Normalisation Statistics ---")
    for k, v in stats.items():
        if k != "brand_counts":
            print(f"{k}: {v}")
    print("\nTop 10 Brands:")
    for b, c in list(stats["brand_counts"].items())[:10]:
        print(f"  {b}: {c}")
