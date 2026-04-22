from django.core.management.base import BaseCommand
from notifications.models import NotificationTemplate


TEMPLATES = [
    {
        'notification_type': 'order.new',
        'name': 'Yangi buyurtma',
        'template_text': (
            '<b>{brand}</b>\n'
            'Yangi buyurtma\n'
            '\n'
            'Buyurtma: #{display_id}\n'
            'Kassir: {cashier_name}\n'
            'Turi: {order_type}\n'
            "Jami: {total_amount} so'm\n"
            '\n'
            '{items_list}\n'
            '\n'
            'Vaqt: {time}'
        ),
    },
    {
        'notification_type': 'order.ready',
        'name': 'Buyurtma tayyor',
        'template_text': (
            '<b>{brand}</b>\n'
            'Buyurtma tayyor\n'
            '\n'
            'Buyurtma: #{display_id}\n'
            'Tayyorlash vaqti: {prep_time}\n'
            "Jami: {total_amount} so'm\n"
            '\n'
            'Vaqt: {time}'
        ),
    },
    {
        'notification_type': 'order.cancelled',
        'name': 'Buyurtma bekor qilindi',
        'template_text': (
            '<b>{brand}</b>\n'
            'Buyurtma bekor qilindi\n'
            '\n'
            'Buyurtma: #{display_id}\n'
            "Jami: {total_amount} so'm\n"
            '\n'
            'Vaqt: {time}'
        ),
    },
    {
        'notification_type': 'order.paid',
        'name': "Buyurtma to'landi",
        'template_text': (
            '<b>{brand}</b>\n'
            "Buyurtma to'landi\n"
            '\n'
            'Buyurtma: #{display_id}\n'
            "Jami: {total_amount} so'm\n"
            '\n'
            'Vaqt: {time}'
        ),
    },
    {
        'notification_type': 'shift.start',
        'name': 'Smena boshlandi',
        'template_text': (
            '<b>{brand}</b>\n'
            'Smena boshlandi\n'
            '\n'
            'Kassir: {cashier_name}\n'
            'Sana: {date}\n'
            'Vaqt: {time}'
        ),
    },
    {
        'notification_type': 'shift.end',
        'name': 'Smena hisoboti',
        'template_text': (
            '<b>{brand}</b>\n'
            '{cashier_name} — Smena hisoboti\n'
            '\n'
            '{date_from} {time_from} — {date_to} {time_to}\n'
            'Davomiyligi: {duration}\n'
            '\n'
            'Buyurtmalar\n'
            'Jami: {total_orders}\n'
            'Bajarilgan: {completed_orders}\n'
            'Bekor qilingan: {cancelled_orders}\n'
            "O'rtacha tayyorlash: {avg_prep_time}\n"
            'Eng band soat: {peak_hour} ({peak_count} ta)\n'
            '\n'
            "To'lovlar\n"
            "To'langan: {paid_orders}\n"
            "To'lanmagan: {unpaid_orders}\n"
            '\n'
            'Buyurtma turlari\n'
            "Zalda: {hall_orders} ({hall_revenue} so'm)\n"
            "Yetkazib berish: {delivery_orders} ({delivery_revenue} so'm)\n"
            "Olib ketish: {pickup_orders} ({pickup_revenue} so'm)\n"
            '\n'
            'Top mahsulotlar\n'
            '{top_products_list}\n'
            '\n'
            'Moliyaviy natija\n'
            "Jami tushum: {total_revenue} so'm\n"
            "O'rtacha chek: {avg_order_value} so'm"
        ),
    },
    {
        'notification_type': 'shift.switch',
        'name': 'Smena almashdi',
        'template_text': (
            '<b>{brand}</b>\n'
            'Smena almashdi\n'
            '\n'
            'Chiqdi: {old_cashier}\n'
            'Kirdi: {new_cashier}\n'
            '\n'
            'Sana: {date}\n'
            'Vaqt: {time}'
        ),
    },
    {
        'notification_type': 'hr.contract_expiry',
        'name': 'Shartnoma muddati tugayapti',
        'template_text': (
            '<b>{brand}</b>\n'
            'Shartnoma muddati tugayapti\n'
            '\n'
            'Xodim: {employee_name}\n'
            'Shartnoma: {contract_number}\n'
            'Tugash sanasi: {end_date}\n'
            'Qolgan kunlar: {days_until}'
        ),
    },
    {
        'notification_type': 'hr.probation_end',
        'name': 'Sinov muddati tugayapti',
        'template_text': (
            '<b>{brand}</b>\n'
            'Sinov muddati tugayapti\n'
            '\n'
            'Xodim: {employee_name}\n'
            'Sinov muddati tugashi: {probation_end_date}\n'
            'Qolgan kunlar: {days_until}'
        ),
    },
    {
        'notification_type': 'hr.document_expiry',
        'name': 'Hujjat muddati tugayapti',
        'template_text': (
            '<b>{brand}</b>\n'
            'Hujjat muddati tugayapti\n'
            '\n'
            'Xodim: {employee_name}\n'
            'Hujjat: {document_title} ({document_type})\n'
            'Tugash sanasi: {expiry_date}\n'
            'Qolgan kunlar: {days_until}'
        ),
    },
]


class Command(BaseCommand):
    help = 'Seed default notification templates'

    def handle(self, *args, **options):
        created = 0
        existing = 0

        for tpl in TEMPLATES:
            _, was_created = NotificationTemplate.objects.get_or_create(
                notification_type=tpl['notification_type'],
                defaults={
                    'name': tpl['name'],
                    'template_text': tpl['template_text'],
                },
            )
            if was_created:
                created += 1
                self.stdout.write(self.style.SUCCESS(f"  Created: {tpl['notification_type']}"))
            else:
                existing += 1
                self.stdout.write(f"  Exists:  {tpl['notification_type']}")

        self.stdout.write(self.style.SUCCESS(
            f'\nDone. Created: {created}, Already existed: {existing}'
        ))
