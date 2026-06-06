import uuid
from decimal import Decimal
from django.db import models, transaction
from django.conf import settings


class SyncQuerySet(models.QuerySet):
    def unsynced(self):
        return self.filter(synced_at__isnull=True)

    def from_branch(self, branch_id):
        return self.filter(branch_id=branch_id)

    def active(self):
        return self.filter(is_deleted=False)


class SyncManager(models.Manager):
    def get_queryset(self):
        return SyncQuerySet(self.model, using=self._db)

    def unsynced(self):
        return self.get_queryset().unsynced()

    def active(self):
        return self.get_queryset().active()


class SyncMixin(models.Model):
    uuid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_index=True,
    )
    synced_at = models.DateTimeField(null=True, blank=True, db_index=True)
    sync_version = models.PositiveIntegerField(default=1)
    is_deleted = models.BooleanField(default=False, db_index=True)
    branch_id = models.CharField(max_length=50, blank=True, default='', db_index=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        syncing = kwargs.pop('_syncing', False)
        if not syncing:
            if not self.branch_id and hasattr(settings, 'BRANCH_ID'):
                self.branch_id = settings.BRANCH_ID
            if self.pk:
                self.sync_version += 1
            mode = getattr(settings, 'DEPLOYMENT_MODE', 'local')
            update_fields = kwargs.get('update_fields')
            content_changed = update_fields is None or any(
                f not in ['synced_at', 'sync_version'] for f in update_fields
            )
            if content_changed:
                if mode == 'local':
                    # Branch: mark pending so the push worker sends it to the hub.
                    self.synced_at = None
                elif mode == 'cloud':
                    # Hub: publish records it originates with a timestamp so the
                    # /changes cursor hands them to branches on pull. (Records
                    # RECEIVED from a branch run with _syncing=True and skip this.)
                    from django.utils import timezone
                    self.synced_at = timezone.now()
        super().save(*args, **kwargs)
        if not syncing and self.synced_at is None and self._is_sync_on_save():
            # Defer queueing until the surrounding transaction commits so a
            # rollback doesn't leave an orphan UUID in the sync queue that
            # the cloud cannot resolve. on_commit fires immediately when no
            # transaction is open.
            transaction.on_commit(self._queue_for_sync)

    @staticmethod
    def _is_sync_on_save():
        from base.services.sync.cache import safe_get
        override = safe_get('sync:config:on_save')
        if override is not None:
            return override
        return getattr(settings, 'SYNC_ON_SAVE', False)

    def delete(self, *args, **kwargs):
        hard_delete = kwargs.pop('hard_delete', False)
        if hard_delete:
            super().delete(*args, **kwargs)
        else:
            self.is_deleted = True
            self.save(update_fields=['is_deleted', 'synced_at', 'sync_version'])

    def hard_delete(self):
        # Capture identity for a tombstone before we delete the row, then
        # enqueue a soft-delete sync record on commit so peers also remove
        # the record. Without this, hard deletes on one branch never
        # propagate and leave dangling FK references on others.
        if self._is_sync_on_save() and self.pk:
            try:
                from base.services.sync.service import SyncService
                model_name = self.__class__.__name__.lower()
                tombstone = self.to_sync_dict()
                tombstone['is_deleted'] = True
                tombstone['sync_version'] = (self.sync_version or 0) + 1
                uuid_val = str(self.uuid)
                transaction.on_commit(
                    lambda: SyncService.queue_tombstone(model_name, uuid_val, tombstone)
                )
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    f"Failed to queue tombstone for {self.__class__.__name__} pk={self.pk}",
                    exc_info=True,
                )
        super().delete()

    def _queue_for_sync(self):
        try:
            from base.services.sync.service import SyncService
            SyncService.queue_record(self)
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                f"Failed to queue {self.__class__.__name__} pk={self.pk} for sync",
                exc_info=True,
            )

    def to_sync_dict(self):
        data = {
            'uuid': str(self.uuid),
            'sync_version': self.sync_version,
            'is_deleted': self.is_deleted,
            'branch_id': self.branch_id,
        }
        for field in self._meta.get_fields():
            if field.concrete and not field.is_relation:
                if field.name not in [
                    'id', 'uuid', 'synced_at', 'sync_version', 'is_deleted', 'branch_id'
                ]:
                    value = getattr(self, field.name, None)
                    if hasattr(value, 'isoformat'):
                        value = value.isoformat()
                    elif isinstance(value, Decimal):
                        value = str(value)
                    elif isinstance(value, uuid.UUID):
                        value = str(value)
                    data[field.name] = value
        return data

    # Class-level deny-list for fields that must never be written by the sync
    # ingestion paths (push or pull). Per-model overrides go on the subclass;
    # see User.SYNC_WRITE_DENYLIST. Empty by default — only safety-critical
    # fields belong here.
    SYNC_WRITE_DENYLIST = frozenset()

    @classmethod
    def _strip_sync_denied(cls, data):
        denied = getattr(cls, 'SYNC_WRITE_DENYLIST', frozenset())
        if not denied:
            return data
        import logging
        logger = logging.getLogger(__name__)
        cleaned = {}
        for key, value in data.items():
            if key in denied:
                logger.warning(
                    'sync ingest: dropping denylisted field %s on %s',
                    key, cls.__name__,
                )
                continue
            cleaned[key] = value
        return cleaned

    @classmethod
    def from_sync_dict(cls, data, branch_id=None):
        from django.utils import timezone
        from django.utils.dateparse import parse_datetime
        from django.apps import apps
        from base.services.sync.config import FK_UUID_MAPPINGS

        data = data.copy()
        uuid_val = data.pop('uuid')
        sync_version = data.pop('sync_version', 1)
        is_deleted = data.pop('is_deleted', False)
        # The kwarg `branch_id` comes from the verified bearer-token mapping
        # (push) or from the trusted cloud connection (pull). If the payload
        # tries to override it with a different value, that's either misrouting
        # or a forgery attempt — drop the record rather than silently pinning
        # it to the wrong branch.
        payload_branch = data.pop('branch_id', None)
        if payload_branch and branch_id and payload_branch != branch_id:
            import logging
            logging.getLogger(__name__).warning(
                'sync ingest: payload branch_id=%s mismatched auth branch_id=%s; '
                'dropping record %s on %s',
                payload_branch, branch_id, uuid_val, cls.__name__,
            )
            return None, 'skipped'
        incoming_branch = payload_branch or branch_id
        data = cls._strip_sync_denied(data)

        # Resolve UUID-keyed FK references to local instances. The push/receive
        # path does this in CloudReceiver._resolve_foreign_keys, but the
        # pull-from-cloud path lands straight here — so a model without an
        # explicit from_sync_dict override (Table, Shift, CashReconciliation,
        # and most stock/HR models) would silently drop every FK to NULL,
        # Integrity-erroring on non-nullable FKs (place, user, shift) or losing
        # the association. Resolving in the default fixes it for every model.
        # Each model's to_sync_dict only emits the *_uuid keys for its own FKs,
        # so iterating the shared mapping over `data` can't cross-wire fields.
        resolved_fks = {}
        for uuid_field, (app_label, model_name, fk_field) in FK_UUID_MAPPINGS.items():
            if uuid_field not in data:
                continue
            uuid_value = data.pop(uuid_field)
            if not uuid_value:
                continue
            try:
                related = apps.get_model(app_label, model_name).objects.filter(
                    uuid=uuid_value,
                ).first()
            except Exception:
                related = None
            if related is not None:
                resolved_fks[fk_field] = related
            else:
                # Don't materialize a row with a missing *required* FK — the
                # parent UUID hasn't synced yet. Skip; the next pull cycle
                # re-delivers once the parent has landed.
                try:
                    if not cls._meta.get_field(fk_field).null:
                        import logging
                        logging.getLogger(__name__).warning(
                            'sync ingest: unresolved required FK %s=%s on %s; '
                            'skipping record %s',
                            fk_field, uuid_value, cls.__name__, uuid_val,
                        )
                        return None, 'skipped'
                except Exception:
                    pass

        # Source-of-truth `updated_at`. We need to preserve this across the
        # save(), because every SyncMixin model declares updated_at with
        # auto_now=True — Django would otherwise overwrite the incoming
        # timestamp with the receiver's local clock at save-time, silently
        # breaking the equal-version tiebreaker on the next round.
        incoming_updated = data.pop('updated_at', None)
        if isinstance(incoming_updated, str):
            incoming_updated = parse_datetime(incoming_updated)

        try:
            instance = cls.objects.get(uuid=uuid_val)
            # Refuse to resurrect a hard-deleted row's slot via an older
            # incoming payload. (Soft-deletes are handled by is_deleted
            # propagation; this branch only fires for live rows.)
            should = cls._should_replace(
                instance, sync_version,
                {**data, 'updated_at': incoming_updated},
                incoming_branch,
            )
            if not should:
                return instance, 'skipped'
            # A locally-tombstoned row is terminal — never resurrect it.
            if instance.is_deleted and not is_deleted:
                return instance, 'skipped'
            for key, value in data.items():
                if hasattr(instance, key):
                    setattr(instance, key, value)
            for fk_field, related in resolved_fks.items():
                setattr(instance, fk_field, related)
            instance.sync_version = sync_version
            instance.is_deleted = is_deleted
            instance.synced_at = timezone.now()
            instance.save(_syncing=True)
            if incoming_updated and hasattr(instance, 'updated_at'):
                # .update() bypasses auto_now so the source-of-truth
                # timestamp survives. Reload onto the instance for callers.
                cls.objects.filter(pk=instance.pk).update(updated_at=incoming_updated)
                instance.updated_at = incoming_updated
            return instance, 'updated'
        except cls.DoesNotExist:
            instance = cls(
                uuid=uuid_val,
                sync_version=sync_version,
                is_deleted=is_deleted,
                branch_id=incoming_branch or '',
                synced_at=timezone.now(),
            )
            for key, value in data.items():
                if hasattr(instance, key):
                    setattr(instance, key, value)
            for fk_field, related in resolved_fks.items():
                setattr(instance, fk_field, related)
            instance.save(_syncing=True)
            if incoming_updated and hasattr(instance, 'updated_at'):
                cls.objects.filter(pk=instance.pk).update(updated_at=incoming_updated)
                instance.updated_at = incoming_updated
            return instance, 'created'

    @classmethod
    def _should_replace(cls, instance, incoming_version, incoming_data, incoming_branch):
        # Higher sync_version always wins. On a tie, fall back to a
        # deterministic tiebreaker so two branches that happened to land at
        # the same version don't silently overwrite each other based on
        # whichever batch arrived second:
        #   1. updated_at (newer wins) when both sides have it
        #   2. branch_id lexicographic comparison as last resort.
        if incoming_version > instance.sync_version:
            return True
        if incoming_version < instance.sync_version:
            return False

        from django.utils.dateparse import parse_datetime
        incoming_updated = incoming_data.get('updated_at')
        if isinstance(incoming_updated, str):
            incoming_updated = parse_datetime(incoming_updated)
        local_updated = getattr(instance, 'updated_at', None)
        if incoming_updated and local_updated:
            if incoming_updated > local_updated:
                return True
            if incoming_updated < local_updated:
                return False

        local_branch = instance.branch_id or ''
        incoming = incoming_branch or ''
        return incoming > local_branch

    @classmethod
    def _is_sync_denylisted(cls, field_name):
        denied = getattr(cls, 'SYNC_WRITE_DENYLIST', frozenset())
        return field_name in denied


