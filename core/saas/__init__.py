"""
SaaS subscription and API key management system for Friday AI.
"""
from .models import SaaSDatabase
from .auth import AuthService
from .keys import APIKeyService
from .subscriptions import SubscriptionService
from .usage import UsageTracker
from .gateway import APIGateway
from .connections import ConnectionManager


class SaaSService:
    """Unified entry point for all SaaS operations."""

    def __init__(self, db_path=None):
        self.db = SaaSDatabase(db_path)
        self.auth = AuthService(self.db)
        self.keys = APIKeyService(self.db)
        self.subscriptions = SubscriptionService(self.db)
        self.usage = UsageTracker(self.db)
        self.gateway = APIGateway(self)
        self.connections = ConnectionManager(self.db)

    # ── Plan info ──

    @staticmethod
    def list_plans():
        return SubscriptionService.list_plans()

    @staticmethod
    def get_plan(plan_id):
        return SubscriptionService.get_plan(plan_id)
