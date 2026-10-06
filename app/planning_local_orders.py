"""Local OF/OV context. Never overwrites CPIS facts or duplicates its order key."""
from datetime import date
from psycopg.types.json import Jsonb
from . import planning
from .dossiers.models import order_number

FIELDS = {'ov','customer','designation','delivery_date'}


def available(conn):
    return bool(conn.execute("SELECT to_regclass('planning_mtg.local_orders') t").fetchone()['t'])


def read(conn, of):
    if not available(conn): return None
    return conn.execute('SELECT * FROM planning_mtg.local_orders WHERE production_order_no=%s',(order_number(of),)).fetchone()


def save(conn, of, payload, actor):
    if not isinstance(payload,dict) or set(payload)-{'values','expected_revision'}:
        raise planning.PlanningError('Contexto local da ordem inválido.')
    if not available(conn): raise planning.PlanningError('Falta instalar o registo de ordens locais.',503)
    values=payload.get('values')
    if not isinstance(values,dict) or set(values)-FIELDS:raise planning.PlanningError('Campos administrativos inválidos.')
    number=order_number(of)
    if not number:raise planning.PlanningError('Indica uma OF válida.')
    prior=conn.execute('SELECT * FROM planning_mtg.local_orders WHERE production_order_no=%s FOR UPDATE',(number,)).fetchone()
    merged={**(prior['values_json'] if prior else {}),**values}
    for field,value in merged.items():
        if value is not None and (not isinstance(value,str) or len(value)>2000):raise planning.PlanningError('Texto administrativo inválido.')
        merged[field]=value.strip() if value else None
    from .raw.registration import enabled as free_entry
    if merged.get('delivery_date') and not free_entry():
        try:date.fromisoformat(merged['delivery_date'])
        except ValueError:raise planning.PlanningError('Data de entrega local inválida.') from None
    if prior and merged==prior['values_json']:return prior
    if payload.get('expected_revision',0)!=(prior['revision'] if prior else 0):
        raise planning.PlanningError('Os dados desta OF mudaram. Reabre a ordem antes de os alterar.',409)
    result=conn.execute('''INSERT INTO planning_mtg.local_orders(production_order_no,values_json,actor)
        VALUES(%s,%s,%s) ON CONFLICT(production_order_no) DO UPDATE
        SET values_json=excluded.values_json,revision=local_orders.revision+1,actor=excluded.actor,updated_at=now()
        RETURNING *''',(number,Jsonb(merged),actor)).fetchone()
    conn.execute('INSERT INTO planning_mtg.local_order_history(production_order_no,revision,values_json,actor) VALUES(%s,%s,%s,%s)',
                 (number,result['revision'],Jsonb(merged),actor))
    return result