class User(SyncMixin, models.Model):
    class RoleChoices(models.TextChoices):
        USER = "USER", "User"
        ADMIN = "ADMIN", "Admin"
        CASHIER = "CASHIER", "Cashier"
        # Monoblock-level manager: logs in on the POS next to cashiers (NOT in
        # the admin dashboard like ADMIN), but with elevated in-app access
        # (settings, etc.). Gated server-side via role_required('MANAGER').
        MANAGER = "MANAGER", "Manager"
        WAITER = "WAITER", "Waiter"

    class UserStatus(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspended"

    first_name = models.CharField(max_length=25)
    last_name = models.CharField(max_length=25)
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=128)

    role = models.CharField(
        max_length=10,
        choices=RoleChoices.choices,
        default=RoleChoices.USER,
    )

    status = models.CharField(
        max_length=10,
        choices=UserStatus.choices,
        default=UserStatus.ACTIVE,
    )

    permissions = models.JSONField(default=list, blank=True)

    last_login_at = models.DateTimeField(null=True, blank=True)
    last_login_api = models.CharField(max_length=20, null=True, blank=True)
    # Required by SyncMixin._should_replace tiebreaker: when two branches
    # land at the same sync_version, the row with the newer updated_at
    # wins. Without this field, equal-version syncs fell through to a
    # branch_id comparison that wasn't deterministic for User updates.
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    # Credentials and privilege metadata must never be overwritten by sync.
    # `to_sync_dict` already strips `password` on the push side, but a
    # compromised cloud or a malicious branch could otherwise still set
    # `role`/`permissions`/`status` via either receive or pull. Pull bypasses
    # the receiver's denylist, so this attribute is the single source of
    # truth honored by both ingest paths.
    SYNC_WRITE_DENYLIST = frozenset({'password', 'role', 'permissions', 'status'})

    objects = SyncManager()

    def to_sync_dict(self):
        data = super().to_sync_dict()
        data.pop('password', None)
        return data

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class Session(models.Model):
    user_id = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, db_index=True)
    ip_address = models.CharField(max_length=45)
    user_agent = models.CharField(max_length=256, null=True, blank=True, default='')
    payload = models.CharField(max_length=128, null=True, blank=True, db_index=True)
    last_activity = models.DateTimeField(auto_now_add=True)
    # Absolute expiry. Set by the auth services on login. A NULL value
    # would indicate either a legacy pre-migration row or a buggy code path
    # that bypassed the auth service; in both cases the session must be
    # treated as expired so it forces re-authentication on the next request.
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['payload']),
        ]

    def is_expired(self):
        if self.expires_at is None:
            return True
        from django.utils import timezone
        return self.expires_at <= timezone.now()

    def __str__(self):
        return f"Session {self.pk} - user {self.user_id_id}"


