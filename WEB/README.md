# Vault Shop

Vault Shop is an anonymous dual-channel e-commerce platform for selling digital/crypto-related products. It features a Telegram bot for interactive purchases and a no-login web viewer for browsing products, creating orders, and checking status. Both channels share a single PostgreSQL database and use NOWPayments for cryptocurrency invoices.

## Features

- **Anonymous Access**: Bot uses Telegram user ID; web uses generated order codes stored in localStorage.
- **Dual Channels**: Telegram bot and web interface.
- **NOWPayments Integration**: Secure crypto invoice creation and IPN validation.
- **Manual Delivery**: Admin receives delivery details via Telegram after payment.
- **Responsive Web UI**: Dark theme with Tailwind CSS and neon green accents.
- **Client-side Confetti**: Celebration on successful payment.
- **Rate Limiting**: Prevents abuse with Flask-Limiter (10 orders/min per IP).
- **Caching**: Product list cached for 5 minutes to reduce DB load.
- **Product Images**: Support for image URLs in products.
- **Admin Panel**: Password-protected panel to add/delete products.
- **Order History**: View recent orders.
- **Order Cancellation**: Cancel pending orders before payment.
- **Multi-Coin Support**: BTC, ETH, LTC, USDT, BCH in bot.
- **CSRF Protection**: Forms secured with Flask-WTF.
- **Error Handling**: Comprehensive try-except blocks with logging.

## Local Setup

1. **Clone or Download**: Place `app.py`, `templates/index.html`, `requirements.txt`, and `README.md` in a flat directory.

2. **Install Dependencies**:
   ```
   pip install -r requirements.txt
   ```

3. **Database Setup**:
   - Create a PostgreSQL database.
   - Run the following SQL to create tables:
     ```sql
     CREATE TABLE products (
         id SERIAL PRIMARY KEY,
         name TEXT,
         price DECIMAL(10,2),
         currency TEXT DEFAULT 'USD',
         description TEXT,
         image_url TEXT,
         created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
     );

     CREATE TABLE orders (
         id SERIAL PRIMARY KEY,
         product_id INTEGER REFERENCES products(id),
         quantity INTEGER DEFAULT 1,
         total_amount DECIMAL(10,2),
         user_identifier TEXT,
         order_status TEXT DEFAULT 'pending',
         payment_id TEXT,
         order_id TEXT,
         created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
         paid_at TIMESTAMP,
         delivered_at TIMESTAMP
     );
     ```
   - Insert sample products:
     ```sql
     INSERT INTO products (name, price, description, image_url) VALUES
     ('CC Fullz', 50.00, 'High-quality credit card fullz', 'https://example.com/cc.jpg'),
     ('Bank Logs', 30.00, 'Access to bank accounts', 'https://example.com/bank.jpg'),
     ('Gift Cards', 20.00, 'Prepaid gift cards', 'https://example.com/gift.jpg'),
     ('Dumps', 40.00, 'Track 1/2 dumps', 'https://example.com/dumps.jpg'),
     ('Fullz + DL', 70.00, 'Fullz with driver license', 'https://example.com/dl.jpg');
     ```

4. **Environment Variables**:
   Set the following in your environment or a `.env` file:
   - `DATABASE_URL`: PostgreSQL connection string (e.g., `postgres://user:pass@localhost/db`)
   - `BOT_TOKEN`: Telegram bot token from @BotFather
   - `NOWPAYMENTS_API_KEY`: API key from NOWPayments
   - `NOWPAYMENTS_IPN_SECRET`: IPN secret from NOWPayments
   - `WEBHOOK_URL`: Full URL for bot webhook (e.g., `https://your-app.onrender.com/bot-webhook`)
   - `ADMIN_CHAT_ID`: Telegram chat ID for admin notifications (numeric)
   - `SECRET_KEY`: Secret key for CSRF and sessions (e.g., `your-secret-key`)
   - `ADMIN_PASSWORD`: Password for admin panel (e.g., `admin123`)

5. **Run Locally**:
   ```
   python app.py
   ```
   The app will set the Telegram webhook on startup and run on port 5000.

## Deployment to Render.com

1. **Create Render Account**: Sign up at render.com.

2. **New Web Service**:
   - Connect your GitHub repo.
   - Set build command: `pip install -r requirements.txt`
   - Set start command: `python app.py`
   - Add environment variables as above.
   - Attach a free PostgreSQL database and note the `DATABASE_URL`.

3. **Deploy**: Push to GitHub, and Render will build and deploy.

4. **Post-Deploy**:
   - Update `WEBHOOK_URL` with your Render app URL.
   - Ensure NOWPayments IPN callback is set to `https://your-app.onrender.com/ipn`.

## Usage

- **Web Viewer**: Visit the root URL to browse products. Click "Buy" to create an order, pay via NOWPayments, and submit delivery details after payment.
- **Telegram Bot**: Start with `/start`, browse products, select coin, pay, and provide delivery info.
- **Admin**: Receives notifications in the specified Telegram chat for new orders and deliveries.

## Security Notes

- IPN signatures are validated using HMAC-SHA512.
- No sensitive data stored; anonymous identifiers used.
- Use HTTPS in production.

## Troubleshooting

- Ensure all env vars are set.
- Check PostgreSQL connection.
- Verify Telegram bot token and webhook URL.
- Monitor logs for errors.
