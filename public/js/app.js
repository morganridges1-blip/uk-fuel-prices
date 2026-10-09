/**
 * UK Fuel Price Tracker - Interactive Leaflet Application
 * Zero external analytics, privacy-first, reads static JSON only.
 */

(function () {
  "use strict";

  // Application State
  const state = {
    allStations: [],
    filteredStations: [],
    currentFuel: "e10", // 'e10', 'b7', 'e5', 'b7_prem'
    regionScope: "southeast", // 'southeast' or 'all'
    userCoords: null,
    activeStation: null,
    filters: {
      searchQuery: "",
      selectedBrands: new Set(),
      maxPrice: Infinity,
      hideStale: true,
    },
    meta: {
      generatedAt: null,
      stats: {},
    },
    percentiles: {
      p25: 135.0,
      p75: 145.0,
      min: 130.0,
      max: 155.0,
      avg: 140.0,
    },
  };

  // DOM Elements
  const DOM = {
    map: document.getElementById("map"),
    refreshTime: document.getElementById("refresh-time"),
    stationCountLabel: document.getElementById("station-count-label"),
    fuelPills: document.querySelectorAll(".fuel-pill"),
    btnNearMe: document.getElementById("btn-near-me"),
    btnFilter: document.getElementById("btn-filter"),
    filterBadge: document.getElementById("filter-badge"),
    btnRegionScope: document.getElementById("btn-region-scope"),
    regionScopeLabel: document.getElementById("region-scope-label"),
    statMin: document.getElementById("stat-min"),
    statAvg: document.getElementById("stat-avg"),
    statMax: document.getElementById("stat-max"),
    loadingOverlay: document.getElementById("loading-overlay"),
    loadingText: document.getElementById("loading-text"),
    
    // Station Details Sheet
    stationSheet: document.getElementById("station-sheet"),
    sheetBrand: document.getElementById("sheet-brand"),
    sheetTitle: document.getElementById("sheet-title"),
    sheetAddress: document.getElementById("sheet-address"),
    sheetDistance: document.getElementById("sheet-distance"),
    sheetStaleTag: document.getElementById("sheet-stale-tag"),
    sheetUpdatedTime: document.getElementById("sheet-updated-time"),
    sheetSource: document.getElementById("sheet-source"),
    btnDirections: document.getElementById("btn-directions"),
    btnCloseSheet: document.getElementById("btn-close-sheet"),
    sheetDragHandle: document.getElementById("sheet-drag-handle"),
    
    // Price Boxes in Sheet
    boxE10: document.getElementById("box-e10"),
    boxB7: document.getElementById("box-b7"),
    boxE5: document.getElementById("box-e5"),
    boxB7Prem: document.getElementById("box-b7-prem"),
    priceValE10: document.getElementById("price-val-e10"),
    priceValB7: document.getElementById("price-val-b7"),
    priceValE5: document.getElementById("price-val-e5"),
    priceValB7Prem: document.getElementById("price-val-b7-prem"),

    // Filter Modal
    filterModal: document.getElementById("filter-modal"),
    modalBackdrop: document.getElementById("modal-backdrop"),
    btnCloseFilter: document.getElementById("btn-close-filter"),
    searchInput: document.getElementById("search-input"),
    btnClearSearch: document.getElementById("btn-clear-search"),
    priceSlider: document.getElementById("price-slider"),
    priceSliderVal: document.getElementById("price-slider-val"),
    brandChipsContainer: document.getElementById("brand-chips-container"),
    btnSelectAllBrands: document.getElementById("btn-select-all-brands"),
    toggleHideStale: document.getElementById("toggle-hide-stale"),
    btnResetFilters: document.getElementById("btn-reset-filters"),
    btnApplyFilters: document.getElementById("btn-apply-filters"),
  };

  let map = null;
  let clusterGroup = null;
  let userLocationMarker = null;

  // Initial Coordinates: Kent & South East (Maidstone area)
  const KENT_COORDS = [51.2787, 0.5217];
  const KENT_ZOOM = 9;
  const UK_COORDS = [54.5, -2.5];
  const UK_ZOOM = 6;

  /**
   * Initialize Leaflet Map
   */
  function initMap() {
    map = L.map("map", {
      zoomControl: false,
      attributionControl: false,
      maxZoom: 18,
      minZoom: 5,
    }).setView(KENT_COORDS, KENT_ZOOM);

    // Zoom control in top right
    L.control.zoom({ position: "topright" }).addTo(map);

    // High quality OpenStreetMap tiles
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);

    // Custom MarkerCluster Group
    clusterGroup = L.markerClusterGroup({
      showCoverageOnHover: false,
      maxClusterRadius: 55,
      spiderfyOnMaxZoom: true,
      zoomToBoundsOnClick: true,
      iconCreateFunction: createClusterIcon,
    });
    map.addLayer(clusterGroup);

    // Update viewport price stats on pan/zoom
    map.on("moveend", updateViewportPriceStats);
  }

  /**
   * Custom MarkerCluster Icon with station count & average fuel price
   */
  function createClusterIcon(cluster) {
    const count = cluster.getChildCount();
    let avgPriceStr = "";

    try {
      const markers = cluster.getAllChildMarkers();
      let priceSum = 0;
      let priceCount = 0;

      for (let i = 0; i < markers.length; i++) {
        const s = markers[i].stationData;
        if (s && s.prices) {
          const p = s.prices[state.currentFuel];
          if (typeof p === "number") {
            priceSum += p;
            priceCount++;
          }
        }
      }

      if (priceCount > 0) {
        avgPriceStr = (priceSum / priceCount).toFixed(1) + "p";
      }
    } catch (e) {
      // Graceful fallback if markers not immediately accessible
    }

    const size = count < 10 ? 38 : count < 50 ? 46 : 54;

    return L.divIcon({
      html: `<div><span class="cluster-count">${count}</span>${avgPriceStr ? `<span class="cluster-price">${avgPriceStr}</span>` : ""}</div>`,
      className: "marker-cluster-custom",
      iconSize: L.point(size, size),
    });
  }

  /**
   * Calculate price percentiles for dynamic relative colouring
   */
  function calculatePricePercentiles(stationsList) {
    const prices = [];
    for (let i = 0; i < stationsList.length; i++) {
      const p = stationsList[i].prices[state.currentFuel];
      if (typeof p === "number") {
        prices.push(p);
      }
    }

    if (prices.length === 0) {
      return { p25: 135, p75: 145, min: 130, max: 155, avg: 140 };
    }

    prices.sort((a, b) => a - b);
    const min = prices[0];
    const max = prices[prices.length - 1];
    const sum = prices.reduce((a, b) => a + b, 0);
    const avg = sum / prices.length;

    const p25Index = Math.floor(prices.length * 0.25);
    const p75Index = Math.floor(prices.length * 0.75);

    return {
      min: min,
      max: max,
      avg: avg,
      p25: prices[p25Index],
      p75: prices[p75Index],
    };
  }

  /**
   * Get price tier class relative to percentiles
   */
  function getPriceTierClass(price, percentiles) {
    if (typeof price !== "number") return "unknown";
    if (price <= percentiles.p25) return "cheap";
    if (price >= percentiles.p75) return "expensive";
    return "avg";
  }

  /**
   * Render station markers to the cluster group
   */
  function renderMarkers() {
    console.log("renderMarkers called with filteredStations:", state.filteredStations.length);
    clusterGroup.clearLayers();

    state.percentiles = calculatePricePercentiles(state.filteredStations);
    console.log("Calculated percentiles:", state.percentiles);

    const markersToAdd = [];

    for (let i = 0; i < state.filteredStations.length; i++) {
      const s = state.filteredStations[i];
      const price = s.prices[state.currentFuel];
      const tierClass = getPriceTierClass(price, state.percentiles);
      const displayPrice = typeof price === "number" ? `${price.toFixed(1)}p` : "--";

      const icon = L.divIcon({
        className: "custom-price-pin-wrap",
        html: `<div class="price-marker-pin ${tierClass}">${displayPrice}</div>`,
        iconSize: [52, 24],
        iconAnchor: [26, 12],
      });

      const marker = L.marker([s.lat, s.lon], { icon: icon });
      marker.stationData = s;
      marker.on("click", () => openStationDetails(s));
      markersToAdd.push(marker);
    }

    clusterGroup.addLayers(markersToAdd);
    updateViewportPriceStats();
    DOM.stationCountLabel.textContent = `${state.filteredStations.length.toLocaleString()} stations`;
    console.log("renderMarkers finished! Added markers count:", markersToAdd.length);
  }

  /**
   * Calculate viewport stats (min, avg, max) for visible area
   */
  function updateViewportPriceStats() {
    if (!map) return;
    const bounds = map.getBounds();
    const visiblePrices = [];

    for (let i = 0; i < state.filteredStations.length; i++) {
      const s = state.filteredStations[i];
      if (bounds.contains([s.lat, s.lon])) {
        const p = s.prices[state.currentFuel];
        if (typeof p === "number") {
          visiblePrices.push(p);
        }
      }
    }

    if (visiblePrices.length > 0) {
      visiblePrices.sort((a, b) => a - b);
      const min = visiblePrices[0].toFixed(1);
      const max = visiblePrices[visiblePrices.length - 1].toFixed(1);
      const avg = (visiblePrices.reduce((a, b) => a + b, 0) / visiblePrices.length).toFixed(1);

      DOM.statMin.textContent = `Min: ${min}p`;
      DOM.statAvg.textContent = `Avg: ${avg}p`;
      DOM.statMax.textContent = `Max: ${max}p`;
    } else {
      DOM.statMin.textContent = "Min: --";
      DOM.statAvg.textContent = "Avg: --";
      DOM.statMax.textContent = "Max: --";
    }
  }

  /**
   * Filter stations based on user inputs
   */
  function applyFilters() {
    const q = state.filters.searchQuery.trim().toLowerCase();
    const maxP = state.filters.maxPrice;
    const hideStale = state.filters.hideStale;
    const brands = state.filters.selectedBrands;

    let activeFilterCount = 0;
    if (q) activeFilterCount++;
    if (brands.size > 0) activeFilterCount++;
    if (maxP < 210) activeFilterCount++;
    if (hideStale) activeFilterCount++;

    if (activeFilterCount > 0) {
      DOM.filterBadge.style.display = "inline-block";
      DOM.filterBadge.textContent = activeFilterCount;
    } else {
      DOM.filterBadge.style.display = "none";
    }

    state.filteredStations = state.allStations.filter((s) => {
      // 1. Regional focus check (if in Kent & South East mode)
      if (state.regionScope === "southeast" && !s.is_se) {
        return false;
      }

      // 2. Hide stale
      if (hideStale && s.stale) {
        return false;
      }

      // 3. Search query (matches postcode, address, name, or brand)
      if (q) {
        const pc = (s.postcode || "").toLowerCase();
        const addr = (s.address || "").toLowerCase();
        const nm = (s.name || "").toLowerCase();
        const br = (s.brand || "").toLowerCase();
        if (!pc.includes(q) && !addr.includes(q) && !nm.includes(q) && !br.includes(q)) {
          return false;
        }
      }

      // 4. Brand filter
      if (brands.size > 0 && !brands.has(s.brand)) {
        return false;
      }

      // 5. Max price on selected fuel
      const p = s.prices[state.currentFuel];
      if (typeof p === "number" && maxP < 210 && p > maxP) {
        return false;
      }

      return true;
    });

    renderMarkers();
  }

  /**
   * Open station details bottom sheet
   */
  function openStationDetails(s) {
    state.activeStation = s;
    DOM.sheetBrand.textContent = s.brand;
    DOM.sheetTitle.textContent = s.name;
    DOM.sheetAddress.textContent = s.address ? `${s.address}, ${s.postcode}` : s.postcode;

    // Distance calculation if user location available
    if (state.userCoords) {
      const distMiles = calculateDistance(state.userCoords.lat, state.userCoords.lon, s.lat, s.lon);
      DOM.sheetDistance.textContent = `📍 ${distMiles.toFixed(1)} miles away`;
      DOM.sheetDistance.style.display = "block";
    } else {
      DOM.sheetDistance.style.display = "none";
    }

    // Staleness tag
    DOM.sheetStaleTag.style.display = s.stale ? "inline-block" : "none";

    // Populate prices
    formatPriceBox(DOM.priceValE10, DOM.boxE10, s.prices.e10, state.currentFuel === "e10");
    formatPriceBox(DOM.priceValB7, DOM.boxB7, s.prices.b7, state.currentFuel === "b7");
    formatPriceBox(DOM.priceValE5, DOM.boxE5, s.prices.e5, state.currentFuel === "e5");
    formatPriceBox(DOM.priceValB7Prem, DOM.boxB7Prem, s.prices.b7_prem, state.currentFuel === "b7_prem");

    // Timestamps & metadata
    DOM.sheetUpdatedTime.textContent = formatRelativeTime(s.updated_at);
    DOM.sheetSource.textContent = s.source || "UK Government Fuel Finder (OGL)";

    // Google Maps directions URL
    DOM.btnDirections.href = `https://www.google.com/maps/dir/?api=1&destination=${s.lat},${s.lon}`;

    DOM.stationSheet.classList.add("open");
    DOM.stationSheet.setAttribute("aria-hidden", "false");
  }

  function formatPriceBox(elVal, elBox, price, isHighlight) {
    if (typeof price === "number") {
      elVal.textContent = `${price.toFixed(1)}p`;
      elVal.classList.remove("na");
    } else {
      elVal.textContent = "Not Sold";
      elVal.classList.add("na");
    }

    if (isHighlight) {
      elBox.classList.add("highlight");
    } else {
      elBox.classList.remove("highlight");
    }
  }

  function closeStationDetails() {
    DOM.stationSheet.classList.remove("open");
    DOM.stationSheet.setAttribute("aria-hidden", "true");
    state.activeStation = null;
  }

  /**
   * Geolocation: localize user on the map
   */
  function localizeUser(isSilent = false) {
    if (!navigator.geolocation) {
      if (!isSilent) alert("Geolocation is not supported by your browser.");
      return;
    }

    if (!isSilent) {
      DOM.btnNearMe.classList.add("loading");
    }

    navigator.geolocation.getCurrentPosition(
      (pos) => {
        if (!isSilent) DOM.btnNearMe.classList.remove("loading");
        const lat = pos.coords.latitude;
        const lon = pos.coords.longitude;
        state.userCoords = { lat, lon };

        // Place or update user location marker
        if (userLocationMarker) {
          map.removeLayer(userLocationMarker);
        }

        userLocationMarker = L.circleMarker([lat, lon], {
          radius: 9,
          fillColor: "#3b82f6",
          color: "#ffffff",
          weight: 3,
          opacity: 1,
          fillOpacity: 0.9,
        }).addTo(map);

        userLocationMarker.bindPopup("<strong>📍 You are here</strong>");

        // Automatically expand to UK scope if outside South East so local stations appear
        if (state.regionScope === "southeast" && !isCoordInSouthEast(lat, lon)) {
          state.regionScope = "all";
          DOM.regionScopeLabel.textContent = "All United Kingdom";
        }

        applyFilters();
        map.flyTo([lat, lon], 13, { duration: 1.5 });
      },
      (err) => {
        if (!isSilent) {
          DOM.btnNearMe.classList.remove("loading");
          console.warn("Geolocation denied or error:", err.message);
          map.flyTo(KENT_COORDS, KENT_ZOOM, { duration: 1.2 });
        } else {
          console.log("Automatic location permission not granted, staying on default view:", err.message);
        }
      },
      { timeout: 9000, enableHighAccuracy: true, maximumAge: 60000 }
    );
  }

  function handleNearMe() {
    localizeUser(false);
  }

  function isCoordInSouthEast(lat, lon) {
    return lat >= 50.5 && lat <= 52.1 && lon >= -1.5 && lon <= 1.5;
  }

  /**
   * Haversine formula for distance in miles
   */
  function calculateDistance(lat1, lon1, lat2, lon2) {
    const R = 3958.8; // Radius of the Earth in miles
    const dLat = (lat2 - lat1) * (Math.PI / 180);
    const dLon = (lon2 - lon1) * (Math.PI / 180);
    const a =
      Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(lat1 * (Math.PI / 180)) *
        Math.cos(lat2 * (Math.PI / 180)) *
        Math.sin(dLon / 2) *
        Math.sin(dLon / 2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return R * c;
  }

  /**
   * Relative time formatter
   */
  function formatRelativeTime(dateStr) {
    if (!dateStr) return "Unknown";
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return dateStr;

    const diffSec = Math.floor((Date.now() - d.getTime()) / 1000);
    if (diffSec < 60) return "Just now";
    if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
    if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
    const days = Math.floor(diffSec / 86400);
    return `${days}d ago (${d.toLocaleDateString("en-GB")})`;
  }

  /**
   * Toggle Region Scope (Kent & South East <-> All UK)
   */
  function toggleRegionScope() {
    const newScope = state.regionScope === "southeast" ? "all" : "southeast";
    setRegionScope(newScope);
  }

  function setRegionScope(scope) {
    state.regionScope = scope;
    if (scope === "southeast") {
      DOM.regionScopeLabel.textContent = "Kent & South East";
      map.flyTo(KENT_COORDS, KENT_ZOOM, { duration: 1.2 });
    } else {
      DOM.regionScopeLabel.textContent = "All United Kingdom";
      map.flyTo(UK_COORDS, UK_ZOOM, { duration: 1.2 });
    }
    applyFilters();
  }

  /**
   * Populate Brand Filter Chips
   */
  function populateBrandChips(brandCounts) {
    DOM.brandChipsContainer.innerHTML = "";
    const brands = Object.keys(brandCounts || {});

    brands.forEach((brand) => {
      const count = brandCounts[brand];
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "brand-chip";
      chip.textContent = `${brand} (${count})`;
      chip.dataset.brand = brand;

      chip.addEventListener("click", () => {
        if (state.filters.selectedBrands.has(brand)) {
          state.filters.selectedBrands.delete(brand);
          chip.classList.remove("selected");
        } else {
          state.filters.selectedBrands.add(brand);
          chip.classList.add("selected");
        }
      });

      DOM.brandChipsContainer.appendChild(chip);
    });
  }

  /**
   * Setup Event Listeners
   */
  function setupEventListeners() {
    // Fuel selector pills
    DOM.fuelPills.forEach((btn) => {
      btn.addEventListener("click", () => {
        DOM.fuelPills.forEach((p) => {
          p.classList.remove("active");
          p.setAttribute("aria-checked", "false");
        });
        btn.classList.add("active");
        btn.setAttribute("aria-checked", "true");
        state.currentFuel = btn.dataset.fuel;

        applyFilters();

        if (state.activeStation) {
          openStationDetails(state.activeStation);
        }
      });
    });

    // Near me button
    DOM.btnNearMe.addEventListener("click", handleNearMe);

    // Region scope toggle button
    DOM.btnRegionScope.addEventListener("click", toggleRegionScope);

    // Station Sheet Close
    DOM.btnCloseSheet.addEventListener("click", closeStationDetails);
    DOM.sheetDragHandle.addEventListener("click", closeStationDetails);

    // Filter Modal Open / Close
    DOM.btnFilter.addEventListener("click", () => {
      DOM.filterModal.classList.add("open");
      DOM.filterModal.setAttribute("aria-hidden", "false");
    });

    DOM.btnCloseFilter.addEventListener("click", closeFilterModal);
    DOM.modalBackdrop.addEventListener("click", closeFilterModal);

    // Price Slider
    DOM.priceSlider.addEventListener("input", (e) => {
      const val = parseInt(e.target.value, 10);
      if (val >= 210) {
        DOM.priceSliderVal.textContent = "Any Price";
        state.filters.maxPrice = Infinity;
      } else {
        DOM.priceSliderVal.textContent = `Max: ${val}p`;
        state.filters.maxPrice = val;
      }
    });

    // Search Input
    DOM.searchInput.addEventListener("input", (e) => {
      const val = e.target.value;
      state.filters.searchQuery = val;
      DOM.btnClearSearch.style.display = val ? "block" : "none";
    });

    DOM.btnClearSearch.addEventListener("click", () => {
      DOM.searchInput.value = "";
      state.filters.searchQuery = "";
      DOM.btnClearSearch.style.display = "none";
    });

    // Select all brands
    DOM.btnSelectAllBrands.addEventListener("click", () => {
      state.filters.selectedBrands.clear();
      document.querySelectorAll(".brand-chip").forEach((chip) => {
        chip.classList.remove("selected");
      });
    });

    // Toggle hide stale
    DOM.toggleHideStale.addEventListener("change", (e) => {
      state.filters.hideStale = e.target.checked;
    });

    // Reset filters button
    DOM.btnResetFilters.addEventListener("click", () => {
      state.filters.searchQuery = "";
      DOM.searchInput.value = "";
      DOM.btnClearSearch.style.display = "none";

      state.filters.selectedBrands.clear();
      document.querySelectorAll(".brand-chip").forEach((chip) => chip.classList.remove("selected"));

      DOM.priceSlider.value = 210;
      DOM.priceSliderVal.textContent = "Any Price";
      state.filters.maxPrice = Infinity;

      DOM.toggleHideStale.checked = true;
      state.filters.hideStale = true;

      applyFilters();
      closeFilterModal();
    });

    // Apply filters button
    DOM.btnApplyFilters.addEventListener("click", () => {
      applyFilters();
      closeFilterModal();
    });
  }

  function closeFilterModal() {
    DOM.filterModal.classList.remove("open");
    DOM.filterModal.setAttribute("aria-hidden", "true");
  }

  /**
   * Load Data Pipeline: Progressive Fast Mobile Loading
   */
  async function loadData() {
    try {
      DOM.loadingText.textContent = "Loading Kent & South East fuel prices...";

      // 1. First fetch lightweight Kent & South East dataset for instant render
      let seDataLoaded = false;
      try {
        const seRes = await fetch("data/prices-southeast.json");
        if (seRes.ok) {
          const seData = await seRes.json();
          state.allStations = seData.stations || [];
          state.meta.generatedAt = seData.generated_at;
          state.meta.stats = seData.stats || {};
          if (seData.generated_at) {
            DOM.refreshTime.textContent = `Refreshed ${formatRelativeTime(seData.generated_at)}`;
          }
          populateBrandChips(seData.stats.brand_counts);
          applyFilters();
          seDataLoaded = true;

          // Hide loading overlay early
          DOM.loadingOverlay.style.opacity = "0";
          setTimeout(() => {
            DOM.loadingOverlay.style.display = "none";
          }, 200);
        }
      } catch (e) {
        console.warn("Could not preload regional dataset, falling back to full dataset:", e);
      }

      // 2. Fetch full national dataset
      const res = await fetch("data/prices.json");
      if (!res.ok) {
        throw new Error(`Failed to load full prices data (HTTP ${res.status})`);
      }
      const data = await res.json();

      state.allStations = data.stations || [];
      state.meta.generatedAt = data.generated_at;
      state.meta.stats = data.stats || {};

      if (data.generated_at) {
        DOM.refreshTime.textContent = `Refreshed ${formatRelativeTime(data.generated_at)}`;
      }

      populateBrandChips(data.stats.brand_counts);
      applyFilters();

      // Automatically localize to user's location on startup
      localizeUser(true);

      // Check for deep link or test parameter in URL
      const urlParams = new URLSearchParams(window.location.search);
      const stationIdParam = urlParams.get("station");
      const testSheetParam = urlParams.get("test_sheet");

      if (stationIdParam) {
        const found = state.allStations.find(s => s.id === stationIdParam);
        if (found) {
          map.setView([found.lat, found.lon], 14);
          openStationDetails(found);
        }
      } else if (testSheetParam && state.filteredStations.length > 0) {
        const sample = state.filteredStations[0];
        map.setView([sample.lat, sample.lon], 13);
        openStationDetails(sample);
      }
    } catch (err) {
      console.error("Error loading fuel data:", err);
      DOM.loadingText.textContent = "Error loading data. Please refresh.";
      setTimeout(() => {
        DOM.loadingOverlay.style.display = "none";
      }, 1500);
    }
  }

  // App Initialization: safe check for readyState
  function start() {
    console.log("start() executing. readyState:", document.readyState);
    initMap();
    console.log("initMap() done.");
    setupEventListeners();
    console.log("setupEventListeners() done.");
    loadData();
    console.log("loadData() invoked.");
  }

  if (document.readyState === "loading") {
    console.log("Waiting for DOMContentLoaded...");
    document.addEventListener("DOMContentLoaded", start);
  } else {
    console.log("Document already loaded, calling start() directly.");
    start();
  }
})();
