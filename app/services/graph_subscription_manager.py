# =============================================================================
# Graph Subscription Manager - Subscription Persistence & Renewal
# =============================================================================

import logging
from datetime import datetime, timedelta
from typing import Optional
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.graph_subscription import GraphSubscription
from app.services.microsoft_graph import GraphClient, GraphAPIError

logger = logging.getLogger(__name__)


class GraphSubscriptionManager:
    """
    Manage Microsoft Graph webhook subscriptions with database persistence.
    
    Per First Review requirements:
    - Store subscriptions in graph_subscriptions table
    - Renew subscriptions 24 hours before expiry
    - Handle subscription lifecycle (create, renew, delete)
    """
    
    def __init__(self, db_session: Session, graph_client: Optional[GraphClient] = None):
        """
        Initialize subscription manager.
        
        Args:
            db_session: Database session for GraphSubscription model
            graph_client: GraphClient instance (creates default if not provided)
        """
        self.db_session = db_session
        self.graph_client = graph_client or GraphClient()
    
    async def create_subscription(
        self,
        resource: str,
        notification_url: str,
        change_types: list[str],
        expiration_minutes: int = 4230,  # ~3 days (max for most resources)
        client_state: Optional[str] = None,
    ) -> GraphSubscription:
        """
        Create a Graph subscription and store in database.
        
        Args:
            resource: Resource path (e.g., "/users/{mailbox}/messages")
            notification_url: HTTPS endpoint for notifications
            change_types: List of change types: ["created", "updated", "deleted"]
            expiration_minutes: Subscription duration (default 4230 = ~3 days)
            client_state: Optional client state token
        
        Returns:
            GraphSubscription record
        """
        # Create subscription via Graph API
        subscription_data = await self.graph_client.create_subscription(
            resource=resource,
            notification_url=notification_url,
            change_types=change_types,
            expiration_minutes=expiration_minutes,
            client_state=client_state,
        )
        
        subscription_id = subscription_data["id"]
        expiration_str = subscription_data["expirationDateTime"]
        expiration = datetime.fromisoformat(expiration_str.replace("Z", "+00:00"))
        
        # Check if subscription already exists in DB
        existing = self.db_session.execute(
            select(GraphSubscription).where(
                GraphSubscription.subscription_id == subscription_id
            )
        ).scalar_one_or_none()
        
        if existing:
            # Update existing record
            existing.resource = resource
            existing.expiry = expiration
            existing.client_state = client_state
            self.db_session.commit()
            logger.info(f"Updated Graph subscription: {subscription_id}")
            return existing
        
        # Create new record
        subscription = GraphSubscription(
            resource=resource,
            subscription_id=subscription_id,
            expiry=expiration,
            client_state=client_state,
        )
        self.db_session.add(subscription)
        self.db_session.commit()
        
        logger.info(f"Created Graph subscription: {subscription_id} for {resource}")
        return subscription
    
    async def renew_subscription(self, subscription: GraphSubscription) -> GraphSubscription:
        """
        Renew a subscription that's expiring soon.
        
        Renews 24 hours before expiry (per First Review requirements).
        
        Args:
            subscription: GraphSubscription record to renew
        
        Returns:
            Updated GraphSubscription record
        
        Raises:
            GraphAPIError: If renewal fails
        """
        try:
            # Renew via Graph API (extends by default 4230 minutes)
            subscription_data = await self.graph_client.renew_subscription(
                subscription_id=subscription.subscription_id,
                expiration_minutes=4230,
            )
            
            expiration_str = subscription_data["expirationDateTime"]
            expiration = datetime.fromisoformat(expiration_str.replace("Z", "+00:00"))
            
            # Update database record
            subscription.expiry = expiration
            self.db_session.commit()
            
            logger.info(f"Renewed Graph subscription: {subscription.subscription_id} until {expiration}")
            return subscription
            
        except GraphAPIError as e:
            logger.error(f"Failed to renew subscription {subscription.subscription_id}: {e}")
            raise
    
    async def delete_subscription(self, subscription: GraphSubscription) -> None:
        """
        Delete a Graph subscription.
        
        Args:
            subscription: GraphSubscription record to delete
        """
        try:
            await self.graph_client.delete_subscription(subscription.subscription_id)
            
            # Delete from database
            self.db_session.delete(subscription)
            self.db_session.commit()
            
            logger.info(f"Deleted Graph subscription: {subscription.subscription_id}")
            
        except GraphAPIError as e:
            logger.error(f"Failed to delete subscription {subscription.subscription_id}: {e}")
            # Still delete from DB if Graph API fails (subscription may already be expired)
            self.db_session.delete(subscription)
            self.db_session.commit()
            raise
    
    def get_subscriptions_needing_renewal(self, hours_before: int = 24) -> list[GraphSubscription]:
        """
        Get subscriptions that need renewal.
        
        Returns subscriptions expiring within the specified hours.
        
        Args:
            hours_before: Hours before expiry to renew (default 24)
        
        Returns:
            List of GraphSubscription records needing renewal
        """
        cutoff = datetime.utcnow() + timedelta(hours=hours_before)
        
        result = self.db_session.execute(
            select(GraphSubscription).where(
                GraphSubscription.expiry <= cutoff
            ).order_by(GraphSubscription.expiry)
        )
        
        return list(result.scalars().all())
    
    async def renew_expiring_subscriptions(self, hours_before: int = 24) -> dict:
        """
        Renew all subscriptions expiring within specified hours.
        
        This is the main method for the renewal cron job.
        
        Args:
            hours_before: Hours before expiry to renew (default 24)
        
        Returns:
            Dict with renewal results
        """
        subscriptions = self.get_subscriptions_needing_renewal(hours_before)
        
        renewed = 0
        failed = 0
        errors = []
        
        for subscription in subscriptions:
            try:
                await self.renew_subscription(subscription)
                renewed += 1
            except Exception as e:
                failed += 1
                error_msg = f"Subscription {subscription.subscription_id}: {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)
        
        result = {
            "renewed": renewed,
            "failed": failed,
            "total": len(subscriptions),
            "errors": errors,
        }
        
        if failed > 0:
            logger.warning(f"Subscription renewal: {renewed} succeeded, {failed} failed")
        else:
            logger.info(f"Subscription renewal: {renewed} subscriptions renewed successfully")
        
        return result
