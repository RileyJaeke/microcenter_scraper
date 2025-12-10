const API_URL = '/api/gpus';
const HISTORY_URL = '/api/history';
const STORES_URL = '/api/stores';
const SCRAPE_URL = '/api/scrape';
const STATUS_URL = '/api/status';

let allGPUs = [];

// --- Event Listeners for Filters ---
document.getElementById('search-input').addEventListener('input', filterGPUs);
document.getElementById('brand-filter').addEventListener('change', filterGPUs);
document.getElementById('store-filter').addEventListener('change', filterGPUs);

// --- 1. Filter Logic ---
function filterGPUs() {
    const searchTerm = document.getElementById('search-input').value.toLowerCase();
    const selectedBrand = document.getElementById('brand-filter').value;
    const selectedStore = document.getElementById('store-filter').value;

    const filtered = allGPUs.filter(gpu => {
        const nameMatch = gpu.model_name.toLowerCase().includes(searchTerm);
        const gpuBrand = (gpu.brand || 'Unknown').toUpperCase();
        const brandMatch = selectedBrand === 'all' || gpuBrand === selectedBrand;
        const gpuStore = (gpu.store_name || 'Unknown');
        const storeMatch = selectedStore === 'all' || gpuStore === selectedStore;

        return nameMatch && brandMatch && storeMatch;
    });

    renderGPUs(filtered);
}

function populateFilters(gpus) {
    const brandSelect = document.getElementById('brand-filter');
    const storeFilter = document.getElementById('store-filter');

    const currentBrand = brandSelect.value;
    const currentStore = storeFilter.value;

    // Keep the "All" option
    const brandOptions = ['<option value="all">All Brands</option>'];
    const brands = new Set();
    gpus.forEach(gpu => {
        if (gpu.brand && gpu.brand !== 'Unknown') brands.add(gpu.brand.toUpperCase());
    });
    Array.from(brands).sort().forEach(brand => {
        brandOptions.push(`<option value="${brand}">${brand}</option>`);
    });
    brandSelect.innerHTML = brandOptions.join('');

    const storeOptions = ['<option value="all">All Stores</option>'];
    const stores = new Set();
    gpus.forEach(gpu => {
        if (gpu.store_name) stores.add(gpu.store_name);
    });
    Array.from(stores).sort().forEach(storeName => {
        storeOptions.push(`<option value="${storeName}">${storeName}</option>`);
    });
    storeFilter.innerHTML = storeOptions.join('');

    if (brands.has(currentBrand) || currentBrand === 'all') {
        brandSelect.value = currentBrand;
    }
    if (stores.has(currentStore) || currentStore === 'all') {
        storeFilter.value = currentStore;
    }
}

// --- 2. Scrape Trigger Logic ---
async function fetchSupportedStores() {
    try {
        const response = await fetch(STORES_URL);
        const stores = await response.json();
        
        const scrapeSelect = document.getElementById('scrape-store-select');
        scrapeSelect.innerHTML = '';
        
        stores.forEach(store => {
            const option = document.createElement('option');
            option.value = store.id;
            option.textContent = `${store.name}, ${store.state}`;
            scrapeSelect.appendChild(option);
        });
    } catch (error) {
        console.error("Failed to load stores list:", error);
    }
}

async function triggerScrape() {
    const storeId = document.getElementById('scrape-store-select').value;
    const btn = document.getElementById('scrape-btn');
    const statusMsg = document.getElementById('scrape-status');
    
    if (!storeId) return;

    btn.disabled = true;
    btn.textContent = "Starting...";
    statusMsg.textContent = "Initializing...";
    statusMsg.style.color = "blue";

    try {
        const response = await fetch(SCRAPE_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ store_id: storeId })
        });
        
        const data = await response.json();
        
        if (response.ok || response.status === 409) {
            statusMsg.textContent = data.message || data.error;
            statusMsg.style.color = response.ok ? "green" : "orange";
            startPolling();
        } else {
            statusMsg.textContent = "Error: " + data.error;
            statusMsg.style.color = "red";
            btn.disabled = false;
            btn.textContent = "Update Stock Now";
        }
    } catch (error) {
        statusMsg.textContent = "Connection failed.";
        statusMsg.style.color = "red";
        btn.disabled = false;
        btn.textContent = "Update Stock Now";
    }
}

let pollInterval;
function startPolling() {
    if (pollInterval) return;
    
    const btn = document.getElementById('scrape-btn');
    const statusMsg = document.getElementById('scrape-status');
    
    // Poll every 5 seconds
    pollInterval = setInterval(async () => {
        try {
            // Check status from server
            const statusResponse = await fetch(STATUS_URL);
            const statusData = await statusResponse.json();
            
            if (statusData.is_scraping) {
                // Still running
                btn.disabled = true;
                btn.textContent = "Scraping...";
                statusMsg.textContent = statusData.message;
                statusMsg.style.color = "blue";
                
                // Refresh grid data quietly
                await fetchGPUs(true); 
            } else {
                clearInterval(pollInterval);
                pollInterval = null;
                
                btn.disabled = false;
                btn.textContent = "Update Stock Now";
                statusMsg.textContent = statusData.message || "Scrape complete.";
                statusMsg.style.color = "green";
                
                // One final refresh
                await fetchGPUs(true);
            }
        } catch (e) {
            console.error("Polling error", e);
        }
    }, 5000);
}


