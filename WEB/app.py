# Vault Shop - Main Application
# This is the core Flask app for Vault Shop, integrating Telegram bot, web interface, and NOWPayments.
# Features: Anonymous e-commerce for digital products, dual channels (bot + web), crypto payments.

import os  # For environment variables
from flask import Flask, request, jsonify, render_template, redirect, url_for, flash  # Flask web framework
import psycopg2  # PostgreSQL driver
from psycopg2 import pool  # Connection pooling for efficiency
import telegram  # Telegram API
from telegram.ext import Updater, Dispatcher, CommandHandler, CallbackQueryHandler, MessageHandler, Filters  # Bot handlers
import requests  # HTTP requests for NOWPayments and webhook setup
import secrets  # Secure random generation
import datetime  # Date/time handling
import hmac  # HMAC for IPN validation
import hashlib  # SHA512 for signatures
import logging  # Logging for debugging and monitoring
from flask_limiter import Limiter  # Rate limiting
from flask_limiter.util import get_remote_address  # For IP-based limiting
from flask_caching import Cache  # Caching
from flask_wtf import FlaskForm, CSRFProtect  # CSRF protection
from wtforms import StringField, FloatField, TextAreaField, SubmitField  # Form fields
from wtforms.validators import DataRequired, NumberRange  # Validators

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default-secret')  # For CSRF and sessions

# Setup rate limiting
limiter = Limiter(get_remote_address, app=app, default_limits=["200 per day", "50 per hour"])

# Setup caching
cache = Cache(app, config={'CACHE_TYPE': 'simple'})

# Setup CSRF protection
csrf = CSRFProtect(app)

# Load environment variables - critical for security and configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')  # Telegram bot token
DATABASE_URL = os.getenv('DATABASE_URL')  # PostgreSQL connection string
NOWPAYMENTS_API_KEY = os.getenv('NOWPAYMENTS_API_KEY')  # NOWPayments API key
NOWPAYMENTS_IPN_SECRET = os.getenv('NOWPAYMENTS_IPN_SECRET')  # Secret for IPN validation
WEBHOOK_URL = os.getenv('WEBHOOK_URL')  # Full webhook URL for bot
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID')  # Admin Telegram chat ID for notifications

# Database connection pool - uses SimpleConnectionPool for thread safety and efficiency
db_pool = psycopg2.pool.SimpleConnectionPool(1, 10, DATABASE_URL)

# WTForms for admin panel
class ProductForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired()])
    price = FloatField('Price', validators=[DataRequired(), NumberRange(min=0)])
    description = TextAreaField('Description', validators=[DataRequired()])
    image_url = StringField('Image URL')
    submit = SubmitField('Add Product')

