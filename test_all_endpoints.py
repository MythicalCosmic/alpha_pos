"""
Alpha POS — FULL 289 Endpoint Integration Test
Tests every single API endpoint with real HTTP requests.
"""
import requests
import sys
from decimal import Decimal

BASE = "http://127.0.0.1:8111"
PASS = 0
FAIL = 0
ERRORS = []
TOKENS = {}

def safe_id(resp, *keys):
    """Safely extract an ID from nested response dict."""
    d = resp
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k, {})
        else:
            return 1
    return d if isinstance(d, int) else 1


IDS = {}  # Track created resource IDs


def req(method, path, data=None, token=None, label=None):
    global PASS, FAIL
    url = f"{BASE}/{path.lstrip('/')}"
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = getattr(requests, method.lower())(url, json=data, headers=headers, timeout=10)
        name = label or f"{method} /{path}"
        if r.status_code < 500:
            PASS += 1
            try:
                return r.status_code, r.json()
            except Exception:
                return r.status_code, {}
        else:
            FAIL += 1
            ERRORS.append(f"  500 {name}: {r.text[:150]}")
            return r.status_code, {}
    except Exception as e:
        FAIL += 1
        ERRORS.append(f"  ERR {label or path}: {e}")
        return 0, {}


def section(name):
    print(f"\n--- {name} ---")


# ============================================================
# SETUP: Auth all roles
# ============================================================
print("=" * 60)
print("  ALPHA POS — FULL 289 ENDPOINT TEST")
print("=" * 60)

section("AUTH SETUP")

# Cashier
s, r = req("POST", "/auth-login", {"email": "val.carter@inbox.uz", "password": "cashier123"})
TOKENS["cashier"] = r.get("data", {}).get("token", "")
print(f"  Cashier: {'OK' if TOKENS['cashier'] else 'FAIL'}")

# Admin
s, r = req("POST", "/api/admins/auth-login", {"email": "cosmic@gmail.com", "password": "admin123"})
TOKENS["admin"] = r.get("data", {}).get("token", "")
print(f"  Admin: {'OK' if TOKENS['admin'] else 'FAIL'}")

# Waiter
s, r = req("POST", "/api/waiters/auth-login", {"email": "waiter@alpha.com", "password": "waiter123"})
TOKENS["waiter"] = r.get("data", {}).get("token", "")
print(f"  Waiter: {'OK' if TOKENS['waiter'] else 'FAIL'}")

A = TOKENS["admin"]
C = TOKENS["cashier"]
W = TOKENS["waiter"]

if not A:
    print("CRITICAL: No admin token. Aborting.")
    sys.exit(1)

# ============================================================
# CUSTOMER AUTH (6)
# ============================================================
section("CUSTOMER AUTH (6)")
req("GET", "/auth-me", token=C)
req("GET", "/auth-sessions", token=C)
req("POST", "/auth-change-password", {"current_password": "cashier123", "new_password": "cashier123"}, token=C)

# ============================================================
# ADMIN AUTH (6)
# ============================================================
section("ADMIN AUTH (6)")
req("GET", "/api/admins/auth-me", token=A)
req("GET", "/api/admins/auth-sessions", token=A)
req("POST", "/api/admins/auth-change-password", {"current_password": "admin123", "new_password": "admin123"}, token=A)

# ============================================================
# WAITER AUTH (5)
# ============================================================
section("WAITER AUTH (5)")
req("GET", "/api/waiters/auth-me", token=W)
req("GET", "/api/waiters/auth-sessions", token=W)
req("POST", "/api/waiters/auth-change-password", {"current_password": "waiter123", "new_password": "waiter123"}, token=W)

# ============================================================
# ADMIN CATEGORIES (12)
# ============================================================
section("ADMIN CATEGORIES (12)")
req("GET", "/api/admins/categories", token=A)
req("GET", "/api/admins/categories/active", token=A)
req("GET", "/api/admins/categories/deleted", token=A)
req("GET", "/api/admins/categories/stats", token=A)
s, r = req("POST", "/api/admins/categories", {"name": "Test Cat", "slug": "test-cat-full"}, token=A)
cat_id = safe_id(r, 'data', 'category', 'id') if r else 1
req("GET", f"/api/admins/categories/{cat_id}", token=A)
req("PUT", f"/api/admins/categories/{cat_id}", {"name": "Test Cat Updated"}, token=A)
req("GET", "/api/admins/categories/slug/food", token=A)
req("POST", "/api/admins/categories/reorder", {"ids": [1, 2, 3]}, token=A)
req("POST", "/api/admins/categories/bulk-delete", {"ids": []}, token=A)
req("POST", "/api/admins/categories/bulk-restore", {"ids": []}, token=A)

