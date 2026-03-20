ORDER_NEW = """<b>YANGI BUYURTMA #{display_id}</b>

Kassir: <b>{cashier_name}</b>
Turi: {order_type}
Jami: <b>{total_amount} so'm</b>

{items_list}

Vaqt: {time}"""


ORDER_READY = """<b>BUYURTMA TAYYOR #{display_id}</b>

Tayyorlash vaqti: <b>{prep_time}</b>
Jami: <b>{total_amount} so'm</b>

Vaqt: {time}"""


ORDER_CANCELLED = """<b>BUYURTMA BEKOR QILINDI #{display_id}</b>

Jami: <b>{total_amount} so'm</b>
Holati: Bekor qilingan

Vaqt: {time}"""


ORDER_PAID = """<b>BUYURTMA TO'LANDI #{display_id}</b>

Jami: <b>{total_amount} so'm</b>

Vaqt: {time}"""


SHIFT_START = """<b>SMENA BOSHLANDI</b>

Kassir: <b>{cashier_name}</b>
Sana: {date}
Vaqt: {time}"""


SHIFT_END = """<b>{cashier_name} — SMENA HISOBOTI</b>

{date_from} {time_from} — {date_to} {time_to}
Davomiyligi: <b>{duration}</b>

<b>BUYURTMALAR</b>
Jami: <b>{total_orders}</b>
Bajarilgan: <b>{completed_orders}</b>
Bekor qilingan: <b>{cancelled_orders}</b>
O'rtacha tayyorlash: <b>{avg_prep_time}</b>
Eng band soat: <b>{peak_hour}</b> ({peak_count} ta)

<b>TO'LOVLAR</b>
To'langan: <b>{paid_orders}</b>
To'lanmagan: <b>{unpaid_orders}</b>

<b>BUYURTMA TURLARI</b>
Zalda: <b>{hall_orders}</b> ({hall_revenue} so'm)
Yetkazib berish: <b>{delivery_orders}</b> ({delivery_revenue} so'm)
Olib ketish: <b>{pickup_orders}</b> ({pickup_revenue} so'm)

<b>TOP MAHSULOTLAR</b>
{top_products_list}

<b>MOLIYAVIY NATIJA</b>
Jami tushum: <b>{total_revenue} so'm</b>
O'rtacha chek: <b>{avg_order_value} so'm</b>"""


SHIFT_SWITCH = """<b>SMENA ALMASHDI</b>

Chiqdi: <b>{old_cashier}</b>
Kirdi: <b>{new_cashier}</b>

Sana: {date}
Vaqt: {time}"""


ORDER_TYPE_LABELS = {
    'HALL': 'Zalda',
    'DELIVERY': 'Yetkazib berish',
    'PICKUP': 'Olib ketish',
}
