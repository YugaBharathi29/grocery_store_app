from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_mail import Mail, Message
from models import db, User, Product, Category, Order, OrderItem, Coupon, Wishlist, Review
from werkzeug.utils import secure_filename
from itsdangerous import URLSafeTimedSerializer
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta
import logging
from sqlalchemy import or_, and_

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration using environment variables
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-fallback-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///grocery_store.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/images/products'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Email Configuration
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'True').lower() == 'true'
app.config['MAIL_USERNAME'] = os.getenv('EMAIL_USER')
app.config['MAIL_PASSWORD'] = os.getenv('EMAIL_PASS')
app.config['MAIL_DEFAULT_SENDER'] = ('Grocery Store', app.config['MAIL_USERNAME'])

# Pagination settings
app.config['PRODUCTS_PER_PAGE'] = 12
app.config['ORDERS_PER_PAGE'] = 10

# Create upload folder if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize extensions
db.init_app(app)
mail = Mail(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please login to access this page.'
login_manager.login_message_category = 'info'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Utility Functions
def send_email(subject, recipients, body, html_body=None):
    """Send email with error handling"""
    try:
        msg = Message(subject, recipients=recipients)
        msg.body = body
        if html_body:
            msg.html = html_body
        mail.send(msg)
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False

def send_reset_email(user):
    """Send password reset email"""
    token = user.get_reset_token()
    subject = 'Password Reset Request - Grocery Store'
    body = f'''To reset your password, visit the following link:
{url_for('reset_password', token=token, _external=True)}

If you did not make this request, simply ignore this email and no changes will be made.

This link will expire in 30 minutes.

Best regards,
Grocery Store Team
'''
    html_body = render_template('email/reset_password.html', user=user, token=token)
    return send_email(subject, [user.email], body, html_body)

def send_verification_email(user):
    """Send email verification email"""
    token = user.get_verification_token()
    subject = 'Verify Your Email - Grocery Store'
    body = f'''Welcome to Grocery Store!

Please verify your email address by clicking the following link:
{url_for('verify_email', token=token, _external=True)}

If you did not create this account, please ignore this email.

Best regards,
Grocery Store Team
'''
    html_body = render_template('email/verify_email.html', user=user, token=token)
    return send_email(subject, [user.email], body, html_body)

def send_order_confirmation_email(order):
    """Send order confirmation email"""
    subject = f'Order Confirmation - #{order.id}'
    body = f'''Thank you for your order!

Order Details:
Order ID: #{order.id}
Total Amount: ₹{order.total_amount:.2f}
Estimated Delivery: {order.estimated_delivery.strftime('%d %B, %Y at %I:%M %p') if order.estimated_delivery else 'TBD'}

We'll send you updates about your order status.

Best regards,
Grocery Store Team
'''
    html_body = render_template('email/order_confirmation.html', order=order)
    return send_email(subject, [order.customer.email], body, html_body)

def get_cart_total():
    """Calculate total cart value"""
    if 'cart' not in session:
        return 0
    
    total = 0
    for product_id, quantity in session['cart'].items():
        product = Product.query.get(int(product_id))
        if product and product.is_active:
            total += product.price * quantity
    return total

def clean_cart():
    """Remove inactive products from cart"""
    if 'cart' not in session:
        return
    
    cart = session['cart'].copy()
    for product_id in cart:
        product = Product.query.get(int(product_id))
        if not product or not product.is_active:
            session['cart'].pop(product_id, None)
            session.modified = True

# Template Context Processors
@app.context_processor
def inject_cart_count():
    """Inject cart count into all templates"""
    if 'cart' not in session:
        return {'cart_count': 0}
    return {'cart_count': sum(session['cart'].values())}

@app.context_processor
def inject_categories():
    """Inject categories into all templates"""
    categories = Category.query.filter_by(is_active=True).all()
    return {'nav_categories': categories}

# Customer Routes
@app.route('/')
def index():
    # Clean cart of inactive products
    clean_cart()
    
    categories = Category.query.filter_by(is_active=True).limit(6).all()
    featured_products = Product.query.filter_by(is_active=True, is_featured=True).limit(8).all()
    
    # If no featured products, get recent products
    if not featured_products:
        featured_products = Product.query.filter_by(is_active=True).order_by(
            Product.created_at.desc()
        ).limit(8).all()
    
    # Get products on sale
    sale_products = Product.query.filter(
        and_(Product.is_active == True, Product.original_price.isnot(None))
    ).limit(4).all()
    
    return render_template('index.html', 
                         categories=categories, 
                         products=featured_products,
                         sale_products=sale_products)

@app.route('/search')
def search():
    query = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    
    if not query:
        return redirect(url_for('products'))
    
    # Search in product names and descriptions
    search_results = Product.query.filter(
        and_(
            Product.is_active == True,
            or_(
                Product.name.ilike(f'%{query}%'),
                Product.description.ilike(f'%{query}%')
            )
        )
    ).paginate(
        page=page, 
        per_page=app.config['PRODUCTS_PER_PAGE'], 
        error_out=False
    )
    
    categories = Category.query.filter_by(is_active=True).all()
    
    return render_template('search_results.html',
                         products=search_results.items,
                         pagination=search_results,
                         query=query,
                         categories=categories)

@app.route('/products')
@app.route('/products/<int:category_id>')
def products(category_id=None):
    page = request.args.get('page', 1, type=int)
    sort_by = request.args.get('sort', 'name')
    min_price = request.args.get('min_price', type=float)
    max_price = request.args.get('max_price', type=float)
    
    # Base query
    products_query = Product.query.filter_by(is_active=True)
    
    # Filter by category
    if category_id:
        products_query = products_query.filter_by(category_id=category_id)
        category = Category.query.get(category_id)
        category_name = category.name if category else 'All Products'
    else:
        category_name = 'All Products'
    
    # Apply price filters
    if min_price is not None:
        products_query = products_query.filter(Product.price >= min_price)
    if max_price is not None:
        products_query = products_query.filter(Product.price <= max_price)
    
    # Apply sorting
    if sort_by == 'price_low':
        products_query = products_query.order_by(Product.price.asc())
    elif sort_by == 'price_high':
        products_query = products_query.order_by(Product.price.desc())
    elif sort_by == 'newest':
        products_query = products_query.order_by(Product.created_at.desc())
    elif sort_by == 'rating':
        # Sort by average rating (requires review system)
        products_query = products_query.order_by(Product.name.asc())  # Placeholder
    else:
        products_query = products_query.order_by(Product.name.asc())
    
    products_pagination = products_query.paginate(
        page=page, 
        per_page=app.config['PRODUCTS_PER_PAGE'], 
        error_out=False
    )
    
    categories = Category.query.filter_by(is_active=True).all()
    
    return render_template('products.html', 
                         products=products_pagination.items,
                         pagination=products_pagination,
                         categories=categories, 
                         current_category=category_name,
                         current_sort=sort_by,
                         min_price=min_price,
                         max_price=max_price,
                         category_id=category_id)

@app.route('/product/<int:product_id>')
def product_detail(product_id):
    product = Product.query.get_or_404(product_id)
    
    if not product.is_active:
        flash('This product is currently not available', 'warning')
        return redirect(url_for('products'))
    
    # Get related products
    related_products = Product.query.filter_by(
        category_id=product.category_id, 
        is_active=True
    ).filter(Product.id != product_id).limit(4).all()
    
    # Check if user has this in wishlist
    in_wishlist = False
    if current_user.is_authenticated:
        in_wishlist = Wishlist.query.filter_by(
            user_id=current_user.id, 
            product_id=product_id
        ).first() is not None
    
    # Get product reviews
    reviews = Review.query.filter_by(
        product_id=product_id, 
        is_approved=True
    ).order_by(Review.created_at.desc()).limit(5).all()
    
    return render_template('product_detail.html', 
                         product=product, 
                         related_products=related_products,
                         in_wishlist=in_wishlist,
                         reviews=reviews)

@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    product_id = request.json.get('product_id')
    quantity = request.json.get('quantity', 1)
    
    if not isinstance(quantity, int) or quantity <= 0:
        return jsonify({'success': False, 'message': 'Invalid quantity'})
    
    # Validate product and stock
    product = Product.query.get(product_id)
    if not product or not product.is_active:
        return jsonify({'success': False, 'message': 'Product not found or inactive'})
    
    if product.is_out_of_stock():
        return jsonify({'success': False, 'message': 'Product is out of stock'})
    
    if product.stock_quantity < quantity:
        return jsonify({'success': False, 'message': f'Only {product.stock_quantity} items available'})
    
    if 'cart' not in session:
        session['cart'] = {}
    
    cart = session['cart']
    current_qty = cart.get(str(product_id), 0)
    new_qty = current_qty + quantity
    
    # Check if total quantity exceeds stock
    if new_qty > product.stock_quantity:
        return jsonify({'success': False, 'message': f'Cannot add {quantity} items. Only {product.stock_quantity - current_qty} more available'})
    
    cart[str(product_id)] = new_qty
    session['cart'] = cart
    session.modified = True
    
    return jsonify({
        'success': True, 
        'cart_count': sum(cart.values()),
        'message': f'Added {quantity} {product.name} to cart'
    })

@app.route('/api/cart/count')
def get_cart_count():
    if 'cart' not in session:
        return jsonify({'count': 0})
    return jsonify({'count': sum(session['cart'].values())})

@app.route('/cart')
def cart():
    if 'cart' not in session:
        session['cart'] = {}
    
    cart_items = []
    total = 0
    
    # Clean cart and build cart items
    cart_copy = session['cart'].copy()
    for product_id, quantity in cart_copy.items():
        product = Product.query.get(int(product_id))
        if product and product.is_active:
            # Check if quantity exceeds current stock
            if quantity > product.stock_quantity:
                if product.stock_quantity > 0:
                    session['cart'][product_id] = product.stock_quantity
                    quantity = product.stock_quantity
                    flash(f'Quantity for {product.name} was reduced to available stock', 'warning')
                else:
                    # Remove out of stock items
                    session['cart'].pop(product_id, None)
                    flash(f'{product.name} was removed from cart (out of stock)', 'warning')
                    continue
                session.modified = True
            
            subtotal = product.price * quantity
            cart_items.append({
                'product': product,
                'quantity': quantity,
                'subtotal': subtotal
            })
            total += subtotal
        else:
            # Remove inactive products
            session['cart'].pop(product_id, None)
            session.modified = True
    
    # Calculate additional charges
    delivery_fee = 5.0
    tax_amount = total * 0.05  # 5% GST
    grand_total = total + delivery_fee + tax_amount
    
    return render_template('cart.html', 
                         cart_items=cart_items, 
                         subtotal=total,
                         delivery_fee=delivery_fee,
                         tax_amount=tax_amount,
                         total=grand_total)

@app.route('/update_cart', methods=['POST'])
def update_cart():
    product_id = str(request.json.get('product_id'))
    quantity = int(request.json.get('quantity'))
    
    if 'cart' in session:
        if quantity > 0:
            # Check stock availability
            product = Product.query.get(int(product_id))
            if product and product.is_active and quantity <= product.stock_quantity:
                session['cart'][product_id] = quantity
                session.modified = True
                return jsonify({'success': True, 'message': 'Cart updated'})
            else:
                available = product.stock_quantity if product else 0
                return jsonify({'success': False, 'message': f'Only {available} items available'})
        else:
            session['cart'].pop(product_id, None)
            session.modified = True
            return jsonify({'success': True, 'message': 'Item removed from cart'})
    
    return jsonify({'success': False, 'message': 'Failed to update cart'})

@app.route('/remove_from_cart', methods=['POST'])
def remove_from_cart():
    product_id = str(request.json.get('product_id'))
    
    if 'cart' in session:
        removed_item = session['cart'].pop(product_id, None)
        session.modified = True
        
        if removed_item:
            return jsonify({'success': True, 'message': 'Item removed from cart'})
    
    return jsonify({'success': False, 'message': 'Item not found in cart'})

@app.route('/clear_cart', methods=['POST'])
def clear_cart():
    session.pop('cart', None)
    return jsonify({'success': True, 'message': 'Cart cleared'})

@app.route('/checkout')
@login_required
def checkout():
    if 'cart' not in session or not session['cart']:
        flash('Your cart is empty', 'warning')
        return redirect(url_for('cart'))
    
    # Clean cart and validate items
    clean_cart()
    
    cart_items = []
    total = 0
    
    for product_id, quantity in session['cart'].items():
        product = Product.query.get(int(product_id))
        if product and product.is_active:
            if quantity > product.stock_quantity:
                flash(f'Insufficient stock for {product.name}. Please update your cart.', 'error')
                return redirect(url_for('cart'))
            
            subtotal = product.price * quantity
            cart_items.append({
                'product': product,
                'quantity': quantity,
                'subtotal': subtotal
            })
            total += subtotal
    
    if not cart_items:
        flash('Your cart is empty or contains invalid items', 'warning')
        return redirect(url_for('cart'))
    
    # Calculate charges
    delivery_fee = 5.0
    tax_amount = total * 0.05
    grand_total = total + delivery_fee + tax_amount
    
    return render_template('checkout.html', 
                         cart_items=cart_items, 
                         subtotal=total,
                         delivery_fee=delivery_fee,
                         tax_amount=tax_amount,
                         total=grand_total)

@app.route('/place_order', methods=['POST'])
@login_required
def place_order():
    if 'cart' not in session or not session['cart']:
        return jsonify({'success': False, 'message': 'Cart is empty'})
    
    data = request.get_json()
    delivery_address = data.get('address', '').strip()
    phone_number = data.get('phone', '').strip()
    instructions = data.get('instructions', '').strip()
    delivery_type = data.get('delivery_type', 'standard')
    payment_method = data.get('payment_method', 'cod')
    
    # Validation
    if not delivery_address:
        return jsonify({'success': False, 'message': 'Delivery address is required'})
    
    if not phone_number:
        return jsonify({'success': False, 'message': 'Phone number is required'})
    
    # Validate phone number format
    phone_clean = ''.join(filter(str.isdigit, phone_number))
    if len(phone_clean) != 10 or not phone_clean[0] in '6789':
        return jsonify({'success': False, 'message': 'Please enter a valid Indian mobile number'})
    
    # Validate stock availability before creating order
    for product_id, quantity in session['cart'].items():
        product = Product.query.get(int(product_id))
        if not product or not product.is_active or product.stock_quantity < quantity:
            product_name = product.name if product else 'Unknown product'
            return jsonify({'success': False, 'message': f'Insufficient stock for {product_name}'})
    
    try:
        # Create order
        order = Order(
            user_id=current_user.id,
            delivery_address=delivery_address,
            phone_number=phone_clean,
            special_instructions=instructions,
            delivery_type=delivery_type,
            payment_method=payment_method
        )
        
        # Create order items and update stock
        for product_id, quantity in session['cart'].items():
            product = Product.query.get(int(product_id))
            if product and product.is_active:
                order_item = OrderItem(
                    product_id=product.id,
                    quantity=quantity,
                    price=product.price,
                    original_price=product.original_price if product.is_on_sale() else None
                )
                order.items.append(order_item)
                
                # Update stock
                product.stock_quantity -= quantity
        
        # Calculate totals
        order.calculate_totals()
        
        # Set estimated delivery
        if delivery_type == 'express':
            order.estimated_delivery = datetime.utcnow() + timedelta(hours=1)
        else:
            order.estimated_delivery = datetime.utcnow() + timedelta(hours=3)
        
        db.session.add(order)
        db.session.commit()
        
        # Send confirmation email
        send_order_confirmation_email(order)
        
        # Clear cart
        session.pop('cart', None)
        
        logger.info(f"Order {order.id} placed successfully by user {current_user.id}")
        
        return jsonify({'success': True, 'order_id': order.id})
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error placing order: {e}")
        return jsonify({'success': False, 'message': 'An error occurred while placing your order. Please try again.'})

@app.route('/orders')
@login_required
def my_orders():
    page = request.args.get('page', 1, type=int)
    status_filter = request.args.get('status', '')
    
    orders_query = Order.query.filter_by(user_id=current_user.id)
    
    if status_filter:
        orders_query = orders_query.filter_by(status=status_filter)
    
    orders_pagination = orders_query.order_by(Order.order_date.desc()).paginate(
        page=page, 
        per_page=app.config['ORDERS_PER_PAGE'], 
        error_out=False
    )
    
    return render_template('orders.html', 
                         orders=orders_pagination.items,
                         pagination=orders_pagination,
                         current_status=status_filter)

@app.route('/order/<int:order_id>')
@login_required
def order_detail(order_id):
    order = Order.query.get_or_404(order_id)
    
    # Check if user owns this order
    if order.user_id != current_user.id:
        flash('Access denied', 'error')
        return redirect(url_for('my_orders'))
    
    return render_template('order_detail.html', order=order)

@app.route('/cancel_order', methods=['POST'])
@login_required
def cancel_order():
    order_id = request.json.get('order_id')
    order = Order.query.get_or_404(order_id)
    
    # Check if user owns this order
    if order.user_id != current_user.id:
        return jsonify({'success': False, 'message': 'Access denied'})
    
    # Only allow canceling pending or confirmed orders
    if not order.can_be_cancelled():
        return jsonify({'success': False, 'message': 'Cannot cancel this order'})
    
    try:
        # Restore stock
        for item in order.items:
            item.product.stock_quantity += item.quantity
        
        order.status = 'cancelled'
        db.session.commit()
        
        logger.info(f"Order {order.id} cancelled by user {current_user.id}")
        
        return jsonify({'success': True, 'message': 'Order cancelled successfully'})
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error cancelling order {order_id}: {e}")
        return jsonify({'success': False, 'message': 'An error occurred while cancelling the order'})

@app.route('/reorder', methods=['POST'])
@login_required
def reorder():
    order_id = request.json.get('order_id')
    order = Order.query.get_or_404(order_id)
    
    # Check if user owns this order
    if order.user_id != current_user.id:
        return jsonify({'success': False, 'message': 'Access denied'})
    
    if 'cart' not in session:
        session['cart'] = {}
    
    # Add items to cart
    cart = session['cart']
    added_items = 0
    unavailable_items = 0
    
    for item in order.items:
        if item.product.is_active and item.product.stock_quantity >= item.quantity:
            product_id = str(item.product.id)
            cart[product_id] = cart.get(product_id, 0) + item.quantity
            added_items += 1
        else:
            unavailable_items += 1
    
    session['cart'] = cart
    session.modified = True
    
    if added_items > 0:
        message = f'{added_items} items added to cart'
        if unavailable_items > 0:
            message += f' ({unavailable_items} items were unavailable)'
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'message': 'No items could be added (all items are out of stock or inactive)'})