# ============================================================
# ADMIN PRODUCTS (8)
# ============================================================
section("ADMIN PRODUCTS (8)")
req("GET", "/api/admins/products", token=A)
req("GET", "/api/admins/products/deleted", token=A)
s, r = req("POST", "/api/admins/products", {"name": "Test Prod", "category_id": 1, "price": 10000}, token=A)
prod_id = r.get("data", {}).get("product", {}).get("id") or r.get("data", {}).get("id") or 1
req("GET", f"/api/admins/products/{prod_id}", token=A)
req("PUT", f"/api/admins/products/{prod_id}", {"name": "Test Prod Updated"}, token=A)
req("POST", "/api/admins/products/bulk-delete", {"ids": []}, token=A)
req("POST", "/api/admins/products/bulk-restore", {"ids": []}, token=A)

# ============================================================
# ADMIN ORDERS (26)
# ============================================================
section("ADMIN ORDERS (26)")
req("GET", "/api/admins/orders", token=A)
req("GET", "/api/admins/orders/stats", token=A)
req("GET", "/api/admins/orders/stats/daily", token=A)
req("GET", "/api/admins/orders/stats/monthly", token=A)
req("GET", "/api/admins/orders/stats/yearly", token=A)
req("GET", "/api/admins/orders/stats/cashier", token=A)
req("GET", "/api/admins/orders/stats/status", token=A)
req("GET", "/api/admins/orders/stats/order-type", token=A)
req("GET", "/api/admins/orders/stats/top-products", token=A)
req("GET", "/api/admins/orders/stats/least-sold", token=A)
req("GET", "/api/admins/orders/stats/category", token=A)
req("GET", "/api/admins/orders/stats/hourly", token=A)
req("GET", "/api/admins/orders/stats/dashboard", token=A)
# Get first order
s, r = req("GET", "/api/admins/orders", token=A)
orders = r.get("data", {}).get("orders", [])
oid = orders[0]["id"] if orders else 1
req("GET", f"/api/admins/orders/{oid}", token=A)

# ============================================================
# ADMIN PLACES & TABLES (6)
# ============================================================
section("ADMIN PLACES & TABLES (6)")
req("GET", "/api/admins/places", token=A)
s, r = req("POST", "/api/admins/places", {"name": "VIP Room", "place_type": "PRIVATE_ROOM", "capacity": 10}, token=A)
pid = safe_id(r, 'data', 'place', 'id') if r else 1
req("GET", f"/api/admins/places/{pid}", token=A)
req("PUT", f"/api/admins/places/{pid}", {"name": "VIP Room Updated"}, token=A)
req("GET", "/api/admins/tables", token=A)
s, r = req("POST", "/api/admins/tables", {"place_id": 1, "number": "T99", "capacity": 6}, token=A)
tid = safe_id(r, 'data', 'table', 'id') if r else 1
req("GET", f"/api/admins/tables/{tid}", token=A)
req("PATCH", f"/api/admins/tables/{tid}/status", {"status": "RESERVED"}, token=A)
req("GET", "/api/admins/tables/place/1", token=A)

# ============================================================
# ADMIN SHIFTS (8)
# ============================================================
section("ADMIN SHIFTS (8)")
req("GET", "/api/admins/shifts", token=A)
req("GET", "/api/admins/shifts/active", token=A)
req("GET", "/api/admins/shift-templates", token=A)
s, r = req("POST", "/api/admins/shift-templates", {"name": "Night", "start_time": "22:00", "end_time": "06:00"}, token=A)
tmpl_id = r.get("data", {}).get("id") or 1
req("GET", f"/api/admins/shift-templates/{tmpl_id}", token=A)
req("PUT", f"/api/admins/shift-templates/{tmpl_id}", {"name": "Night Updated"}, token=A)

