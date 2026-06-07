"""Regression tests for base / sync bugs."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.test import override_settings
from django.utils import timezone


pytestmark = pytest.mark.django_db


class TestSyncConflictTiebreaker:
    """Higher sync_version always wins. On an equal-version conflict the policy
    is BRANCH-dominant: a branch (mode='local') keeps its own row, while the
    cloud (mode='cloud') accepts the incoming branch push. This is deterministic
    and doesn't depend on cross-machine clock skew."""

    def test_higher_version_wins(self):
        from base.models import User

        local = User.objects.create(
            first_name='Old', last_name='Name', email='u@test.local',
            password='hashed', role='USER', sync_version=2,
        )
        User.from_sync_dict({
            'uuid': str(local.uuid),
            'sync_version': 3,
            'is_deleted': False,
            'first_name': 'New',
            'last_name': 'Name',
            'email': 'u@test.local',
            'password': 'hashed',
            'role': 'USER',
        })
        local.refresh_from_db()
        assert local.first_name == 'New'

    def test_lower_version_does_not_overwrite(self):
        from base.models import User

        local = User.objects.create(
            first_name='Local', last_name='Name', email='u@test.local',
            password='hashed', role='USER', sync_version=5,
        )
        User.from_sync_dict({
            'uuid': str(local.uuid),
            'sync_version': 3,
            'is_deleted': False,
            'first_name': 'Old',
            'last_name': 'Name',
            'email': 'u@test.local',
            'password': 'hashed',
            'role': 'USER',
        })
        local.refresh_from_db()
        assert local.first_name == 'Local', 'older version must not overwrite'

    def test_equal_version_branch_keeps_local_even_if_incoming_newer(self):
        """On a branch (mode='local'), an equal-version conflict keeps the local
        row — the branch dominates the cloud — even when the incoming record has
        a newer updated_at. (Old policy let newer updated_at win; reversed per
        operator decision so a branch's data is never clobbered on a tie.)"""
        from base.models import User

        local = User.objects.create(
            first_name='Local', last_name='Name', email='u@test.local',
            password='hashed', role='USER', sync_version=3,
        )
        future = (timezone.now() + timedelta(hours=1)).isoformat()

        User.from_sync_dict({
            'uuid': str(local.uuid),
            'sync_version': 3,
            'is_deleted': False,
            'first_name': 'Newer',
            'last_name': 'Name',
            'email': 'u@test.local',
            'password': 'hashed',
            'role': 'USER',
            'updated_at': future,
        })
        local.refresh_from_db()
        assert local.first_name == 'Local'

    @override_settings(DEPLOYMENT_MODE='cloud')
    def test_equal_version_cloud_accepts_branch_push(self):
        """On the cloud (mode='cloud'), an equal-version conflict accepts the
        incoming branch push — the branch is the source of truth."""
        from base.models import User

        local = User.objects.create(
            first_name='Local', last_name='Name', email='u@test.local',
            password='hashed', role='USER', sync_version=3,
        )
        User.from_sync_dict({
            'uuid': str(local.uuid),
            'sync_version': 3,
            'is_deleted': False,
            'first_name': 'FromBranch',
            'last_name': 'Name',
            'email': 'u@test.local',
            'password': 'hashed',
            'role': 'USER',
        })
        local.refresh_from_db()
        assert local.first_name == 'FromBranch'


