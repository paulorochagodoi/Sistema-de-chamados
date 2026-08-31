"""Cálculo de prazos de SLA respeitando a janela de atendimento do contrato.

Regras implementadas:

* Contratos 24x7 consomem tempo corrido.
* Demais contratos só consomem tempo dentro da janela de atendimento
  (``BusinessHours.start``..``end``), nos dias úteis do contrato e fora dos
  feriados informados.
* Um chamado aberto fora da janela começa a contar na próxima abertura —
  é isso que evita "estourar" SLA durante a madrugada.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from .models import BusinessHours, SLARequest, SLAResponse

_MAX_DAYS_LOOKAHEAD = 3650  # 10 anos: guarda contra calendário sem dia útil


def _parse_time(value: str) -> time:
    hour, _, minute = value.partition(":")
    return time(hour=int(hour), minute=int(minute or 0))


def is_working_day(day: date, hours: BusinessHours) -> bool:
    if hours.around_the_clock:
        return True
    return day.weekday() in hours.workdays and day not in set(hours.holidays)


def _next_window_start(moment: datetime, hours: BusinessHours) -> datetime:
    """Primeiro instante >= ``moment`` que está dentro da janela de atendimento."""
    opening = _parse_time(hours.start)
    closing = _parse_time(hours.end)

    current = moment
    for _ in range(_MAX_DAYS_LOOKAHEAD):
        day = current.date()
        if is_working_day(day, hours):
            day_open = datetime.combine(day, opening)
            day_close = datetime.combine(day, closing)
            if current < day_open:
                return day_open
            if current < day_close:
                return current
        # depois do fechamento (ou dia não útil): tenta a abertura do dia seguinte
        current = datetime.combine(day + timedelta(days=1), opening)
    raise ValueError("calendário sem dias úteis: verifique workdays/holidays do contrato")


def add_business_minutes(start: datetime, minutes: int, hours: BusinessHours) -> datetime:
    """Soma ``minutes`` de atendimento a ``start``, pulando fora de janela."""
    if minutes < 0:
        raise ValueError("minutes deve ser >= 0")
    if hours.around_the_clock:
        return start + timedelta(minutes=minutes)
    if _parse_time(hours.end) <= _parse_time(hours.start):
        raise ValueError("janela de atendimento inválida: end deve ser maior que start")

    closing = _parse_time(hours.end)
    current = _next_window_start(start, hours)
    remaining = timedelta(minutes=minutes)

    for _ in range(_MAX_DAYS_LOOKAHEAD):
        if remaining <= timedelta(0):
            return current
        day_close = datetime.combine(current.date(), closing)
        available = day_close - current
        if remaining <= available:
            return current + remaining
        remaining -= available
        # avança para a abertura do próximo dia útil
        current = _next_window_start(
            datetime.combine(current.date() + timedelta(days=1), time(0, 0)), hours
        )
    raise ValueError("não foi possível calcular o prazo dentro do horizonte suportado")


def business_minutes_between(start: datetime, end: datetime, hours: BusinessHours) -> int:
    """Minutos de atendimento consumidos entre dois instantes (0 se end <= start)."""
    if end <= start:
        return 0
    if hours.around_the_clock:
        return int((end - start).total_seconds() // 60)

    closing = _parse_time(hours.end)
    total = timedelta(0)
    current = _next_window_start(start, hours)

    while current < end:
        day_close = datetime.combine(current.date(), closing)
        segment_end = min(day_close, end)
        if segment_end > current:
            total += segment_end - current
        if day_close >= end:
            break
        current = _next_window_start(
            datetime.combine(current.date() + timedelta(days=1), time(0, 0)), hours
        )
    return int(total.total_seconds() // 60)


def compute(request: SLARequest) -> SLAResponse:
    """Calcula os prazos de primeira resposta e de resolução de um chamado."""
    response_due = add_business_minutes(
        request.opened_at, request.response_minutes, request.business_hours
    )
    resolution_due = add_business_minutes(
        request.opened_at, request.resolution_minutes, request.business_hours
    )
    return SLAResponse(
        opened_at=request.opened_at,
        response_due_at=response_due,
        resolution_due_at=resolution_due,
        business_minutes_to_response=request.response_minutes,
        business_minutes_to_resolution=request.resolution_minutes,
    )


def is_at_risk(
    due_at: datetime, now: datetime, threshold_minutes: int, hours: BusinessHours
) -> bool:
    """True quando faltam menos de ``threshold_minutes`` úteis para o prazo.

    Um prazo já estourado também conta como em risco — é o que dispara o
    escalonamento antes de o cliente reclamar.
    """
    if due_at <= now:
        return True
    return business_minutes_between(now, due_at, hours) <= threshold_minutes
