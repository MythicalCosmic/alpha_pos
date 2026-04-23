"""
Alpha POS — Full Integration Test
Hits every API endpoint and reports results.
"""
import requests
import json
import sys
from datetime import date, datetime

BASE = "http://127.0.0.1:8111"
RESULTS = {"pass": 0, "fail": 0, "errors": []}

def test(method, path, expected_status=None, data=None, token=None, label=None):
    url = f"{BASE}{path}"
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        if method == "GET":
            r = requests.get(url, headers=headers, timeout=10)
        elif method == "POST":
            r = requests.post(url, json=data or {}, headers=headers, timeout=10)
        elif method == "PUT":
            r = requests.put(url, json=data or {}, headers=headers, timeout=10)
        elif method == "PATCH":
            r = requests.patch(url, json=data or {}, headers=headers, timeout=10)
        elif method == "DELETE":
            r = requests.delete(url, headers=headers, timeout=10)

        status = r.status_code
        name = label or f"{method} {path}"

        if expected_status:
            if status == expected_status:
                RESULTS["pass"] += 1
                return r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
            else:
                RESULTS["fail"] += 1
                body = r.text[:200]
                RESULTS["errors"].append(f"  FAIL {name}: expected {expected_status}, got {status} — {body}")
                return None
        else:
            # Accept any non-500
            if status < 500:
                RESULTS["pass"] += 1
                return r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
            else:
                RESULTS["fail"] += 1
                RESULTS["errors"].append(f"  FAIL {name}: got {status} (server error)")
                return None
    except Exception as e:
        RESULTS["fail"] += 1
        RESULTS["errors"].append(f"  FAIL {label or path}: {e}")
        return None

def section(name):
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")

# ============================================================
# CUSTOMER AUTH
# ============================================================
section("CUSTOMER AUTH")

# Login as cashier
r = test("POST", "/auth-login", 200, {"email": "val.carter@inbox.uz", "password": "cashier123"}, label="Customer login (cashier)")
CASHIER_TOKEN = r["data"]["token"] if r and r.get("data") else None
print(f"  Cashier token: {CASHIER_TOKEN[:20] if CASHIER_TOKEN else 'FAILED'}...")

# Me
test("GET", "/auth-me", token=CASHIER_TOKEN, label="Customer me")
# Sessions
test("GET", "/auth-sessions", token=CASHIER_TOKEN, label="Customer sessions")

# ============================================================
# ADMIN AUTH
# ============================================================
section("ADMIN AUTH")

r = test("POST", "/api/admins/auth-login", 200, {"email": "cosmic@gmail.com", "password": "admin123"}, label="Admin login")
if not r or not r.get("success"):
    r = test("POST", "/api/admins/auth-login", 200, {"email": "hollis.rivera@inbox.uz", "password": "admin123"}, label="Admin login (seed)")
ADMIN_TOKEN = r["data"]["token"] if r and r.get("data") else None
print(f"  Admin token: {ADMIN_TOKEN[:20] if ADMIN_TOKEN else 'FAILED'}...")

if not ADMIN_TOKEN:
    print("\n  CRITICAL: Cannot get admin token. Aborting admin tests.")
    # Print what we have so far
    print(f"\n{'='*60}")
    print(f"  RESULTS: {RESULTS['pass']} passed, {RESULTS['fail']} failed")
    for e in RESULTS["errors"]:
        print(e)
    sys.exit(1)

test("GET", "/api/admins/auth-me", token=ADMIN_TOKEN, label="Admin me")
test("GET", "/api/admins/auth-sessions", token=ADMIN_TOKEN, label="Admin sessions")

# ============================================================
# WAITER AUTH
# ============================================================
section("WAITER AUTH")

r = test("POST", "/api/waiters/auth-login", 200, {"email": "waiter@alpha.com", "password": "waiter123"}, label="Waiter login")
WAITER_TOKEN = r["data"]["token"] if r and r.get("data") else None
print(f"  Waiter token: {WAITER_TOKEN[:20] if WAITER_TOKEN else 'FAILED'}...")

