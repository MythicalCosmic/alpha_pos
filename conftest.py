import os

import django
import pytest

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'alpha_pos.settings')
os.environ.setdefault('DEBUG', 'True')
os.environ.setdefault('SECRET_KEY', 'pytest-secret-key')

django.setup()


@pytest.fixture
def admin_user(db):
    from base.models import User
    from base.security.hashing import hash_password
    return User.objects.create(
        first_name='Admin',
        last_name='Tester',
        email='admin@test.local',
        password=hash_password('adminpass'),
        role=User.RoleChoices.ADMIN,
        status=User.UserStatus.ACTIVE,
    )


@pytest.fixture
def cashier_user(db):
    from base.models import User
    from base.security.hashing import hash_password
    return User.objects.create(
        first_name='Cashier',
        last_name='One',
        email='cashier1@test.local',
        password=hash_password('cashierpass'),
        role=User.RoleChoices.CASHIER,
        status=User.UserStatus.ACTIVE,
    )


@pytest.fixture
def other_cashier_user(db):
    from base.models import User
    from base.security.hashing import hash_password
    return User.objects.create(
        first_name='Cashier',
        last_name='Two',
        email='cashier2@test.local',
        password=hash_password('cashierpass'),
        role=User.RoleChoices.CASHIER,
        status=User.UserStatus.ACTIVE,
    )


@pytest.fixture
def regular_user(db):
    from base.models import User
    from base.security.hashing import hash_password
    return User.objects.create(
        first_name='User',
        last_name='One',
        email='user1@test.local',
        password=hash_password('userpass'),
        role=User.RoleChoices.USER,
        status=User.UserStatus.ACTIVE,
    )


@pytest.fixture
def other_user(db):
    from base.models import User
    from base.security.hashing import hash_password
    return User.objects.create(
        first_name='User',
        last_name='Two',
        email='user2@test.local',
        password=hash_password('userpass'),
        role=User.RoleChoices.USER,
        status=User.UserStatus.ACTIVE,
    )


@pytest.fixture
def category(db):
    from base.models import Category
    return Category.objects.create(name='Test Category')


@pytest.fixture
def product(db, category):
    from base.models import Product
    return Product.objects.create(
        name='Test Product', price='10.00', category=category,
    )


@pytest.fixture
def order_factory(db, regular_user, product):
    from base.models import Order, OrderItem

    def _make(user=None, cashier=None, status='PREPARING', is_paid=False, items=1):
        order = Order.objects.create(
            user=user or regular_user,
            cashier=cashier,
            order_type='HALL',
            status=status,
            is_paid=is_paid,
            display_id=Order.objects.count() + 1,
            subtotal='10.00',
            total_amount='10.00',
        )
        for _ in range(items):
            OrderItem.objects.create(
                order=order, product=product, quantity=1, price=product.price,
            )
        return order

    return _make