class TestUserCredentialSync:
    """Central user management: the owner creates/edits users on the cloud hub
    and they must work on every terminal. So sync propagates the password HASH
    (PBKDF2, portable across machines), role, permissions and status — single-
    tenant deployment, the cloud and branches are one operator's. (This
    deliberately reverses the earlier denylist; see User.SYNC_WRITE_DENYLIST.)"""

    def test_pull_propagates_credentials_and_role(self):
        from base.models import User

        local = User.objects.create(
            first_name='Local', last_name='Name', email='u@test.local',
            password='old-hash', role='USER', sync_version=2,
        )
        User.from_sync_dict({
            'uuid': str(local.uuid),
            'sync_version': 3,
            'is_deleted': False,
            'first_name': 'Local',
            'last_name': 'Name',
            'email': 'u@test.local',
            'password': 'new-hash',
            'role': 'ADMIN',
            'status': 'ACTIVE',
            'permissions': ['stock.view'],
        })
        local.refresh_from_db()
        assert local.role == 'ADMIN'
        assert local.password == 'new-hash'
        assert local.permissions == ['stock.view']

    def test_pull_reconciles_email_collision_instead_of_dropping(self):
        # A server-created user whose email matches an existing local row (e.g.
        # a bootstrap admin) must reconcile onto that row, not raise an
        # IntegrityError that silently drops it. The local row converges on the
        # incoming uuid.
        from base.models import User
        import uuid as uuid_module

        local = User.objects.create(
            first_name='Boot', last_name='Admin', email='admin@test.local',
            password='boot-hash', role='ADMIN', sync_version=1,
        )
        incoming_uuid = str(uuid_module.uuid4())
        instance, action = User.from_sync_dict({
            'uuid': incoming_uuid,
            'sync_version': 5,
            'is_deleted': False,
            'first_name': 'Server',
            'last_name': 'Admin',
            'email': 'admin@test.local',
            'password': 'server-hash',
            'role': 'ADMIN',
            'status': 'ACTIVE',
        })
        assert action == 'updated'
        assert User.objects.filter(email='admin@test.local').count() == 1
        reconciled = User.objects.get(email='admin@test.local')
        assert str(reconciled.uuid) == incoming_uuid
        assert reconciled.first_name == 'Server'
        assert reconciled.password == 'server-hash'

    def test_receive_ignores_spoofed_branch_id(self):
        from base.models import User
        from base.services.sync.receiver import CloudReceiver

        result = CloudReceiver.receive_batch(
            'base.User',
            branch_id='branch-a',
            records=[{
                'uuid': '11111111-1111-1111-1111-111111111111',
                'sync_version': 1,
                'is_deleted': False,
                # Attacker-controlled spoof attempt; receiver must ignore it.
                'branch_id': 'branch-b',
                'first_name': 'Spoof', 'last_name': 'Try',
                'email': 'spoof@test.local',
            }],
        )
        assert result['created'] == 1
        u = User.objects.get(uuid='11111111-1111-1111-1111-111111111111')
        assert u.branch_id == 'branch-a'


class TestDurableSyncQueue:
    """Pre-fix: queue lived only in cache; LocMem default lost it on
    process restart and Redis crashes between flushes lost unsent records.
    Now: SyncQueueRecord row per (model, uuid) survives process restart."""

    def test_add_persists_to_db(self):
        from base.services.sync.queue import SyncQueue
        from base.models import SyncQueueRecord
        import uuid as uuid_module

        u = uuid_module.uuid4()
        SyncQueue.add('user', str(u), {'uuid': str(u), 'first_name': 'Persisted'})

        assert SyncQueueRecord.objects.filter(record_uuid=u).exists()

    def test_add_is_upsert_on_model_uuid(self):
        from base.services.sync.queue import SyncQueue
        from base.models import SyncQueueRecord
        import uuid as uuid_module

        u = uuid_module.uuid4()
        SyncQueue.add('user', str(u), {'first_name': 'V1'})
        SyncQueue.add('user', str(u), {'first_name': 'V2'})

        rows = SyncQueueRecord.objects.filter(record_uuid=u)
        assert rows.count() == 1
        assert rows.first().payload['first_name'] == 'V2'

    def test_remove_deletes_rows(self):
        from base.services.sync.queue import SyncQueue
        from base.models import SyncQueueRecord
        import uuid as uuid_module

        u1, u2 = uuid_module.uuid4(), uuid_module.uuid4()
        SyncQueue.add('user', str(u1), {'first_name': 'A'})
        SyncQueue.add('user', str(u2), {'first_name': 'B'})

        SyncQueue.remove([str(u1)])
        assert not SyncQueueRecord.objects.filter(record_uuid=u1).exists()
        assert SyncQueueRecord.objects.filter(record_uuid=u2).exists()

    def test_count_distinguishes_failed(self):
        from base.services.sync.queue import SyncQueue
        from base.models import SyncQueueRecord
        import uuid as uuid_module

        u1, u2 = uuid_module.uuid4(), uuid_module.uuid4()
        SyncQueue.add('user', str(u1), {'first_name': 'A'})
        SyncQueue.add('user', str(u2), {'first_name': 'B'})
        SyncQueue.mark_failed(str(u1), 'transport error')

        total, failed = SyncQueue.count()
        assert total == 2
        assert failed == 1


