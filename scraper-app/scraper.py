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

# Load environment variables from .env file
load_dotenv()

# --- HELPER FUNCTION ---
def parse_gpu_details(full_name, brand):
    """
    Attempts to parse the manufacturer and model from a full product name.
    """
    details = {
        'brand': brand, 
        'manufacturer': 'Unknown',
        'model_name': full_name 
    }
    
    MANUFACTURERS = ["NVIDIA", "AMD", "Intel"]
    for manu in MANUFACTURERS:
        if manu.lower() in full_name.lower():
            details['manufacturer'] = manu
            break 

    model_keywords = ["GeForce RTX", "Radeon RX", "Intel Arc"]
    found_model = False
    for keyword in model_keywords:
        if keyword.lower() in full_name.lower():
            try:
                start_index = full_name.lower().find(keyword.lower())
                sub_string = full_name[start_index:]
                model_parts = sub_string.split()
                if "Ti" in model_parts or "XT" in model_parts:
                    details['model_name'] = " ".join(model_parts[:4])
                else:
                    details['model_name'] = " ".join(model_parts[:3])
                found_model = True
                break
            except Exception:
                pass 
    
    if not found_model and len(full_name) > 100:
        temp_name = full_name.replace(details['brand'], '').strip()
        temp_name = temp_name.replace(details['manufacturer'], '').strip()
        temp_parts = temp_name.split()
        details['model_name'] = " ".join(temp_parts[:4])

    if len(details['model_name']) > 100:
        details['model_name'] = details['model_name'][:99]

    return details

# --- DATABASE FUNCTIONS ---

def get_db_connection():
    try:
        conn = mysql.connector.connect(
            host=os.getenv('DB_HOST'),
            user=os.getenv('DB_USER'),
            password=os.getenv('DB_PASSWORD'),
            database=os.getenv('DB_NAME')
        )
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
    query = "SELECT store_id FROM stores WHERE name = %s AND city = %s"
    cursor.execute(query, (store_name, city))
    result = cursor.fetchone()
    
    if result:
        return result[0] 
    else:
        insert_query = "INSERT INTO stores (name, city, state) VALUES (%s, %s, %s)"
        cursor.execute(insert_query, (store_name, city, state))
        print(f"Created new store: {store_name}, {city}")
        return cursor.lastrowid

def get_or_create_gpu(cursor, brand, model_name, manufacturer, full_name):
    query = """
    SELECT gpu_id, brand, model_name, manufacturer 
    FROM gpus 
    WHERE full_name = %s
    """
    cursor.execute(query, (full_name,))
    result = cursor.fetchone()
    
    if result:
        gpu_id, old_brand, old_model, old_manu = result
        if (old_brand != brand and brand != 'Unknown') or \
           (old_model != model_name) or \
           (old_manu != manufacturer and manufacturer != 'Unknown'):
            
            update_query = """
            UPDATE gpus SET 
                brand = %s, 
                model_name = %s, 
                manufacturer = %s
            WHERE gpu_id = %s
            """
            try:
                cursor.execute(update_query, (brand, model_name, manufacturer, gpu_id))
            except mysql.connector.Error as err:
                print(f"Error updating GPU: {err}")
        return gpu_id 
    else:
        insert_query = """
        INSERT INTO gpus (brand, model_name, manufacturer, full_name) 
        VALUES (%s, %s, %s, %s)
        """
        try:
            cursor.execute(insert_query, (brand, model_name, manufacturer, full_name))
            print(f"Created new GPU: {full_name}")
            return cursor.lastrowid
        except mysql.connector.Error as err:
            if err.errno == 1406: 
                print("Retrying with truncated model_name...")
                model_name_truncated = model_name[:99]
                try:
                    cursor.execute(insert_query, (brand, model_name_truncated, manufacturer, full_name))
                    return cursor.lastrowid
                except Exception as e:
                    print(f"Failed to create GPU: {e}")
            return None

def get_or_create_product(cursor, store_id, gpu_id, sku, product_url, image_url):
    """
    Finds a product by SKU AND Store ID.
    This creates separate product entries for each store, allowing unique history tracking.
    """
    query = "SELECT product_id FROM products WHERE microcenter_sku = %s AND store_id = %s"
    cursor.execute(query, (sku, store_id))
    result = cursor.fetchone()
    
    if result:
        update_query = """
        UPDATE products SET product_url = %s, last_seen_image_url = %s
        WHERE product_id = %s
        """
        cursor.execute(update_query, (product_url, image_url, result[0]))
        return result[0]
    else:
        insert_query = """
        INSERT INTO products (store_id, gpu_id, microcenter_sku, product_url, last_seen_image_url)
        VALUES (%s, %s, %s, %s, %s)
        """
        cursor.execute(insert_query, (store_id, gpu_id, sku, product_url, image_url))
        print(f"Created new product entry for SKU: {sku} at Store ID: {store_id}")
        return cursor.lastrowid