class Category(SyncMixin, models.Model):
    name = models.CharField(max_length=50)
    parent = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='children',
    )
    sort_order = models.IntegerField(default=0)
    colors = models.JSONField(default=list, blank=True, help_text="Colors: ['#e74c3c', '#3498db']")
    status = models.CharField(
        max_length=10,
        choices=[('ACTIVE', 'Active'), ('INACTIVE', 'Inactive')],
        default='ACTIVE',
    )
    slug = models.SlugField(unique=True)
    description = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SyncManager()

    def to_sync_dict(self):
        data = super().to_sync_dict()
        data['parent_category_uuid'] = str(self.parent.uuid) if self.parent else None
        return data

    @classmethod
    def from_sync_dict(cls, data, branch_id=None):
        # The base implementation only setattrs keys the model has, so
        # parent_category_uuid (a synthetic FK pointer) is silently dropped on
        # the pull path — flattening the category tree on pulled branches.
        # Resolve it explicitly here, then defer to the base for everything
        # else (updated_at preservation, version tiebreaker, branch checks).
        from django.utils import timezone

        data = data.copy()
        parent_uuid = data.pop('parent_category_uuid', None)
        instance, action = super().from_sync_dict(data, branch_id=branch_id)
        # Only touch the parent link when the row was actually written —
        # a 'skipped' result means the incoming version lost the tiebreaker,
        # so its parent must not overwrite the newer local value.
        if instance is None or action not in ('created', 'updated'):
            return instance, action

        parent = None
        if parent_uuid and parent_uuid != str(instance.uuid):  # never self-parent
            parent = cls.objects.filter(uuid=parent_uuid).first()
        if instance.parent_id != (parent.id if parent else None):
            instance.parent = parent
            cls.objects.filter(pk=instance.pk).update(
                parent=parent, synced_at=timezone.now(),
            )
        return instance, action

    def __str__(self):
        return self.name