# Wishlist Routes
@app.route('/wishlist')
@login_required
def wishlist():
    wishlist_items = Wishlist.query.filter_by(user_id=current_user.id).all()
    return render_template('wishlist.html', wishlist_items=wishlist_items)

@app.route('/add_to_wishlist', methods=['POST'])
@login_required
def add_to_wishlist():
    product_id = request.json.get('product_id')
    
    # Check if already in wishlist
    existing = Wishlist.query.filter_by(
        user_id=current_user.id, 
        product_id=product_id
    ).first()
    
    if existing:
        return jsonify({'success': False, 'message': 'Item already in wishlist'})
    
    # Add to wishlist
    wishlist_item = Wishlist(user_id=current_user.id, product_id=product_id)
    db.session.add(wishlist_item)
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'Added to wishlist'})

@app.route('/remove_from_wishlist', methods=['POST'])
@login_required
def remove_from_wishlist():
    product_id = request.json.get('product_id')
    
    wishlist_item = Wishlist.query.filter_by(
        user_id=current_user.id, 
        product_id=product_id
    ).first()
    
    if wishlist_item:
        db.session.delete(wishlist_item)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Removed from wishlist'})
    
    return jsonify({'success': False, 'message': 'Item not found in wishlist'})

# Authentication Routes
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        username = request.form['username'].strip()
        email = request.form['email'].strip().lower()
        password = request.form['password']
        phone = request.form.get('phone', '').strip()
        address = request.form['address'].strip()
        pincode = request.form.get('pincode', '').strip()
        
        # Validation
        errors = []
        
        if not username or len(username) < 3:
            errors.append('Username must be at least 3 characters long')
        
        if not email or '@' not in email:
            errors.append('Please enter a valid email address')
        
        if not password or len(password) < 6:
            errors.append('Password must be at least 6 characters long')
        
        if not address:
            errors.append('Address is required')
        
        if User.query.filter_by(username=username).first():
            errors.append('Username already exists')
        
        if User.query.filter_by(email=email).first():
            errors.append('Email already exists')
        
        # Clean and validate phone number
        if phone:
            phone_clean = ''.join(filter(str.isdigit, phone))
            if len(phone_clean) != 10 or not phone_clean[0] in '6789':
                errors.append('Please enter a valid Indian mobile number')
            else:
                phone = phone_clean
        
        # Validate PIN code
        if pincode and (not pincode.isdigit() or len(pincode) != 6):
            errors.append('PIN code must be 6 digits')
        
        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('register.html')
        
        try:
            user = User(
                username=username, 
                email=email, 
                phone=phone or None, 
                address=address,
                pincode=pincode or None
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            
            # Send verification email
            if send_verification_email(user):
                flash('Registration successful! Please check your email to verify your account.', 'success')
            else:
                flash('Registration successful! Please login.', 'success')
            
            logger.info(f"New user registered: {username}")
            return redirect(url_for('login'))
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error during registration: {e}")
            flash('An error occurred during registration. Please try again.', 'error')
    
    return render_template('register.html')

@app.route('/verify_email/<token>')
def verify_email(token):
    if current_user.is_authenticated and current_user.email_verified:
        return redirect(url_for('index'))
    
    user = User.verify_email_token(token)
    if not user:
        flash('That is an invalid or expired verification link', 'warning')
        return redirect(url_for('index'))
    
    if user.email_verified:
        flash('Email already verified', 'info')
        return redirect(url_for('login'))
    
    user.email_verified = True
    db.session.commit()
    
    flash('Your email has been verified! You can now login.', 'success')
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        remember_me = request.form.get('remember_me')
        
        if not username or not password:
            flash('Please enter both username and password', 'error')
            return render_template('login.html')
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            if not user.is_active:
                flash('Your account has been deactivated. Please contact support.', 'error')
                return render_template('login.html')
            
            login_user(user, remember=bool(remember_me))
            user.update_last_login()
            
            next_page = request.args.get('next')
            if next_page and next_page.startswith('/'):
                redirect_url = next_page
            else:
                redirect_url = url_for('index')
            
            flash(f'Welcome back, {user.username}!', 'success')
            return redirect(redirect_url)
        else:
            flash('Invalid username or password', 'error')
    
    return render_template('login.html')

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        # ✅ FIXED: Use .get() method instead of direct key access
        email = request.form.get('email', '').strip().lower()
        
        if not email:
            flash('Please enter your email address', 'error')
            return render_template('forgot_password.html')
        
        # Basic email validation
        if '@' not in email or '.' not in email:
            flash('Please enter a valid email address', 'error')
            return render_template('forgot_password.html')
        
        user = User.query.filter_by(email=email).first()
        
        if user and user.is_active:
            try:
                if send_reset_email(user):
                    flash('An email has been sent with instructions to reset your password.', 'info')
                else:
                    flash('Failed to send email. Please try again later.', 'error')
            except Exception as e:
                logger.error(f"Error sending reset email: {e}")
                flash('Failed to send email. Please try again later.', 'error')
        else:
            # Don't reveal whether user exists for security
            flash('An email has been sent with instructions to reset your password.', 'info')
        
        return redirect(url_for('login'))
    
    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    user = User.verify_reset_token(token)
    if not user:
        flash('That is an invalid or expired token', 'warning')
        return redirect(url_for('forgot_password'))
    
    if request.method == 'POST':
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        
        if not password or len(password) < 6:
            flash('Password must be at least 6 characters long', 'error')
            return render_template('reset_password.html')
        
        if password != confirm_password:
            flash('Passwords do not match', 'error')
            return render_template('reset_password.html')
        
        user.set_password(password)
        db.session.commit()
        
        flash('Your password has been updated! You can now log in.', 'success')
        logger.info(f"Password reset for user: {user.username}")
        return redirect(url_for('login'))
    
    return render_template('reset_password.html')

@app.route('/logout')
@login_required
def logout():
    username = current_user.username
    logout_user()
    flash(f'Goodbye {username}! You have been logged out successfully.', 'info')
    return redirect(url_for('index'))

# Profile Routes
@app.route('/profile')
@login_required
def profile():
    return render_template('profile.html')

@app.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    try:
        current_user.phone = request.form.get('phone', '').strip() or None
        current_user.address = request.form.get('address', '').strip()
        current_user.pincode = request.form.get('pincode', '').strip() or None
        
        db.session.commit()
        flash('Profile updated successfully', 'success')
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating profile for user {current_user.id}: {e}")
        flash('An error occurred while updating your profile', 'error')
    
    return redirect(url_for('profile'))

# Admin Routes
@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('index'))
    
    # Calculate metrics
    total_products = Product.query.count()
    active_products = Product.query.filter_by(is_active=True).count()
    total_orders = Order.query.count()
    pending_orders = Order.query.filter_by(status='pending').count()
    confirmed_orders = Order.query.filter_by(status='confirmed').count()
    delivered_orders = Order.query.filter_by(status='delivered').count()
    total_users = User.query.filter_by(is_admin=False).count()
    active_users = User.query.filter_by(is_admin=False, is_active=True).count()
    low_stock_products = Product.query.filter(Product.stock_quantity <= Product.min_stock).count()
    
    # Calculate revenue metrics
    today = datetime.utcnow().date()
    today_orders = Order.query.filter(
        Order.order_date >= datetime.combine(today, datetime.min.time()),
        Order.status.in_(['confirmed', 'delivered'])
    ).all()
    today_sales = sum(order.total_amount for order in today_orders)
    
    # This month's sales
    first_of_month = today.replace(day=1)
    month_orders = Order.query.filter(
        Order.order_date >= datetime.combine(first_of_month, datetime.min.time()),
        Order.status.in_(['confirmed', 'delivered'])
    ).all()
    month_sales = sum(order.total_amount for order in month_orders)
    
    recent_orders = Order.query.order_by(Order.order_date.desc()).limit(5).all()
    
    return render_template('admin/dashboard.html', 
                         total_products=total_products,
                         active_products=active_products,
                         total_orders=total_orders,
                         pending_orders=pending_orders,
                         confirmed_orders=confirmed_orders,
                         delivered_orders=delivered_orders,
                         total_users=total_users,
                         active_users=active_users,
                         low_stock_products=low_stock_products,
                         today_sales=today_sales,
                         month_sales=month_sales,
                         recent_orders=recent_orders)

