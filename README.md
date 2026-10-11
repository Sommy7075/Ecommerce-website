# Flask Store

E-commerce site built with Flask: product listing, user registration and login, shopping cart, Stripe Checkout payments, and order history.

## Features
- Register, log in and log out (hashed passwords, CSRF protection)
- Product listing and a per-user cart (add, update, remove)
- Real payments through Stripe Checkout (test mode)
- Stripe webhook that confirms payment, saves the order and clears the cart
- Order history page

## Stack
Flask, Flask-SQLAlchemy, Flask-Login, Flask-WTF, Stripe, SQLite

## Run locally
```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Fill in `.env` with your own Stripe test keys, then:

```bash
python seed.py
python main.py
```

The store runs at http://127.0.0.1:5001

## Webhooks (second terminal)
```bash
stripe listen --events checkout.session.completed --forward-to localhost:5001/webhook
```

Copy the `whsec_...` it prints into `STRIPE_WEBHOOK_SECRET` in `.env`, then restart Flask.

## Test payment
Card `4242 4242 4242 4242`, any future expiry, any CVC.