class Product(SyncMixin, models.Model):
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name="products",
        db_index=True,
    )
    colors = models.JSONField(default=list, blank=True, help_text="Colors: ['#e74c3c', '#3498db']")
    name = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    # Soliq IKPU / SPIC / MXIK classification code (from tasnif.soliq.uz).
    # Required by the OFD for live fiscalization; blank is tolerated in
    # mock/sandbox so the catalog can be coded gradually.
    ikpu_code = models.CharField(max_length=17, blank=True, default='')
    # Instant items (drinks, packaged goods) need no kitchen preparation:
    # their order items are auto-readied the moment the order is created and
    # they're excluded from the kitchen / chef display.
    is_instant = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SyncManager()

    # Price changes are administrative — they must originate at the cloud
    # / admin path with an audit row, not silently arrive via a peer branch
    # push. Denylisted from sync ingestion as a defense-in-depth measure
    # in case a branch token is ever compromised.
    SYNC_WRITE_DENYLIST = frozenset({'price'})

    def to_sync_dict(self):
        data = super().to_sync_dict()
        data['category_uuid'] = str(self.category.uuid) if self.category else None
        return data

    @classmethod
    def from_sync_dict(cls, data, branch_id=None):
        from django.utils import timezone
        from django.utils.dateparse import parse_datetime

        data = data.copy()
        category_uuid = data.pop('category_uuid', None)
        uuid_val = data.pop('uuid')
        sync_version = data.pop('sync_version', 1)
        is_deleted = data.pop('is_deleted', False)
        incoming_branch = data.pop('branch_id', branch_id)
        data = cls._strip_sync_denied(data)

        # Preserve the source-of-truth updated_at across save(). updated_at is
        # auto_now=True, so a plain setattr+save would overwrite it with the
        # receiver's local clock and silently break the equal-version
        # tiebreaker in _should_replace on the next sync round.
        incoming_updated = data.pop('updated_at', None)
        if isinstance(incoming_updated, str):
            incoming_updated = parse_datetime(incoming_updated)

        category = None
        if category_uuid:
            try:
                category = Category.objects.get(uuid=category_uuid)
            except Category.DoesNotExist:
                pass

        try:
            instance = cls.objects.get(uuid=uuid_val)
            if cls._should_replace(
                instance, sync_version,
                {**data, 'updated_at': incoming_updated}, incoming_branch,
            ):
                for key, value in data.items():
                    if hasattr(instance, key):
                        setattr(instance, key, value)
                if category:
                    instance.category = category
                instance.sync_version = sync_version
                instance.is_deleted = is_deleted
                instance.synced_at = timezone.now()
                instance.save(_syncing=True)
                if incoming_updated:
                    cls.objects.filter(pk=instance.pk).update(updated_at=incoming_updated)
                    instance.updated_at = incoming_updated
            return instance, 'updated'
        except cls.DoesNotExist:
            instance = cls(
                uuid=uuid_val,
                sync_version=sync_version,
                is_deleted=is_deleted,
                branch_id=incoming_branch or '',
                synced_at=timezone.now(),
                category=category,
            )
            for key, value in data.items():
                if hasattr(instance, key):
                    setattr(instance, key, value)
            instance.save(_syncing=True)
            if incoming_updated:
                cls.objects.filter(pk=instance.pk).update(updated_at=incoming_updated)
                instance.updated_at = incoming_updated
            return instance, 'created'

    def __str__(self):
        return self.name


class DeliveryPerson(SyncMixin, models.Model):
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50, null=True, blank=True)
    phone_number = models.CharField(max_length=50)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = SyncManager()

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class Place(SyncMixin, models.Model):
    class PlaceType(models.TextChoices):
        HALL = "HALL", "Hall"
        BAR = "BAR", "Bar"
        TERRACE = "TERRACE", "Terrace"
        PRIVATE_ROOM = "PRIVATE_ROOM", "Private Room"
        OUTDOOR = "OUTDOOR", "Outdoor"

    name = models.CharField(max_length=100)
    place_type = models.CharField(
        max_length=15,
        choices=PlaceType.choices,
        default=PlaceType.HALL,
    )
    capacity = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SyncManager()

    class Meta:
        ordering = ['sort_order', 'name']

    def __str__(self):
        return f"{self.name} ({self.get_place_type_display()})"


class Table(SyncMixin, models.Model):
    class Status(models.TextChoices):
        AVAILABLE = "AVAILABLE", "Available"
        OCCUPIED = "OCCUPIED", "Occupied"
        RESERVED = "RESERVED", "Reserved"
        OUT_OF_SERVICE = "OUT_OF_SERVICE", "Out of Service"

    place = models.ForeignKey(
        Place,
        on_delete=models.CASCADE,
        related_name="tables",
    )
    number = models.CharField(max_length=20)
    capacity = models.PositiveIntegerField(default=4)
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.AVAILABLE,
    )
    is_active = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SyncManager()

    class Meta:
        ordering = ['place', 'sort_order', 'number']
        unique_together = ['place', 'number']

    def to_sync_dict(self):
        data = super().to_sync_dict()
        data['place_uuid'] = str(self.place.uuid) if self.place else None
        return data

    def __str__(self):
        return f"Table {self.number} ({self.place.name})"