@app.route('/admin/inventory')
@login_required
def admin_inventory():
    if not current_user.is_admin:
        flash('Access denied', 'error')
        return redirect(url_for('index'))
    
    page = request.args.get('page', 1, type=int)
    filter_type = request.args.get('filter', '')
    search_query = request.args.get('q', '').strip()
    
    products_query = Product.query
    
    # Apply search filter
    if search_query:
        products_query = products_query.filter(
            or_(
                Product.name.ilike(f'%{search_query}%'),
                Product.description.ilike(f'%{search_query}%')
            )
        )
    
    # Apply status filters
    if filter_type == 'low_stock':
        products_query = products_query.filter(Product.stock_quantity <= Product.min_stock)
    elif filter_type == 'out_of_stock':
        products_query = products_query.filter(Product.stock_quantity <= 0)
    elif filter_type == 'inactive':
        products_query = products_query.filter_by(is_active=False)
    elif filter_type == 'featured':
        products_query = products_query.filter_by(is_featured=True)
    
    products_pagination = products_query.order_by(Product.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    
    categories = Category.query.filter_by(is_active=True).all()
    
    return render_template('admin/inventory.html', 
                         products=products_pagination.items,
                         pagination=products_pagination,
                         categories=categories,
                         current_filter=filter_type,
                         search_query=search_query)

# NEW: Edit Product Route
@app.route('/admin/edit_product/<int:product_id>', methods=['GET', 'POST'])
@login_required
def edit_product(product_id):
    if not current_user.is_admin:
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('index'))
    
    product = Product.query.get_or_404(product_id)
    
    if request.method == 'POST':
        try:
            data = request.get_json()
            
            # Validation
            if not data.get('name') or not data.get('price'):
                return jsonify({'success': False, 'message': 'Name and price are required'})
            
            if float(data['price']) < 0:
                return jsonify({'success': False, 'message': 'Price cannot be negative'})
            
            if int(data['stock']) < 0:
                return jsonify({'success': False, 'message': 'Stock cannot be negative'})
            
            # Update product fields
            product.name = data['name'].strip()
            product.description = data.get('description', '').strip()
            product.price = float(data['price'])
            product.original_price = float(data.get('original_price', 0)) or None
            product.stock_quantity = int(data['stock'])
            product.min_stock = int(data.get('min_stock', 10))
            product.unit = data['unit']
            product.category_id = int(data['category_id'])
            product.image_url = data.get('image_url', '').strip() or None
            product.is_featured = bool(data.get('is_featured', False))
            product.updated_at = datetime.utcnow()
            
            db.session.commit()
            
            logger.info(f"Product {product_id} updated by admin {current_user.id}")
            
            return jsonify({'success': True, 'message': 'Product updated successfully'})
            
        except ValueError:
            return jsonify({'success': False, 'message': 'Invalid data format'})
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating product {product_id}: {e}")
            return jsonify({'success': False, 'message': 'An error occurred while updating the product'})
    
    # GET request - render edit form
    categories = Category.query.filter_by(is_active=True).all()
    return render_template('admin/edit_product.html', product=product, categories=categories)