class TestInkassaAtomic:
    """InkassaService.add_to_register must use F() so two concurrent calls
    don't lose updates. Verify F-expression behavior with sequential adds."""

    def test_sequential_increments_accumulate(self):
        from base.models import CashRegister
        from base.services.inkassa_service import InkassaService

        CashRegister.objects.create(current_balance=Decimal('0'))
        InkassaService.add_to_register(Decimal('100'))
        InkassaService.add_to_register(Decimal('50'))
        InkassaService.add_to_register(Decimal('25'))

        register = CashRegister.objects.first()
        assert register.current_balance == Decimal('175')


class TestPartialUniqueAllowsEmpty:
    """Regression: partial unique constraints must NOT constrain empty values —
    many categories have no slug. This broke cloud sync with
    'duplicate key ... uniq_category_slug_active ... slug=()'."""

    def test_multiple_empty_slug_categories_ok(self):
        from base.models import Category
        Category.objects.create(name='A', slug='')
        Category.objects.create(name='B', slug='')
        assert Category.objects.filter(slug='').count() == 2

    def test_nonempty_slug_still_unique(self):
        from base.models import Category
        from django.db import IntegrityError, transaction
        Category.objects.create(name='A', slug='drinks')
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Category.objects.create(name='B', slug='drinks')


class TestCategorySlugReconcile:
    """Sync must reconcile an incoming category onto an existing same-slug row
    instead of INSERTing a duplicate (UNIQUE constraint failed: base_category.slug)."""

    def test_slug_collision_reconciles_not_inserts(self):
        from base.models import Category
        import uuid as _uuid
        Category.objects.create(name='Drinks', slug='drinks', sync_version=1)
        incoming = str(_uuid.uuid4())
        inst, action = Category.from_sync_dict({
            'uuid': incoming, 'sync_version': 5, 'is_deleted': False,
            'name': 'Beverages', 'slug': 'drinks',
        })
        assert action == 'updated'
        assert Category.objects.filter(slug='drinks').count() == 1
        assert str(Category.objects.get(slug='drinks').uuid) == incoming

    def test_empty_slug_incoming_inserts(self):
        from base.models import Category
        import uuid as _uuid
        Category.objects.create(name='A', slug='', sync_version=1)
        inst, action = Category.from_sync_dict({
            'uuid': str(_uuid.uuid4()), 'sync_version': 1, 'is_deleted': False,
            'name': 'B', 'slug': '',
        })
        assert action == 'created'
        assert Category.objects.filter(slug='').count() == 2


class TestRehashPasswords:
    """Repair for users created via Django /admin/ with a plaintext PIN."""

    def test_plaintext_pin_rehashed_and_verifies(self):
        from base.models import User
        from base.security.hashing import verify_password
        from django.core.management import call_command
        u = User.objects.create(
            first_name='P', last_name='IN', email='pin@t.local',
            password='2233', role='CASHIER', status='ACTIVE')
        # Plaintext can't be verified by check_password — this is the 401 cause.
        assert verify_password('2233', u.password) is False
        call_command('rehash_passwords', verbosity=0)
        u.refresh_from_db()
        assert verify_password('2233', u.password) is True

    def test_existing_hash_left_untouched(self):
        from base.models import User
        from base.security.hashing import hash_password, verify_password
        from django.core.management import call_command
        h = hash_password('9999')
        u = User.objects.create(
            first_name='H', last_name='Ash', email='hash@t.local',
            password=h, role='CASHIER', status='ACTIVE')
        call_command('rehash_passwords', verbosity=0)
        u.refresh_from_db()
        assert u.password == h  # untouched
        assert verify_password('9999', u.password) is True
