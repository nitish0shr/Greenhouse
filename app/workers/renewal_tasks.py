# =============================================================================
# Renewal Tasks - Graph Subscription Renewal
# =============================================================================

import logging
import asyncio

from app.services.graph_subscription_manager import GraphSubscriptionManager

logger = logging.getLogger(__name__)


def renew_graph_subscriptions():
    """
    Celery task to renew Graph subscriptions.
    
    Runs periodically (via Celery Beat) to renew subscriptions 24 hours
    before expiry.
    """
    from app.database import SyncSessionLocal
    
    session = SyncSessionLocal()
    
    try:
        graph_client = None  # Will be created by manager
        manager = GraphSubscriptionManager(db_session=session, graph_client=graph_client)
        
        # Run async renewal
        result = asyncio.run(manager.renew_expiring_subscriptions(hours_before=24))
        
        logger.info(
            f"Subscription renewal: {result['renewed']} renewed, "
            f"{result['failed']} failed"
        )
        
        if result["failed"] > 0:
            logger.error(f"Subscription renewal errors: {result['errors']}")
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to renew subscriptions: {e}", exc_info=True)
        raise
    finally:
        session.close()
