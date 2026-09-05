"""Idempotent demo marketplace seed data for Merco.

Set MERCO_SEED_DEMO_DATA=1 to create 50 demo sellers and 50 demo products.
Seller account emails use Gmail plus-addresses so the public contact email can
remain the requested nwahiridaviduche@gmail.com while the User.email column
stays unique.
"""
from decimal import Decimal

from werkzeug.security import generate_password_hash

from app import app, db, User, Product, Category
from bootstrap import SellerContact

DEMO_PUBLIC_EMAIL = 'nwahiridaviduche@gmail.com'
DEMO_PHONE = '+2347037065177'
DEMO_WHATSAPP = '+2347037065177'
DEMO_PASSWORD = 'DemoSeller123!'

PRODUCTS = [
    ('Nova Wireless Earbuds', 'Electronics', 28500),
    ('AeroFit Smart Watch', 'Electronics', 42000),
    ('Titan Bluetooth Speaker', 'Electronics', 55000),
    ('Luma LED Desk Lamp', 'Home & Living', 18500),
    ('Urban Canvas Backpack', 'Fashion', 26000),
    ('Classic Leather Wallet', 'Fashion', 15000),
    ('Motion Running Sneakers', 'Fashion', 48000),
    ('Silk Touch Handbag', 'Fashion', 62000),
    ('Pure Glow Skincare Set', 'Beauty', 32000),
    ('Velvet Matte Lip Kit', 'Beauty', 18500),
    ('Apex Android Phone', 'Phones & Accessories', 185000),
    ('Crystal Fast Charger', 'Phones & Accessories', 12500),
    ('MagSafe Power Bank', 'Phones & Accessories', 28500),
    ('ProType Mechanical Keyboard', 'Computers', 65000),
    ('Vision 24 Monitor', 'Computers', 145000),
    ('CloudBook Laptop Stand', 'Computers', 22000),
    ('GameCore Wireless Controller', 'Gaming', 45000),
    ('RGB Gaming Headset', 'Gaming', 58000),
    ('Arcade USB Game Pad', 'Gaming', 24000),
    ('NextGen Console Cooling Stand', 'Gaming', 35000),
    ('Minimalist Coffee Table', 'Home & Living', 78000),
    ('Luxe Throw Pillow Set', 'Home & Living', 24000),
    ('Bamboo Storage Organizer', 'Home & Living', 19500),
    ('Modern Wall Clock', 'Home & Living', 21000),
    ('Smart Plug Mini', 'Electronics', 16000),
    ('Portable Mini Projector', 'Electronics', 92000),
    ('Noise Cancel Headphones', 'Electronics', 85000),
    ('USB-C Hub Pro', 'Computers', 39000),
    ('Slim Wireless Mouse', 'Computers', 18000),
    ('Creator Ring Light', 'Electronics', 33000),
    ('Everyday Polo Shirt', 'Fashion', 18000),
    ('Premium Denim Jacket', 'Fashion', 52000),
    ('Heritage Sunglasses', 'Fashion', 28000),
    ('Travel Duffel Bag', 'Fashion', 41000),
    ('Fresh Scent Perfume', 'Beauty', 36000),
    ('Daily Care Grooming Kit', 'Beauty', 29000),
    ('Hydra Face Moisturizer', 'Beauty', 17500),
    ('Natural Hair Care Bundle', 'Beauty', 27000),
    ('Fast Charge Cable Pack', 'Phones & Accessories', 11000),
    ('Phone Camera Lens Kit', 'Phones & Accessories', 14500),
    ('Laptop Sleeve 15-inch', 'Computers', 25000),
    ('Ergo Wireless Keyboard', 'Computers', 44000),
    ('Gaming Mouse Ultra', 'Gaming', 37000),
    ('Console Carry Case', 'Gaming', 46000),
    ('Strategy Board Game Set', 'Books', 22000),
    ('Business Skills Handbook', 'Books', 16500),
    ('Home Repair Toolkit', 'Other', 38000),
    ('Premium Car Phone Mount', 'Vehicles', 19500),
    ('Auto Emergency Kit', 'Vehicles', 47000),
    ('Detailing Care Bundle', 'Vehicles', 31000),
]


def seed_demo_data():
    with app.app_context():
        categories = {c.name: c for c in Category.query.all()}
        if len(categories) < 1:
            return 0

        created = 0
        for index, (product_name, category_name, price) in enumerate(PRODUCTS, start=1):
            seller_name = f'Merco Demo Store {index:02d}'
            account_email = f'nwahiridaviduche+seller{index:02d}@gmail.com'
            slug = f'merco-demo-store-{index:02d}'

            seller = User.query.filter_by(seller_slug=slug).first()
            if not seller:
                seller = User.query.filter_by(email=account_email).first()
            if not seller:
                seller = User(
                    username=seller_name,
                    email=account_email,
                    password=generate_password_hash(DEMO_PASSWORD),
                    role='seller',
                    whatsapp_number=DEMO_WHATSAPP,
                    seller_slug=slug,
                    preferred_language='en',
                    preferred_currency='NGN',
                    email_verified=True,
                    email_notifications=True,
                )
                db.session.add(seller)
                db.session.flush()
                created += 1
            else:
                seller.username = seller_name
                seller.role = 'seller'
                seller.whatsapp_number = DEMO_WHATSAPP
                seller.seller_slug = slug
                seller.email_verified = True
                seller.email_notifications = True

            contact = SellerContact.query.filter_by(seller_id=seller.id).first()
            if not contact:
                contact = SellerContact(
                    seller_id=seller.id,
                    public_email=DEMO_PUBLIC_EMAIL,
                    phone_number=DEMO_PHONE,
                    free_listing_used=True,
                )
                db.session.add(contact)
            else:
                contact.public_email = DEMO_PUBLIC_EMAIL
                contact.phone_number = DEMO_PHONE
                contact.free_listing_used = True

            existing = Product.query.filter_by(seller_id=seller.id, name=product_name).first()
            if not existing:
                category = categories.get(category_name) or categories.get('Other')
                db.session.add(Product(
                    name=product_name,
                    price=float(Decimal(str(price))),
                    description=f'Premium demo listing from {seller_name}. Contact the seller directly through the marketplace for availability and purchase details.',
                    cover_image=f'https://picsum.photos/seed/merco-product-{index}/900/650',
                    screenshots='',
                    is_sold_out=False,
                    seller_id=seller.id,
                    category_id=category.id if category else None,
                ))
        db.session.commit()
        return created


if __name__ == '__main__':
    with app.app_context():
        count = seed_demo_data()
        print(f'Merco demo seed complete. Created {count} sellers; demo data is idempotent.')
