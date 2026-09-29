from fastapi import APIRouter

from src.api.v1.lists import lists_router
from src.api.v1.notification_stream import notification_stream_router
from src.api.v1.notifications import notifications_router
from src.api.v1.tasks import tasks_router


v1_router = APIRouter(prefix="/v1")

v1_router.include_router(lists_router)
v1_router.include_router(tasks_router)
# stream/ticket до любых path-id на /notifications
v1_router.include_router(notification_stream_router)
v1_router.include_router(notifications_router)