def log_price_history(cursor, product_id, price, stock_status):
    query = """
    INSERT INTO price_history (product_id, price_usd, stock_status)
    VALUES (%s, %s, %s)
    """
    cursor.execute(query, (product_id, price, stock_status))

# --- MAIN SCRAPER FUNCTION ---

def run_scraper(store_details):
    print(f"--- Processing Store: {store_details['name']} ---")
    conn = None
    driver = None
    items_scraped = 0 
    
    try:
        conn = get_db_connection()
        if not conn: return 0
        cursor = conn.cursor()
        
        store_id = get_or_create_store(
            cursor, 
            store_details['name'], 
            store_details['city'], 
            store_details['state']
        )
        conn.commit()

        service = Service(ChromeDriverManager().install())
        chrome_options = webdriver.ChromeOptions()
        chrome_options.add_argument("--headless=new") 
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--log-level=3") 
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36")
        
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        print(f"Scraping URL: {store_details['url']}")
        driver.get(store_details['url'])

        try:
            cookie_button = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.ID, "onetrust-accept-btn-handler"))
            )
            cookie_button.click()
            time.sleep(1) 
        except (TimeoutException, NoSuchElementException):
            pass 

        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CLASS_NAME, "productClickItemV2"))
            )
        except TimeoutException:
            print(f"Page timed out for {store_details['name']}. No products found.")
            return 0

        time.sleep(2)
        
        page_html = driver.page_source
        soup = BeautifulSoup(page_html, 'html.parser')
        product_containers = soup.find_all('li', class_='product_wrapper')
        print(f"Found {len(product_containers)} products.")

        for container in product_containers:
            try:
                name_element = container.find('a', class_='productClickItemV2')
                if not name_element: continue
                
                full_name = name_element.get('data-name', 'N/A').strip()
                brand = name_element.get('data-brand', 'Unknown').strip()
                product_url = "https://www.microcenter.com" + name_element.get('href', 'N/A')
                price = name_element.get('data-price', '0.00')

                sku_element = container.find('p', class_='sku')
                sku = sku_element.text.replace('SKU:', '').strip() if sku_element else 'N/A'

                if full_name == 'N/A' or sku == 'N/A': continue
                
                stock_status = "UNKNOWN"
                stock_element = container.find('span', class_='inventoryCnt')
                if stock_element:
                    stock_status = ' '.join(stock_element.text.split()).strip()
                else:
                    stock_element = container.find('div', class_='stock', recursive=False)
                    if stock_element:
                        stock_status = stock_element.text.strip().upper()
                    elif "SOLD OUT" in container.text.upper():
                        stock_status = "SOLD OUT"

                image_url = 'N/A'
                image_element = container.find('img', class_='SearchResultProductImage')
                if image_element:
                    image_url = image_element.get('data-src') or image_element.get('src')
                
                gpu_details = parse_gpu_details(full_name, brand)
                
                gpu_id = get_or_create_gpu(cursor,
                                           gpu_details['brand'],
                                           gpu_details['model_name'],
                                           gpu_details['manufacturer'],
                                           full_name)
                if not gpu_id: continue
                
                product_id = get_or_create_product(cursor,
                                                   store_id,
                                                   gpu_id,
                                                   sku,
                                                   product_url,
                                                   image_url)
                if not product_id: continue
                
                log_price_history(cursor, product_id, price, stock_status)
                items_scraped += 1

            except Exception as e:
                print(f"Error parsing container: {e}")

        conn.commit() 
        print(f"Successfully scraped {items_scraped} items from {store_details['name']}.")
        
    except Exception as e:
        print(f"An unexpected error occurred for {store_details['name']}: {e}")
        if conn: conn.rollback()
    finally:
        if driver: driver.quit()
        if conn: conn.close()
        
    return items_scraped

# --- SCRIPT ENTRY POINT (FOR AUTOMATION) ---
if __name__ == "__main__":
    print("--- Starting Automated Micro Center Scraper ---")
    
    STORES_TO_CHECK = [
        {"name": "Overland Park", "city": "Overland Park", "state": "KS", "id": "191"},
        {"name": "Tustin", "city": "Tustin", "state": "CA", "id": "101"},
        {"name": "Denver", "city": "Denver", "state": "CO", "id": "181"},
        {"name": "Dallas", "city": "Dallas", "state": "TX", "id": "131"},
    ]
    
    for store in STORES_TO_CHECK:
        base_url = f"https://www.microcenter.com/search/search_results.aspx?N=4294966937&NTK=all&sortby=match&storeid={store['id']}&rpp=96"
        
        page_num = 1
        while True:
            print(f"Scraping Page {page_num} for {store['name']}...")
            store['url'] = f"{base_url}&page={page_num}"
            
            count = run_scraper(store)
            
            if count < 96:
                break
            
            page_num += 1
            print("Sleeping 5 seconds before next page...")
            time.sleep(5)
        
        print("Sleeping 10 seconds before next store...")
        time.sleep(10)
    
    print("--- All scheduled scraping jobs finished ---")