# ⛽ UK Fuel Price Tracker

An interactive, mobile-first map that tracks live petrol and diesel forecourt prices across the United Kingdom (with initial focus on **Kent & the South East**, expanding UK-wide), powered by official UK Government open data and retailer feeds.

Live forecourt prices are updated automatically every day at 4:00 AM UK time via a scheduled GitHub Actions job and published on GitHub Pages.

---

## 🌟 Key Features

- **Official Open Data**: Directly integrated with the statutory **UK Government Fuel Finder scheme** (*The Motor Fuel Price (Open Data) Regulations 2025*) and retailer feeds (Asda, MFG, Applegreen, etc.), mapping over **8,900 petrol stations**.
- **Automatic Geolocation**: Automatically localises the map to the user's location on startup, showing nearby forecourts and driving distances.
- **Four Fuel Types**: Instant toggle between **E10 Unleaded**, **B7 Diesel**, **E5 Super Unleaded**, and **Premium Diesel**.
- **Dynamic Relative Price Colouring**:
  - 🟢 **Green**: Cheapest 25% within the visible map area
  - 🟡 **Amber**: Mid-range average
  - 🔴 **Red**: Most expensive 25%
- **Mobile First Design**: Touch-optimised bottom sheet, fast marker clustering, and zero battery drain.
- **Station Detail Cards**: Forecourt brand badges, full addresses, all fuel prices, freshness timestamps, and a 1-click **Get Directions** link to Google Maps / Apple Maps.
- **Filters**: Filter by brand (Esso, BP, Shell, Asda, Tesco, Morrisons, Sainsbury's, Texaco, Jet, etc.), maximum price slider, area/postcode search, and a toggle to hide stale prices (>7 days old).
- **Fail-Safe Publishing**: GitHub Actions validates the dataset before publishing. If a data feed is down, the workflow fails safely and keeps serving the last known good dataset.

---

## 🚀 Quick Start: Running Locally

The project requires only standard **Python 3.8+** with **zero external pip dependencies** (built entirely using Python's standard library).

### 1. Refresh Data & Rebuild Site
Run the unified refresh command in the project root:

```bash
python refresh.py
```

This single command will:
1. Fetch latest raw feeds in parallel from the official UK Fuel Finder scheme and CMA retailer endpoints into `data/raw/`.
2. Clean, validate, and normalise all records.
3. Eliminate price anomalies (<100p or >250p) and flag stale data.
4. Output the compact production datasets (`public/data/prices.json` and `public/data/prices-southeast.json`).
5. Print a summary report of forecourts, fuel availability, and feed health.

### 2. View the Interactive Map Locally
Serve the `public` directory using Python's built-in HTTP server:

```bash
python -m http.server 8080 -d public
```

Then open your browser to:
[http://localhost:8080](http://localhost:8080)

---

## 🔄 How the Data Refresh Works

1. **Parallel Collection (`src/collector.py`)**:
   - Queries the official UK Government Fuel Finder CSV endpoint (`fuel-finder.service.gov.uk`) and retailer JSON feeds concurrently.
   - Saves raw files to `data/raw/` with a friendly User-Agent identification.
2. **Normalisation & Cleansing (`src/normaliser.py`)**:
   - Parses forecourt coordinates, addresses, and postcodes into canonical formats.
   - Deduplicates forecourts appearing across multiple feeds, retaining the newest timestamp.
   - Enforces plausibility bounds (rejecting values under 100p or above 250p, e.g. placeholder `999.9p`).
   - Flags prices older than 7 days as `stale: true`.
3. **Fail-Safe Deployment (`refresh.py` & `.github/workflows/refresh.yml`)**:
   - If the refresh produces fewer than 500 valid stations or if the feed fails, the script aborts immediately.
   - `public/data/prices.json` is never overwritten with empty or corrupted data.

---

## ⏰ Changing the Refresh Schedule

The automated refresh frequency is configured in [`.github/workflows/refresh.yml`](.github/workflows/refresh.yml):

```yaml
on:
  schedule:
    # Run every day at 4:00 AM UK time
    # (03:00 UTC during British Summer Time BST / 04:00 UTC during Greenwich Mean Time GMT)
    - cron: '0 3,4 * * *'
```

To adjust how often prices refresh:
- **Daily at 6:00 AM UK time**: `cron: '0 5,6 * * *'`
- **Every 3 hours**: `cron: '0 */3 * * *'`
- **Hourly**: `cron: '0 * * * *'`

You can also trigger an immediate refresh at any time using the **Run workflow** button under the GitHub Actions tab.

---

## 🌐 Steps to Put the Site Online on GitHub Pages

Follow these exact steps when you are ready to publish:

### Step 1: Create a GitHub Repository
1. Log in to [GitHub](https://github.com) and click **New repository**.
2. Name it (e.g., `uk-fuel-prices`) and keep it **Public**.
3. Do not initialize with a README, `.gitignore`, or license (they are already present here).

### Step 2: Push Your Local Code
Open your terminal in this directory and run:

```bash
git init
git add .
git commit -m "feat: initial commit of UK Fuel Price Tracker"
git branch -M main
git remote add origin https://github.com/<YOUR-USERNAME>/uk-fuel-prices.git
git push -u origin main
```

### Step 3: Enable GitHub Pages
1. Go to your repository on GitHub.
2. Click **Settings** (top tab) -> **Pages** (in the left sidebar).
3. Under **Build and deployment** -> **Source**, select **GitHub Actions**.
4. That's it! The workflow defined in `.github/workflows/refresh.yml` will automatically build the site, deploy it, and refresh it every 3 hours.
5. Your website will be live at:
   `https://<YOUR-USERNAME>.github.io/uk-fuel-prices/`

---

## 📄 Data Sources & Licences

- **UK Government Fuel Finder Data**: Published under the [Open Government Licence v3.0 (OGL)](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/). Overseen by the Department for Energy Security and Net Zero (DESNZ) and the Competition and Markets Authority (CMA).
- **Map Data**: &copy; [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors.
- **Software**: Distributed under the MIT Licence.
