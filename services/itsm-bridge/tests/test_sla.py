"""Prazos de SLA com janela de atendimento, fim de semana e feriado."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.models import BusinessHours, SLARequest
from app.sla import add_business_minutes, business_minutes_between, compute, is_at_risk

# 2026-08-31 é uma segunda-feira; 2026-09-05 é sábado.
COMERCIAL = BusinessHours(start="08:00", end="18:00", workdays=[0, 1, 2, 3, 4])


def test_prazo_dentro_do_mesmo_dia():
    due = add_business_minutes(datetime(2026, 8, 31, 9, 0), 120, COMERCIAL)
    assert due == datetime(2026, 8, 31, 11, 0)


def test_prazo_atravessa_a_noite_e_continua_no_dia_seguinte():
    # abre 17h, precisa de 3h úteis: 1h hoje + 2h amanhã a partir das 8h
    due = add_business_minutes(datetime(2026, 8, 31, 17, 0), 180, COMERCIAL)
    assert due == datetime(2026, 9, 1, 10, 0)


def test_chamado_aberto_de_madrugada_comeca_a_contar_na_abertura():
    due = add_business_minutes(datetime(2026, 8, 31, 3, 0), 60, COMERCIAL)
    assert due == datetime(2026, 8, 31, 9, 0)


def test_fim_de_semana_nao_consome_sla():
    # sexta 17h + 2h úteis -> segunda 9h
    due = add_business_minutes(datetime(2026, 9, 4, 17, 0), 120, COMERCIAL)
    assert due == datetime(2026, 9, 7, 9, 0)


def test_feriado_e_pulado():
    hours = COMERCIAL.model_copy(update={"holidays": [date(2026, 9, 1)]})
    due = add_business_minutes(datetime(2026, 8, 31, 17, 30), 60, hours)
    assert due == datetime(2026, 9, 2, 8, 30)


def test_contrato_24x7_usa_tempo_corrido():
    hours = BusinessHours(around_the_clock=True)
    due = add_business_minutes(datetime(2026, 8, 31, 23, 0), 120, hours)
    assert due == datetime(2026, 9, 1, 1, 0)


def test_minutos_uteis_entre_dois_instantes():
    # de sexta 17h a segunda 9h: 1h na sexta + 1h na segunda
    minutes = business_minutes_between(
        datetime(2026, 9, 4, 17, 0), datetime(2026, 9, 7, 9, 0), COMERCIAL
    )
    assert minutes == 120


def test_minutos_uteis_zero_quando_intervalo_invertido():
    assert (
        business_minutes_between(
            datetime(2026, 9, 4, 17, 0), datetime(2026, 9, 4, 16, 0), COMERCIAL
        )
        == 0
    )


def test_compute_devolve_os_dois_prazos():
    response = compute(
        SLARequest(
            opened_at=datetime(2026, 8, 31, 9, 0),
            response_minutes=30,
            resolution_minutes=480,
            business_hours=COMERCIAL,
        )
    )
    assert response.response_due_at == datetime(2026, 8, 31, 9, 30)
    # 8h úteis a partir das 9h ainda cabem no mesmo dia (janela 8h-18h)
    assert response.resolution_due_at == datetime(2026, 8, 31, 17, 0)


def test_sla_em_risco_quando_falta_menos_que_o_limiar():
    due = datetime(2026, 8, 31, 12, 0)
    assert is_at_risk(due, datetime(2026, 8, 31, 11, 30), 60, COMERCIAL) is True
    assert is_at_risk(due, datetime(2026, 8, 31, 9, 0), 60, COMERCIAL) is False


def test_sla_estourado_conta_como_em_risco():
    assert is_at_risk(
        datetime(2026, 8, 31, 12, 0), datetime(2026, 8, 31, 13, 0), 60, COMERCIAL
    ) is True


def test_janela_invalida_e_rejeitada():
    hours = BusinessHours(start="18:00", end="08:00")
    with pytest.raises(ValueError, match="janela de atendimento inválida"):
        add_business_minutes(datetime(2026, 8, 31, 9, 0), 60, hours)


def test_calendario_sem_dia_util_e_rejeitado():
    hours = BusinessHours(workdays=[])
    with pytest.raises(ValueError, match="sem dias úteis"):
        add_business_minutes(datetime(2026, 8, 31, 9, 0), 60, hours)