@app.route('/admin/add_product', methods=['POST'])
@login_required
def add_product():
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Access denied'})
    
    try:
        data = request.get_json()
        
        # Validation
        if not data.get('name') or not data.get('price') or not data.get('category_id'):
            return jsonify({'success': False, 'message': 'Name, price, and category are required'})
        
        if float(data['price']) < 0:
            return jsonify({'success': False, 'message': 'Price cannot be negative'})
        
        if int(data['stock']) < 0:
            return jsonify({'success': False, 'message': 'Stock cannot be negative'})
        
        # Check if product with same name exists
        if Product.query.filter_by(name=data['name'].strip()).first():
            return jsonify({'success': False, 'message': 'Product with this name already exists'})
        
        product = Product(
            name=data['name'].strip(),
            description=data.get('description', '').strip(),
            price=float(data['price']),
            original_price=float(data.get('original_price', 0)) or None,
            stock_quantity=int(data['stock']),
            min_stock=int(data.get('min_stock', 10)),
            unit=data['unit'],
            category_id=int(data['category_id']),
            image_url=data.get('image_url', '').strip() or None,
            is_featured=bool(data.get('is_featured', False))
        )
        
        db.session.add(product)
        db.session.commit()
        
        logger.info(f"Product added by admin {current_user.id}: {product.name}")
        
        return jsonify({'success': True, 'message': 'Product added successfully'})
    
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid data format'})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error adding product: {e}")
        return jsonify({'success': False, 'message': 'An error occurred while adding the product'})

