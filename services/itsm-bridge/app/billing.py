"""Motor de faturamento: apontamentos de horas + contrato -> fatura.

Regras suportadas (seção 2.4 da especificação):

``hourly``            todas as horas billáveis pelo valor/hora do contrato
``per_ticket``        valor fixo por chamado encerrado no período
``per_asset``         valor por ativo monitorado no período
``fixed``             recorrência fixa, independente do volume
``fixed_plus_hourly`` recorrência fixa com franquia de horas + excedente

Sobre arredondamento: cada apontamento é arredondado individualmente para cima
até o múltiplo de ``rounding_increment_minutes``, respeitando o mínimo cobrado
por atendimento (``minimum_billable_minutes``). Arredondar por apontamento (e
não no total) é o comportamento que MSPs praticam e o que o cliente confere na
fatura, linha a linha.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from itertools import groupby

from .models import BillingModel, Contract, Invoice, InvoiceLine, InvoiceRequest, TimeEntry

CENTS = Decimal("0.01")
MINUTES_PER_HOUR = Decimal("60")


class BillingError(ValueError):
    """Entrada inconsistente para o cálculo da fatura."""


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def _hours(minutes: int | Decimal) -> Decimal:
    return (Decimal(minutes) / MINUTES_PER_HOUR).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def billable_minutes(entry: TimeEntry, contract: Contract) -> int:
    """Minutos cobráveis de um apontamento após mínimo e arredondamento."""
    if not entry.billable or entry.minutes <= 0:
        return 0
    minutes = max(entry.minutes, contract.minimum_billable_minutes)
    increment = contract.rounding_increment_minutes
    if increment > 1:
        remainder = minutes % increment
        if remainder:
            minutes += increment - remainder
    return minutes


def _in_period(entry: TimeEntry, start: date, end: date) -> bool:
    # apontamento sem data é considerado dentro do período solicitado
    return entry.performed_at is None or start <= entry.performed_at <= end


def _hourly_lines(
    entries: list[TimeEntry], contract: Contract, total_minutes: int
) -> list[InvoiceLine]:
    """Linhas por hora, agrupadas por valor/hora aplicado.

    Apontamentos com ``rate_override`` viram linhas próprias — é como se
    representa hora de plantão, deslocamento ou especialista.
    """
    priced: list[tuple[Decimal, int]] = []
    for entry in entries:
        minutes = billable_minutes(entry, contract)
        if minutes:
            rate = entry.rate_override if entry.rate_override is not None else contract.hourly_rate
            priced.append((rate, minutes))

    lines: list[InvoiceLine] = []
    priced.sort(key=lambda item: item[0])
    for rate, group in groupby(priced, key=lambda item: item[0]):
        minutes = sum(item[1] for item in group)
        quantity = _hours(minutes)
        lines.append(
            InvoiceLine(
                kind="hours",
                description=f"Horas técnicas ({quantity}h a {rate}/h)",
                quantity=quantity,
                unit_price=_money(rate),
                amount=_money(quantity * rate),
            )
        )
    if not lines and total_minutes == 0:
        return []
    return lines


def generate_invoice(request: InvoiceRequest) -> Invoice:
    """Gera a fatura do período a partir do contrato e dos apontamentos."""
    contract = request.contract
    if request.period_end < request.period_start:
        raise BillingError("period_end anterior a period_start")
    if contract.valid_from and request.period_end < contract.valid_from:
        raise BillingError("período anterior ao início de vigência do contrato")
    if contract.valid_until and request.period_start > contract.valid_until:
        raise BillingError("período posterior ao fim de vigência do contrato")

    entries = [
        e for e in request.time_entries
        if _in_period(e, request.period_start, request.period_end)
    ]
    billable_total = sum(billable_minutes(e, contract) for e in entries)
    non_billable_total = sum(e.minutes for e in entries if not e.billable)

    lines: list[InvoiceLine] = []

    if contract.billing_model is BillingModel.HOURLY:
        lines.extend(_hourly_lines(entries, contract, billable_total))

    elif contract.billing_model is BillingModel.PER_TICKET:
        if request.closed_tickets:
            quantity = Decimal(request.closed_tickets)
            lines.append(
                InvoiceLine(
                    kind="tickets",
                    description=f"Chamados encerrados no período ({request.closed_tickets})",
                    quantity=quantity,
                    unit_price=_money(contract.per_ticket_rate),
                    amount=_money(quantity * contract.per_ticket_rate),
                )
            )

    elif contract.billing_model is BillingModel.PER_ASSET:
        if request.monitored_assets:
            quantity = Decimal(request.monitored_assets)
            lines.append(
                InvoiceLine(
                    kind="assets",
                    description=f"Ativos monitorados ({request.monitored_assets})",
                    quantity=quantity,
                    unit_price=_money(contract.per_asset_rate),
                    amount=_money(quantity * contract.per_asset_rate),
                )
            )

    elif contract.billing_model is BillingModel.FIXED:
        lines.append(
            InvoiceLine(
                kind="fixed",
                description="Mensalidade contratual",
                quantity=Decimal("1"),
                unit_price=_money(contract.fixed_amount),
                amount=_money(contract.fixed_amount),
            )
        )

    elif contract.billing_model is BillingModel.FIXED_PLUS_HOURLY:
        lines.append(
            InvoiceLine(
                kind="fixed",
                description=(
                    f"Mensalidade contratual (franquia de {contract.included_hours}h)"
                ),
                quantity=Decimal("1"),
                unit_price=_money(contract.fixed_amount),
                amount=_money(contract.fixed_amount),
            )
        )
        consumed_hours = _hours(billable_total)
        overage = consumed_hours - contract.included_hours
        if overage > 0:
            lines.append(
                InvoiceLine(
                    kind="overage_hours",
                    description=(
                        f"Horas excedentes ({overage}h além da franquia de "
                        f"{contract.included_hours}h)"
                    ),
                    quantity=overage,
                    unit_price=_money(contract.hourly_rate),
                    amount=_money(overage * contract.hourly_rate),
                )
            )
    else:  # pragma: no cover - enum exaustivo
        raise BillingError(f"modelo de cobrança não suportado: {contract.billing_model}")

    subtotal = _money(sum((line.amount for line in lines), Decimal("0")))

    discount = _money(subtotal * contract.discount_percent / Decimal("100"))
    if discount:
        lines.append(
            InvoiceLine(
                kind="discount",
                description=f"Desconto contratual ({contract.discount_percent}%)",
                quantity=Decimal("1"),
                unit_price=-discount,
                amount=-discount,
            )
        )

    taxable = subtotal - discount
    tax = _money(taxable * contract.tax_percent / Decimal("100"))
    if tax:
        lines.append(
            InvoiceLine(
                kind="tax",
                description=f"Impostos ({contract.tax_percent}%)",
                quantity=Decimal("1"),
                unit_price=tax,
                amount=tax,
            )
        )

    return Invoice(
        contract_id=contract.id,
        client=contract.client,
        period_start=request.period_start,
        period_end=request.period_end,
        currency=contract.currency,
        lines=lines,
        subtotal=subtotal,
        discount=discount,
        tax=tax,
        total=_money(taxable + tax),
        billable_minutes=billable_total,
        non_billable_minutes=non_billable_total,
    )
