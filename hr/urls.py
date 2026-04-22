from django.urls import path
from hr.views import department_views, employee_views, expense_views, salary_views, cash_views

app_name = 'hr'

urlpatterns = [
    # Departments
    path('departments/', department_views.departments, name='department-list'),
    path('departments/<int:department_id>/', department_views.department_detail, name='department-detail'),

    # Employees
    path('employees/', employee_views.employees, name='employee-list'),
    path('employees/stats/', employee_views.employee_stats, name='employee-stats'),
    path('employees/<int:employee_id>/', employee_views.employee_detail, name='employee-detail'),

    # Expense Categories
    path('expense-categories/', expense_views.expense_categories, name='expense-category-list'),
    path('expense-categories/<int:category_id>/', expense_views.expense_category_detail, name='expense-category-detail'),

    # Expenses
    path('expenses/', expense_views.expenses, name='expense-list'),
    path('expenses/stats/', expense_views.expense_stats, name='expense-stats'),
    path('expenses/<int:expense_id>/', expense_views.expense_detail, name='expense-detail'),
    path('expenses/<int:expense_id>/approve/', expense_views.expense_approve, name='expense-approve'),
    path('expenses/<int:expense_id>/reject/', expense_views.expense_reject, name='expense-reject'),
    path('expenses/<int:expense_id>/pay/', expense_views.expense_pay, name='expense-pay'),

    # Salary
    path('salaries/', salary_views.salaries, name='salary-list'),
    path('salaries/generate/', salary_views.salary_generate, name='salary-generate'),
    path('salaries/approve-all/', salary_views.salary_approve_all, name='salary-approve-all'),
    path('salaries/summary/', salary_views.salary_summary, name='salary-summary'),
    path('salaries/<int:salary_id>/', salary_views.salary_detail, name='salary-detail'),
    path('salaries/<int:salary_id>/approve/', salary_views.salary_approve, name='salary-approve'),
    path('salaries/<int:salary_id>/pay/', salary_views.salary_pay, name='salary-pay'),

    # Cash
    path('cash/', cash_views.cash_transactions, name='cash-list'),
    path('cash/deposit/', cash_views.cash_deposit, name='cash-deposit'),
    path('cash/withdraw/', cash_views.cash_withdraw, name='cash-withdraw'),
    path('cash/balance/', cash_views.cash_balance, name='cash-balance'),
    path('cash/<int:transaction_id>/', cash_views.cash_transaction_detail, name='cash-detail'),
]