test("GET", "/api/waiters/auth-me", token=WAITER_TOKEN, label="Waiter me")

# ============================================================
# ADMIN — CATEGORIES
# ============================================================
section("ADMIN — CATEGORIES")

test("GET", "/api/admins/categories", token=ADMIN_TOKEN, label="List categories")
test("GET", "/api/admins/categories/active", token=ADMIN_TOKEN, label="Active categories")
test("GET", "/api/admins/categories/deleted", token=ADMIN_TOKEN, label="Deleted categories")
test("GET", "/api/admins/categories/stats", token=ADMIN_TOKEN, label="Category stats")

# ============================================================
# ADMIN — PRODUCTS
# ============================================================
section("ADMIN — PRODUCTS")

test("GET", "/api/admins/products", token=ADMIN_TOKEN, label="List products")
test("GET", "/api/admins/products/deleted", token=ADMIN_TOKEN, label="Deleted products")

# ============================================================
# ADMIN — ORDERS
# ============================================================
section("ADMIN — ORDERS")

test("GET", "/api/admins/orders", token=ADMIN_TOKEN, label="List orders")
test("GET", "/api/admins/orders/stats", token=ADMIN_TOKEN, label="Order stats")

# ============================================================
# ADMIN — PLACES & TABLES
# ============================================================
section("ADMIN — PLACES & TABLES")

test("GET", "/api/admins/places", token=ADMIN_TOKEN, label="List places")
test("GET", "/api/admins/tables", token=ADMIN_TOKEN, label="List tables")

# ============================================================
# ADMIN — SHIFTS
# ============================================================
section("ADMIN — SHIFTS")

test("GET", "/api/admins/shifts", token=ADMIN_TOKEN, label="List shifts")
test("GET", "/api/admins/shifts/active", token=ADMIN_TOKEN, label="Active shifts")
test("GET", "/api/admins/shift-templates", token=ADMIN_TOKEN, label="Shift templates")

# Create shift template
r = test("POST", "/api/admins/shift-templates", 201, {
    "name": "Morning", "start_time": "08:00", "end_time": "16:00"
}, token=ADMIN_TOKEN, label="Create shift template")

# ============================================================
# ADMIN — APP SETTINGS
# ============================================================
section("ADMIN — APP SETTINGS")

test("GET", "/api/admins/app-settings", token=ADMIN_TOKEN, label="Get app settings")

# ============================================================
# CUSTOMER — CREATE ORDER (full flow)
# ============================================================
section("CUSTOMER — ORDER FLOW")

if CASHIER_TOKEN:
    # Create order with place+table
    r = test("POST", "/orders/create", 201, {
        "items": [
            {"product_id": 1, "quantity": 2},
            {"product_id": 3, "quantity": 1},
        ],
        "order_type": "HALL",
        "place_id": 1,
        "table_id": 1,
    }, token=CASHIER_TOKEN, label="Create order")

    ORDER_ID = r["data"]["order_id"] if r and r.get("data") else None
    print(f"  Order ID: {ORDER_ID}")

    if ORDER_ID:
        # Get order
        test("GET", f"/orders/{ORDER_ID}", token=CASHIER_TOKEN, label="Get order detail")

        # Add item
        test("POST", f"/orders/{ORDER_ID}/add-item", token=CASHIER_TOKEN, data={
            "product_id": 2, "quantity": 1
        }, label="Add item to order")

        # Mark ready
        test("POST", f"/orders/{ORDER_ID}/ready", token=CASHIER_TOKEN, label="Mark order ready")

        # Pay
        test("POST", f"/orders/{ORDER_ID}/pay", token=CASHIER_TOKEN, label="Pay order")

    # Display endpoints (no auth needed)
    test("GET", "/orders/client-display", label="Client display")
    test("GET", "/orders/chef-display", label="Chef display")

