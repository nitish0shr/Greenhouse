# =============================================================================
# Graph Subscription Model - Microsoft Graph Webhook Subscriptions
# =============================================================================

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GraphSubscription(Base):
    """
    Track Microsoft Graph webhook subscriptions.
    
    Stores subscription metadata for renewal tracking and validation.
    """
    
    __tablename__ = "graph_subscriptions"
    
    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    
    # Resource path (e.g., "/users/{mailbox}/messages")
    resource: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    
    # Graph subscription ID (UNIQUE constraint)
    subscription_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
    )
    
    # Expiry timestamp
    expiry: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    
    # Client state token (for validation)
    client_state: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    
    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    
    def __repr__(self) -> str:
        return f"<GraphSubscription {self.subscription_id} resource={self.resource} expiry={self.expiry}>"
