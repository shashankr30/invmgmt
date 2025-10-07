from flask import Flask, render_template, request, jsonify, url_for, session, redirect, send_from_directory, send_file
from flask_bcrypt import Bcrypt
import sqlite3
import os
import uuid
import logging
from datetime import datetime
from werkzeug.utils import secure_filename
from openpyxl import Workbook
from io import BytesIO

app = Flask(__name__)
app.secret_key = 'your-secret-key'
bcrypt = Bcrypt(app)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# File upload configuration
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Initialize SQLite database
def init_db():
    try:
        conn = sqlite3.connect('inventory.db')
        conn.execute('PRAGMA foreign_keys = ON')
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS products
                     (product_id TEXT PRIMARY KEY, name TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS variants
                     (variant_id TEXT PRIMARY KEY, product_id TEXT, barcode TEXT UNIQUE, type TEXT, size TEXT, 
                      cost REAL, selling_price REAL, stock INTEGER, photo TEXT,
                      FOREIGN KEY(product_id) REFERENCES products(product_id) ON DELETE CASCADE)''')
        c.execute('''CREATE TABLE IF NOT EXISTS requests
                     (request_id TEXT PRIMARY KEY, variant_id TEXT, customer_name TEXT, contact_info TEXT,
                      FOREIGN KEY(variant_id) REFERENCES variants(variant_id) ON DELETE CASCADE)''')
        c.execute('''CREATE TABLE IF NOT EXISTS sales
                     (sale_id TEXT PRIMARY KEY, variant_id TEXT, quantity INTEGER, revenue REAL, sale_time TEXT,
                      FOREIGN KEY(variant_id) REFERENCES variants(variant_id) ON DELETE CASCADE)''')
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (user_id TEXT PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT, is_admin INTEGER)''')
        c.execute('''CREATE TABLE IF NOT EXISTS purchases
                     (purchase_id TEXT PRIMARY KEY, variant_id TEXT, quantity INTEGER, purchase_time TEXT,
                      FOREIGN KEY(variant_id) REFERENCES variants(variant_id) ON DELETE CASCADE)''')
        c.execute('''CREATE TABLE IF NOT EXISTS pre_orders
                     (pre_order_id TEXT PRIMARY KEY, variant_id TEXT, customer_name TEXT, contact_info TEXT, quantity INTEGER, pre_order_time TEXT,
                      FOREIGN KEY(variant_id) REFERENCES variants(variant_id) ON DELETE CASCADE)''')
        c.execute("SELECT COUNT(*) FROM products")
        product_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users")
        user_count = c.fetchone()[0]
        if product_count == 0:
            logger.info("Adding sample product data")
            c.execute("INSERT INTO products VALUES (?, ?)", ('p1', 'Team Jersey'))
            c.execute("INSERT INTO products VALUES (?, ?)", ('p2', 'Practice Kit'))
            c.execute("INSERT INTO variants VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      ('v1', 'p1', '123456789', 'Home', 'M', 49.99, 79.99, 10, 'placeholder.jpg'))
            c.execute("INSERT INTO variants VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      ('v2', 'p1', '123456790', 'Home', 'L', 49.99, 79.99, 0, 'placeholder.jpg'))
            c.execute("INSERT INTO variants VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      ('v3', 'p1', '987654321', 'Away', 'S', 59.99, 89.99, 5, 'placeholder.jpg'))
            c.execute("INSERT INTO variants VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      ('v4', 'p2', '111222333', 'Training', 'M', 39.99, 69.99, 8, 'placeholder.jpg'))
        if user_count == 0:
            logger.info("Adding default admin user")
            admin_id = str(uuid.uuid4())
            password_hash = bcrypt.generate_password_hash('adminpass').decode('utf-8')
            c.execute("INSERT INTO users VALUES (?, ?, ?, ?)", (admin_id, 'admin', password_hash, 1))
        conn.commit()
        logger.info(f"Database initialized: {product_count} products, {user_count} users before initialization")
    except sqlite3.Error as e:
        logger.error(f"Database initialization failed: {e}")
    finally:
        conn.close()

# Middleware to check authentication
def login_required(f):
    def wrap(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    wrap.__name__ = f.__name__
    return wrap

# Admin-only middleware
def admin_required(f):
    def wrap(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login'))
        if not session.get('is_admin'):
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    wrap.__name__ = f.__name__
    return wrap

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        try:
            data = request.json
            username = data['username']
            password = data['password']
            conn = sqlite3.connect('inventory.db')
            conn.execute('PRAGMA foreign_keys = ON')
            c = conn.cursor()
            c.execute("SELECT user_id, username, password_hash, is_admin FROM users WHERE username = ?", (username,))
            user = c.fetchone()
            conn.close()
            if user and bcrypt.check_password_hash(user[2], password):
                session['user_id'] = user[0]
                session['username'] = user[1]
                session['is_admin'] = user[3]
                return jsonify({'success': True})
            return jsonify({'error': 'Invalid username or password'}), 401
        except sqlite3.Error as e:
            logger.error(f"Login error: {e}")
            return jsonify({'error': 'Database error'}), 500
    return render_template('login.html')

@app.route('/logout', methods=['POST'])
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    session.pop('is_admin', None)
    return jsonify({'success': True})

@app.route('/users', methods=['GET', 'POST'])
@admin_required
def users():
    if request.method == 'POST':
        try:
            data = request.json
            username = data['username']
            password = data['password']
            is_admin = data.get('is_admin', 0)
            user_id = str(uuid.uuid4())
            password_hash = bcrypt.generate_password_hash(password).decode('utf-8')
            conn = sqlite3.connect('inventory.db')
            conn.execute('PRAGMA foreign_keys = ON')
            c = conn.cursor()
            c.execute("INSERT INTO users VALUES (?, ?, ?, ?)", (user_id, username, password_hash, is_admin))
            conn.commit()
            conn.close()
            return jsonify({'success': True})
        except sqlite3.Error as e:
            logger.error(f"Add user error: {e}")
            return jsonify({'error': 'Database error or username exists'}), 500
    try:
        conn = sqlite3.connect('inventory.db')
        conn.execute('PRAGMA foreign_keys = ON')
        c = conn.cursor()
        c.execute("SELECT user_id, username, is_admin FROM users")
        users = c.fetchall()
        conn.close()
        return render_template('users.html', users=users, username=session.get('username'), is_admin=session.get('is_admin'))
    except sqlite3.Error as e:
        logger.error(f"Users page error: {e}")
        return render_template('users.html', users=[], username=session.get('username'), is_admin=session.get('is_admin'), error="Database error")

@app.route('/delete_user', methods=['POST'])
@admin_required
def delete_user():
    try:
        user_id = request.json['user_id']
        if user_id == session.get('user_id'):
            return jsonify({'error': 'Cannot delete own account'}), 400
        conn = sqlite3.connect('inventory.db')
        conn.execute('PRAGMA foreign_keys = ON')
        c = conn.cursor()
        c.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except sqlite3.Error as e:
        logger.error(f"Delete user error: {e}")
        return jsonify({'error': 'Database error'}), 500

@app.route('/inventory', methods=['GET', 'POST'])
@login_required
def inventory():
    if request.method == 'POST' and session.get('is_admin'):
        try:
            data = request.json
            action = data.get('action')
            if action == 'update_stock':
                variant_id = data['variant_id']
                stock = data['stock']
                if stock < 0:
                    return jsonify({'error': 'Stock cannot be negative'}), 400
                conn = sqlite3.connect('inventory.db')
                conn.execute('PRAGMA foreign_keys = ON')
                c = conn.cursor()
                c.execute("UPDATE variants SET stock = ? WHERE variant_id = ?", (stock, variant_id))
                conn.commit()
                conn.close()
                return jsonify({'success': True})
            else:
                return jsonify({'error': 'Invalid action'}), 400
        except sqlite3.Error as e:
            logger.error(f"Inventory action error: {e}")
            return jsonify({'error': 'Database error'}), 500
    try:
        conn = sqlite3.connect('inventory.db')
        conn.execute('PRAGMA foreign_keys = ON')
        c = conn.cursor()
        c.execute('''SELECT p.product_id, p.name, v.variant_id, v.type, v.size, v.barcode, v.cost, v.selling_price, v.stock
                     FROM products p LEFT JOIN variants v ON p.product_id = v.product_id
                     ORDER BY p.product_id, v.variant_id''')
        rows = c.fetchall()
        products = {}
        for row in rows:
            product_id, name, variant_id, type_, size, barcode, cost, selling_price, stock = row
            if product_id not in products:
                products[product_id] = {'product_id': product_id, 'name': name, 'variants': []}
            if variant_id:  # Only add variants if they exist
                products[product_id]['variants'].append({
                    'variant_id': variant_id, 'type': type_, 'size': size, 'barcode': barcode,
                    'cost': cost, 'selling_price': selling_price, 'stock': stock
                })
        products = list(products.values())
        logger.info(f"Inventory fetched: {len(products)} products")
        c.execute('''SELECT SUM(s.revenue - (v.cost * s.quantity)) as total_profit
                     FROM sales s JOIN variants v ON s.variant_id = v.variant_id''')
        total_profit = c.fetchone()[0] or 0
        c.execute('SELECT SUM(revenue) as total_revenue FROM sales')
        total_revenue = c.fetchone()[0] or 0
        c.execute('''SELECT p.name, v.type, v.size, s.quantity, s.revenue, v.cost, s.sale_time
                     FROM sales s JOIN variants v ON s.variant_id = v.variant_id
                     JOIN products p ON v.product_id = p.product_id''')
        sales = c.fetchall()
        conn.close()
        if not products:
            logger.warning("No products found in inventory")
        return render_template('inventory.html', products=products, total_profit=total_profit, total_revenue=total_revenue,
                               sales=sales, username=session.get('username'), is_admin=session.get('is_admin'))
    except sqlite3.Error as e:
        logger.error(f"Inventory error: {e}")
        return render_template('inventory.html', products=[], total_profit=0, total_revenue=0, sales=[],
                               username=session.get('username'), is_admin=session.get('is_admin'), error="Database error")

@app.route('/add_product', methods=['GET', 'POST'])
@login_required
def add_product():
    if request.method == 'POST':
        try:
            data = request.form
            product_id = str(uuid.uuid4())
            conn = sqlite3.connect('inventory.db')
            conn.execute('PRAGMA foreign_keys = ON')
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO products VALUES (?, ?)", (product_id, data['name']))
            for i in range(len(request.files)):
                variant_id = str(uuid.uuid4())
                barcode = data[f'barcode_{i}']
                if not barcode or c.execute("SELECT barcode FROM variants WHERE barcode = ?", (barcode,)).fetchone():
                    conn.close()
                    return jsonify({'error': 'Duplicate or empty barcode'}), 400
                type_ = data[f'type_{i}']
                size = data[f'size_{i}']
                cost = float(data[f'cost_{i}'])
                selling_price = float(data[f'selling_price_{i}'])
                stock = int(data[f'stock_{i}'])
                if cost < 0 or selling_price < 0 or stock < 0:
                    conn.close()
                    return jsonify({'error': 'Negative values not allowed'}), 400
                file = request.files[f'photo_{i}']
                if not file or not allowed_file(file.filename):
                    conn.close()
                    return jsonify({'error': 'Valid image file required for each variant'}), 400
                filename = secure_filename(f"{variant_id}.{file.filename.rsplit('.', 1)[1].lower()}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                c.execute("INSERT OR REPLACE INTO variants VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                          (variant_id, product_id, barcode, type_, size, cost, selling_price, stock, filename))
            conn.commit()
            conn.close()
            return jsonify({'success': True})
        except (sqlite3.Error, ValueError) as e:
            logger.error(f"Add product error: {e}")
            return jsonify({'error': 'Database or input error'}), 500
    try:
        conn = sqlite3.connect('inventory.db')
        conn.execute('PRAGMA foreign_keys = ON')
        c = conn.cursor()
        c.execute('SELECT product_id, name FROM products')
        products = c.fetchall()
        c.execute('''SELECT v.variant_id, p.name, v.type, v.size, v.barcode
                     FROM variants v JOIN products p ON v.product_id = p.product_id''')
        variants = c.fetchall()
        conn.close()
        return render_template('add_product.html', products=products, variants=variants,
                               username=session.get('username'), is_admin=session.get('is_admin'))
    except sqlite3.Error as e:
        logger.error(f"Add product page error: {e}")
        return render_template('add_product.html', products=[], variants=[],
                               username=session.get('username'), is_admin=session.get('is_admin'), error="Database error")

@app.route('/delete_product', methods=['POST'])
@admin_required
def delete_product():
    try:
        product_id = request.json['product_id']
        conn = sqlite3.connect('inventory.db')
        conn.execute('PRAGMA foreign_keys = ON')
        c = conn.cursor()
        c.execute("SELECT photo FROM variants WHERE product_id = ?", (product_id,))
        photos = c.fetchall()
        for photo in photos:
            photo_path = os.path.join(app.config['UPLOAD_FOLDER'], photo[0])
            if os.path.exists(photo_path) and photo[0] != 'placeholder.jpg':
                os.remove(photo_path)
        c.execute("DELETE FROM products WHERE product_id = ?", (product_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except (sqlite3.Error, OSError) as e:
        logger.error(f"Delete product error: {e}")
        return jsonify({'error': 'Database or file error'}), 500

@app.route('/delete_variant', methods=['POST'])
@admin_required
def delete_variant():
    try:
        variant_id = request.json['variant_id']
        conn = sqlite3.connect('inventory.db')
        conn.execute('PRAGMA foreign_keys = ON')
        c = conn.cursor()
        c.execute("SELECT photo FROM variants WHERE variant_id = ?", (variant_id,))
        photo = c.fetchone()[0]
        if photo and photo != 'placeholder.jpg':
            photo_path = os.path.join(app.config['UPLOAD_FOLDER'], photo)
            if os.path.exists(photo_path):
                os.remove(photo_path)
        c.execute("DELETE FROM variants WHERE variant_id = ?", (variant_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except (sqlite3.Error, OSError) as e:
        logger.error(f"Delete variant error: {e}")
        return jsonify({'error': 'Database or file error'}), 500

@app.route('/approve_purchase', methods=['POST'])
@admin_required
def approve_purchase():
    try:
        purchase_id = request.json['purchase_id']
        conn = sqlite3.connect('inventory.db')
        conn.execute('PRAGMA foreign_keys = ON')
        c = conn.cursor()
        c.execute("SELECT variant_id, quantity FROM purchases WHERE purchase_id = ?", (purchase_id,))
        purchase = c.fetchone()
        if not purchase:
            conn.close()
            return jsonify({'error': 'Purchase not found'}), 404
        variant_id, quantity = purchase
        c.execute("UPDATE variants SET stock = stock + ? WHERE variant_id = ?", (quantity, variant_id))
        c.execute("DELETE FROM purchases WHERE purchase_id = ?", (purchase_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except sqlite3.Error as e:
        logger.error(f"Approve purchase error: {e}")
        return jsonify({'error': 'Database error'}), 500

@app.route('/reject_purchase', methods=['POST'])
@admin_required
def reject_purchase():
    try:
        purchase_id = request.json['purchase_id']
        conn = sqlite3.connect('inventory.db')
        conn.execute('PRAGMA foreign_keys = ON')
        c = conn.cursor()
        c.execute("DELETE FROM purchases WHERE purchase_id = ?", (purchase_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except sqlite3.Error as e:
        logger.error(f"Reject purchase error: {e}")
        return jsonify({'error': 'Database error'}), 500

@app.route('/transactions', methods=['GET', 'POST'])
@login_required
def transactions():
    if request.method == 'POST':
        try:
            action = request.json['action']
            variant_id = request.json['variant_id']
            conn = sqlite3.connect('inventory.db')
            conn.execute('PRAGMA foreign_keys = ON')
            c = conn.cursor()
            if action == 'sell':
                selling_price = float(request.json['selling_price'])
                c.execute("SELECT stock FROM variants WHERE variant_id = ?", (variant_id,))
                stock = c.fetchone()[0]
                if stock > 0:
                    c.execute("UPDATE variants SET stock = stock - 1 WHERE variant_id = ?", (variant_id,))
                    sale_id = str(uuid.uuid4())
                    c.execute("INSERT INTO sales VALUES (?, ?, ?, ?, ?)",
                              (sale_id, variant_id, 1, selling_price, datetime.now().isoformat()))
                    conn.commit()
                    conn.close()
                    return jsonify({'success': True, 'new_stock': stock - 1, 'request_url': ''})
                conn.close()
                return jsonify({'error': 'Out of stock', 'request_url': url_for('contact_form', variant_id=variant_id, _external=True)}), 400
            elif action == 'buy':
                quantity = request.json['quantity']
                if quantity < 1:
                    return jsonify({'error': 'Invalid quantity'}), 400
                purchase_id = str(uuid.uuid4())
                c.execute("INSERT INTO purchases VALUES (?, ?, ?, ?)",
                          (purchase_id, variant_id, quantity, datetime.now().isoformat()))
                conn.commit()
                conn.close()
                return jsonify({'success': True, 'message': f'Purchase request for {quantity} units submitted'})
            else:
                return jsonify({'error': 'Invalid action'}), 400
        except sqlite3.Error as e:
            logger.error(f"Transaction error: {e}")
            return jsonify({'error': 'Database error'}), 500
    return render_template('transactions.html', username=session.get('username'), is_admin=session.get('is_admin'))

@app.route('/scan', methods=['POST'])
@login_required
def scan():
    try:
        barcode = request.json['barcode']
        conn = sqlite3.connect('inventory.db')
        conn.execute('PRAGMA foreign_keys = ON')
        c = conn.cursor()
        c.execute('''SELECT p.product_id, p.name, v.type, v.selling_price, v.variant_id, v.barcode, v.size, v.stock, v.photo
                     FROM products p JOIN variants v ON p.product_id = v.product_id
                     WHERE v.barcode = ?''', (barcode,))
        product = c.fetchone()
        conn.close()
        if product:
            return jsonify({
                'product_id': product[0],
                'name': product[1],
                'type': product[2],
                'selling_price': product[3],
                'variant_id': product[4],
                'barcode': product[5],
                'size': product[6],
                'stock': product[7],
                'photo': url_for('static', filename=f'uploads/{product[8]}') if product[8] != 'placeholder.jpg' else url_for('static', filename='placeholder.jpg'),
                'request_url': url_for('contact_form', variant_id=product[4], _external=True) if product[7] == 0 else ''
            })
        return jsonify({'error': 'Product not found'}), 404
    except sqlite3.Error as e:
        logger.error(f"Scan error: {e}")
        return jsonify({'error': 'Database error'}), 500

@app.route('/contact/<variant_id>', methods=['GET', 'POST'])
def contact_form(variant_id):
    try:
        conn = sqlite3.connect('inventory.db')
        conn.execute('PRAGMA foreign_keys = ON')
        c = conn.cursor()
        c.execute('''SELECT p.name, v.type, v.size
                     FROM products p JOIN variants v ON p.product_id = v.product_id
                     WHERE v.variant_id = ?''', (variant_id,))
        product = c.fetchone()
        if not product:
            conn.close()
            return "Product not found", 404
        if request.method == 'POST':
            customer_name = request.form['customer_name']
            contact_info = request.form['contact_info']
            request_id = str(uuid.uuid4())
            c.execute("INSERT INTO requests VALUES (?, ?, ?, ?)",
                      (request_id, variant_id, customer_name, contact_info))
            conn.commit()
            conn.close()
            return render_template('contact_success.html', product_name=product[0], type=product[1], size=product[2])
        conn.close()
        return render_template('contact_form.html', variant_id=variant_id, product_name=product[0], type=product[1], size=product[2])
    except sqlite3.Error as e:
        logger.error(f"Contact form error: {e}")
        return jsonify({'error': 'Database error'}), 500

@app.route('/pre_order/<variant_id>', methods=['GET', 'POST'])
def pre_order(variant_id):
    try:
        conn = sqlite3.connect('inventory.db')
        conn.execute('PRAGMA foreign_keys = ON')
        c = conn.cursor()
        c.execute('''SELECT p.name, v.type, v.size
                     FROM products p JOIN variants v ON p.product_id = v.product_id
                     WHERE v.variant_id = ?''', (variant_id,))
        product = c.fetchone()
        if not product:
            conn.close()
            return "Product not found", 404
        if request.method == 'POST':
            customer_name = request.form['customer_name']
            contact_info = request.form['contact_info']
            quantity = int(request.form['quantity'])
            pre_order_id = str(uuid.uuid4())
            c.execute("INSERT INTO pre_orders VALUES (?, ?, ?, ?, ?, ?)",
                      (pre_order_id, variant_id, customer_name, contact_info, quantity, datetime.now().isoformat()))
            conn.commit()
            conn.close()
            return render_template('pre_order_success.html', product_name=product[0], type=product[1], size=product[2], quantity=quantity)
        conn.close()
        return render_template('pre_order.html', variant_id=variant_id, product_name=product[0], type=product[1], size=product[2])
    except sqlite3.Error as e:
        logger.error(f"Pre order error: {e}")
        return jsonify({'error': 'Database error'}), 500

@app.route('/pre_orders')
@login_required
def pre_orders():
    try:
        conn = sqlite3.connect('inventory.db')
        conn.execute('PRAGMA foreign_keys = ON')
        c = conn.cursor()
        c.execute('''SELECT r.request_id, p.name, v.type, v.size, r.customer_name, r.contact_info
                     FROM requests r
                     JOIN variants v ON r.variant_id = v.variant_id
                     JOIN products p ON v.product_id = p.product_id''')
        requests = c.fetchall()
        c.execute('''SELECT p.purchase_id, p_.name, v.type, v.size, p.quantity, p.purchase_time
                     FROM purchases p
                     JOIN variants v ON p.variant_id = v.variant_id
                     JOIN products p_ ON v.product_id = p_.product_id''')
        purchases = c.fetchall()
        c.execute('''SELECT po.pre_order_id, p.name, v.type, v.size, po.customer_name, po.contact_info, po.quantity, po.pre_order_time
                     FROM pre_orders po
                     JOIN variants v ON po.variant_id = v.variant_id
                     JOIN products p ON v.product_id = p.product_id''')
        pre_orders = c.fetchall()
        conn.close()
        logger.info(f"Requests fetched: {len(requests)} customer requests, {len(purchases)} purchase requests, {len(pre_orders)} pre-orders")
        return render_template('requests.html', requests=requests, purchases=purchases, pre_orders=pre_orders,
                               username=session.get('username'), is_admin=session.get('is_admin'))
    except sqlite3.Error as e:
        logger.error(f"Requests error: {e}")
        return render_template('requests.html', requests=[], purchases=[], pre_orders=[],
                               username=session.get('username'), is_admin=session.get('is_admin'), error="Database error")

@app.route('/export_inventory')
@login_required
def export_inventory():
    try:
        conn = sqlite3.connect('inventory.db')
        conn.execute('PRAGMA foreign_keys = ON')
        c = conn.cursor()
        c.execute('''SELECT p.name, v.type, v.size, v.barcode, v.cost, v.selling_price, v.stock
                     FROM products p JOIN variants v ON p.product_id = v.product_id''')
        data = c.fetchall()
        conn.close()
        wb = Workbook()
        ws = wb.active
        ws.title = "Inventory"
        ws.append(['Product Name', 'Type', 'Size', 'Barcode', 'Cost', 'Selling Price', 'Stock'])
        for row in data:
            ws.append(row)
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        return send_file(output, download_name='inventory.xlsx', as_attachment=True)
    except Exception as e:
        logger.error(f"Export inventory error: {e}")
        return jsonify({'error': 'Export failed'}), 500

@app.route('/export_sales')
@login_required
def export_sales():
    try:
        conn = sqlite3.connect('inventory.db')
        conn.execute('PRAGMA foreign_keys = ON')
        c = conn.cursor()
        c.execute('''SELECT p.name, v.type, v.size, s.quantity, s.revenue, v.cost, s.sale_time
                     FROM sales s JOIN variants v ON s.variant_id = v.variant_id
                     JOIN products p ON v.product_id = p.product_id''')
        data = c.fetchall()
        conn.close()
        wb = Workbook()
        ws = wb.active
        ws.title = "Sales History"
        ws.append(['Product Name', 'Type', 'Size', 'Quantity', 'Revenue', 'Cost', 'Sale Time'])
        for row in data:
            ws.append(row)
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        return send_file(output, download_name='sales_history.xlsx', as_attachment=True)
    except Exception as e:
        logger.error(f"Export sales error: {e}")
        return jsonify({'error': 'Export failed'}), 500

if __name__ == '__main__':
    logger.info("Starting application and initializing database")
    init_db()
    app.run(debug=True)