@app.route('/admin/toggle_product', methods=['POST'])
@login_required
def toggle_product():
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Access denied'})
    
    product_id = request.json.get('product_id')
    product = Product.query.get(product_id)
    
    if product:
        product.is_active = not product.is_active
        product.updated_at = datetime.utcnow()
        db.session.commit()
        
        status = 'activated' if product.is_active else 'deactivated'
        logger.info(f"Product {product_id} {status} by admin {current_user.id}")
        
        return jsonify({'success': True, 'message': f'Product {status} successfully'})
    
    return jsonify({'success': False, 'message': 'Product not found'})

@app.route('/admin/delete_product/<int:product_id>', methods=['POST'])
@login_required
def delete_product(product_id):
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Access denied'})
    
    product = Product.query.get_or_404(product_id)
    
    try:
        # Check if product has any orders
        if OrderItem.query.filter_by(product_id=product_id).first():
            return jsonify({'success': False, 'message': 'Cannot delete product with existing orders'})
        
        db.session.delete(product)
        db.session.commit()
        
        logger.info(f"Product {product_id} deleted by admin {current_user.id}")
        
        return jsonify({'success': True, 'message': 'Product deleted successfully'})
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting product {product_id}: {e}")
        return jsonify({'success': False, 'message': 'An error occurred while deleting the product'})

