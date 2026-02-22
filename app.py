import os
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session, g
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
# Secret key for session management (MCA Project Requirement)
app.secret_key = 'mca_cake_shop_super_secret_key'
DATABASE = 'database.db'

# --- DATABASE SETUP ---

def get_db():
    """Get database connection for the current request context."""
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        # Allows accessing columns by name
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    """Close database connection after request ends."""
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    """Initialize SQLite database schema and default admin."""
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        
        # 1. Admin Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        ''')
        
        # 2. Orders Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                cake_name TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                total_price REAL NOT NULL,
                payment_status TEXT DEFAULT 'pending',
                order_status TEXT DEFAULT 'new',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 3. Create Default Admin Profile
        cursor.execute("SELECT * FROM admin WHERE username='admin'")
        if not cursor.fetchone():
            hashed_pw = generate_password_hash('admin123') # Default password
            cursor.execute("INSERT INTO admin (username, password) VALUES (?, ?)", ('admin', hashed_pw))
            
        # 4. Schema Migrations (Add missing columns gracefully)
        try:
            cursor.execute("ALTER TABLE orders ADD COLUMN address TEXT DEFAULT 'N/A'")
        except Exception:
            pass # Column already exists
            
        db.commit()

# Initialize Database when server starts
init_db()

# --- FRONTEND TEMPLATE ROUTES ---

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/contact")
def contact():
    return render_template("contact.html")

@app.route("/cart")
def cart():
    return render_template("cart.html")

@app.route("/customize")
def customize():
    return render_template("customize.html")

@app.route("/admin")
def admin():
    return render_template("admin.html")


# --- REST API ARCHITECTURE ---

@app.route('/place-order', methods=['POST'])
def place_order():
    """API to place a new cake order correctly from frontend."""
    data = request.get_json()
    required_fields = ['customer_name', 'phone', 'cake_name', 'quantity', 'total_price']
    
    # Server-Side Validation
    if not data or not all(k in data for k in required_fields):
        return jsonify({"success": False, "message": "Missing required fields"}), 400
        
    address = data.get('address', 'N/A')
        
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute('''
            INSERT INTO orders (customer_name, phone, cake_name, quantity, total_price, address)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            data['customer_name'], 
            data['phone'], 
            data['cake_name'], 
            int(data['quantity']), 
            float(data['total_price']),
            address
        ))
        db.commit()
        order_id = cursor.lastrowid
        return jsonify({"success": True, "message": "Order placed successfully!", "order_id": order_id}), 201
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/admin-login', methods=['POST'])
def admin_login():
    """API to authenticate admin and generate session."""
    data = request.get_json()
    if not data or 'username' not in data or 'password' not in data:
        return jsonify({"success": False, "message": "Missing credentials"}), 400
        
    username = data['username']
    password = data['password']
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM admin WHERE username=?", (username,))
    admin_user = cursor.fetchone()
    
    # Verify password hash
    if admin_user and check_password_hash(admin_user['password'], password):
        session['admin_logged_in'] = True
        session['admin_id'] = admin_user['id']
        session['username'] = admin_user['username']
        return jsonify({"success": True, "message": "Login successful"}), 200
    else:
        return jsonify({"success": False, "message": "Invalid username or password"}), 401

@app.route('/admin-logout', methods=['POST'])
def admin_logout():
    """API to destroy admin session."""
    session.clear()
    return jsonify({"success": True, "message": "Logged out successfully"}), 200

@app.route('/check-session', methods=['GET'])
def check_session():
    """Helper API for frontend to verify auth state on page load."""
    if session.get('admin_logged_in'):
        return jsonify({"success": True, "message": "Authenticated"}), 200
    return jsonify({"success": False, "message": "Not authenticated"}), 401
    
# Persistent shop status using a simple JSON file
SHOP_STATUS_FILE = 'shop_status.json'

def get_shop_status():
    if not os.path.exists(SHOP_STATUS_FILE):
        return True
    try:
        import json
        with open(SHOP_STATUS_FILE, 'r') as f:
            data = json.load(f)
            return data.get('open', True)
    except:
        return True

def set_shop_status(is_open):
    import json
    with open(SHOP_STATUS_FILE, 'w') as f:
        json.dump({'open': is_open}, f)

@app.route('/shop-status', methods=['GET'])
def shop_status_get():
    """API to get the current shop status."""
    return jsonify({"success": True, "open": get_shop_status()}), 200

@app.route('/shop-status', methods=['POST'])
def shop_status_post():
    """API to set the shop status (Admin Protected)."""
    if not session.get('admin_logged_in'):
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    data = request.get_json()
    is_open = data.get('open', True)
    set_shop_status(is_open)
    return jsonify({"success": True, "open": is_open}), 200

@app.route('/get-orders', methods=['GET'])
def get_orders():
    """API to fetch all orders (Admin Protected)."""
    if not session.get('admin_logged_in'):
        return jsonify({"success": False, "message": "Unauthorized"}), 403
        
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM orders ORDER BY created_at DESC")
    orders = cursor.fetchall()
    
    # Convert sqlite3.Row to standard Dictionary
    orders_list = [dict(ix) for ix in orders]
    return jsonify({"success": True, "orders": orders_list}), 200

@app.route('/verify-payment/<int:order_id>', methods=['PUT'])
def verify_payment(order_id):
    """API to verify payment for a specific order (Admin Protected)."""
    if not session.get('admin_logged_in'):
        return jsonify({"success": False, "message": "Unauthorized"}), 403
        
    db = get_db()
    cursor = db.cursor()
    cursor.execute("UPDATE orders SET payment_status='Verified', order_status='Processing' WHERE id=?", (order_id,))
    db.commit()
    
    if cursor.rowcount == 0:
        return jsonify({"success": False, "message": "Order not found"}), 404
        
    return jsonify({"success": True, "message": "Payment verified and order is now processing."}), 200

@app.route('/delete-order/<int:order_id>', methods=['DELETE'])
def delete_order(order_id):
    """API to delete an order record entirely (Admin Protected)."""
    if not session.get('admin_logged_in'):
        return jsonify({"success": False, "message": "Unauthorized"}), 403
        
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM orders WHERE id=?", (order_id,))
    db.commit()
    
    if cursor.rowcount == 0:
        return jsonify({"success": False, "message": "Order not found"}), 404
        
    return jsonify({"success": True, "message": "Order deleted permanently."}), 200

if __name__ == "__main__":
    app.run(debug=True, port=8080)
