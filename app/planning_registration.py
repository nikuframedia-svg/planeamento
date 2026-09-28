"""Stable, local-calendar forecast anchored to a successful preparation save."""
from datetime import timedelta
from zoneinfo import ZoneInfo
from . import planning
from .config import settings
from .dossiers.models import order_number


def forecast(instant, zone):
    if instant.tzinfo is None:
        raise ValueError('Registration instants must be timezone-aware')
    return instant.astimezone(ZoneInfo(zone)).date()+timedelta(days=7)


def read(of, conn=None):
    if conn is None:
        with planning.connect(readonly=True) as connection:return read(of,connection)
    row=conn.execute('SELECT * FROM planning_mtg.order_registration WHERE production_order_no=%s',
                     (order_number(of),)).fetchone()
    return planning.serializable(row) if row else None


def register(conn, of):
    # The caller's record transaction owns this insert: failed saves roll it back.
    number=order_number(of)
    zone=settings.display_timezone
    instant=conn.execute('''SELECT min(created_at) AS first_at FROM planning_mtg.records
        WHERE upper(trim(production_order_no)) IN (%s,%s)''',(number,number[2:])).fetchone()['first_at']
    if instant is None:raise ValueError('A saved preparation is required')
    conn.execute('''INSERT INTO planning_mtg.order_registration VALUES (%s,%s,%s,%s)
        ON CONFLICT(production_order_no) DO NOTHING''',(number,instant,zone,forecast(instant,zone)))
    return read(number,conn)


def human_actor(payload):
    # No individual authentication is configured. A client name is not identity.
    return 'Utilizador não identificado'
