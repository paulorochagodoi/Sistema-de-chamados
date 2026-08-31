"""Faturamento: apontamentos + contrato -> fatura."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.billing import BillingError, billable_minutes, generate_invoice
from app.models import BillingModel, Contract, InvoiceRequest, TimeEntry

PERIOD_START = date(2026, 8, 1)
PERIOD_END = date(2026, 8, 31)


def contract(**overrides) -> Contract:
    base = {
        "id": "CT-001",
        "client": "Cliente Exemplo Ltda",
        "billing_model": BillingModel.HOURLY,
        "hourly_rate": Decimal("180.00"),
    }
    base.update(overrides)
    return Contract(**base)


def invoice_for(contract_obj: Contract, **overrides) -> InvoiceRequest:
    payload = {
        "contract": contract_obj,
        "period_start": PERIOD_START,
        "period_end": PERIOD_END,
    }
    payload.update(overrides)
    return InvoiceRequest(**payload)


# --- arredondamento --------------------------------------------------------
def test_arredonda_para_o_multiplo_seguinte():
    ct = contract(rounding_increment_minutes=15)
    assert billable_minutes(TimeEntry(ticket_id=1, minutes=1), ct) == 15
    assert billable_minutes(TimeEntry(ticket_id=1, minutes=16), ct) == 30
    assert billable_minutes(TimeEntry(ticket_id=1, minutes=30), ct) == 30


def test_respeita_minimo_cobravel_por_atendimento():
    ct = contract(minimum_billable_minutes=30, rounding_increment_minutes=15)
    assert billable_minutes(TimeEntry(ticket_id=1, minutes=5), ct) == 30


def test_apontamento_nao_billavel_nao_gera_minutos():
    ct = contract(minimum_billable_minutes=30)
    assert billable_minutes(TimeEntry(ticket_id=1, minutes=90, billable=False), ct) == 0


# --- modelos de cobrança ---------------------------------------------------
def test_por_hora_soma_apontamentos_billaveis():
    ct = contract()
    invoice = generate_invoice(
        invoice_for(
            ct,
            time_entries=[
                TimeEntry(ticket_id=1, minutes=90),
                TimeEntry(ticket_id=2, minutes=30),
                TimeEntry(ticket_id=3, minutes=60, billable=False),
            ],
        )
    )
    assert invoice.billable_minutes == 120
    assert invoice.non_billable_minutes == 60
    assert invoice.total == Decimal("360.00")  # 2h x 180
    assert [line.kind for line in invoice.lines] == ["hours"]


def test_hora_com_rate_override_vira_linha_propria():
    ct = contract()
    invoice = generate_invoice(
        invoice_for(
            ct,
            time_entries=[
                TimeEntry(ticket_id=1, minutes=60),
                TimeEntry(ticket_id=2, minutes=60, rate_override=Decimal("270.00")),
            ],
        )
    )
    assert len(invoice.lines) == 2
    assert invoice.total == Decimal("450.00")


def test_por_chamado():
    ct = contract(billing_model=BillingModel.PER_TICKET, per_ticket_rate=Decimal("95.50"))
    invoice = generate_invoice(invoice_for(ct, closed_tickets=12))
    assert invoice.total == Decimal("1146.00")


def test_por_ativo_monitorado():
    ct = contract(billing_model=BillingModel.PER_ASSET, per_asset_rate=Decimal("29.90"))
    invoice = generate_invoice(invoice_for(ct, monitored_assets=40))
    assert invoice.total == Decimal("1196.00")


def test_recorrencia_fixa_independe_do_volume():
    ct = contract(billing_model=BillingModel.FIXED, fixed_amount=Decimal("4200.00"))
    invoice = generate_invoice(
        invoice_for(ct, time_entries=[TimeEntry(ticket_id=1, minutes=600)])
    )
    assert invoice.total == Decimal("4200.00")
    # as horas continuam contabilizadas para relatório, mesmo sem cobrança extra
    assert invoice.billable_minutes == 600


def test_franquia_mais_excedente():
    ct = contract(
        billing_model=BillingModel.FIXED_PLUS_HOURLY,
        fixed_amount=Decimal("3000.00"),
        included_hours=Decimal("10"),
        hourly_rate=Decimal("200.00"),
    )
    invoice = generate_invoice(
        invoice_for(ct, time_entries=[TimeEntry(ticket_id=1, minutes=750)])  # 12,5h
    )
    kinds = [line.kind for line in invoice.lines]
    assert kinds == ["fixed", "overage_hours"]
    assert invoice.total == Decimal("3500.00")  # 3000 + 2,5h x 200


def test_franquia_sem_excedente_nao_gera_linha_extra():
    ct = contract(
        billing_model=BillingModel.FIXED_PLUS_HOURLY,
        fixed_amount=Decimal("3000.00"),
        included_hours=Decimal("10"),
        hourly_rate=Decimal("200.00"),
    )
    invoice = generate_invoice(
        invoice_for(ct, time_entries=[TimeEntry(ticket_id=1, minutes=300)])
    )
    assert [line.kind for line in invoice.lines] == ["fixed"]
    assert invoice.total == Decimal("3000.00")


# --- desconto, imposto e período ------------------------------------------
def test_desconto_e_imposto_aplicados_na_ordem_correta():
    ct = contract(discount_percent=Decimal("10"), tax_percent=Decimal("5"))
    invoice = generate_invoice(
        invoice_for(ct, time_entries=[TimeEntry(ticket_id=1, minutes=600)])  # 10h = 1800
    )
    assert invoice.subtotal == Decimal("1800.00")
    assert invoice.discount == Decimal("180.00")
    assert invoice.tax == Decimal("81.00")       # 5% sobre 1620
    assert invoice.total == Decimal("1701.00")


def test_apontamento_fora_do_periodo_e_ignorado():
    ct = contract()
    invoice = generate_invoice(
        invoice_for(
            ct,
            time_entries=[
                TimeEntry(ticket_id=1, minutes=60, performed_at=date(2026, 7, 31)),
                TimeEntry(ticket_id=2, minutes=60, performed_at=date(2026, 8, 15)),
                TimeEntry(ticket_id=3, minutes=60, performed_at=date(2026, 9, 1)),
            ],
        )
    )
    assert invoice.billable_minutes == 60
    assert invoice.total == Decimal("180.00")


def test_periodo_invertido_e_rejeitado():
    with pytest.raises(BillingError):
        generate_invoice(
            invoice_for(contract(), period_start=PERIOD_END, period_end=PERIOD_START)
        )


def test_periodo_fora_da_vigencia_do_contrato_e_rejeitado():
    ct = contract(valid_from=date(2026, 9, 1))
    with pytest.raises(BillingError, match="vigência"):
        generate_invoice(invoice_for(ct))


def test_fatura_sem_movimento_fica_zerada():
    invoice = generate_invoice(invoice_for(contract()))
    assert invoice.lines == []
    assert invoice.total == Decimal("0.00")