# Function to generate unique order IDs
# Format: Prefix (B for bot, W for web) - 6 random alphanum - ddmmyy
def generate_order_id(prefix):
    random_part = ''.join(secrets.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789') for _ in range(6))
    date_part = datetime.datetime.now().strftime('%d%m%y')
    return f"{prefix}-{random_part}-{date_part}"

# Function to create NOWPayments invoice
# Supports different coins, defaults to BTC for web
def create_invoice(price, order_id, coin='BTC'):
    url = 'https://api.nowpayments.io/v1/invoice'
    headers = {'x-api-key': NOWPAYMENTS_API_KEY, 'Content-Type': 'application/json'}
    data = {
        'price_amount': price,
        'price_currency': 'USD',
        'order_id': order_id,
        'pay_currency': coin,
        'ipn_callback_url': WEBHOOK_URL.replace('/bot-webhook', '/ipn')  # IPN callback URL
    }
    response = requests.post(url, headers=headers, json=data)
    logger.info(f"Created invoice for order {order_id}: {response.status_code}")
    return response.json()

# Function to validate NOWPayments IPN signatures
# Uses HMAC-SHA512 for security
def validate_ipn(request):
    signature = request.headers.get('x-nowpayments-sig')
    body = request.get_data()
    expected_sig = hmac.new(NOWPAYMENTS_IPN_SECRET.encode(), body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(signature, expected_sig)

# Telegram Bot Setup
# Uses webhook mode (not polling) for production efficiency
updater = Updater(token=BOT_TOKEN, use_context=True)
dispatcher = updater.dispatcher

# Bot Handler: /start command
# Welcomes user and provides product browsing button
def start(update, context):
    keyboard = [[telegram.InlineKeyboardButton("View Products", callback_data='view_products')]]
    reply_markup = telegram.InlineKeyboardMarkup(keyboard)
    update.message.reply_text('Welcome to Vault Shop!', reply_markup=reply_markup)

dispatcher.add_handler(CommandHandler('start', start))

# Bot Handler: View products callback
# Queries DB for products and shows inline buttons
def view_products(update, context):
    conn = db_pool.getconn()
    cur = conn.cursor()
    cur.execute("SELECT id, name, price FROM products")
    products = cur.fetchall()
    cur.close()
    db_pool.putconn(conn)
    keyboard = [[telegram.InlineKeyboardButton(f"{name} - ${price}", callback_data=f'buy_{id}')] for id, name, price in products]
    reply_markup = telegram.InlineKeyboardMarkup(keyboard)
    update.callback_query.edit_message_text('Select a product:', reply_markup=reply_markup)

dispatcher.add_handler(CallbackQueryHandler(view_products, pattern='^view_products$'))

# Bot Handler: Buy product callback
# Shows product details and coin selection
def buy_product(update, context):
    product_id = update.callback_query.data.split('_')[1]
    conn = db_pool.getconn()
    cur = conn.cursor()
    cur.execute("SELECT name, price, description FROM products WHERE id = %s", (product_id,))
    product = cur.fetchone()
    cur.close()
    db_pool.putconn(conn)
    if product:
        name, price, desc = product
        text = f"{name}\nPrice: ${price}\n{desc}\n\nChoose coin:"
        keyboard = [[telegram.InlineKeyboardButton(coin, callback_data=f'confirm_{product_id}_{coin}')] for coin in ['BTC', 'ETH', 'LTC', 'USDT', 'BCH']]
        reply_markup = telegram.InlineKeyboardMarkup(keyboard)
        update.callback_query.edit_message_text(text, reply_markup=reply_markup)

dispatcher.add_handler(CallbackQueryHandler(buy_product, pattern='^buy_\d+$'))

# Bot Handler: Confirm purchase callback
# Creates order in DB, generates invoice, sends payment link
def confirm_purchase(update, context):
    _, product_id, coin = update.callback_query.data.split('_')
    user_id = update.callback_query.from_user.id
    order_id = generate_order_id('B')
    conn = db_pool.getconn()
    cur = conn.cursor()
    cur.execute("SELECT price FROM products WHERE id = %s", (product_id,))
    price = cur.fetchone()[0]
    cur.execute("INSERT INTO orders (product_id, total_amount, user_identifier, order_id, payment_id) VALUES (%s, %s, %s, %s, %s)",
                (product_id, price, str(user_id), order_id, ''))
    conn.commit()
    cur.close()
    db_pool.putconn(conn)
    invoice = create_invoice(price, order_id, coin)
    payment_url = invoice.get('invoice_url')
    keyboard = [[telegram.InlineKeyboardButton("Pay Now", url=payment_url)]]
    reply_markup = telegram.InlineKeyboardMarkup(keyboard)
    update.callback_query.edit_message_text(f'Order created: {order_id}\nPay here:', reply_markup=reply_markup)

dispatcher.add_handler(CallbackQueryHandler(confirm_purchase, pattern='^confirm_\d+_[A-Z]+$'))

# Bot Handler: Choose delivery method callback
# Stores method in context for next step
def choose_delivery(update, context):
    method, order_id = update.callback_query.data.split('_')[1], '_'.join(update.callback_query.data.split('_')[2:])
    context.user_data['method'] = method
    context.user_data['order_id'] = order_id
    update.callback_query.edit_message_text(f'Enter your {method} details:')

dispatcher.add_handler(CallbackQueryHandler(choose_delivery, pattern='^delivery_(telegram|email)_'))

# Bot Handler: Receive delivery details
# Forwards to admin and confirms to user
def receive_details(update, context):
    details = update.message.text
    method = context.user_data.get('method')
    order_id = context.user_data.get('order_id')
    if method and order_id:
        bot = telegram.Bot(token=BOT_TOKEN)
        message = f"New Order: {order_id}\nDelivery: {method} ({details})"
        bot.send_message(chat_id=ADMIN_CHAT_ID, text=message)
        update.message.reply_text('Details submitted! You will receive your product soon.')

dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, receive_details))

