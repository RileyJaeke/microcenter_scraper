import os
import threading
import time # Added time import for sleep
from flask import Flask, jsonify, send_from_directory, make_response, request
from flask_cors import CORS
import mysql.connector
from dotenv import load_dotenv

# Import your existing scraper script
import scraper

load_dotenv()

# --- CONFIGURATION ---
base_dir = os.path.abspath(os.path.dirname(__file__))
frontend_dir = os.path.join(base_dir, '../frontend')

app = Flask(__name__, static_folder=frontend_dir, static_url_path='')
CORS(app)

# Global status tracker
SCRAPE_STATUS = {
    "is_scraping": False,
    "current_store": None,
    "message": ""
}

# --- CORRECTED STORE LIST ---
SUPPORTED_STORES = [
    {"name": "Overland Park", "city": "Overland Park", "state": "KS", "id": "191"},
    {"name": "Tustin", "city": "Tustin", "state": "CA", "id": "101"},
    {"name": "Denver", "city": "Denver", "state": "CO", "id": "181"},
    {"name": "Dallas", "city": "Dallas", "state": "TX", "id": "131"},
    {"name": "Houston", "city": "Houston", "state": "TX", "id": "155"},
    {"name": "Chicago", "city": "Chicago", "state": "IL", "id": "151"},
    {"name": "Cambridge", "city": "Cambridge", "state": "MA", "id": "121"},
    {"name": "Brooklyn", "city": "Brooklyn", "state": "NY", "id": "115"},
    {"name": "Mayfield Heights", "city": "Mayfield Heights", "state": "OH", "id": "051"},
    {"name": "Columbus", "city": "Columbus", "state": "OH", "id": "141"},
    {"name": "Fairfax", "city": "Fairfax", "state": "VA", "id": "081"},
]

def get_db_connection():
    """Connects to the database using credentials from .env"""
    try:
        conn = mysql.connector.connect(
            host=os.getenv('DB_HOST'),
            user=os.getenv('DB_USER'),
            password=os.getenv('DB_PASSWORD'),
            database=os.getenv('DB_NAME')
        )
        return conn
    except mysql.connector.Error as err:
        print(f"Error connecting to database: {err}")
        return None

# --- ROUTE: Serve the Homepage ---
@app.route('/')
def serve_index():
    return send_from_directory(app.static_folder, 'index.html')

# --- ROUTE: Get List of Supported Stores ---
@app.route('/api/stores', methods=['GET'])
def get_supported_stores():
    return jsonify(SUPPORTED_STORES)

# --- ROUTE: Get Scrape Status ---
@app.route('/api/status', methods=['GET'])
def get_scrape_status():
    return jsonify(SCRAPE_STATUS)

# --- HELPER: Background Scrape Task ---
def scrape_store_pages(store_info):
    """
    Background thread function that loops through pages
    until no more items are found.
    """
    global SCRAPE_STATUS
    SCRAPE_STATUS["is_scraping"] = True
    SCRAPE_STATUS["current_store"] = store_info['name']
    SCRAPE_STATUS["message"] = f"Starting scrape for {store_info['name']}..."

    base_url = f"https://www.microcenter.com/search/search_results.aspx?N=4294966937&NTK=all&sortby=match&storeid={store_info['id']}&rpp=96"
    
    page_num = 1
    MAX_PAGES = 10 # Safety limit to prevent infinite loops

    try:
        while page_num <= MAX_PAGES:
            SCRAPE_STATUS["message"] = f"Scraping Page {page_num} for {store_info['name']}..."
            print(f"--- API Triggered: Scraping Page {page_num} for {store_info['name']} ---")
            
            store_config = {
                "name": store_info['name'],
                "city": store_info['city'],
                "state": store_info['state'],
                "url": f"{base_url}&page={page_num}"
            }
            
            # Call the scraper for this specific page
            # Now captures the return value (number of items found)
            items_found = scraper.run_scraper(store_config)
            
            print(f"--- Page {page_num} results: {items_found} items found ---")

            # Logic: If we found less than 96 items, this is likely the last page
            if items_found < 96:
                break
            
            page_num += 1
            # Sleep between pages to be polite
            time.sleep(5)
            
    except Exception as e:
        print(f"Error in background scraper: {e}")
    finally:
        # Reset status when done
        SCRAPE_STATUS["is_scraping"] = False
        SCRAPE_STATUS["message"] = f"Finished scraping {store_info['name']}."
        print(f"--- API Triggered: Finished scraping {store_info['name']} ---")

# --- ROUTE: Trigger Scrape ---
@app.route('/api/scrape', methods=['POST'])
def trigger_scrape():
    # Check if a job is already running
    if SCRAPE_STATUS["is_scraping"]:
         return jsonify({
             "error": "A scrape job is already running.",
             "status": "busy"
         }), 409

    data = request.json
    store_id = data.get('store_id')
    
    # Find the store details from our list
    store_info = next((s for s in SUPPORTED_STORES if s['id'] == store_id), None)
    
    if not store_info:
        return jsonify({"error": "Invalid Store ID selected."}), 400

    # Start the multi-page scraper in a background thread
    thread = threading.Thread(target=scrape_store_pages, args=(store_info,))
    thread.start()
    
    return jsonify({
        "message": f"Scraping started for {store_info['name']}! Data will appear shortly.",
        "status": "started"
    })

# --- ROUTE: API Data ---
@app.route('/api/gpus', methods=['GET'])
def get_gpus():
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor(dictionary=True)
    
    # UPDATED QUERY: Now joins with 'stores' table to get the store name
    query = """
    SELECT 
        p.product_id,
        s.name as store_name,
        g.brand, 
        g.model_name, 
        g.manufacturer,
        p.product_url, 
        p.last_seen_image_url, 
        ph.price_usd, 
        ph.stock_status, 
        ph.scraped_at
    FROM products p
    JOIN gpus g ON p.gpu_id = g.gpu_id
    JOIN stores s ON p.store_id = s.store_id
    JOIN price_history ph ON p.product_id = ph.product_id
    WHERE ph.history_id IN (
        SELECT MAX(history_id) 
        FROM price_history 
        GROUP BY product_id
    )
    ORDER BY ph.price_usd DESC;
    """
    
    try:
        cursor.execute(query)
        results = cursor.fetchall()
        
        response = make_response(jsonify(results))
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            cursor.close()
            conn.close()

# --- NEW ROUTE: Product History ---
@app.route('/api/history/<int:product_id>', methods=['GET'])
def get_product_history(product_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor(dictionary=True)
    
    query = """
    SELECT price_usd, stock_status, scraped_at
    FROM price_history
    WHERE product_id = %s
    ORDER BY scraped_at ASC
    """
    
    try:
        cursor.execute(query, (product_id,))
        results = cursor.fetchall()
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            cursor.close()
            conn.close()

if __name__ == '__main__':
    print(f"Serving frontend from: {frontend_dir}")
    print("Starting Flask API on http://localhost:5000")
    app.run(debug=True, port=5000)