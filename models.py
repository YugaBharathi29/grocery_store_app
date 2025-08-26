from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer
from flask import current_app

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    phone = db.Column(db.String(15))
    address = db.Column(db.Text)
    pincode = db.Column(db.String(6))
    is_admin = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    email_verified = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    
    orders = db.relationship('Order', backref='customer', lazy=True)
    
    def set_password(self, password):
        """Hash and set password"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Check if provided password matches hash"""
        return check_password_hash(self.password_hash, password)
    
    def get_reset_token(self, expires_sec=1800):
        """Generate password reset token (30 minutes default)"""
        s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        return s.dumps({'user_id': self.id})
    
    @staticmethod
    def verify_reset_token(token, expires_sec=1800):
        """Verify password reset token"""
        s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        try:
            user_id = s.loads(token, max_age=expires_sec)['user_id']
        except:
            return None
        return User.query.get(user_id)
    
    def get_verification_token(self):
        """Generate email verification token"""
        s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        return s.dumps({'user_id': self.id, 'action': 'verify_email'})
    
    @staticmethod
    def verify_email_token(token):
        """Verify email verification token"""
        s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        try:
            data = s.loads(token, max_age=86400)  # 24 hours
            if data.get('action') == 'verify_email':
                return User.query.get(data.get('user_id'))
        except:
            return None
        return None
    
    def update_last_login(self):
        """Update last login timestamp"""
        self.last_login = datetime.utcnow()
        db.session.commit()
    
    def __repr__(self):
        return f'<User {self.username}>'

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False, unique=True)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    products = db.relationship('Product', backref='category', lazy=True)
    
    def __repr__(self):
        return f'<Category {self.name}>'

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Float, nullable=False)
    original_price = db.Column(db.Float)  # For sale prices
    stock_quantity = db.Column(db.Integer, default=0)
    min_stock = db.Column(db.Integer, default=10)  # Minimum stock alert
    unit = db.Column(db.String(20), default='piece')  # kg, liter, piece, etc.
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    image_url = db.Column(db.String(200))
    expiry_date = db.Column(db.Date)
    is_active = db.Column(db.Boolean, default=True)
    is_featured = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def is_on_sale(self):
        """Check if product is on sale"""
        return self.original_price and self.original_price > self.price
    
    def get_discount_percentage(self):
        """Get discount percentage if on sale"""
        if self.is_on_sale():
            return round(((self.original_price - self.price) / self.original_price) * 100)
        return 0
    
    def is_low_stock(self):
        """Check if product stock is below minimum threshold"""
        return self.stock_quantity <= self.min_stock
    
    def is_out_of_stock(self):
        """Check if product is out of stock"""
        return self.stock_quantity <= 0
    
    def __repr__(self):
        return f'<Product {self.name}>'

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    total_amount = db.Column(db.Float, nullable=False)
    subtotal = db.Column(db.Float, nullable=False, default=0)
    delivery_fee = db.Column(db.Float, default=5.0)
    tax_amount = db.Column(db.Float, default=0)
    discount_amount = db.Column(db.Float, default=0)
    status = db.Column(db.String(20), default='pending')  # pending, confirmed, delivered, cancelled
    payment_method = db.Column(db.String(20), default='cod')  # cod, online
    delivery_type = db.Column(db.String(20), default='standard')  # standard, express
    delivery_address = db.Column(db.Text, nullable=False)
    phone_number = db.Column(db.String(15), nullable=False)
    special_instructions = db.Column(db.Text)
    order_date = db.Column(db.DateTime, default=datetime.utcnow)
    delivery_date = db.Column(db.DateTime)
    estimated_delivery = db.Column(db.DateTime)
    
    items = db.relationship('OrderItem', backref='order', lazy=True, cascade='all, delete-orphan')
    
    def calculate_totals(self):
        """Calculate order totals"""
        self.subtotal = sum(item.price * item.quantity for item in self.items)
        self.tax_amount = self.subtotal * 0.05  # 5% GST
        
        # Delivery fee based on type
        if self.delivery_type == 'express':
            self.delivery_fee = 25.0
        else:
            self.delivery_fee = 5.0
            
        self.total_amount = self.subtotal + self.tax_amount + self.delivery_fee - self.discount_amount
    
    def get_status_color(self):
        """Get color code for order status"""
        colors = {
            'pending': '#ff9800',
            'confirmed': '#2196f3',
            'delivered': '#4caf50',
            'cancelled': '#f44336'
        }
        return colors.get(self.status, '#666')
    
    def can_be_cancelled(self):
        """Check if order can be cancelled"""
        return self.status in ['pending', 'confirmed']
    
    def __repr__(self):
        return f'<Order {self.id}>'

class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)  # Price at time of order
    original_price = db.Column(db.Float)  # Original price if there was a discount
    
    product = db.relationship('Product', backref='order_items')
    
    def get_subtotal(self):
        """Get subtotal for this item"""
        return self.price * self.quantity
    
    def was_discounted(self):
        """Check if item was discounted at time of purchase"""
        return self.original_price and self.original_price > self.price
    
    def __repr__(self):
        return f'<OrderItem {self.product.name} x{self.quantity}>'

# Additional models for future features

class Coupon(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    description = db.Column(db.String(200))
    discount_type = db.Column(db.String(20), default='percentage')  # percentage, fixed
    discount_value = db.Column(db.Float, nullable=False)
    min_order_amount = db.Column(db.Float, default=0)
    max_discount = db.Column(db.Float)
    usage_limit = db.Column(db.Integer)
    used_count = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    valid_from = db.Column(db.DateTime, default=datetime.utcnow)
    valid_until = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def is_valid(self, order_amount=0):
        """Check if coupon is valid"""
        now = datetime.utcnow()
        return (self.is_active and 
                now >= self.valid_from and 
                (not self.valid_until or now <= self.valid_until) and
                (not self.usage_limit or self.used_count < self.usage_limit) and
                order_amount >= self.min_order_amount)
    
    def calculate_discount(self, order_amount):
        """Calculate discount amount"""
        if not self.is_valid(order_amount):
            return 0
        
        if self.discount_type == 'percentage':
            discount = order_amount * (self.discount_value / 100)
            if self.max_discount:
                discount = min(discount, self.max_discount)
        else:
            discount = self.discount_value
        
        return min(discount, order_amount)
    
    def __repr__(self):
        return f'<Coupon {self.code}>'

class Wishlist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='wishlist_items')
    product = db.relationship('Product', backref='wishlisted_by')
    
    __table_args__ = (db.UniqueConstraint('user_id', 'product_id'),)
    
    def __repr__(self):
        return f'<Wishlist {self.user.username} - {self.product.name}>'

class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)  # 1-5 stars
    comment = db.Column(db.Text)
    is_verified = db.Column(db.Boolean, default=False)  # Verified purchase
    is_approved = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='reviews')
    product = db.relationship('Product', backref='reviews')
    
    __table_args__ = (db.UniqueConstraint('user_id', 'product_id'),)
    
    def __repr__(self):
        return f'<Review {self.product.name} - {self.rating} stars>'
