import os
import re  # For cleaning up stock text
import time
import mysql.connector
from mysql.connector import errorcode
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager

load_dotenv()

# --- HELPER FUNCTION ---
def parse_gpu_details(full_name, brand):
    """
    Attempts to parse the manufacturer and model from a full product name.
    The brand is passed in directly from the scraped 'data-brand' attribute.
    """
    details = {
        'brand': brand,
        'manufacturer': 'Unknown',
        'model_name': full_name # Default to full name
    }
    
    # Common manufacturers
    MANUFACTURERS = ["NVIDIA", "AMD", "Intel"]
    
    # Find Manufacturer
    for manu in MANUFACTURERS:
        if manu.lower() in full_name.lower():
            details['manufacturer'] = manu
            break # Found it

    # Try to find a cleaner model name (e.g., "GeForce RTX 5070 Ti")
    model_keywords = ["GeForce RTX", "Radeon RX", "Intel Arc"]
    found_model = False
    for keyword in model_keywords:
        if keyword.lower() in full_name.lower():
            try:
                # Find the start of the keyword
                start_index = full_name.lower().find(keyword.lower())
                # Get the substring from that point
                sub_string = full_name[start_index:]
                # Split by space and take the first 3 or 4 parts
                model_parts = sub_string.split()
                # e.g., ["GeForce", "RTX", "5070", "Ti"]
                if "Ti" in model_parts or "XT" in model_parts:
                    details['model_name'] = " ".join(model_parts[:4])
                else:
                    details['model_name'] = " ".join(model_parts[:3])
                found_model = True
                break
            except Exception:
                pass # Stick with default
    
    # If no keywords found, but name is too long, just truncate
    if not found_model and len(full_name) > 100:
        # Try to find the model part after the brand
        temp_name = full_name.replace(details['brand'], '').strip()
        temp_name = temp_name.replace(details['manufacturer'], '').strip()
        
        # Take the first few words of whatever is left
        temp_parts = temp_name.split()
        details['model_name'] = " ".join(temp_parts[:4])

    # Final check to prevent database errors
    if len(details['model_name']) > 100:
        details['model_name'] = details['model_name'][:99]

    return details

# --- DATABASE FUNCTIONS ---

def get_db_connection():
    """Establishes a connection to the MySQL database."""
    try:
        conn = mysql.connector.connect(
            host=os.getenv('DB_HOST'),
            user=os.getenv('DB_USER'),
            password=os.getenv('DB_PASSWORD'),
            database=os.getenv('DB_NAME')
        )
        print("Database connection successful.")
        return conn
    except mysql.connector.Error as err:
        if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
            print("Error: Access denied. Check your DB_USER and DB_PASSWORD.")
        elif err.errno == errorcode.ER_BAD_DB_ERROR:
            print(f"Error: Database '{os.getenv('DB_NAME')}' does not exist.")
        else:
            print(f"Error connecting to database: {err}")
        return None

def get_or_create_store(cursor, store_name, city, state):
    """Finds a store by name, or creates it if it doesn't exist."""
    query = "SELECT store_id FROM stores WHERE name = %s AND city = %s"
    cursor.execute(query, (store_name, city))
    result = cursor.fetchone()
    
    if result:
        return result[0] # Return existing store_id
    else:
        # Create the store
        insert_query = "INSERT INTO stores (name, city, state) VALUES (%s, %s, %s)"
        cursor.execute(insert_query, (store_name, city, state))
        print(f"Created new store: {store_name}, {city}")
        return cursor.lastrowid # Return new store_id

def get_or_create_gpu(cursor, brand, model_name, manufacturer, full_name):
    """
    Finds a GPU by full_name.
    If it exists, UPDATE it with the new (and likely better) data.
    If it doesn't exist, CREATE it.
    """
    query = """
    SELECT gpu_id, brand, model_name, manufacturer 
    FROM gpus 
    WHERE full_name = %s
    """
    cursor.execute(query, (full_name,))
    result = cursor.fetchone()
    
    if result:
        # --- UPDATE LOGIC ---
        gpu_id, old_brand, old_model, old_manu = result
        
        # Check if the new data is better than the old data
        if (old_brand != brand and brand != 'Unknown') or \
           (old_model != model_name) or \
           (old_manu != manufacturer and manufacturer != 'Unknown'):
            
            # Build the update query
            update_query = """
            UPDATE gpus SET 
                brand = %s, 
                model_name = %s, 
                manufacturer = %s
            WHERE gpu_id = %s
            """
            try:
                cursor.execute(update_query, (brand, model_name, manufacturer, gpu_id))
                print(f"Updated GPU data for: {full_name}")
            except mysql.connector.Error as err:
                print(f"Error updating GPU: {err}")
                
        return gpu_id # Return the existing ID

    else:
        # --- CREATE LOGIC ---
        insert_query = """
        INSERT INTO gpus (brand, model_name, manufacturer, full_name) 
        VALUES (%s, %s, %s, %s)
        """
        try:
            cursor.execute(insert_query, (brand, model_name, manufacturer, full_name))
            print(f"Created new GPU: {full_name}")
            return cursor.lastrowid
        except mysql.connector.Error as err:
            print(f"Error creating GPU: {err}")
            # Handle specific errors like data too long
            if err.errno == 1406: # Data too long
                print("Retrying with truncated model_name...")
                model_name_truncated = model_name[:99]
                try:
                    cursor.execute(insert_query, (brand, model_name_truncated, manufacturer, full_name))
                    print(f"Created new GPU (truncated): {full_name}")
                    return cursor.lastrowid
                except Exception as e:
                    print(f"Failed to create GPU even with truncation: {e}")
            return None

