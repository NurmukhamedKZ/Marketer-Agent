from fastapi import APIRouter

from app_v2.agents.social_agent import build_marketer_agent


router = APIRouter(prefix="/api/agents")

@router.post("/content_agent")
async def content_agent(prompt: str)