"""Assinatura HMAC dos webhooks."""

from __future__ import annotations

import pytest

from app.security import InvalidSignature, sign, verify

BODY = b'{"alert_id":"a-1","hostname":"srv","check":"cpu"}'
SECRET = "segredo-compartilhado"


def test_assinatura_gerada_e_aceita():
    verify(BODY, sign(BODY, SECRET), SECRET)


def test_corpo_adulterado_e_rejeitado():
    signature = sign(BODY, SECRET)
    with pytest.raises(InvalidSignature, match="não confere"):
        verify(BODY + b" ", signature, SECRET)


def test_segredo_errado_e_rejeitado():
    with pytest.raises(InvalidSignature):
        verify(BODY, sign(BODY, "outro-segredo"), SECRET)


def test_cabecalho_ausente_e_rejeitado():
    with pytest.raises(InvalidSignature, match="ausente"):
        verify(BODY, None, SECRET)


@pytest.mark.parametrize("signature", ["", "sha1=abc", "abc", "sha256=", "sha256"])
def test_formato_invalido_e_rejeitado(signature):
    with pytest.raises(InvalidSignature):
        verify(BODY, signature, SECRET)


def test_sem_segredo_configurado_a_validacao_e_ignorada():
    # modo desenvolvimento: aceita qualquer coisa (documentado em segurança)
    verify(BODY, None, "")
    verify(BODY, "sha256=qualquer", "")