def get_or_create_product(cursor, store_id, gpu_id, sku, product_url, image_url):
    """Finds a product by SKU, or creates it. Updates URL/image if found."""
    query = "SELECT product_id FROM products WHERE microcenter_sku = %s"
    cursor.execute(query, (sku,))
    result = cursor.fetchone()
    
    if result:
        # Product exists, update its URL and image URL just in case
        update_query = """
        UPDATE products SET product_url = %s, last_seen_image_url = %s
        WHERE product_id = %s
        """
        cursor.execute(update_query, (product_url, image_url, result[0]))
        return result[0]
    else:
        # Product doesn't exist, create it
        insert_query = """
        INSERT INTO products (store_id, gpu_id, microcenter_sku, product_url, last_seen_image_url)
        VALUES (%s, %s, %s, %s, %s)
        """
        cursor.execute(insert_query, (store_id, gpu_id, sku, product_url, image_url))
        print(f"Created new product entry for SKU: {sku}")
        return cursor.lastrowid

def log_price_history(cursor, product_id, price, stock_status):
    """Inserts a new price and stock record into the price_history table."""
    query = """
    INSERT INTO price_history (product_id, price_usd, stock_status)
    VALUES (%s, %s, %s)
    """
    cursor.execute(query, (product_id, price, stock_status))
    print(f"Logged new history for product_id {product_id}: Price={price}, Stock='{stock_status}'")

# --- MAIN SCRAPER FUNCTION ---