class Order(SyncMixin, models.Model):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        PREPARING = "PREPARING", "Preparing"
        READY = "READY", "Ready"
        COMPLETED = "COMPLETED", "Completed"
        CANCELED = "CANCELED", "Canceled"

    class OrderType(models.TextChoices):
        HALL = "HALL", "Hall (Dine-in)"
        DELIVERY = "DELIVERY", "Delivery"
        PICKUP = "PICKUP", "Pickup"

    delivery_person = models.ForeignKey(
        DeliveryPerson,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deliveries",
    )

    place = models.ForeignKey(
        Place,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
    )
    table = models.ForeignKey(
        Table,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    cashier = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="handled_orders",
    )

    display_id = models.IntegerField(default=1)

    order_type = models.CharField(
        max_length=10,
        choices=OrderType.choices,
        default=OrderType.HALL,
    )

    phone_number = models.CharField(max_length=20, null=True, blank=True)
    description = models.TextField(null=True, blank=True)

    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
    )

    class PaymentMethod(models.TextChoices):
        CASH = "CASH", "Cash"
        UZCARD = "UZCARD", "Uzcard"
        HUMO = "HUMO", "Humo"
        PAYME = "PAYME", "Payme"
        # Set on the Order when a single sale is split across >1 distinct method.
        # The per-line breakdown lives in OrderPayment rows.
        MIXED = "MIXED", "Mixed"

    is_paid = models.BooleanField(default=False, db_index=True)
    payment_method = models.CharField(
        max_length=10,
        choices=PaymentMethod.choices,
        null=True, blank=True,
        db_index=True,
    )
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # Pay-time percent discount (0..100) applied to total_amount at checkout.
    # The amount due the cashier collects is total_amount * (1 - pct/100).
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    # Indexed: dashboard/today, forecast/tomorrow, menu-engineering,
    # shift_performance, 1C export, and the Telegram /status command all
    # filter by created_at range; without the index every analytics call
    # is a heap scan on a constantly-growing table.
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    objects = SyncManager()

    # Refuse sync ingestion of payment / total fields. The cloud is the
    # collector of these; a peer cannot dictate "this order is paid for
    # 99999". Field-level guard, not row-level — the rest of the order
    # (status transitions, item changes) still syncs normally.
    SYNC_WRITE_DENYLIST = frozenset({
        'is_paid', 'payment_method', 'total_amount', 'subtotal',
        'discount_amount', 'discount_percent', 'paid_at',
    })

    def to_sync_dict(self):
        data = super().to_sync_dict()
        data['user_uuid'] = str(self.user.uuid) if self.user else None
        data['cashier_uuid'] = str(self.cashier.uuid) if self.cashier else None
        data['delivery_person_uuid'] = str(self.delivery_person.uuid) if self.delivery_person else None
        data['place_uuid'] = str(self.place.uuid) if self.place else None
        data['table_uuid'] = str(self.table.uuid) if self.table else None
        return data

    @classmethod
    def from_sync_dict(cls, data, branch_id=None):
        from django.utils import timezone
        from django.utils.dateparse import parse_datetime

        data = data.copy()
        user_uuid = data.pop('user_uuid', None)
        cashier_uuid = data.pop('cashier_uuid', None)
        delivery_person_uuid = data.pop('delivery_person_uuid', None)
        uuid_val = data.pop('uuid')
        sync_version = data.pop('sync_version', 1)
        is_deleted = data.pop('is_deleted', False)
        incoming_branch = data.pop('branch_id', branch_id)
        data = cls._strip_sync_denied(data)

        # Preserve the source-of-truth updated_at across save() (auto_now would
        # overwrite it with the local clock and break the equal-version
        # tiebreaker — see the base from_sync_dict for the full rationale).
        incoming_updated = data.pop('updated_at', None)
        if isinstance(incoming_updated, str):
            incoming_updated = parse_datetime(incoming_updated)

        user = None
        cashier = None
        delivery_person = None

        if user_uuid:
            try:
                user = User.objects.get(uuid=user_uuid)
            except User.DoesNotExist:
                raise ValueError(f"User with UUID {user_uuid} not found")

        if cashier_uuid:
            try:
                cashier = User.objects.get(uuid=cashier_uuid)
            except User.DoesNotExist:
                pass

        if delivery_person_uuid:
            try:
                delivery_person = DeliveryPerson.objects.get(uuid=delivery_person_uuid)
            except DeliveryPerson.DoesNotExist:
                pass

        if not user:
            raise ValueError(f"User with UUID {user_uuid} not found - sync User first")

        try:
            instance = cls.objects.get(uuid=uuid_val)
            if cls._should_replace(
                instance, sync_version,
                {**data, 'updated_at': incoming_updated}, incoming_branch,
            ):
                for key, value in data.items():
                    if hasattr(instance, key):
                        setattr(instance, key, value)
                instance.user = user
                instance.cashier = cashier
                instance.delivery_person = delivery_person
                instance.sync_version = sync_version
                instance.is_deleted = is_deleted
                instance.synced_at = timezone.now()
                instance.save(_syncing=True)
                if incoming_updated:
                    cls.objects.filter(pk=instance.pk).update(updated_at=incoming_updated)
                    instance.updated_at = incoming_updated
            return instance, 'updated'
        except cls.DoesNotExist:
            instance = cls(
                uuid=uuid_val,
                sync_version=sync_version,
                is_deleted=is_deleted,
                branch_id=incoming_branch or '',
                synced_at=timezone.now(),
                user=user,
                cashier=cashier,
                delivery_person=delivery_person,
            )
            for key, value in data.items():
                if hasattr(instance, key):
                    setattr(instance, key, value)
            instance.save(_syncing=True)
            if incoming_updated:
                cls.objects.filter(pk=instance.pk).update(updated_at=incoming_updated)
                instance.updated_at = incoming_updated
            return instance, 'created'

    def __str__(self):
        return f"Order #{self.display_id} - {self.order_type} - {self.status}"


