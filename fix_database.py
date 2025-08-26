import sqlite3
import os
from datetime import datetime

def fix_database():
    """Add ALL missing columns to existing database (SQLite compatible)"""
    db_path = 'instance/grocery_store.db'
    
    if not os.path.exists(db_path):
        print("❌ Database file not found!")
        print(f"Looking for: {os.path.abspath(db_path)}")
        return
    
    print(f"✅ Found database at: {os.path.abspath(db_path)}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        print("🔧 Checking and fixing USER table...")
        
        # Check current user table structure
        cursor.execute("PRAGMA table_info(user)")
        existing_columns = [row[1] for row in cursor.fetchall()]
        print(f"📋 Current user columns: {existing_columns}")
        
        # Add missing user columns (only constant defaults allowed)
        user_columns_to_add = [
            ("pincode", "VARCHAR(6)"),
            ("is_active", "BOOLEAN DEFAULT 1"),
            ("email_verified", "BOOLEAN DEFAULT 0"),
            ("created_at", "DATETIME"),  # No default here
            ("last_login", "DATETIME")   # No default here
        ]
        
        for column_name, column_type in user_columns_to_add:
            if column_name not in existing_columns:
                try:
                    cursor.execute(f"ALTER TABLE user ADD COLUMN {column_name} {column_type}")
                    print(f"✅ Added '{column_name}' column to user table")
                except sqlite3.OperationalError as e:
                    print(f"❌ Error adding {column_name}: {e}")
            else:
                print(f"⚠️  Column '{column_name}' already exists in user table")
        
        print("\n🔧 Checking and fixing PRODUCT table...")
        
        # Check current product table structure
        cursor.execute("PRAGMA table_info(product)")
        existing_product_columns = [row[1] for row in cursor.fetchall()]
        print(f"📋 Current product columns: {existing_product_columns}")
        
        # Add missing product columns
        product_columns_to_add = [
            ("original_price", "FLOAT"),
            ("min_stock", "INTEGER DEFAULT 10"),
            ("is_featured", "BOOLEAN DEFAULT 0"),
            ("updated_at", "DATETIME"),  # No default here
            ("expiry_date", "DATE")
        ]
        
        for column_name, column_type in product_columns_to_add:
            if column_name not in existing_product_columns:
                try:
                    cursor.execute(f"ALTER TABLE product ADD COLUMN {column_name} {column_type}")
                    print(f"✅ Added '{column_name}' column to product table")
                except sqlite3.OperationalError as e:
                    print(f"❌ Error adding {column_name}: {e}")
            else:
                print(f"⚠️  Column '{column_name}' already exists in product table")
        
        print("\n🔧 Setting default values for existing records...")
        
        # Update existing records with current timestamp (SQLite compatible)
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Set default values for user table
        cursor.execute("UPDATE user SET is_active = 1 WHERE is_active IS NULL")
        cursor.execute("UPDATE user SET email_verified = 0 WHERE email_verified IS NULL")
        cursor.execute(f"UPDATE user SET created_at = '{current_time}' WHERE created_at IS NULL")
        
        # Set default values for product table  
        cursor.execute("UPDATE product SET min_stock = 10 WHERE min_stock IS NULL")
        cursor.execute("UPDATE product SET is_featured = 0 WHERE is_featured IS NULL")
        cursor.execute(f"UPDATE product SET updated_at = '{current_time}' WHERE updated_at IS NULL")
        
        conn.commit()
        print("✅ Default values updated for existing records")
        
        conn.close()
        print("\n🎉 Database schema updated successfully!")
        print("✅ All missing columns have been added!")
        print("✅ You can now run your Flask app!")
        
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        conn.close()

if __name__ == "__main__":
    fix_database()