// --- 3. Main Data Fetching ---

async function fetchGPUs(isPolling = false) {
    try {
        if (!isPolling) console.log("Fetching GPU data...");
        
        const timestamp = new Date().getTime();
        const response = await fetch(`${API_URL}?t=${timestamp}`);
        const data = await response.json();
        
        allGPUs = data;
        
        populateFilters(data);
        
        renderGPUs(data);
        
    } catch (error) {
        if (!isPolling) {
            console.error('Error fetching data:', error);
            document.getElementById('gpu-grid').innerHTML = `
                <div class="error-message">
                    <h3>Connection Error</h3>
                    <p>Failed to load data. Is 'python app.py' running?</p>
                </div>`;
        }
    }
}

function renderGPUs(gpus) {
    const grid = document.getElementById('gpu-grid');
    grid.innerHTML = ''; 

    if (!Array.isArray(gpus) || gpus.length === 0) {
        grid.innerHTML = '<div class="empty-state"><h3>No GPUs Found</h3></div>';
        return;
    }

    try {
        if (allGPUs[0] && allGPUs[0].scraped_at) {
            const lastScraped = new Date(allGPUs[0].scraped_at).toLocaleString();
            const timeElement = document.getElementById('last-updated');
            if (timeElement) timeElement.textContent = `Last Scraped: ${lastScraped}`;
        }
    } catch (e) { console.warn("Date error", e); }

    gpus.forEach((gpu, index) => {
        try {
            const card = document.createElement('div');
            card.className = 'gpu-card';
            
            let stockStatus = gpu.stock_status || 'Unknown';
            let stockClass = 'stock-out';
            if (stockStatus && stockStatus.toString().toUpperCase().includes('IN STOCK')) {
                stockClass = 'stock-in';
            }

            const PLACEHOLDER_URL = 'https://placehold.co/200x200?text=No+Image';
            let imageUrl = gpu.last_seen_image_url;
            if (!imageUrl || imageUrl === 'N/A' || imageUrl.includes('noimageproduct.gif')) {
                imageUrl = PLACEHOLDER_URL;
            }

            const brand = gpu.brand || 'Unknown';
            const modelName = gpu.model_name || 'Unknown Model';
            const price = gpu.price_usd || '0.00';
            const productUrl = gpu.product_url || '#';
            const storeName = gpu.store_name || 'Unknown Store';
            const productId = gpu.product_id; 

            const safeModelName = modelName.replace(/'/g, "\\'");

            card.innerHTML = `
                <div class="card-image">
                    <img src="${imageUrl}" alt="Product Image" onerror="this.src='${PLACEHOLDER_URL}'">
                </div>
                <div class="card-details">
                    <div class="brand">
                        <span>${brand}</span>
                        <span class="store-badge">${storeName}</span>
                    </div>
                    <h3>${modelName}</h3>
                    <div class="price">$${price}</div>
                    <div class="stock ${stockClass}">${stockStatus}</div>
                    
                    <div class="card-actions">
                        <button class="history-btn" onclick="showHistory(${productId}, '${safeModelName}')">History</button>
                        <a href="${productUrl}" target="_blank" class="buy-btn">View</a>
                    </div>
                </div>
            `;
            grid.appendChild(card);
        } catch (err) {
            console.error(`Error rendering GPU at index ${index}:`, err);
        }
    });
}

// --- Modal Logic ---
const modal = document.getElementById("history-modal");
const span = document.getElementsByClassName("close-btn")[0];
let myChart = null; 

span.onclick = function() { modal.style.display = "none"; }
window.onclick = function(event) { if (event.target == modal) modal.style.display = "none"; }

async function showHistory(productId, modelName) {
    modal.style.display = "block";
    document.getElementById("modal-title").innerText = `History: ${modelName}`;
    if (myChart) myChart.destroy();

    try {
        const response = await fetch(`${HISTORY_URL}/${productId}`);
        const historyData = await response.json();
        
        const labels = historyData.map(item => new Date(item.scraped_at).toLocaleString());
        const prices = historyData.map(item => item.price_usd);
        
        const ctx = document.getElementById('historyChart').getContext('2d');
        myChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Price (USD)',
                    data: prices,
                    borderColor: 'rgb(75, 192, 192)',
                    backgroundColor: 'rgba(75, 192, 192, 0.2)',
                    tension: 0.1,
                    fill: true
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: { y: { beginAtZero: false } }
            }
        });
    } catch (error) {
        console.error("Error fetching history:", error);
    }
}

// Initialize
fetchSupportedStores();
fetchGPUs();