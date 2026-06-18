"""Generate ``data/demo_buggy.db``: a small SQLite database seeded with a wide
variety of *intentional* problems so every detector in DBug Hunter has something
to find. Run it with:  python scripts/make_demo_db.py
"""
from __future__ import annotations

import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE_DIR, "data", "demo_buggy.db")


def build(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        os.remove(path)

    conn = sqlite3.connect(path)
    cur = conn.cursor()
    # Foreign keys stay OFF (the default) so we can insert orphan rows on purpose.

    cur.executescript(
        """
        CREATE TABLE customers (
            id          INTEGER PRIMARY KEY,
            name        TEXT,
            email       TEXT,
            signup_date TEXT,
            city        TEXT
        );

        CREATE TABLE products (
            id    INTEGER PRIMARY KEY,
            name  TEXT,
            price REAL,
            stock,                 -- no declared type: free to mix int & text (a bug)
            sku   TEXT
        );

        CREATE TABLE orders (
            id          INTEGER PRIMARY KEY,
            customer_id INTEGER,
            total       REAL,
            created_at  TEXT,
            FOREIGN KEY (customer_id) REFERENCES customers(id)   -- no index => slow
        );

        CREATE TABLE order_items (              -- intentionally NO primary key
            order_id   INTEGER,
            product_id INTEGER,
            quantity   INTEGER,
            FOREIGN KEY (order_id)   REFERENCES orders(id),
            FOREIGN KEY (product_id) REFERENCES products(id)
        );

        CREATE TABLE audit_log (                -- intentionally left empty
            id     INTEGER PRIMARY KEY,
            action TEXT
        );
        """
    )

    # -- customers: dup email, invalid emails, NULL name, whitespace, empty city,
    #    invalid + future signup dates ---------------------------------------
    customers = [
        (1, "Alice Martin",   "alice@example.com",    "2021-04-12", "Paris"),
        (2, "  Bob Dupont ",  "bob[at]example.com",   "2021-05-01", "Lyon"),    # bad email + whitespace
        (3, None,             "carol@example.com",    "2021-06-20", ""),        # NULL name, empty city
        (4, "David Bernard",  "alice@example.com",    "2021-13-40", "Lille"),   # dup email + invalid date
        (5, "Emma Petit",     "emma@@example.com",    "2099-01-01", "Nice"),    # bad email + future date
        (6, "Hugo Moreau",    "hugo@example.com",     "2021-08-15", "Paris"),
    ]
    cur.executemany("INSERT INTO customers VALUES (?,?,?,?,?)", customers)

    # -- products: negative price, mixed-type stock, price outlier, dup sku ----
    products = [
        (1, "Clavier",  29.90,  120,    "KB-001"),
        (2, "Souris",   19.90,  "85",   "MS-002"),    # stock stored as TEXT (mixed type)
        (3, "Écran",   -149.00, 40,     "SCR-3"),     # negative price
        (4, "Webcam",   49.00,  "N/A",  "WC-004"),    # stock = text 'N/A' (mixed type)
        (5, "Casque",   89.00,  30,     "KB-001"),    # duplicate sku
        (6, "Station",  999999.0, 5,    "DOCK-6"),    # price outlier
        (7, "Câble",    4.50,   500,    "CB-007"),
        (8, "Tapis",    9.90,   200,    "TP-008"),
        (9, "Support",  24.00,  60,     "SP-009"),
        (10, "Lampe",   14.50,  75,     "LP-010"),
    ]
    cur.executemany("INSERT INTO products VALUES (?,?,?,?,?)", products)

    # -- orders: orphan customer_id, negative total, invalid + future dates ----
    orders = [
        (1, 1,    59.80,  "2022-01-10"),
        (2, 2,    19.90,  "2022-01-11"),
        (3, 9999, 89.00,  "2022-01-12"),   # orphan: customer 9999 does not exist
        (4, 3,   -10.00,  "2022-13-01"),   # negative total + invalid date
        (5, 4,    49.00,  "2030-12-31"),   # future date
        (6, 1,    24.00,  "2022-02-02"),
    ]
    cur.executemany("INSERT INTO orders VALUES (?,?,?,?)", orders)

    # -- order_items: duplicate rows, negative quantity, orphan product_id ------
    items = [
        (1, 1, 2),
        (1, 1, 2),     # exact duplicate row
        (1, 7, 1),
        (2, 2, 1),
        (3, 4, -3),    # negative quantity
        (4, 555, 1),   # orphan: product 555 does not exist
        (6, 9, 1),
        (6, 9, 1),     # exact duplicate row
    ]
    cur.executemany("INSERT INTO order_items VALUES (?,?,?)", items)

    conn.commit()
    conn.close()
    print(f"Base de démo générée : {path}")


if __name__ == "__main__":
    build(OUT)
