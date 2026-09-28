"""Stable, local-calendar forecast anchored to a successful preparation save."""
from contextvars import ContextVar
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


ANONYMOUS='Utilizador não identificado'
# Set per request by the planning app's proxy-identity middleware (app/sector/auth.py), only when the
# request carries the reverse proxy's secret. The MES never sets it, so its behaviour is unchanged.
ACTOR=ContextVar('planning_actor',default=None)


def human_actor(payload):
    # A name sent by the client is not identity; only the authenticated proxy user counts.
    return ACTOR.get() or ANONYMOUS