# List orders
test("GET", "/orders", token=CASHIER_TOKEN, label="List customer orders")

# ============================================================
# CUSTOMER — CATEGORIES & PRODUCTS
# ============================================================
section("CUSTOMER — CATEGORIES & PRODUCTS")

test("GET", "/categories", token=CASHIER_TOKEN, label="List categories (customer)")
test("GET", "/categories/active", token=CASHIER_TOKEN, label="Active categories (customer)")
test("GET", "/products", token=CASHIER_TOKEN, label="List products (customer)")

# ============================================================
# WAITER — ORDER FLOW
# ============================================================
section("WAITER — ORDER FLOW")

if WAITER_TOKEN:
    test("GET", "/api/waiters/places", token=WAITER_TOKEN, label="Waiter list places")
    test("GET", "/api/waiters/tables", token=WAITER_TOKEN, label="Waiter list tables")

    r = test("POST", "/api/waiters/orders/create", 201, {
        "items": [{"product_id": 1, "quantity": 1}],
        "place_id": 2,
        "table_id": 3,
    }, token=WAITER_TOKEN, label="Waiter create order")

    W_ORDER_ID = r["data"]["order_id"] if r and r.get("data") else None
    if W_ORDER_ID:
        test("GET", f"/api/waiters/orders/{W_ORDER_ID}", token=WAITER_TOKEN, label="Waiter get order")
        test("GET", "/api/waiters/orders", token=WAITER_TOKEN, label="Waiter my orders")

# ============================================================
# ADMIN — STOCK
# ============================================================
section("ADMIN — STOCK")

test("GET", "/api/admins/stock/settings/", token=ADMIN_TOKEN, label="Stock settings")
test("GET", "/api/admins/stock/locations/", token=ADMIN_TOKEN, label="Stock locations")
test("GET", "/api/admins/stock/units/", token=ADMIN_TOKEN, label="Stock units")
test("GET", "/api/admins/stock/categories/", token=ADMIN_TOKEN, label="Stock categories")
test("GET", "/api/admins/stock/items/", token=ADMIN_TOKEN, label="Stock items")
test("GET", "/api/admins/stock/levels/", token=ADMIN_TOKEN, label="Stock levels")
test("GET", "/api/admins/stock/low-stock/", token=ADMIN_TOKEN, label="Low stock")
test("GET", "/api/admins/stock/transactions/", token=ADMIN_TOKEN, label="Stock transactions")
test("GET", "/api/admins/stock/batches/", token=ADMIN_TOKEN, label="Stock batches")
test("GET", "/api/admins/stock/batches/expiring/", token=ADMIN_TOKEN, label="Expiring batches")
test("GET", "/api/admins/stock/batches/expired/", token=ADMIN_TOKEN, label="Expired batches")
test("GET", "/api/admins/stock/suppliers/", token=ADMIN_TOKEN, label="Suppliers")
test("GET", "/api/admins/stock/purchase-orders/", token=ADMIN_TOKEN, label="Purchase orders")
test("GET", "/api/admins/stock/recipes/", token=ADMIN_TOKEN, label="Recipes")
test("GET", "/api/admins/stock/production-orders/", token=ADMIN_TOKEN, label="Production orders")
test("GET", "/api/admins/stock/transfers/", token=ADMIN_TOKEN, label="Transfers")
test("GET", "/api/admins/stock/counts/", token=ADMIN_TOKEN, label="Stock counts")
test("GET", "/api/admins/stock/variance-codes/", token=ADMIN_TOKEN, label="Variance codes")
test("GET", "/api/admins/stock/product-links/", token=ADMIN_TOKEN, label="Product links")
test("GET", "/api/admins/stock/items/search/?q=test", token=ADMIN_TOKEN, label="Stock item search")
test("GET", "/api/admins/stock/items/stats/", token=ADMIN_TOKEN, label="Stock item stats")
test("GET", "/api/admins/stock/alerts/", token=ADMIN_TOKEN, label="Stock alerts")

