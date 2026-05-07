"""Regression tests for base / sync bugs."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone


pytestmark = pytest.mark.django_db


class TestSyncConflictTiebreaker:
    """Pre-fix: from_sync_dict accepted on `>=`, so two branches landing at
    the same sync_version silently let whichever-arrived-second overwrite.
    Now: strict `>`, with updated_at/branch_id deterministic tiebreakers."""

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

    def test_equal_version_newer_updated_at_wins(self):
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
        assert local.first_name == 'Newer'

    def test_equal_version_older_updated_at_loses(self):
        from base.models import User

        local = User.objects.create(
            first_name='Local', last_name='Name', email='u@test.local',
            password='hashed', role='USER', sync_version=3,
        )
        past = (timezone.now() - timedelta(hours=1)).isoformat()

        User.from_sync_dict({
            'uuid': str(local.uuid),
            'sync_version': 3,
            'is_deleted': False,
            'first_name': 'Older',
            'last_name': 'Name',
            'email': 'u@test.local',
            'password': 'hashed',
            'role': 'USER',
            'updated_at': past,
        })
        local.refresh_from_db()
        assert local.first_name == 'Local'


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
