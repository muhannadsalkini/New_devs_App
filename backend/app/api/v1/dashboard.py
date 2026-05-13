from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any
from decimal import Decimal, ROUND_HALF_UP
from app.services.cache import get_revenue_summary
from app.core.auth import authenticate_request as get_current_user

router = APIRouter()

@router.get("/dashboard/summary")
async def get_dashboard_summary(
    property_id: str,
    current_user: dict = Depends(get_current_user)
) -> Dict[str, Any]:

    tenant_id = getattr(current_user, "tenant_id", "default_tenant") or "default_tenant"

    revenue_data = await get_revenue_summary(property_id, tenant_id)

    # BUGFIX: Do NOT cast monetary amounts through float — IEEE-754 binary
    # floats cannot represent decimal fractions exactly, which is what caused
    # the "off by a few cents" reports from finance. Keep the value as a
    # Decimal, quantize to 2dp with banker-safe HALF_UP, and serialize as a
    # string so JSON doesn't reintroduce the float round-trip on the client.
    total_decimal = Decimal(str(revenue_data['total'])).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP
    )

    return {
        "property_id": revenue_data['property_id'],
        "total_revenue": str(total_decimal),
        "currency": revenue_data['currency'],
        "reservations_count": revenue_data['count']
    }

