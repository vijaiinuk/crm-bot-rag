from dataclasses import dataclass

from chatbot.admin.insights import AdminInsights
from chatbot.admin.service import AdminService
from chatbot.ports.conversations import ConversationStore


@dataclass(frozen=True, slots=True)
class AdminBundle:
    """Everything the admin API and the chat recorder need from one store."""

    service: AdminService
    insights: AdminInsights
    conversations: ConversationStore