@app.route('/admin/orders')
@login_required
def admin_orders():
    if not current_user.is_admin:
        flash('Access denied', 'error')
        return redirect(url_for('index'))
    
    page = request.args.get('page', 1, type=int)
    status_filter = request.args.get('status', '')
    date_filter = request.args.get('date', '')
    search_query = request.args.get('q', '').strip()
    
    orders_query = Order.query
    
    # Apply search filter
    if search_query:
        orders_query = orders_query.join(User).filter(
            or_(
                Order.id == int(search_query) if search_query.isdigit() else False,
                User.username.ilike(f'%{search_query}%'),
                User.email.ilike(f'%{search_query}%'),
                Order.phone_number.ilike(f'%{search_query}%')
            )
        )
    
    # Apply status filter
    if status_filter:
        orders_query = orders_query.filter_by(status=status_filter)
    
    # Apply date filter
    if date_filter:
        try:
            filter_date = datetime.strptime(date_filter, '%Y-%m-%d').date()
            orders_query = orders_query.filter(
                Order.order_date >= datetime.combine(filter_date, datetime.min.time()),
                Order.order_date < datetime.combine(filter_date, datetime.max.time())
            )
        except ValueError:
            pass
    
    orders_pagination = orders_query.order_by(Order.order_date.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    
    return render_template('admin/orders.html', 
                         orders=orders_pagination.items,
                         pagination=orders_pagination,
                         current_status=status_filter,
                         current_date=date_filter,
                         search_query=search_query)

@app.route('/admin/update_order_status', methods=['POST'])
@login_required
def update_order_status():
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Access denied'})
    
    order_id = request.json.get('order_id')
    status = request.json.get('status')
    
    if status not in ['pending', 'confirmed', 'delivered', 'cancelled']:
        return jsonify({'success': False, 'message': 'Invalid status'})
    
    order = Order.query.get(order_id)
    if not order:
        return jsonify({'success': False, 'message': 'Order not found'})
    
    try:
        old_status = order.status
        
        # If cancelling, restore stock
        if status == 'cancelled' and old_status != 'cancelled':
            for item in order.items:
                item.product.stock_quantity += item.quantity
        
        # If uncancelling, reduce stock
        elif old_status == 'cancelled' and status != 'cancelled':
            for item in order.items:
                if item.product.stock_quantity < item.quantity:
                    return jsonify({'success': False, 'message': f'Insufficient stock for {item.product.name}'})
                item.product.stock_quantity -= item.quantity
        
        order.status = status
        if status == 'delivered':
            order.delivery_date = datetime.utcnow()
        
        db.session.commit()
        
        logger.info(f"Order {order_id} status changed from {old_status} to {status} by admin {current_user.id}")
        
        return jsonify({'success': True, 'message': f'Order status updated to {status}'})
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating order {order_id} status: {e}")
        return jsonify({'success': False, 'message': 'An error occurred while updating the order'})

@app.route('/admin/order_details/<int:order_id>')
@login_required
def admin_order_details(order_id):
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Access denied'})
    
    order = Order.query.get_or_404(order_id)
    
    # Format order data for JSON response
    order_data = {
        'id': order.id,
        'customer_name': order.customer.username,
        'customer_email': order.customer.email,
        'phone_number': order.phone_number,
        'delivery_address': order.delivery_address,
        'special_instructions': order.special_instructions,
        'order_date': order.order_date.strftime('%d %b, %Y at %I:%M %p'),
        'status': order.status,
        'payment_method': order.payment_method,
        'delivery_type': order.delivery_type,
        'total_amount': f"{order.total_amount:.2f}",
        'subtotal': f"{order.subtotal:.2f}",
        'delivery_fee': f"{order.delivery_fee:.2f}",
        'tax_amount': f"{order.tax_amount:.2f}",
        'discount_amount': f"{order.discount_amount:.2f}",
        'estimated_delivery': order.estimated_delivery.strftime('%d %b, %Y at %I:%M %p') if order.estimated_delivery else None,
        'delivery_date': order.delivery_date.strftime('%d %b, %Y at %I:%M %p') if order.delivery_date else None,
        'items': [{
            'name': item.product.name,
            'description': item.product.description or 'No description available',
            'price': f"{item.price:.2f}",
            'original_price': f"{item.original_price:.2f}" if item.original_price else None,
            'quantity': item.quantity,
            'unit': item.product.unit,
            'subtotal': f"{item.get_subtotal():.2f}",
            'image_url': item.product.image_url or '/static/images/no-image.jpg'
        } for item in order.items]
    }
    
    return jsonify({'success': True, 'order': order_data})

@app.route('/admin/print_order/<int:order_id>')
@login_required
def print_order(order_id):
    if not current_user.is_admin:
        flash('Access denied', 'error')
        return redirect(url_for('index'))
    
    order = Order.query.get_or_404(order_id)
    return render_template('admin/print_order.html', order=order)

@app.route('/admin/add_category', methods=['POST'])
@login_required
def add_category():
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Access denied'})
    
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        description = data.get('description', '').strip()
        
        if not name:
            return jsonify({'success': False, 'message': 'Category name is required'})
        
        # Check if category already exists
        if Category.query.filter_by(name=name).first():
            return jsonify({'success': False, 'message': 'Category already exists'})
        
        category = Category(name=name, description=description)
        db.session.add(category)
        db.session.commit()
        
        logger.info(f"Category added by admin {current_user.id}: {name}")
        
        return jsonify({'success': True, 'message': 'Category added successfully'})
    
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error adding category: {e}")
        return jsonify({'success': False, 'message': 'An error occurred while adding the category'})

@app.route('/admin/users')
@login_required
def admin_users():
    if not current_user.is_admin:
        flash('Access denied', 'error')
        return redirect(url_for('index'))
    
    page = request.args.get('page', 1, type=int)
    search_query = request.args.get('q', '').strip()
    
    users_query = User.query.filter_by(is_admin=False)
    
    if search_query:
        users_query = users_query.filter(
            or_(
                User.username.ilike(f'%{search_query}%'),
                User.email.ilike(f'%{search_query}%')
            )
        )
    
    users_pagination = users_query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    
    return render_template('admin/users.html',
                         users=users_pagination.items,
                         pagination=users_pagination,
                         search_query=search_query)

@app.route('/admin/toggle_user_status', methods=['POST'])
@login_required
def toggle_user_status():
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Access denied'})
    
    user_id = request.json.get('user_id')
    user = User.query.get(user_id)
    
    if not user or user.is_admin:
        return jsonify({'success': False, 'message': 'User not found or cannot modify admin user'})
    
    user.is_active = not user.is_active
    db.session.commit()
    
    status = 'activated' if user.is_active else 'deactivated'
    logger.info(f"User {user_id} {status} by admin {current_user.id}")
    
    return jsonify({'success': True, 'message': f'User {status} successfully'})

# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    return render_template('errors/404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    logger.error(f"Internal server error: {error}")
    return render_template('errors/500.html'), 500

@app.errorhandler(403)
def forbidden_error(error):
    return render_template('errors/403.html'), 403

@app.errorhandler(413)
def too_large(error):
    return jsonify({'success': False, 'message': 'File too large'}), 413

# Helper function to update product images
def update_product_images():
    """Update sample products with image URLs"""
    image_mappings = {
        'Salted Butter (500g)': 'products/amul-butter.jpg',
        'Cheese Slices (200g)': 'products/cheese-slices.jpg', 
        'Farm Fresh Eggs (12 pcs)': 'products/farm-eggs.jpg',
        'Fresh Milk (1L)': 'products/fresh-milk.jpg',
        'Greek Yogurt (500g)': 'products/greek-yogurt.jpg',
        'Paneer (250g)': 'products/paneer.jpg',
        'Fresh Bananas': 'products/bananas.jpg',
        'Red Apples': 'products/red-apples.jpg',
        'Basmati Rice (5kg)': 'products/basmati-rice.jpg',
        'Whole Wheat Flour (5kg)': 'products/wheat-flour.jpg',
        'Cooking Oil (1L)': 'products/cooking-oil.jpg'
    }
    
    for product_name, image_url in image_mappings.items():
        product = Product.query.filter_by(name=product_name).first()
        if product:
            product.image_url = image_url
    
    db.session.commit()
    print("✅ Product images updated!")

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        
        # Create admin user if doesn't exist
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(username='admin', email='admin@grocery.com', is_admin=True, email_verified=True)
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print("Admin user created: username='admin', password='admin123'")
        
        # Create sample categories if none exist
        if not Category.query.first():
            categories = [
                Category(name='Fruits & Vegetables', description='Fresh produce', is_active=True),
                Category(name='Dairy & Eggs', description='Milk, cheese, eggs', is_active=True),
                Category(name='Meat & Seafood', description='Fresh meat and fish', is_active=True),
                Category(name='Bakery', description='Bread and baked goods', is_active=True),
                Category(name='Pantry', description='Canned goods and dry items', is_active=True),
                Category(name='Beverages', description='Drinks and beverages', is_active=True),
                Category(name='Snacks', description='Chips, cookies, and snacks', is_active=True),
                Category(name='Personal Care', description='Health and beauty products', is_active=True)
            ]
            for category in categories:
                db.session.add(category)
            print("Sample categories created")
        
        # Create sample products if none exist
        if not Product.query.first():
            sample_products = [
                # Fruits & Vegetables
                Product(name='Fresh Bananas', description='Sweet ripe bananas, perfect for smoothies and snacks', price=40.0, stock_quantity=50, unit='kg', category_id=1, is_featured=True, image_url='products/bananas.jpg'),
                Product(name='Red Apples', description='Crispy red apples, great for snacking and cooking', price=120.0, original_price=140.0, stock_quantity=30, unit='kg', category_id=1, is_featured=True, image_url='products/red-apples.jpg'),
                Product(name='Fresh Onions', description='Premium quality onions for cooking', price=30.0, stock_quantity=40, unit='kg', category_id=1),
                Product(name='Ripe Tomatoes', description='Fresh red tomatoes, ideal for salads and cooking', price=25.0, stock_quantity=35, unit='kg', category_id=1),
                Product(name='Potatoes', description='Fresh potatoes for various dishes', price=20.0, stock_quantity=60, unit='kg', category_id=1),
                Product(name='Fresh Carrots', description='Orange carrots, rich in vitamins', price=35.0, stock_quantity=25, unit='kg', category_id=1),
                Product(name='Green Spinach', description='Fresh leafy spinach, packed with nutrients', price=45.0, stock_quantity=20, unit='kg', category_id=1),
                
                # Dairy & Eggs
                Product(name='Fresh Milk (1L)', description='Fresh full cream milk from local farms', price=25.0, stock_quantity=50, unit='liter', category_id=2, is_featured=True, image_url='products/fresh-milk.jpg'),
                Product(name='Farm Fresh Eggs (12 pcs)', description='Free-range chicken eggs', price=60.0, stock_quantity=25, unit='packet', category_id=2, image_url='products/farm-eggs.jpg'),
                Product(name='Paneer (250g)', description='Fresh cottage cheese for Indian dishes', price=80.0, stock_quantity=15, unit='packet', category_id=2, image_url='products/paneer.jpg'),
                Product(name='Greek Yogurt (500g)', description='Thick and creamy Greek yogurt', price=85.0, stock_quantity=18, unit='packet', category_id=2, image_url='products/greek-yogurt.jpg'),
                Product(name='Salted Butter (500g)', description='Premium quality salted butter', price=120.0, stock_quantity=12, unit='packet', category_id=2, image_url='products/amul-butter.jpg'),
                Product(name='Cheese Slices (200g)', description='Processed cheese slices', price=95.0, stock_quantity=20, unit='packet', category_id=2, image_url='products/cheese-slices.jpg'),
                
                # Pantry
                Product(name='Basmati Rice (5kg)', description='Premium aged basmati rice', price=350.0, stock_quantity=25, unit='kg', category_id=5, is_featured=True, image_url='products/basmati-rice.jpg'),
                Product(name='Whole Wheat Flour (5kg)', description='Fresh ground whole wheat flour', price=175.0, stock_quantity=30, unit='kg', category_id=5, image_url='products/wheat-flour.jpg'),
                Product(name='Cooking Oil (1L)', description='Heart-healthy refined cooking oil', price=180.0, stock_quantity=20, unit='liter', category_id=5, image_url='products/cooking-oil.jpg'),
                Product(name='Toor Dal (1kg)', description='Premium quality yellow lentils', price=120.0, stock_quantity=18, unit='kg', category_id=5),
                Product(name='Chickpeas (1kg)', description='Premium quality dried chickpeas', price=80.0, stock_quantity=22, unit='kg', category_id=5),
                Product(name='Brown Sugar (1kg)', description='Natural brown sugar', price=65.0, stock_quantity=15, unit='kg', category_id=5),
                
                # Beverages
                Product(name='Orange Juice (1L)', description='Fresh orange juice, no preservatives', price=85.0, stock_quantity=15, unit='liter', category_id=6),
                Product(name='Green Tea (100g)', description='Premium green tea leaves', price=150.0, stock_quantity=10, unit='packet', category_id=6),
                Product(name='Coffee Beans (500g)', description='Freshly roasted arabica coffee beans', price=280.0, stock_quantity=8, unit='packet', category_id=6),
                Product(name='Mineral Water (1L)', description='Pure mineral water', price=20.0, stock_quantity=100, unit='bottle', category_id=6),
                
                # Snacks
                Product(name='Mixed Nuts (250g)', description='Premium mixed nuts for healthy snacking', price=320.0, original_price=350.0, stock_quantity=14, unit='packet', category_id=7),
                Product(name='Potato Chips (150g)', description='Crispy potato chips', price=45.0, stock_quantity=30, unit='packet', category_id=7),
                Product(name='Chocolate Cookies (200g)', description='Delicious chocolate chip cookies', price=75.0, stock_quantity=25, unit='packet', category_id=7),
                
                # Bakery
                Product(name='Whole Wheat Bread', description='Fresh whole wheat bread loaf', price=35.0, stock_quantity=20, unit='piece', category_id=4),
                Product(name='Croissants (4 pcs)', description='Buttery French croissants', price=120.0, stock_quantity=12, unit='packet', category_id=4),
                
                # Personal Care
                Product(name='Hand Sanitizer (500ml)', description='Antibacterial hand sanitizer', price=85.0, stock_quantity=25, unit='bottle', category_id=8),
                Product(name='Face Mask (Pack of 10)', description='Disposable face masks', price=150.0, stock_quantity=30, unit='packet', category_id=8)
            ]
            
            for product in sample_products:
                db.session.add(product)
            print("Sample products created")
        
        # Create sample coupon
        if not Coupon.query.first():
            coupons = [
                Coupon(
                    code='WELCOME10',
                    description='Welcome discount for new customers',
                    discount_type='percentage',
                    discount_value=10.0,
                    min_order_amount=100.0,
                    max_discount=50.0,
                    usage_limit=100,
                    valid_until=datetime.utcnow() + timedelta(days=30)
                ),
                Coupon(
                    code='SAVE50',
                    description='Flat ₹50 off on orders above ₹500',
                    discount_type='fixed',
                    discount_value=50.0,
                    min_order_amount=500.0,
                    usage_limit=50,
                    valid_until=datetime.utcnow() + timedelta(days=15)
                )
            ]
            for coupon in coupons:
                db.session.add(coupon)
            print("Sample coupons created")
        
        db.session.commit()
        print("Database initialized successfully!")
        
        print("\n" + "="*60)
        print("🛒 GROCERY STORE APPLICATION STARTED")
        print("="*60)
        print("🌐 Customer Site: http://localhost:5000")
        print("👑 Admin Panel: http://localhost:5000/admin")
        print("📧 Admin Login: username='admin', password='admin123'")
        print("📱 Features: Full e-commerce, Admin panel, Email system, Edit products")
        print("🔧 Environment: Development mode")
        print("="*60 + "\n")
    
    # Run the application
    debug_mode = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'
    app.run(debug=debug_mode, host='0.0.0.0', port=5000)