class OrderItem(SyncMixin, models.Model):
    order = models.ForeignKey(
        Order,
        related_name="items",
        on_delete=models.CASCADE,
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
    )
    quantity = models.PositiveIntegerField()
    detail = models.TextField(null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    original_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    objects = SyncManager()

    def to_sync_dict(self):
        data = super().to_sync_dict()
        data['order_uuid'] = str(self.order.uuid) if self.order else None
        data['product_uuid'] = str(self.product.uuid) if self.product else None
        return data

    @classmethod
    def from_sync_dict(cls, data, branch_id=None):
        from django.utils import timezone

        data = data.copy()
        order_uuid = data.pop('order_uuid', None)
        product_uuid = data.pop('product_uuid', None)
        uuid_val = data.pop('uuid')
        sync_version = data.pop('sync_version', 1)
        is_deleted = data.pop('is_deleted', False)
        incoming_branch = data.pop('branch_id', branch_id)
        data = cls._strip_sync_denied(data)

        order = None
        product = None

        if order_uuid:
            try:
                order = Order.objects.get(uuid=order_uuid)
            except Order.DoesNotExist:
                raise ValueError(f"Order with UUID {order_uuid} not found")

        if product_uuid:
            try:
                product = Product.objects.get(uuid=product_uuid)
            except Product.DoesNotExist:
                pass

        if not order:
            raise ValueError(f"Order with UUID {order_uuid} not found - sync Order first")

        try:
            instance = cls.objects.get(uuid=uuid_val)
            if cls._should_replace(instance, sync_version, data, incoming_branch):
                for key, value in data.items():
                    if hasattr(instance, key):
                        setattr(instance, key, value)
                instance.order = order
                if product:
                    instance.product = product
                instance.sync_version = sync_version
                instance.is_deleted = is_deleted
                instance.synced_at = timezone.now()
                instance.save(_syncing=True)
            return instance, 'updated'
        except cls.DoesNotExist:
            instance = cls(
                uuid=uuid_val,
                sync_version=sync_version,
                is_deleted=is_deleted,
                branch_id=incoming_branch or '',
                synced_at=timezone.now(),
                order=order,
                product=product,
            )
            for key, value in data.items():
                if hasattr(instance, key):
                    setattr(instance, key, value)
            instance.save(_syncing=True)
            return instance, 'created'

    def __str__(self):
        return f"{self.product.name} x {self.quantity}"


class CashRegister(SyncMixin, models.Model):
    current_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    last_updated = models.DateTimeField(auto_now=True)

    objects = SyncManager()

    class Meta:
        db_table = 'cash_register'

    def __str__(self):
        return f"Cash Register: {self.current_balance}"


class Inkassa(SyncMixin, models.Model):
    cashier = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="inkassas",
    )

    class InkassType(models.TextChoices):
        CASH = "CASH", "Cash"
        UZCARD = "UZCARD", "Uzcard"
        HUMO = "HUMO", "Humo"
        PAYME = "PAYME", "Payme"

    amount = models.DecimalField(max_digits=12, decimal_places=2)

    inkass_type = models.CharField(
        max_length=10,
        choices=InkassType.choices,
    )

    balance_before = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    period_start = models.DateTimeField(null=True, blank=True)
    period_end = models.DateTimeField(auto_now_add=True)
    total_orders = models.IntegerField(default=0)
    total_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = SyncManager()

    # Inkassa is a cash-history record. The amounts, balances, and
    # collected-revenue numbers must never be set from a peer push — they
    # are only ever computed locally at performance time. Sync should
    # propagate the *existence* of an Inkassa event, not let a peer dictate
    # its financial figures.
    SYNC_WRITE_DENYLIST = frozenset({
        'amount', 'balance_before', 'balance_after', 'total_revenue',
    })

    def to_sync_dict(self):
        data = super().to_sync_dict()
        data['cashier_uuid'] = str(self.cashier.uuid) if self.cashier else None
        return data

    @classmethod
    def from_sync_dict(cls, data, branch_id=None):
        from django.utils import timezone

        data = data.copy()
        cashier_uuid = data.pop('cashier_uuid', None)
        uuid_val = data.pop('uuid')
        sync_version = data.pop('sync_version', 1)
        is_deleted = data.pop('is_deleted', False)
        incoming_branch = data.pop('branch_id', branch_id)
        data = cls._strip_sync_denied(data)

        cashier = None
        if cashier_uuid:
            try:
                cashier = User.objects.get(uuid=cashier_uuid)
            except User.DoesNotExist:
                pass

        try:
            instance = cls.objects.get(uuid=uuid_val)
            if cls._should_replace(instance, sync_version, data, incoming_branch):
                for key, value in data.items():
                    if hasattr(instance, key):
                        setattr(instance, key, value)
                instance.cashier = cashier
                instance.sync_version = sync_version
                instance.is_deleted = is_deleted
                instance.synced_at = timezone.now()
                instance.save(_syncing=True)
            return instance, 'updated'
        except cls.DoesNotExist:
            instance = cls(
                uuid=uuid_val,
                sync_version=sync_version,
                is_deleted=is_deleted,
                branch_id=incoming_branch or '',
                synced_at=timezone.now(),
                cashier=cashier,
            )
            for key, value in data.items():
                if hasattr(instance, key):
                    setattr(instance, key, value)
            instance.save(_syncing=True)
            return instance, 'created'

    def __str__(self):
        return f"Inkassa #{self.id} - {self.amount} on {self.created_at.strftime('%Y-%m-%d %H:%M')}"


class TreasuryAccount(SyncMixin, models.Model):
    """A money pot the business holds outside the till drawer.

    SAFE = physical cash moved out of the registers by inkassa.
    BANK = electronic money (card / Payme settlements).
    One (soft-undeleted) row per kind; read/created via get_or_create.
    """
    class Kind(models.TextChoices):
        SAFE = 'SAFE', 'Safe (cash)'
        BANK = 'BANK', 'Bank (cards)'

    kind = models.CharField(max_length=10, choices=Kind.choices)
    balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    last_updated = models.DateTimeField(auto_now=True)

    objects = SyncManager()

    # Balance is only ever mutated locally inside TreasuryService under a row
    # lock; a peer push must never dictate it.
    SYNC_WRITE_DENYLIST = frozenset({'balance'})

    def __str__(self):
        return f"{self.kind}: {self.balance}"


class TreasuryTransaction(SyncMixin, models.Model):
    """Append-only ledger of every SAFE / BANK movement."""
    class Type(models.TextChoices):
        INKASSA = 'INKASSA', 'Inkassa deposit'
        TRANSFER_IN = 'TRANSFER_IN', 'Transfer in'
        TRANSFER_OUT = 'TRANSFER_OUT', 'Transfer out'
        FEE = 'FEE', 'Transfer fee'
        EXPENSE = 'EXPENSE', 'Expense'
        ADJUSTMENT = 'ADJUSTMENT', 'Adjustment'

    account = models.ForeignKey(
        TreasuryAccount, on_delete=models.CASCADE, related_name='transactions',
    )
    type = models.CharField(max_length=15, choices=Type.choices)
    # Signed change applied to the account balance (+ in / - out).
    delta = models.DecimalField(max_digits=14, decimal_places=2)
    fee = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    balance_before = models.DecimalField(max_digits=14, decimal_places=2)
    balance_after = models.DecimalField(max_digits=14, decimal_places=2)
    # The other side of a transfer (null for inkassa / expense).
    counterparty = models.ForeignKey(
        TreasuryAccount, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='counterparty_transactions',
    )
    category = models.CharField(max_length=50, blank=True, default='')
    description = models.TextField(blank=True, default='')
    reference_type = models.CharField(max_length=50, blank=True, default='')
    reference_id = models.PositiveIntegerField(null=True, blank=True)
    performed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='treasury_transactions',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = SyncManager()

    SYNC_WRITE_DENYLIST = frozenset({'delta', 'fee', 'balance_before', 'balance_after'})

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.type} {self.delta} ({self.account_id})"