# ============================================================
# ADMIN — HR
# ============================================================
section("ADMIN — HR")

test("GET", "/api/admins/hr/departments/", token=ADMIN_TOKEN, label="HR departments")
test("GET", "/api/admins/hr/employees/", token=ADMIN_TOKEN, label="HR employees")
test("GET", "/api/admins/hr/employees/stats/", token=ADMIN_TOKEN, label="HR employee stats")
test("GET", "/api/admins/hr/expense-categories/", token=ADMIN_TOKEN, label="HR expense categories")
test("GET", "/api/admins/hr/expenses/", token=ADMIN_TOKEN, label="HR expenses")
test("GET", "/api/admins/hr/salaries/", token=ADMIN_TOKEN, label="HR salaries")
test("GET", "/api/admins/hr/cash/", token=ADMIN_TOKEN, label="HR cash transactions")
test("GET", "/api/admins/hr/cash/balance/", token=ADMIN_TOKEN, label="HR cash balance")
test("GET", "/api/admins/hr/contracts/", token=ADMIN_TOKEN, label="HR contracts")
test("GET", "/api/admins/hr/contracts/expiring/", token=ADMIN_TOKEN, label="HR expiring contracts")
test("GET", "/api/admins/hr/leave-types/", token=ADMIN_TOKEN, label="HR leave types")
test("GET", "/api/admins/hr/leaves/", token=ADMIN_TOKEN, label="HR leave requests")
test("GET", "/api/admins/hr/leave-balances/", token=ADMIN_TOKEN, label="HR leave balances")
test("GET", "/api/admins/hr/attendance/", token=ADMIN_TOKEN, label="HR attendance")
test("GET", "/api/admins/hr/documents/", token=ADMIN_TOKEN, label="HR documents")
test("GET", "/api/admins/hr/documents/expiring/", token=ADMIN_TOKEN, label="HR expiring docs")
test("GET", "/api/admins/hr/reviews/", token=ADMIN_TOKEN, label="HR reviews")
test("GET", "/api/admins/hr/goals/", token=ADMIN_TOKEN, label="HR goals")
test("GET", "/api/admins/hr/events/", token=ADMIN_TOKEN, label="HR events")

# HR — Create department (no created_by_id — service doesn't accept it)
r = test("POST", "/api/admins/hr/departments/", token=ADMIN_TOKEN, data={
    "name": "Kitchen Staff"
}, label="Create department")

# HR — Cash deposit
test("POST", "/api/admins/hr/cash/deposit/", token=ADMIN_TOKEN, data={
    "amount": 100000, "description": "Opening cash", "payment_method": "CASH"
}, label="Cash deposit")

# ============================================================
# ADMIN — DISCOUNTS
# ============================================================
section("ADMIN — DISCOUNTS")

test("GET", "/api/admins/discounts/types/", token=ADMIN_TOKEN, label="Discount types")
test("GET", "/api/admins/discounts/discounts/", token=ADMIN_TOKEN, label="Discounts list")

# Create discount type
r = test("POST", "/api/admins/discounts/types/", 201, {
    "name": "Percentage Off", "code": "percent", "discount_method": "PERCENTAGE"
}, token=ADMIN_TOKEN, label="Create discount type")
DTYPE_ID = r["data"]["id"] if r and r.get("data") else None

# Create discount
if DTYPE_ID:
    r = test("POST", "/api/admins/discounts/discounts/", 201, {
        "discount_type_id": DTYPE_ID, "name": "10% Off", "code": "SAVE10",
        "value": 10, "applies_to": "ENTIRE_ORDER"
    }, token=ADMIN_TOKEN, label="Create 10% discount")

