from main import app, db, Product

products = [
    Product(name="Classic Tee", description="100% cotton t-shirt.", price_cents=2500, image="tee.jpg"),
    Product(name="Coffee Mug", description="Ceramic, 350ml.", price_cents=1200, image="mug.jpg"),
    Product(name="Tote Bag", description="Heavy canvas tote.", price_cents=1800, image="tote.jpg"),
]

with app.app_context():
    if not db.session.execute(db.select(Product)).first():
        db.session.add_all(products)
        db.session.commit()
        print("Seeded.")
    else:
        print("Products already exist.")