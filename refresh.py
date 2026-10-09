#!/usr/bin/env python3
"""Unified Refresh Script for UK Fuel Price Tracker.

Refreshes fuel price data from all live feeds, validates and normalises the dataset,
and updates public/data/prices.json and public/data/summary.json.

Fail-safe: If collection or normalisation fails to produce a valid dataset (>500 stations),
existing production files are preserved untouched.
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

from src.collector import collect_all_feeds
from src.normaliser import normalise_all

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Refresh")

MIN_REQUIRED_STATIONS = 500


def main():
    start_time = time.time()
    logger.info("=== UK Fuel Price Tracker: Data Refresh Started ===")

    # 1. Fetch raw data in parallel
    logger.info("Step 1: Collecting data from official feeds...")
    feed_results = collect_all_feeds(output_dir="data/raw")

    successful_feeds = [r for r in feed_results if r["success"]]
    failed_feeds = [r for r in feed_results if not r["success"]]

    logger.info("Feeds status: %d succeeded, %d failed", len(successful_feeds), len(failed_feeds))

    if not successful_feeds:
        logger.critical("All data collection feeds failed! Aborting refresh to preserve existing data.")
        sys.exit(1)

    # 2. Normalise, validate, and write output to temporary path first
    logger.info("Step 2: Normalising and validating data...")
    temp_output = "public/data/prices.tmp.json"
    prod_output = "public/data/prices.json"
    summary_output = "public/data/summary.json"

    try:
        norm_result = normalise_all(raw_dir="data/raw", output_file=temp_output)
        dataset = norm_result["dataset"]
        rejected_prices = norm_result["rejected_prices"]
        stats = dataset["stats"]

        total_stations = stats["total_stations"]
        logger.info("Normalisation complete. Valid stations: %d", total_stations)

        # 3. Fail-safe sanity check
        if total_stations < MIN_REQUIRED_STATIONS:
            logger.critical(
                "Safety check failed: only %d stations generated (minimum required: %d). Preserving existing dataset.",
                total_stations, MIN_REQUIRED_STATIONS
            )
            if os.path.exists(temp_output):
                os.remove(temp_output)
            sys.exit(1)

        # Atomic replacement of production dataset
        if os.path.exists(prod_output):
            try:
                os.replace(temp_output, prod_output)
            except OSError:
                # Windows atomic replacement fallback
                os.remove(prod_output)
                os.rename(temp_output, prod_output)
        else:
            os.rename(temp_output, prod_output)

        # Also write Kent & South East quick-start file for superfast initial mobile rendering
        se_stations = [s for s in dataset["stations"] if s.get("is_se")]
        se_output = "public/data/prices-southeast.json"
        se_dataset = {
            "generated_at": dataset["generated_at"],
            "stats": {
                **stats,
                "total_stations": len(se_stations),
            },
            "stations": se_stations,
        }
        with open(se_output, "w", encoding="utf-8") as f:
            json.dump(se_dataset, f, separators=(",", ":"))

        # Write execution summary & diagnostics report
        summary_data = {
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": round(time.time() - start_time, 2),
            "stats": stats,
            "feed_statuses": feed_results,
            "rejected_price_count": len(rejected_prices),
            "rejected_prices_sample": rejected_prices[:20],
        }

        with open(summary_output, "w", encoding="utf-8") as f:
            json.dump(summary_data, f, indent=2)

        # Print friendly summary report
        print("\n" + "=" * 60)
        print(" UK FUEL PRICE TRACKER: REFRESH COMPLETE")
        print("=" * 60)
        print(f"Total forecourts mapped:       {stats['total_stations']:,}")
        print(f"  - In Kent:                  {stats['kent_count']:,}")
        print(f"  - In South East England:    {stats['south_east_count']:,}")
        print(f"Fuel availability:")
        print(f"  - E10 (Standard Petrol):    {stats['e10_count']:,} stations")
        print(f"  - E5 (Super Unleaded):      {stats['e5_count']:,} stations")
        print(f"  - B7 (Standard Diesel):     {stats['b7_standard_count']:,} stations")
        print(f"  - Premium Diesel:           {stats['b7_premium_count']:,} stations")
        print(f"Quality flags:")
        print(f"  - Stale prices (>7 days):   {stats['stale_count']:,}")
        print(f"  - Implausible/errors:       {stats['rejected_price_count']:,} prices removed (<100p or >250p)")
        print(f"Feeds:")
        for r in feed_results:
            st = "OK" if r["success"] else f"FAILED ({r['error']})"
            print(f"  - {r['label']}: {st}")
        print(f"Execution time:                {round(time.time() - start_time, 2)}s")
        print("=" * 60 + "\n")

    except Exception as e:
        logger.exception("Unexpected error during refresh: %s", e)
        if os.path.exists(temp_output):
            os.remove(temp_output)
        sys.exit(1)


if __name__ == "__main__":
    main()
