"""Faturamento: transforma apontamentos de horas em fatura conforme o contrato."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from ..billing import BillingError, generate_invoice
from ..models import Invoice, InvoiceRequest

router = APIRouter(prefix="/api/billing", tags=["faturamento"])


@router.post(
    "/invoices/preview",
    response_model=Invoice,
    summary="Calcula a prévia da fatura de um contrato no período",
    description=(
        "Cálculo puro e determinístico: não grava nada. É o passo que o n8n "
        "executa antes de enviar a fatura ao ERP/emissor fiscal, permitindo "
        "revisão humana das linhas."
    ),
)
def preview_invoice(request: InvoiceRequest) -> Invoice:
    try:
        return generate_invoice(request)
    except BillingError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
