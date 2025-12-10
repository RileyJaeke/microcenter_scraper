const API_URL = 'http://localhost:5000/api/gpus';
const HISTORY_URL = 'http://localhost:5000/api/history';

// Store all fetched GPUs globally so we can filter them locally
let allGPUs = [];

// --- Event Listeners for Filters ---
document.getElementById('search-input').addEventListener('input', filterGPUs);
document.getElementById('brand-filter').addEventListener('change', filterGPUs);

// --- Filter Logic ---
function filterGPUs() {
    const searchTerm = document.getElementById('search-input').value.toLowerCase();
    const selectedBrand = document.getElementById('brand-filter').value;

    const filtered = allGPUs.filter(gpu => {
        // 1. Check Search Term (match name or sku)
        const nameMatch = gpu.model_name.toLowerCase().includes(searchTerm);
        
        // 2. Check Brand (match selected or 'all')
        const gpuBrand = (gpu.brand || 'Unknown').toUpperCase();
        const brandMatch = selectedBrand === 'all' || gpuBrand === selectedBrand;

        return nameMatch && brandMatch;
    });

    renderGPUs(filtered);
}

function populateBrands(gpus) {
    const brandSelect = document.getElementById('brand-filter');
    // Clear existing options except "All Brands"
    brandSelect.innerHTML = '<option value="all">All Brands</option>';
    
    const brands = new Set();

    gpus.forEach(gpu => {
        if (gpu.brand && gpu.brand !== 'Unknown') {
            brands.add(gpu.brand.toUpperCase());
        }
    });

    // Sort brands A-Z
    const sortedBrands = Array.from(brands).sort();

    sortedBrands.forEach(brand => {
        const option = document.createElement('option');
        option.value = brand;
        option.textContent = brand;
        brandSelect.appendChild(option);
    });
}

// --- Modal Logic ---
const modal = document.getElementById("history-modal");
const span = document.getElementsByClassName("close-btn")[0];
let myChart = null; 

span.onclick = function() {
  modal.style.display = "none";
}

window.onclick = function(event) {
  if (event.target == modal) {
    modal.style.display = "none";
  }
}

async function showHistory(productId, modelName) {
    modal.style.display = "block";
    document.getElementById("modal-title").innerText = `History: ${modelName}`;
    
    if (myChart) {
        myChart.destroy();
    }

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
                scales: {
                    y: {
                        beginAtZero: false
                    }
                }
            }
        });

    } catch (error) {
        console.error("Error fetching history:", error);
        document.getElementById("modal-title").innerText = "Error loading history";
    }
}

// --- Main App Logic ---

async function fetchGPUs() {
    try {
        console.log("Fetching GPU data...");
        // Add timestamp to prevent caching
        const timestamp = new Date().getTime();
        const response = await fetch(`${API_URL}?t=${timestamp}`);
        const data = await response.json();
        console.log(`Data received from API: ${data.length} items found.`);
        
        // Save to global variable
        allGPUs = data;
        
        // Initialize filters and render
        populateBrands(data);
        renderGPUs(data);
        
    } catch (error) {
        console.error('Error fetching data:', error);
        document.getElementById('gpu-grid').innerHTML = `
            <div class="error-message">
                <h3>Connection Error</h3>
                <p>Failed to load data. Is 'python app.py' running?</p>
            </div>`;
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

            // Using placehold.co instead of via.placeholder
            const PLACEHOLDER_URL = 'https://placehold.co/200x200?text=No+Image';
            let imageUrl = gpu.last_seen_image_url;
            if (!imageUrl || imageUrl === 'N/A' || imageUrl.includes('noimageproduct.gif')) {
                imageUrl = PLACEHOLDER_URL;
            }

            const brand = gpu.brand || 'Unknown';
            const modelName = gpu.model_name || 'Unknown Model';
            const price = gpu.price_usd || '0.00';
            const productUrl = gpu.product_url || '#';
            const productId = gpu.product_id; 

            // Escape quotes for the onclick handler
            const safeModelName = modelName.replace(/'/g, "\\'");

            card.innerHTML = `
                <div class="card-image">
                    <img src="${imageUrl}" alt="Product Image" onerror="this.src='${PLACEHOLDER_URL}'">
                </div>
                <div class="card-details">
                    <span class="brand">${brand}</span>
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

fetchGPUs();