# Web Route: Home page
# Renders product grid with caching
@app.route('/')
@cache.cached(timeout=300)  # Cache for 5 minutes
def index():
    try:
        conn = db_pool.getconn()
        cur = conn.cursor()
        cur.execute("SELECT id, name, price, description, image_url FROM products")
        products = cur.fetchall()
        cur.close()
        db_pool.putconn(conn)
        return render_template('index.html', products=products)
    except Exception as e:
        logger.error(f"Error loading products: {e}")
        flash("Error loading products. Please try again.")
        return render_template('index.html', products=[])

# Web Route: Create order (POST)
# For web purchases, creates order and invoice with rate limiting
@app.route('/create-order', methods=['POST'])
@limiter.limit("10 per minute")
def create_order():
    try:
        data = request.get_json()
        if not data or 'product_id' not in data:
            return jsonify({'error': 'Missing product_id'}), 400
        product_id = data['product_id']
        order_id = generate_order_id('W')
        conn = db_pool.getconn()
        cur = conn.cursor()
        cur.execute("SELECT price FROM products WHERE id = %s", (product_id,))
        product = cur.fetchone()
        if not product:
            cur.close()
            db_pool.putconn(conn)
            return jsonify({'error': 'Product not found'}), 404
        price = product[0]
        cur.execute("INSERT INTO orders (product_id, total_amount, order_id, payment_id) VALUES (%s, %s, %s, %s)",
                    (product_id, price, order_id, ''))
        conn.commit()
        cur.close()
        db_pool.putconn(conn)
        invoice = create_invoice(price, order_id)
        if not invoice or 'invoice_url' not in invoice:
            return jsonify({'error': 'Failed to create invoice'}), 500
        payment_url = invoice.get('invoice_url')
        return jsonify({'order_id': order_id, 'payment_url': payment_url})
    except Exception as e:
        logger.error(f"Error in create_order: {e}")
        return jsonify({'error': 'Internal server error'}), 500

# Web Route: Order status (GET)
# Polled by JS for status updates
@app.route('/order-status/<order_id>')
def order_status(order_id):
    try:
        conn = db_pool.getconn()
        cur = conn.cursor()
        cur.execute("SELECT order_status FROM orders WHERE order_id = %s", (order_id,))
        status = cur.fetchone()
        cur.close()
        db_pool.putconn(conn)
        if status:
            return jsonify({'status': status[0]})
        return jsonify({'status': 'not found'}), 404
    except Exception as e:
        logger.error(f"Error in order_status: {e}")
        return jsonify({'status': 'error'}), 500