class AppSettings(models.Model):
    hr_enabled = models.BooleanField(default=False)
    waiter_enabled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'app settings'
        verbose_name_plural = 'app settings'

    _CACHE_KEY = 'app_settings:v1'
    _CACHE_TTL = 60

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        # Bust the per-process cache so the next reader sees the new state.
        from django.core.cache import cache
        cache.delete(self._CACHE_KEY)

    @classmethod
    def load(cls):
        # Wrap the get_or_create with a short cache so every request that
        # reads the toggle (every HR/waiter view, etc.) doesn't pay a SELECT.
        from django.core.cache import cache
        cached = cache.get(cls._CACHE_KEY)
        if cached is not None:
            return cached
        obj, _ = cls.objects.get_or_create(pk=1)
        cache.set(cls._CACHE_KEY, obj, cls._CACHE_TTL)
        return obj

    def __str__(self):
        return "App Settings"


class ShiftTemplate(SyncMixin, models.Model):
    name = models.CharField(max_length=100)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SyncManager()

    class Meta:
        ordering = ['start_time']

    def __str__(self):
        return f"{self.name} ({self.start_time} - {self.end_time})"


class Shift(SyncMixin, models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        # ENDED = cashier closed the shift; totals frozen, awaiting the
        # manager's cash reconciliation. COMPLETED = manager confirmed it.
        ENDED = 'ENDED', 'Ended'
        COMPLETED = 'COMPLETED', 'Completed'
        ABANDONED = 'ABANDONED', 'Abandoned'

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='shifts')
    shift_template = models.ForeignKey(
        ShiftTemplate, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='shifts',
    )
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    total_orders = models.PositiveIntegerField(default=0)
    total_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cash_collected = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SyncManager()

    class Meta:
        ordering = ['-start_time']

    def to_sync_dict(self):
        data = super().to_sync_dict()
        data['user_uuid'] = str(self.user.uuid) if self.user else None
        data['shift_template_uuid'] = str(self.shift_template.uuid) if self.shift_template else None
        return data

    def __str__(self):
        return f"Shift: {self.user} ({self.start_time})"


class CashReconciliation(SyncMixin, models.Model):
    shift = models.OneToOneField(Shift, on_delete=models.CASCADE, related_name='reconciliation')
    expected_cash = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    actual_cash = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    difference = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True, default='')
    reconciled_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='reconciliations',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = SyncManager()

    class Meta:
        ordering = ['-created_at']

    def to_sync_dict(self):
        data = super().to_sync_dict()
        data['shift_uuid'] = str(self.shift.uuid) if self.shift else None
        data['reconciled_by_uuid'] = str(self.reconciled_by.uuid) if self.reconciled_by else None
        return data

    def __str__(self):
        return f"Reconciliation for {self.shift} (diff: {self.difference})"


class SyncQueueRecord(models.Model):
    """Durable queue for outbound sync records.

    Replaces the cache-backed queue so a process restart (LocMem) or a Redis
    crash before a flush no longer loses unsent records. Not a SyncMixin —
    this table is local-only bookkeeping and must never sync itself.
    """

    model_name = models.CharField(max_length=100, db_index=True)
    record_uuid = models.UUIDField(db_index=True)
    payload = models.JSONField()
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'sync_queue_record'
        # One pending entry per (model, uuid). Re-queueing the same record
        # collapses on the unique constraint and updates the row in place.
        constraints = [
            models.UniqueConstraint(
                fields=['model_name', 'record_uuid'],
                name='uniq_sync_queue_model_uuid',
            ),
        ]
        ordering = ['created_at']

    def __str__(self):
        return f"SyncQueue<{self.model_name} {self.record_uuid}>"