def run_scraper(store_details):
    """
    Main function to run the scraper for a specific store.
    """
    print("Setting up Selenium WebDriver...")
    conn = None
    driver = None
    
    try:
        # --- 1. Database Connection ---
        print(f"Connecting to database for store: {store_details['name']}...")
        conn = get_db_connection()
        if not conn:
            return # Exit if connection fails
        
        cursor = conn.cursor()
        
        # --- 2. Selenium WebDriver Setup ---
        print("Launching Chrome WebDriver...")
        service = Service(ChromeDriverManager().install())
        chrome_options = webdriver.ChromeOptions()
        chrome_options.add_argument("--headless=new") 
        
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--log-level=3") # Suppress console noise
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36")
        
            
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        # --- 3. Scrape Page ---
        target_url = store_details['url']
        print(f"Scraping URL: {target_url}")
        driver.get(target_url)

        # "Smart Wait": Wait up to 20s for the first product link to load
        print("Waiting up to 20 seconds for product data to load...")
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CLASS_NAME, "productClickItemV2"))
            )
            print("Product data has loaded.")
        except TimeoutException:
            print("Page timed out after 20 seconds. No products loaded.")
            return # Exit the function

        # Give a final second for anything else to render
        time.sleep(1)
        
        page_html = driver.page_source
        
        # --- 4. Parse Content ---
        print("Page content retrieved. Parsing with BeautifulSoup...")
        soup = BeautifulSoup(page_html, 'html.parser')
        
        # This is the main container for each product on the search results page
        product_containers = soup.find_all('li', class_='product_wrapper')
        print(f"Found {len(product_containers)} products on the page.")

        if len(product_containers) == 0:
            # If we found no products, save the HTML for debugging
            with open("debug_page.html", "w", encoding="utf-8") as f:
                f.write(soup.prettify())
            print("Could not find any 'product_wrapper' containers. Saved HTML to debug_page.html.")
            return

        # Get or create the store
        store_id = get_or_create_store(cursor, 
                                       store_details['name'], 
                                       store_details['city'], 
                                       store_details['state'])
        
        # --- 5. Loop Through Products ---
        for container in product_containers:
            try:
                # --- Get Name, Brand, Price, URL (from the <a> tag) ---
                name_element = container.find('a', class_='productClickItemV2')
                if not name_element:
                    print("Could not find name element. Skipping product.")
                    continue
                
                full_name = name_element.get('data-name', 'N/A').strip()
                product_url = "https://www.microcenter.com" + name_element.get('href', 'N/A')
                brand = name_element.get('data-brand', 'Unknown').strip()
                price = name_element.get('data-price', '0.00')

                # --- Get SKU (from the <p> tag) ---
                sku_element = container.find('p', class_='sku')
                if sku_element:
                    sku = sku_element.text.replace('SKU:', '').strip()
                else:
                    sku = 'N/A'

                # --- Check for valid essential data ---
                if full_name == 'N/A' or sku == 'N/A':
                    print(f"Skipping product, incomplete data. Name: {full_name}, SKU: {sku}")
                    continue
                
                # --- Get Stock (from inventoryCnt span or stock div) ---
                stock_status = "UNKNOWN"
                stock_element = container.find('span', class_='inventoryCnt')
                if stock_element:
                    # Get all text and collapse whitespace: "   9   IN STOCK  " -> "9 IN STOCK"
                    stock_status = ' '.join(stock_element.text.split()).strip()
                else:
                    # Fallback to the simpler stock div
                    stock_element = container.find('div', class_='stock', recursive=False)
                    if stock_element:
                        stock_status = stock_element.text.strip().upper()
                    elif "SOLD OUT" in container.text.upper():
                        stock_status = "SOLD OUT"

                # --- Get Image ---
                image_url = 'N/A'
                image_element = container.find('img', class_='SearchResultProductImage')
                if image_element:
                    # Check 'data-src' first (for lazy-loaded images), then 'src'
                    image_url = image_element.get('data-src') or image_element.get('src')
                
                # --- 6. Process Data and Update Database ---
                
                # Parse Brand, Manufacturer, and Model
                gpu_details = parse_gpu_details(full_name, brand)
                
                # Get or Create GPU entry
                gpu_id = get_or_create_gpu(cursor,
                                           gpu_details['brand'],
                                           gpu_details['model_name'],
                                           gpu_details['manufacturer'],
                                           full_name)
                if not gpu_id:
                    print(f"Failed to get or create GPU for {full_name}. Skipping.")
                    continue
                
                # Get or Create Product entry (links GPU to Store)
                product_id = get_or_create_product(cursor,
                                                   store_id,
                                                   gpu_id,
                                                   sku,
                                                   product_url,
                                                   image_url)
                if not product_id:
                    print(f"Failed to get or create product for SKU {sku}. Skipping.")
                    continue
                
                # Log the price history for this run
                log_price_history(cursor, product_id, price, stock_status)

            except Exception as e:
                print(f"Error parsing a product container: {e}")
                # Save HTML of the failing container for debugging
                with open("error_container.html", "a", encoding="utf-8") as f:
                    f.write(str(container) + "\n\n")

        # --- 7. Finalize ---
        conn.commit() # Commit all changes to the database
        print("Scraping run complete. Changes committed.")
        
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        if conn:
            conn.rollback() # Roll back changes on error
    finally:
        # --- 8. Cleanup ---
        if driver:
            driver.quit()
            print("Chrome WebDriver closed.")
        if conn:
            conn.close()
            print("Database connection closed.")
        print("--- Scraper run finished ---")


# --- SCRIPT ENTRY POINT ---
if __name__ == "__main__":
    
    # --- CONFIGURATION ---
    # Define the store and URL to scrape
    
    STORE_TO_SCRAPE = {
        "name": "Overland Park",
        "city": "Overland Park",
        "state": "KS",
        "base_url": "https://www.microcenter.com/search/search_results.aspx?N=4294966937&NTK=all&sortby=match&storeid=101&rpp=96"
        # storeid=101 is Overland Park, KS
        # N=4294966937 is the category for "Graphics Cards"
    }

    PAGES_TO_SCRAPE = 3 # How many pages to loop through

    # --- EXECUTION ---
    print("--- Starting Micro Center Scraper ---")
    
    for page_num in range(1, PAGES_TO_SCRAPE + 1):
        print(f"\n--- Scraping Page {page_num} of {PAGES_TO_SCRAPE} ---")
        
        # Create the full URL for the current page
        store_config = STORE_TO_SCRAPE.copy() # Make a copy to avoid modifying the original
        store_config['url'] = f"{store_config['base_url']}&page={page_num}"
        
        run_scraper(store_config)
        
        # Add a small delay between scraping pages to be polite to the server
        if page_num < PAGES_TO_SCRAPE:
            print(f"Waiting 5 seconds before scraping next page...")
            time.sleep(5)
            
    print("\n--- All scraping jobs finished ---")