# Create secret word discount
r = test("POST", "/api/admins/discounts/types/", token=ADMIN_TOKEN, data={
    "name": "Secret Word", "code": "secret-word", "discount_method": "SECRET_WORD"
}, label="Create secret word type")
SW_TYPE_ID = r["data"]["id"] if r and r.get("data") else None

if SW_TYPE_ID:
    test("POST", "/api/admins/discounts/discounts/", token=ADMIN_TOKEN, data={
        "discount_type_id": SW_TYPE_ID, "name": "Alpha Secret", "code": "SECRETALPHA",
        "value": 15, "secret_word": "ALPHA", "applies_to": "ENTIRE_ORDER"
    }, label="Create secret word discount")

# ============================================================
# ADMIN — NOTIFICATIONS
# ============================================================
section("ADMIN — NOTIFICATIONS")

test("GET", "/api/admins/notifications/settings/", token=ADMIN_TOKEN, label="Notification settings")
test("GET", "/api/admins/notifications/settings/status/", token=ADMIN_TOKEN, label="Notification status")
test("GET", "/api/admins/notifications/types/", token=ADMIN_TOKEN, label="Notification types")
test("GET", "/api/admins/notifications/templates/", token=ADMIN_TOKEN, label="Notification templates")
test("GET", "/api/admins/notifications/queue/", token=ADMIN_TOKEN, label="Notification queue")
test("GET", "/api/admins/notifications/logs/", token=ADMIN_TOKEN, label="Notification logs")

# ============================================================
# DISCOUNT — APPLY TO ORDER
# ============================================================
section("DISCOUNT FLOW")

if CASHIER_TOKEN:
    # Create a new order for discount testing
    r = test("POST", "/orders/create", 201, {
        "items": [{"product_id": 1, "quantity": 2}, {"product_id": 3, "quantity": 1}],
        "order_type": "HALL",
    }, token=CASHIER_TOKEN, label="Create order for discount")

    DISC_ORDER_ID = r["data"]["order_id"] if r and r.get("data") else None
    if DISC_ORDER_ID:
        # Apply discount code
        test("POST", f"/orders/{DISC_ORDER_ID}/apply-discount", token=CASHIER_TOKEN, data={
            "code": "SAVE10"
        }, label="Apply SAVE10 discount")

        # Check secret     
        test("POST", f"/orders/{DISC_ORDER_ID}/check-secret-word", token=CASHIER_TOKEN, data={
            "word": "ALPHA"
        }, label="Check secret word ALPHA")

# ============================================================
# ADMIN — STOCK AI
# ============================================================
section("ADMIN — STOCK AI")

test("GET", "/api/admins/stock/ai/suggestions/", token=ADMIN_TOKEN, label="AI suggestions")
test("GET", "/api/admins/stock/ai/quick-actions/", token=ADMIN_TOKEN, label="AI quick actions")

# ============================================================
# RESULTS
# ============================================================
print(f"\n{'='*60}")
print(f"  FINAL RESULTS")
print(f"{'='*60}")
print(f"  PASSED: {RESULTS['pass']}")
print(f"  FAILED: {RESULTS['fail']}")
print(f"  TOTAL:  {RESULTS['pass'] + RESULTS['fail']}")
print(f"  RATE:   {RESULTS['pass']/(RESULTS['pass']+RESULTS['fail'])*100:.1f}%")

if RESULTS["errors"]:
    print(f"\n  FAILURES:")
    for e in RESULTS["errors"]:
        print(e)

# Cleanup: logout
if CASHIER_TOKEN:
    test("POST", "/auth-logout", token=CASHIER_TOKEN, label="Cashier logout")
if WAITER_TOKEN:
    test("POST", "/api/waiters/auth-logout", token=WAITER_TOKEN, label="Waiter logout")
if ADMIN_TOKEN:
    test("POST", "/api/admins/auth-logout", token=ADMIN_TOKEN, label="Admin logout")
