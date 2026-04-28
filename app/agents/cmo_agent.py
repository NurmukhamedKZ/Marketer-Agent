from langchain.agents import create_agent
from langchain_core.messages import AIMessageChunk
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.interceptors import MCPToolCallRequest
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from apps.shared.config import get_settings

config = get_settings()

SYSTEM_PROMPT = """You are a senior content marketer.

## What you do
1. Research 3–5 trending topics relevant to the product and audience
2. Pick the strongest angle — timely, relevant, not already covered
3. Draft a post that stops the scroll in the first line
4. Present the draft to the user and ask for feedback or approval

## Writing rules
- Lead with tension, a question, or a surprising insight — never with the brand name
- One idea per post. Cut everything that doesn't serve it.
- Match the brand voice exactly as described by the user
- No hashtag spam. One max, only if it earns its place.
- Never invent statistics or quotes

## Your mindset
You think like a founder who also happens to write well. You have opinions. If you think a topic is weak, say so and suggest a better one. You're here to drive results, not to produce content for its own sake."""

async def build_content_agent(config, thread_id: str):
    mcp_client = MultiServerMCPClient(
        {
            "image_generation": {
                "command": "uv",
                "args": ["run", "python", "-m", "apps.mcp_servers_v2.image_generation.server"],
                "transport": "stdio",
            },
            "search": {
                "command": "uv",
                "args": ["run", "python", "-m", "apps.mcp_servers_v2.web_search.server"],
                "transport": "stdio",
            }
        },
    )

    tools = await mcp_client.get_tools()

    model = ChatOpenAI(
        model="gpt-5.4-nano",
        api_key=config.openai_api_key,
    )

    agent = create_agent(
        model=model,
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
        checkpointer=InMemorySaver(),
    )

    agent_config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 100,
    }

    return agent, tools, agent_config