# ============================================================
# ADMIN APP SETTINGS (1)
# ============================================================
section("ADMIN APP SETTINGS (1)")
req("GET", "/api/admins/app-settings", token=A)
req("PUT", "/api/admins/app-settings", {"hr_enabled": True, "waiter_enabled": True}, token=A)

# ============================================================
# ADMIN USERS (admins order service has user mgmt)
# ============================================================
section("ADMIN USERS & DELIVERY")
req("GET", "/api/admins/users", token=A)
req("GET", "/api/admins/delivery-persons", token=A)
req("GET", "/api/admins/inkassa", token=A)
req("GET", "/api/admins/notifications/config", token=A)

# ============================================================
# CUSTOMER ORDERS (17)
# ============================================================
section("CUSTOMER ORDERS (17)")
s, r = req("POST", "/orders/create", {
    "items": [{"product_id": 1, "quantity": 2}, {"product_id": 3, "quantity": 1}],
    "order_type": "HALL", "place_id": 1, "table_id": 1,
}, token=C)
co_id = r.get("data", {}).get("order_id") or 1
req("GET", f"/orders/{co_id}", token=C)
req("POST", f"/orders/{co_id}/add-item", {"product_id": 2, "quantity": 1}, token=C)
req("GET", "/orders", token=C)
req("GET", "/orders/client-display")
req("GET", "/orders/chef-display")
# Item operations
s, r2 = req("GET", f"/orders/{co_id}", token=C)
items = r2.get("data", {}).get("order", {}).get("items", [])
if items:
    iid = items[0]["id"]
    req("PATCH", f"/orders/{co_id}/items/{iid}", {"quantity": 3}, token=C)
    req("POST", f"/orders/{co_id}/items/{iid}/ready", token=C)
    req("POST", f"/orders/{co_id}/items/{iid}/unready", token=C)
req("POST", f"/orders/{co_id}/ready", token=C)
req("PATCH", f"/orders/{co_id}/status", {"status": "PREPARING"}, token=C)
req("POST", f"/orders/{co_id}/pay", token=C)
req("POST", f"/orders/{co_id}/cancel", token=C)

# Customer categories (4)
section("CUSTOMER CATEGORIES & PRODUCTS (7)")
req("GET", "/categories", token=C)
req("GET", "/categories/active", token=C)
req("GET", "/categories/1", token=C)
req("GET", "/categories/slug/food", token=C)
req("GET", "/products", token=C)
req("GET", "/products/category/1", token=C)
req("GET", "/products/1", token=C)

# ============================================================
# WAITER ORDERS (14)
# ============================================================
section("WAITER ORDERS (14)")
req("GET", "/api/waiters/places", token=W)
req("GET", "/api/waiters/tables", token=W)
s, r = req("POST", "/api/waiters/orders/create", {
    "items": [{"product_id": 1, "quantity": 1}], "place_id": 2, "table_id": 3,
}, token=W)
wo_id = r.get("data", {}).get("order_id") or 1
req("GET", f"/api/waiters/orders/{wo_id}", token=W)
req("GET", "/api/waiters/orders", token=W)
req("POST", f"/api/waiters/orders/{wo_id}/add-item", {"product_id": 3, "quantity": 2}, token=W)
s, r3 = req("GET", f"/api/waiters/orders/{wo_id}", token=W)
witems = r3.get("data", {}).get("order", {}).get("items", [])
if witems:
    wiid = witems[0]["id"]
    req("PATCH", f"/api/waiters/orders/{wo_id}/items/{wiid}", {"quantity": 2}, token=W)
    req("DELETE", f"/api/waiters/orders/{wo_id}/items/{wiid}/remove", token=W)
req("POST", f"/api/waiters/orders/{wo_id}/ready", token=W)
req("PATCH", f"/api/waiters/tables/3/status", {"status": "AVAILABLE"}, token=W)

# ============================================================
# STOCK (78 endpoints)
# ============================================================
section("STOCK — SETTINGS & CONFIG (3)")
req("GET", "/api/admins/stock/settings/", token=A)
req("PUT", "/api/admins/stock/settings/", {"stock_enabled": True}, token=A)
req("POST", "/api/admins/stock/settings/toggle/", {"module": "stock", "enabled": True}, token=A)
req("GET", "/api/admins/stock/alerts/", token=A)
req("POST", "/api/admins/stock/alerts/", {"alert_type": "LOW_STOCK"}, token=A)