class AuditLog(SyncMixin, models.Model):
    """Append-only record of sensitive admin actions.

    Written from the view layer where the actor (request.user) and the client
    IP are already known. Conflict-free under sync: each row is created once
    with sync_version=1 and never mutated, so the standard SyncMixin tiebreak
    naturally leaves it alone on the receiving side.
    """

    class Action(models.TextChoices):
        INKASSA_PERFORM = "INKASSA_PERFORM", "Inkassa performed"
        USER_CREATE = "USER_CREATE", "User created"
        USER_UPDATE = "USER_UPDATE", "User updated"
        USER_DELETE = "USER_DELETE", "User deleted"
        SHIFT_RECONCILE = "SHIFT_RECONCILE", "Shift reconciled"
        ORDER_CANCEL = "ORDER_CANCEL", "Order canceled"
        PRODUCT_PRICE_CHANGE = "PRODUCT_PRICE_CHANGE", "Product price changed"
        DISCOUNT_CREATE = "DISCOUNT_CREATE", "Discount created"
        DISCOUNT_UPDATE = "DISCOUNT_UPDATE", "Discount updated"
        DISCOUNT_DELETE = "DISCOUNT_DELETE", "Discount deleted"
        LOYALTY_REDEEM = "LOYALTY_REDEEM", "Loyalty stamps redeemed"
        TREASURY_TRANSFER = "TREASURY_TRANSFER", "Treasury transfer"
        TREASURY_EXPENSE = "TREASURY_EXPENSE", "Treasury expense"

    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_actions',
    )
    action = models.CharField(max_length=32, choices=Action.choices, db_index=True)
    target_type = models.CharField(max_length=32, blank=True, default='', db_index=True)
    target_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.CharField(max_length=45, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = SyncManager()

    class Meta:
        ordering = ['-created_at']

    # AuditLog is push-only to the cloud collector. Branch peers must not
    # be able to materialize forged entries via /api/sync/receive (e.g.,
    # claiming the victim's cashier_id performed an inkassa pull). Refuse
    # inbound writes entirely; the receiver-side handler short-circuits on
    # `_sync_ingest_disabled`.
    _sync_ingest_disabled = True

    @classmethod
    def from_sync_dict(cls, data, branch_id=None):
        # No-op: refuse to materialize AuditLog rows from peer payloads.
        # Cloud-side collectors must construct AuditLog directly from the
        # local request context (actor=request.user, ip from REMOTE_ADDR).
        return None, 'skipped'

    @classmethod
    def record(cls, *, actor, action, target_type='', target_id=None,
               metadata=None, ip_address=''):
        return cls.objects.create(
            actor=actor,
            action=action,
            target_type=target_type,
            target_id=target_id,
            metadata=metadata or {},
            ip_address=ip_address,
        )

    def __str__(self):
        return f"AuditLog<{self.action} {self.target_type}#{self.target_id}>"


class IdempotencyKey(models.Model):
    """Local-only dedup record for retried write requests.

    Keyed by (scope, key). `scope` embeds the actor id and the endpoint so two
    clients can't accidentally replay each other's responses with the same
    header value. `response_status == 0` flags a still-in-flight claim and
    causes concurrent retries to fail fast with 409 instead of double-acting.

    Not a SyncMixin — like SyncQueueRecord this is per-branch bookkeeping and
    must never propagate.
    """

    scope = models.CharField(max_length=100, db_index=True)
    key = models.CharField(max_length=128, db_index=True)
    response_status = models.PositiveSmallIntegerField(default=0)
    response_body = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'idempotency_key'
        constraints = [
            models.UniqueConstraint(
                fields=['scope', 'key'],
                name='uniq_idempotency_scope_key',
            ),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"IdempotencyKey<{self.scope} {self.key[:12]}…>"


class DisplayIdCounter(models.Model):
    """Per-scope counter for Order.display_id allocation.

    `display_id` is the small kitchen-handoff number ("order #42 ready") and
    must be unique enough to be unambiguous on the line. Pre-fix, each
    surface (admin / cashier / waiter) read the latest order's display_id
    and added one — racy under concurrent creates, and the customer surface
    used `last+1` while the others used `(last % 100)+1`, so the same id
    could be assigned twice on the same day.

    The counter is locked via select_for_update inside the order-create
    transaction. One row per branch_id (default scope: 'default').

    Not a SyncMixin — counters are per-branch bookkeeping and must never
    propagate (each branch maintains its own kitchen-handoff numbering).
    """

    scope = models.CharField(max_length=64, primary_key=True)
    value = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'display_id_counter'

    def __str__(self):
        return f"DisplayIdCounter<{self.scope}={self.value}>"


class SequenceCounter(models.Model):
    """Per-scope monotonic counter for human-readable document numbers
    (TRX / PO / TRF / CNT / PROD / RCV - YYYYMMDD - NNNN).

    Replaces the racy read-max-then-+1 in
    `stock.services.base_service.generate_number`, which under concurrent
    creates produced duplicate numbers and tripped the unique constraint
    (e.g. `StockTransaction.transaction_number`) — aborting the sale's stock
    deduction. On Postgres the old read wasn't locked; on SQLite this counter
    plus the IMMEDIATE-transaction setting serialize allocation. Locked via
    select_for_update, exactly like DisplayIdCounter.

    One row per `prefix-date` scope. Seeded lazily from the current max so it
    never collides with numbers created before this counter existed.

    Not a SyncMixin — numbering is per-branch bookkeeping and must never
    propagate to sibling branches or the cloud.
    """

    scope = models.CharField(max_length=64, primary_key=True)
    value = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'sequence_counter'

    def __str__(self):
        return f"SequenceCounter<{self.scope}={self.value}>"


class OrderPayment(SyncMixin, models.Model):
    """One line of a (possibly split) order payment. A single sale can carry
    several rows — e.g. 60 000 Humo + 40 000 Cash, or two CASH lines. The
    Order keeps the rolled-up `payment_method` (a single method, or MIXED)."""
    order = models.ForeignKey(
        'base.Order', on_delete=models.CASCADE, related_name='payments',
    )
    method = models.CharField(max_length=10, choices=Order.PaymentMethod.choices)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = SyncManager()

    # The cloud is the collector of money rows; a peer cannot invent payments.
    SYNC_WRITE_DENYLIST = frozenset({'amount', 'method'})

    class Meta:
        db_table = 'order_payment'
        indexes = [models.Index(fields=['order', 'method'])]

    def to_sync_dict(self):
        data = super().to_sync_dict()
        data['order_uuid'] = str(self.order.uuid) if self.order else None
        return data

    def __str__(self):
        return f"OrderPayment<{self.method} {self.amount} on #{self.order_id}>"


class PaymentMethodConfig(models.Model):
    """Branding/catalog for the cashier payment screen: which methods show,
    their label, inline SVG icon and accent color. Seeded with the four
    built-ins; vendor-editable in admin. Plain (non-synced) per-install config
    — the frontend caches it per-PC after login."""
    code = models.CharField(
        max_length=10, unique=True, choices=Order.PaymentMethod.choices,
    )
    label = models.CharField(max_length=40)
    icon = models.TextField(blank=True, default='', help_text='Inline SVG (24x24, currentColor)')
    color = models.CharField(max_length=9, default='#3b82f6')
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'payment_method_config'
        ordering = ['sort_order', 'code']

    def __str__(self):
        return f"PaymentMethodConfig<{self.code}>"


class RolePermission(models.Model):
    """Per-role default permission set, edited by Settings → Roles. Enforcement
    is per-user (User.permissions); this is the role template the editor manages
    and new users inherit. Plain (non-synced) config."""
    role = models.CharField(max_length=20, unique=True, choices=User.RoleChoices.choices)
    permissions = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'role_permission'

    def __str__(self):
        return f"RolePermission<{self.role}>"
