"""Which imported CPIS copy decides when the two copies inside the Excel workbooks disagree.

Decisão do Luís de 06/10/2026, que substitui a regra de 20/09 («não se resolve escolhendo uma cópia»)
e a de 23/09 (C06, «basta uma cópia dizer Fechada»): manda a cópia mais recente, para todos os campos.
Módulo próprio para que serviços já em execução não misturem uma versão antiga de planning_population.
"""
from datetime import datetime, timezone


def _instant(value):
    """Comparable moment; naive values are read as UTC so both copies compare."""
    if value is None:
        return None
    if not isinstance(value, datetime):  # a plain date
        value = datetime(value.year, value.month, value.day)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def latest_first(rows, *, loaded='copy_loaded_at', recorded='copy_record_date'):
    """CPIS copies newest first: the copy whose Excel was loaded later, then the greater record date.

    Decisão do Luís de 06/10/2026 (substitui 20/09 e C06 de 23/09): quando as cópias do CPIS
    discordam, manda a cópia mais recente, para todos os campos.
    """
    floor = datetime.min.replace(tzinfo=timezone.utc)
    return sorted(rows, key=lambda r: (_instant(r.get(loaded)) or floor, _instant(r.get(recorded)) or floor),
                  reverse=True)