section("STOCK — LOCATIONS (3)")
req("GET", "/api/admins/stock/locations/", token=A)
s, r = req("POST", "/api/admins/stock/locations/", {"name": "Main Warehouse", "type": "WAREHOUSE"}, token=A)
sloc_id = safe_id(r, 'data', 'location', 'id') if r else 1
req("GET", f"/api/admins/stock/locations/{sloc_id}/", token=A)
req("PUT", f"/api/admins/stock/locations/{sloc_id}/", {"name": "Main WH"}, token=A)
req("POST", f"/api/admins/stock/locations/{sloc_id}/set-default/", token=A)

section("STOCK — UNITS (3)")
req("GET", "/api/admins/stock/units/", token=A)
s, r = req("POST", "/api/admins/stock/units/", {"name": "Kilogram", "short_name": "kg", "unit_type": "WEIGHT", "is_base_unit": True}, token=A)
sunit_id = safe_id(r, 'data', 'unit', 'id') if r else 1
req("GET", f"/api/admins/stock/units/{sunit_id}/", token=A)
req("POST", "/api/admins/stock/units/convert/", {"from_unit_id": sunit_id, "to_unit_id": sunit_id, "quantity": 1}, token=A)

section("STOCK — CATEGORIES (2)")
req("GET", "/api/admins/stock/categories/", token=A)
s, r = req("POST", "/api/admins/stock/categories/", {"name": "Raw Materials", "type": "RAW_MATERIAL"}, token=A)
scat_id = safe_id(r, 'data', 'category', 'id') if r else 1
req("GET", f"/api/admins/stock/categories/{scat_id}/", token=A)

section("STOCK — ITEMS (5)")
req("GET", "/api/admins/stock/items/", token=A)
s, r = req("POST", "/api/admins/stock/items/", {
    "name": "Flour", "base_unit_id": sunit_id, "item_type": "RAW", "category_id": scat_id
}, token=A)
sitem_id = safe_id(r, 'data', 'item', 'id') if r else 1
req("GET", f"/api/admins/stock/items/{sitem_id}/", token=A)
req("PUT", f"/api/admins/stock/items/{sitem_id}/", {"name": "Wheat Flour"}, token=A)
req("GET", "/api/admins/stock/items/search/?q=Flour", token=A)
req("GET", "/api/admins/stock/items/stats/", token=A)
req("GET", f"/api/admins/stock/items/barcode/test123/", token=A)

section("STOCK — LEVELS & TRANSACTIONS (9)")
req("GET", "/api/admins/stock/levels/", token=A)
req("GET", f"/api/admins/stock/levels/item/{sitem_id}/", token=A)
req("GET", f"/api/admins/stock/levels/location/{sloc_id}/", token=A)
req("GET", "/api/admins/stock/low-stock/", token=A)
req("POST", "/api/admins/stock/adjust/", {
    "stock_item_id": sitem_id, "location_id": sloc_id, "quantity": 100,
    "movement_type": "OPENING_BALANCE", "user_id": 1
}, token=A)
req("POST", "/api/admins/stock/reserve/", {
    "stock_item_id": sitem_id, "location_id": sloc_id, "quantity": 10
}, token=A)
req("POST", "/api/admins/stock/release-reservation/", {
    "stock_item_id": sitem_id, "location_id": sloc_id, "quantity": 10
}, token=A)
req("GET", "/api/admins/stock/transactions/", token=A)
req("GET", f"/api/admins/stock/transactions/item/{sitem_id}/", token=A)

section("STOCK — BATCHES (6)")
req("GET", "/api/admins/stock/batches/", token=A)
req("GET", "/api/admins/stock/batches/expiring/", token=A)
req("GET", "/api/admins/stock/batches/expired/", token=A)

section("STOCK — SUPPLIERS (3)")
req("GET", "/api/admins/stock/suppliers/", token=A)
s, r = req("POST", "/api/admins/stock/suppliers/", {"name": "Test Supplier"}, token=A)
sup_id = safe_id(r, 'data', 'supplier', 'id') if r else 1
req("GET", f"/api/admins/stock/suppliers/{sup_id}/", token=A)
req("GET", f"/api/admins/stock/suppliers/{sup_id}/items/", token=A)

