import os
from flask import Flask, jsonify, send_from_directory, make_response
from flask_cors import CORS
import mysql.connector
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
base_dir = os.path.abspath(os.path.dirname(__file__))
frontend_dir = os.path.join(base_dir, '../frontend')

app = Flask(__name__, static_folder=frontend_dir, static_url_path='')
CORS(app)

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

# --- ROUTE: API Data ---
@app.route('/api/gpus', methods=['GET'])
def get_gpus():
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor(dictionary=True)
    
    # Updated query to include p.product_id so we can link to history
    query = """
    SELECT 
        p.product_id,
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
        
        # Force fresh data
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
    
    # Get all history points for this specific product, oldest to newest
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