from django.db import models
from base.models import SyncMixin, SyncManager


class Department(SyncMixin, models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default='')
    manager = models.ForeignKey(
        'base.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='managed_departments',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SyncManager()

    class Meta:
        ordering = ['name']

    def to_sync_dict(self):
        data = super().to_sync_dict()
        data['manager_uuid'] = str(self.manager.uuid) if self.manager else None
        return data

    def __str__(self):
        return self.name


class Employee(SyncMixin, models.Model):
    class ContractType(models.TextChoices):
        FULL_TIME = 'FULL_TIME', 'Full Time'
        PART_TIME = 'PART_TIME', 'Part Time'
        CONTRACT = 'CONTRACT', 'Contract'

    class PaymentFrequency(models.TextChoices):
        MONTHLY = 'MONTHLY', 'Monthly'
        WEEKLY = 'WEEKLY', 'Weekly'
        BI_WEEKLY = 'BI_WEEKLY', 'Bi-Weekly'

    user = models.OneToOneField(
        'base.User',
        on_delete=models.CASCADE,
        related_name='employee_profile',
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='employees',
    )
    position = models.CharField(max_length=100)
    hire_date = models.DateField()
    contract_type = models.CharField(
        max_length=15,
        choices=ContractType.choices,
        default=ContractType.FULL_TIME,
    )
    base_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payment_frequency = models.CharField(
        max_length=10,
        choices=PaymentFrequency.choices,
        default=PaymentFrequency.MONTHLY,
    )
    phone = models.CharField(max_length=20, blank=True, default='')
    address = models.TextField(blank=True, default='')
    emergency_contact_name = models.CharField(max_length=100, blank=True, default='')
    emergency_contact_phone = models.CharField(max_length=20, blank=True, default='')
    bank_account = models.CharField(max_length=50, blank=True, default='')
    bank_name = models.CharField(max_length=100, blank=True, default='')
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SyncManager()

    class Meta:
        ordering = ['user__first_name', 'user__last_name']

    def to_sync_dict(self):
        data = super().to_sync_dict()
        data['user_uuid'] = str(self.user.uuid) if self.user else None
        data['department_uuid'] = str(self.department.uuid) if self.department else None
        return data

    def __str__(self):
        return f"{self.user.first_name} {self.user.last_name} - {self.position}"


class ExpenseCategory(SyncMixin, models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default='')
    budget_limit = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SyncManager()

    class Meta:
        verbose_name_plural = 'expense categories'
        ordering = ['name']

    def __str__(self):
        return self.name


class Expense(SyncMixin, models.Model):
    class PaymentMethod(models.TextChoices):
        CASH = 'CASH', 'Cash'
        UZCARD = 'UZCARD', 'Uzcard'
        HUMO = 'HUMO', 'Humo'
        PAYME = 'PAYME', 'Payme'
        BANK_TRANSFER = 'BANK_TRANSFER', 'Bank Transfer'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Rejected'
        PAID = 'PAID', 'Paid'

    category = models.ForeignKey(
        ExpenseCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='expenses',
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.TextField(blank=True, default='')
    expense_date = models.DateField()
    payment_method = models.CharField(
        max_length=15,
        choices=PaymentMethod.choices,
        default=PaymentMethod.CASH,
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
    )
    receipt_number = models.CharField(max_length=100, blank=True, default='')
    receipt_image_url = models.URLField(max_length=500, blank=True, default='')
    created_by = models.ForeignKey(
        'base.User',
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_expenses',
    )
    approved_by = models.ForeignKey(
        'base.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_expenses',
    )
    paid_by = models.ForeignKey(
        'base.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='paid_expenses',
    )
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SyncManager()

    class Meta:
        ordering = ['-expense_date', '-created_at']

    def to_sync_dict(self):
        data = super().to_sync_dict()
        data['expense_category_uuid'] = str(self.category.uuid) if self.category else None
        data['created_by_uuid'] = str(self.created_by.uuid) if self.created_by else None
        data['approved_by_uuid'] = str(self.approved_by.uuid) if self.approved_by else None
        data['paid_by_uuid'] = str(self.paid_by.uuid) if self.paid_by else None
        return data

    def __str__(self):
        return f"Expense #{self.id} - {self.amount} ({self.status})"


class SalaryPayment(SyncMixin, models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        APPROVED = 'APPROVED', 'Approved'
        PAID = 'PAID', 'Paid'

    class PaymentMethod(models.TextChoices):
        CASH = 'CASH', 'Cash'
        UZCARD = 'UZCARD', 'Uzcard'
        HUMO = 'HUMO', 'Humo'
        PAYME = 'PAYME', 'Payme'
        BANK_TRANSFER = 'BANK_TRANSFER', 'Bank Transfer'

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='salary_payments',
    )
    period_year = models.PositiveIntegerField()
    period_month = models.PositiveSmallIntegerField()
    base_amount = models.DecimalField(max_digits=12, decimal_places=2)
    bonus = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    net_amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
    )
    payment_method = models.CharField(
        max_length=15,
        choices=PaymentMethod.choices,
        default=PaymentMethod.CASH,
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        'base.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_salaries',
    )
    created_by = models.ForeignKey(
        'base.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_salaries',
    )
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    objects = SyncManager()

    class Meta:
        unique_together = ['employee', 'period_year', 'period_month']
        ordering = ['-period_year', '-period_month']

    def to_sync_dict(self):
        data = super().to_sync_dict()
        data['employee_uuid'] = str(self.employee.uuid) if self.employee else None
        data['approved_by_uuid'] = str(self.approved_by.uuid) if self.approved_by else None
        data['created_by_uuid'] = str(self.created_by.uuid) if self.created_by else None
        return data

    def __str__(self):
        return f"Salary: {self.employee} - {self.period_year}/{self.period_month}"


class CashTransaction(SyncMixin, models.Model):
    class TransactionType(models.TextChoices):
        DEPOSIT = 'DEPOSIT', 'Deposit'
        WITHDRAWAL = 'WITHDRAWAL', 'Withdrawal'
        EXPENSE_PAYMENT = 'EXPENSE_PAYMENT', 'Expense Payment'
        SALARY_PAYMENT = 'SALARY_PAYMENT', 'Salary Payment'

    class PaymentMethod(models.TextChoices):
        CASH = 'CASH', 'Cash'
        UZCARD = 'UZCARD', 'Uzcard'
        HUMO = 'HUMO', 'Humo'
        PAYME = 'PAYME', 'Payme'
        BANK_TRANSFER = 'BANK_TRANSFER', 'Bank Transfer'

    type = models.CharField(max_length=20, choices=TransactionType.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.TextField(blank=True, default='')
    payment_method = models.CharField(
        max_length=15,
        choices=PaymentMethod.choices,
        default=PaymentMethod.CASH,
    )
    reference_type = models.CharField(max_length=50, blank=True, default='')
    reference_id = models.PositiveIntegerField(null=True, blank=True)
    balance_before = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    performed_by = models.ForeignKey(
        'base.User',
        on_delete=models.SET_NULL,
        null=True,
        related_name='cash_transactions',
    )
    approved_by = models.ForeignKey(
        'base.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_cash_transactions',
    )
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    objects = SyncManager()

    class Meta:
        ordering = ['-created_at']

    def to_sync_dict(self):
        data = super().to_sync_dict()
        data['performed_by_uuid'] = str(self.performed_by.uuid) if self.performed_by else None
        data['approved_by_uuid'] = str(self.approved_by.uuid) if self.approved_by else None
        return data

    def __str__(self):
        return f"{self.type} - {self.amount} ({self.created_at})"