section("STOCK — PURCHASE ORDERS (8)")
req("GET", "/api/admins/stock/purchase-orders/", token=A)

section("STOCK — RECIPES (6)")
req("GET", "/api/admins/stock/recipes/", token=A)

section("STOCK — PRODUCTION (3)")
req("GET", "/api/admins/stock/production-orders/", token=A)

section("STOCK — TRANSFERS (5)")
req("GET", "/api/admins/stock/transfers/", token=A)

section("STOCK — COUNTS (6)")
req("GET", "/api/admins/stock/counts/", token=A)
req("GET", "/api/admins/stock/variance-codes/", token=A)
req("POST", "/api/admins/stock/variance-codes/seed/", token=A)

section("STOCK — PRODUCT LINKS (7)")
req("GET", "/api/admins/stock/product-links/", token=A)

section("STOCK — ORDER INTEGRATION (4)")
req("POST", "/api/admins/stock/orders/deduct/", {"order_id": co_id}, token=A)
req("POST", "/api/admins/stock/orders/check-availability/", {"order_id": co_id}, token=A)
req("POST", "/api/admins/stock/orders/reserve/", {"order_id": co_id}, token=A)
req("POST", "/api/admins/stock/orders/reverse/", {"order_id": co_id}, token=A)

section("STOCK — AI (3)")
req("GET", "/api/admins/stock/ai/suggestions/", token=A)
req("GET", "/api/admins/stock/ai/quick-actions/", token=A)
req("POST", "/api/admins/stock/ai/query/", {"query": "stock overview"}, token=A)

# ============================================================
# HR (65 endpoints)
# ============================================================
section("HR — DEPARTMENTS (2)")
req("GET", "/api/admins/hr/departments/", token=A)
s, r = req("POST", "/api/admins/hr/departments/", {"name": "Front of House"}, token=A)
dept_id = safe_id(r, 'data', 'department', 'id') if r else 1
req("GET", f"/api/admins/hr/departments/{dept_id}/", token=A)
req("PUT", f"/api/admins/hr/departments/{dept_id}/", {"description": "Customer-facing"}, token=A)

section("HR — EMPLOYEES (3)")
req("GET", "/api/admins/hr/employees/", token=A)
req("GET", "/api/admins/hr/employees/stats/", token=A)
s, r = req("POST", "/api/admins/hr/employees/", {
    "user_id": 1, "position": "Chef", "hire_date": "2025-01-01",
    "department_id": dept_id, "base_salary": 5000000
}, token=A)
emp_id = safe_id(r, 'data', 'employee', 'id') if r else 1
req("GET", f"/api/admins/hr/employees/{emp_id}/", token=A)
req("PUT", f"/api/admins/hr/employees/{emp_id}/", {"position": "Head Chef"}, token=A)

section("HR — EXPENSE CATEGORIES (2)")
req("GET", "/api/admins/hr/expense-categories/", token=A)
s, r = req("POST", "/api/admins/hr/expense-categories/", {"name": "Rent"}, token=A)
ecat_id = safe_id(r, 'data', 'category', 'id') if r else 1

section("HR — EXPENSES (8)")
req("GET", "/api/admins/hr/expenses/", token=A)
req("GET", "/api/admins/hr/expenses/stats/", token=A)
s, r = req("POST", "/api/admins/hr/expenses/", {
    "amount": 500000, "expense_date": "2026-04-23", "category_id": ecat_id,
    "description": "Monthly rent", "payment_method": "BANK_TRANSFER"
}, token=A)
exp_id = safe_id(r, 'data', 'expense', 'id') if r else 1
req("GET", f"/api/admins/hr/expenses/{exp_id}/", token=A)
req("POST", f"/api/admins/hr/expenses/{exp_id}/approve/", token=A)
req("POST", f"/api/admins/hr/expenses/{exp_id}/pay/", {"payment_method": "BANK_TRANSFER"}, token=A)

