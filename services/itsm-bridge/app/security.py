"""Validação de assinatura HMAC dos webhooks recebidos.

Todo webhook (RMM, Chatwoot, ERP) deve chegar assinado com um segredo
compartilhado. O emissor calcula HMAC-SHA256 sobre o corpo bruto e envia o
resultado no cabeçalho ``X-ITSM-Signature`` no formato ``sha256=<hex>``.

Se o segredo não estiver configurado a validação é ignorada — aceitável só em
desenvolvimento; em produção o deploy deve falhar sem segredo (ver
``docs/06-seguranca-compliance.md``).
"""

from __future__ import annotations

import hashlib
import hmac

SIGNATURE_HEADER = "X-ITSM-Signature"


class InvalidSignature(Exception):
    """Assinatura ausente, malformada ou divergente."""


def sign(body: bytes, secret: str) -> str:
    """Gera o valor do cabeçalho de assinatura para um corpo."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify(body: bytes, signature: str | None, secret: str) -> None:
    """Valida a assinatura; levanta :class:`InvalidSignature` se não conferir.

    Sem segredo configurado a checagem é desabilitada (modo desenvolvimento).
    """
    if not secret:
        return

    if not signature:
        raise InvalidSignature("cabeçalho de assinatura ausente")

    algo, _, received = signature.partition("=")
    if algo != "sha256" or not received:
        raise InvalidSignature("formato de assinatura inválido; esperado sha256=<hex>")

    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    # compare_digest evita vazar informação por tempo de comparação
    if not hmac.compare_digest(expected, received.strip()):
        raise InvalidSignature("assinatura não confere")
