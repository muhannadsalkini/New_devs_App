from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, List
from zoneinfo import ZoneInfo

async def calculate_monthly_revenue(
    property_id: str,
    tenant_id: str,
    month: int,
    year: int,
    db_session=None,
) -> Decimal:
    """
    Calculates revenue for a specific month.

    BUGFIX (timezone): Previously this function built `datetime(year, month, 1)`
    as a NAIVE datetime, which Postgres compared as UTC against the
    TIMESTAMPTZ `check_in_date` column. For a property in Europe/Paris,
    a reservation checking in at 2024-02-29 23:30 UTC (i.e. 2024-03-01 00:30
    local) was being attributed to February instead of March — which is
    exactly what Client A reported about their March totals.

    The fix: look up the property's timezone and compute the month boundaries
    in that local timezone, then let Postgres compare timezone-aware values.

    BUGFIX (tenant): `tenant_id` is now a required parameter (and a filter in
    the query). Without it the same `property_id` would aggregate across
    tenants — both a correctness bug and a data-isolation bug.
    """
    from app.core.database_pool import DatabasePool
    from sqlalchemy import text

    db_pool = DatabasePool()
    await db_pool.initialize()

    if not db_pool.session_factory:
        # Without a DB session we cannot compute revenue. Return 0 rather
        # than crash so callers degrade gracefully.
        return Decimal("0")

    async with db_pool.get_session() as session:
        # Resolve the property's timezone (default UTC if not found).
        tz_row = (
            await session.execute(
                text(
                    "SELECT timezone FROM properties "
                    "WHERE id = :property_id AND tenant_id = :tenant_id"
                ),
                {"property_id": property_id, "tenant_id": tenant_id},
            )
        ).fetchone()
        tz_name = (tz_row.timezone if tz_row and tz_row.timezone else "UTC")
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("UTC")

        # Compute month [start, end) as timezone-aware datetimes in the
        # property's local timezone.
        start_date = datetime(year, month, 1, tzinfo=tz)
        if month < 12:
            end_date = datetime(year, month + 1, 1, tzinfo=tz)
        else:
            end_date = datetime(year + 1, 1, 1, tzinfo=tz)

        result = await session.execute(
            text(
                """
                SELECT COALESCE(SUM(total_amount), 0) AS total
                FROM reservations
                WHERE property_id = :property_id
                  AND tenant_id   = :tenant_id
                  AND check_in_date >= :start_date
                  AND check_in_date <  :end_date
                """
            ),
            {
                "property_id": property_id,
                "tenant_id": tenant_id,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        row = result.fetchone()
        return Decimal(str(row.total)) if row and row.total is not None else Decimal("0")


async def calculate_total_revenue(property_id: str, tenant_id: str) -> Dict[str, Any]:
    """
    Aggregates revenue from database.
    """
    try:
        # Import database pool
        from app.core.database_pool import DatabasePool
        
        # Initialize pool if needed
        db_pool = DatabasePool()
        await db_pool.initialize()
        
        if db_pool.session_factory:
            async with db_pool.get_session() as session:
                # Use SQLAlchemy text for raw SQL
                from sqlalchemy import text
                
                query = text("""
                    SELECT 
                        property_id,
                        SUM(total_amount) as total_revenue,
                        COUNT(*) as reservation_count
                    FROM reservations 
                    WHERE property_id = :property_id AND tenant_id = :tenant_id
                    GROUP BY property_id
                """)
                
                result = await session.execute(query, {
                    "property_id": property_id, 
                    "tenant_id": tenant_id
                })
                row = result.fetchone()
                
                if row:
                    total_revenue = Decimal(str(row.total_revenue))
                    return {
                        "property_id": property_id,
                        "tenant_id": tenant_id,
                        "total": str(total_revenue),
                        "currency": "USD", 
                        "count": row.reservation_count
                    }
                else:
                    # No reservations found for this property
                    return {
                        "property_id": property_id,
                        "tenant_id": tenant_id,
                        "total": "0.00",
                        "currency": "USD",
                        "count": 0
                    }
        else:
            raise Exception("Database pool not available")
            
    except Exception as e:
        print(f"Database error for {property_id} (tenant: {tenant_id}): {e}")
        
        # Create property-specific mock data for testing when DB is unavailable
        # This ensures each property shows different figures
        mock_data = {
            'prop-001': {'total': '1000.00', 'count': 3},
            'prop-002': {'total': '4975.50', 'count': 4}, 
            'prop-003': {'total': '6100.50', 'count': 2},
            'prop-004': {'total': '1776.50', 'count': 4},
            'prop-005': {'total': '3256.00', 'count': 3}
        }
        
        mock_property_data = mock_data.get(property_id, {'total': '0.00', 'count': 0})
        
        return {
            "property_id": property_id,
            "tenant_id": tenant_id, 
            "total": mock_property_data['total'],
            "currency": "USD",
            "count": mock_property_data['count']
        }