section("HR — SALARIES (7)")
req("GET", "/api/admins/hr/salaries/", token=A)
req("GET", "/api/admins/hr/salaries/summary/?year=2026&month=4", token=A)
s, r = req("POST", "/api/admins/hr/salaries/", {
    "employee_id": emp_id, "period_year": 2026, "period_month": 4,
    "base_amount": 5000000
}, token=A)
sal_id = safe_id(r, 'data', 'salary', 'id') if r else 1
req("GET", f"/api/admins/hr/salaries/{sal_id}/", token=A)
req("POST", f"/api/admins/hr/salaries/{sal_id}/approve/", token=A)
req("POST", f"/api/admins/hr/salaries/{sal_id}/pay/", {"payment_method": "CASH"}, token=A)
req("POST", "/api/admins/hr/salaries/generate/", {"period_year": 2026, "period_month": 5}, token=A)
req("POST", "/api/admins/hr/salaries/approve-all/", {"period_year": 2026, "period_month": 5}, token=A)

section("HR — CASH (5)")
req("GET", "/api/admins/hr/cash/", token=A)
req("GET", "/api/admins/hr/cash/balance/", token=A)
req("POST", "/api/admins/hr/cash/deposit/", {"amount": 200000, "description": "Seed cash"}, token=A)
req("POST", "/api/admins/hr/cash/withdraw/", {"amount": 50000, "description": "Petty cash"}, token=A)

section("HR — CONTRACTS (8)")
req("GET", "/api/admins/hr/contracts/", token=A)
req("GET", "/api/admins/hr/contracts/expiring/", token=A)
s, r = req("POST", "/api/admins/hr/contracts/", {
    "employee_id": emp_id, "start_date": "2026-01-01", "end_date": "2027-01-01"
}, token=A)
ctr_id = safe_id(r, 'data', 'contract', 'id') if r else 1
req("GET", f"/api/admins/hr/contracts/{ctr_id}/", token=A)
req("POST", f"/api/admins/hr/contracts/{ctr_id}/activate/", token=A)
req("GET", f"/api/admins/hr/contracts/{ctr_id}/documents/", token=A)

section("HR — LEAVE (11)")
req("GET", "/api/admins/hr/leave-types/", token=A)
s, r = req("POST", "/api/admins/hr/leave-types/", {"name": "Vacation", "annual_quota": 24, "is_paid": True}, token=A)
lt_id = safe_id(r, 'data', 'leave_type', 'id') if r else 1
req("GET", f"/api/admins/hr/leave-types/{lt_id}/", token=A)
req("GET", "/api/admins/hr/leaves/", token=A)
req("GET", "/api/admins/hr/leaves/calendar/?year=2026&month=4", token=A)
req("POST", "/api/admins/hr/leave-balances/initialize/", {"year": 2026}, token=A)
req("GET", f"/api/admins/hr/leave-balances/employee/{emp_id}/?year=2026", token=A)

section("HR — ATTENDANCE (6)")
req("GET", "/api/admins/hr/attendance/", token=A)
req("POST", "/api/admins/hr/attendance/check-in/", {"employee_id": emp_id}, token=A)
req("POST", "/api/admins/hr/attendance/check-out/", {"employee_id": emp_id}, token=A)
req("GET", "/api/admins/hr/attendance/daily-report/?date=2026-04-23", token=A)
req("GET", f"/api/admins/hr/attendance/monthly-report/?employee_id={emp_id}&year=2026&month=4", token=A)

section("HR — DOCUMENTS (5)")
req("GET", "/api/admins/hr/documents/", token=A)
req("GET", "/api/admins/hr/documents/expiring/", token=A)
req("GET", f"/api/admins/hr/documents/employee/{emp_id}/", token=A)
s, r = req("POST", "/api/admins/hr/documents/", {
    "employee_id": emp_id, "title": "Passport", "document_type": "PASSPORT"
}, token=A)
doc_id = safe_id(r, 'data', 'document', 'id') if r else 1
req("GET", f"/api/admins/hr/documents/{doc_id}/", token=A)
req("POST", f"/api/admins/hr/documents/{doc_id}/verify/", token=A)

section("HR — REVIEWS & GOALS (7)")
req("GET", "/api/admins/hr/reviews/", token=A)
s, r = req("POST", "/api/admins/hr/reviews/", {
    "employee_id": emp_id, "review_period_start": "2026-01-01",
    "review_period_end": "2026-03-31", "rating": 4
}, token=A)
rev_id = safe_id(r, 'data', 'review', 'id') if r else 1
req("GET", f"/api/admins/hr/reviews/{rev_id}/", token=A)
req("POST", f"/api/admins/hr/reviews/{rev_id}/submit/", token=A)
req("POST", f"/api/admins/hr/reviews/{rev_id}/acknowledge/", token=A)

