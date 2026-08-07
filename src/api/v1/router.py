from fastapi import APIRouter

from src.api.v1.lists import lists_router
from src.api.v1.tasks import tasks_router


v1_router = APIRouter(prefix="/v1")

v1_router.include_router(lists_router)
v1_router.include_router(tasks_router)
