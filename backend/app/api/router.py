from fastapi import APIRouter

from app.api import admin, auth, business, chat, evaluations, handoffs, knowledge

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(business.router)
api_router.include_router(chat.router)
api_router.include_router(handoffs.router)
api_router.include_router(evaluations.router)
api_router.include_router(knowledge.router)
api_router.include_router(admin.router)