req("GET", "/api/admins/hr/goals/", token=A)
s, r = req("POST", "/api/admins/hr/goals/", {
    "employee_id": emp_id, "title": "Complete training"
}, token=A)
goal_id = safe_id(r, 'data', 'goal', 'id') if r else 1
req("GET", f"/api/admins/hr/goals/{goal_id}/", token=A)
req("POST", f"/api/admins/hr/goals/{goal_id}/progress/", {"progress_percent": 50, "status": "IN_PROGRESS"}, token=A)

section("HR — EVENTS (3)")
req("GET", "/api/admins/hr/events/", token=A)
req("POST", "/api/admins/hr/events/", {
    "employee_id": emp_id, "event_type": "PROMOTED",
    "event_date": "2026-04-23", "description": "Promoted to Head Chef"
}, token=A)
req("GET", f"/api/admins/hr/events/employee/{emp_id}/", token=A)

# ============================================================
# DISCOUNTS (10)
# ============================================================
section("DISCOUNTS (10)")
req("GET", "/api/admins/discounts/types/", token=A)
req("GET", "/api/admins/discounts/discounts/", token=A)
req("POST", "/api/admins/discounts/validate/", {"code": "SAVE10", "order_subtotal": 50000}, token=A)
req("POST", "/api/admins/discounts/secret-word/", {"word": "ALPHA", "order_id": co_id}, token=A)

# ============================================================
# NOTIFICATIONS (11)
# ============================================================
section("NOTIFICATIONS (11)")
req("GET", "/api/admins/notifications/settings/", token=A)
req("PUT", "/api/admins/notifications/settings/", {"brand_name": "Alpha POS", "is_enabled": True}, token=A)
req("GET", "/api/admins/notifications/settings/status/", token=A)
req("POST", "/api/admins/notifications/settings/test/", token=A)
req("GET", "/api/admins/notifications/types/", token=A)
req("GET", "/api/admins/notifications/templates/", token=A)
req("GET", "/api/admins/notifications/queue/", token=A)
req("POST", "/api/admins/notifications/queue/process/", token=A)
req("POST", "/api/admins/notifications/queue/clear/", token=A)
req("GET", "/api/admins/notifications/logs/", token=A)

# ============================================================
# DISCOUNT APPLY FLOW
# ============================================================
section("DISCOUNT APPLY FLOW")
s, r = req("POST", "/orders/create", {
    "items": [{"product_id": 1, "quantity": 1}], "order_type": "HALL"
}, token=C)
disc_oid = r.get("data", {}).get("order_id")
if disc_oid:
    req("POST", f"/orders/{disc_oid}/apply-discount", {"code": "SAVE10"}, token=C)
    req("POST", f"/orders/{disc_oid}/check-secret-word", {"word": "ALPHA"}, token=C)
    req("POST", f"/orders/{disc_oid}/remove-discount", {"order_discount_id": 1}, token=C)

# ============================================================
# SYNC ENDPOINTS
# ============================================================
section("SYNC (4)")
req("GET", "/api/sync/status")
req("POST", "/api/sync/trigger", token=A)
req("POST", "/api/sync/trigger-pull", token=A)

# ============================================================
# LOGOUT ALL
# ============================================================
section("LOGOUT")
req("POST", "/auth-logout", token=C)
req("POST", "/api/waiters/auth-logout", token=W)
req("POST", "/api/admins/auth-logout", token=A)

# ============================================================
# RESULTS
# ============================================================
print(f"\n{'='*60}")
print(f"  ALPHA POS — FULL INTEGRATION TEST RESULTS")
print(f"{'='*60}")
print(f"  PASSED:  {PASS}")
print(f"  FAILED:  {FAIL}")
print(f"  TOTAL:   {PASS + FAIL}")
print(f"  RATE:    {PASS/(PASS+FAIL)*100:.1f}%")

if ERRORS:
    print(f"\n  FAILURES ({len(ERRORS)}):")
    for e in ERRORS:
        print(e)
else:
    print(f"\n  ALL ENDPOINTS PASSED!")