@app.route('/cancel-order/<order_id>', methods=['POST'])
def cancel_order(order_id):
    try:
        conn = db_pool.getconn()
        cur = conn.cursor()
        cur.execute("UPDATE orders SET order_status = 'cancelled' WHERE order_id = %s AND order_status = 'pending'", (order_id,))
        if cur.rowcount > 0:
            conn.commit()
            cur.close()
            db_pool.putconn(conn)
            return jsonify({'success': True})
        else:
            cur.close()
            db_pool.putconn(conn)
            return jsonify({'error': 'Order not found or not cancellable'}), 404
    except Exception as e:
        logger.error(f"Error in cancel_order: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/order-history')
def order_history():
    # For web, show orders from localStorage or all if admin
    # Simple: show all orders (for demo)
    try:
        conn = db_pool.getconn()
        cur = conn.cursor()
        cur.execute("SELECT order_id, order_status, created_at FROM orders ORDER BY created_at DESC LIMIT 50")
        orders = cur.fetchall()
        cur.close()
        db_pool.putconn(conn)
        return render_template('order_history.html', orders=orders)
    except Exception as e:
        logger.error(f"Error loading order history: {e}")
        return render_template('order_history.html', orders=[])

# Web Route: Submit delivery (POST)
# For web, forwards delivery details to admin
@app.route('/submit-delivery', methods=['POST'])
def submit_delivery():
    try:
        data = request.get_json()
        order_id = data['order_id']
        method = data['method']
        details = data['details']
        bot = telegram.Bot(token=BOT_TOKEN)
        message = f"New Order: {order_id}\nDelivery: {method} ({details})"
        bot.send_message(chat_id=ADMIN_CHAT_ID, text=message)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error in submit_delivery: {e}")
        return jsonify({'error': 'Internal server error'}), 500

# Admin Panel Routes
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin123')  # Simple password for demo

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == ADMIN_PASSWORD:
            return redirect(url_for('admin_panel'))
        else:
            flash('Invalid password')
    return render_template('admin_login.html')

@app.route('/admin/panel')
def admin_panel():
    try:
        conn = db_pool.getconn()
        cur = conn.cursor()
        cur.execute("SELECT id, name, price, description, image_url FROM products")
        products = cur.fetchall()
        cur.close()
        db_pool.putconn(conn)
        return render_template('admin_panel.html', products=products)
    except Exception as e:
        logger.error(f"Error loading admin panel: {e}")
        flash("Error loading panel")
        return render_template('admin_panel.html', products=[])

@app.route('/admin/add', methods=['GET', 'POST'])
def add_product():
    form = ProductForm()
    if form.validate_on_submit():
        try:
            conn = db_pool.getconn()
            cur = conn.cursor()
            cur.execute("INSERT INTO products (name, price, description, image_url) VALUES (%s, %s, %s, %s)",
                        (form.name.data, form.price.data, form.description.data, form.image_url.data))
            conn.commit()
            cur.close()
            db_pool.putconn(conn)
            flash('Product added successfully')
            return redirect(url_for('admin_panel'))
        except Exception as e:
            logger.error(f"Error adding product: {e}")
            flash('Error adding product')
    return render_template('add_product.html', form=form)

@app.route('/admin/delete/<int:product_id>')
def delete_product(product_id):
    try:
        conn = db_pool.getconn()
        cur = conn.cursor()
        cur.execute("DELETE FROM products WHERE id = %s", (product_id,))
        conn.commit()
        cur.close()
        db_pool.putconn(conn)
        flash('Product deleted')
    except Exception as e:
        logger.error(f"Error deleting product: {e}")
        flash('Error deleting product')
    return redirect(url_for('admin_panel'))

# Web Route: NOWPayments IPN (POST)
# Validates signature, updates order, notifies user/bot
@app.route('/ipn', methods=['POST'])
def ipn():
    if not validate_ipn(request):
        logger.warning("Invalid IPN signature")
        return 'Invalid signature', 400
    data = request.get_json()
    if data.get('payment_status') == 'finished':
        order_id = data['order_id']
        conn = db_pool.getconn()
        cur = conn.cursor()
        cur.execute("UPDATE orders SET order_status = 'paid', paid_at = CURRENT_TIMESTAMP WHERE order_id = %s", (order_id,))
        cur.execute("SELECT user_identifier FROM orders WHERE order_id = %s", (order_id,))
        user_id = cur.fetchone()
        conn.commit()
        cur.close()
        db_pool.putconn(conn)
        if user_id:
            bot = telegram.Bot(token=BOT_TOKEN)
            keyboard = [[telegram.InlineKeyboardButton("Telegram", callback_data=f'delivery_telegram_{order_id}'), telegram.InlineKeyboardButton("Email", callback_data=f'delivery_email_{order_id}')]]
            reply_markup = telegram.InlineKeyboardMarkup(keyboard)
            bot.send_message(chat_id=user_id[0], text="Payment received! Choose delivery method:", reply_markup=reply_markup)
        logger.info(f"Order {order_id} marked as paid")
    return 'OK'

# Web Route: Telegram webhook (POST)
# Processes bot updates
@app.route('/bot-webhook', methods=['POST'])
def bot_webhook():
    update = telegram.Update.de_json(request.get_json(), updater.bot)
    dispatcher.process_update(update)
    return 'OK'

# Main entry point
if __name__ == '__main__':
    # Set Telegram webhook on startup
    requests.get(f'https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={WEBHOOK_URL}')
    logger.info("Webhook set, starting app")
    app.run()