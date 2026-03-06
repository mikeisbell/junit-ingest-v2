import json
import logging
import os

import anthropic
from sqlalchemy.orm import Session

from .agent_tools import TOOL_DEFINITIONS, execute_tool
from .logging_config import configure_logging

configure_logging()

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a test failure analyst with access to a test results database. 
Use the available tools to gather relevant data before answering. 
Always use at least one tool before providing your final answer.
Base your analysis only on data returned by the tools.
Be concise and specific in your analysis."""


def run_agent(query: str, db: Session) -> dict:
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    messages = [{'role': 'user', 'content': query}]
    tools_called: list[str] = []
    final_answer = "Agent did not produce a final answer."
    iterations = 0
    total_input_tokens = 0
    total_output_tokens = 0

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        tools=TOOL_DEFINITIONS,
        messages=messages,
    )
    total_input_tokens += response.usage.input_tokens
    total_output_tokens += response.usage.output_tokens

    for _ in range(10):
        iterations += 1

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    final_answer = block.text
            break

        if response.stop_reason == "tool_use":
            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

            # Append assistant message with all content blocks
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for block in tool_use_blocks:
                tool_name = block.name
                tool_inputs = block.input
                tool_use_id = block.id

                result = execute_tool(tool_name, tool_inputs, db)
                tools_called.append(tool_name)
                logger.info("tool_called", extra={"tool_name": tool_name, "tool_use_id": tool_use_id})

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": json.dumps(result),
                })

            messages.append({"role": "user", "content": tool_results})

            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                tools=TOOL_DEFINITIONS,
                messages=messages,
            )
            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens
        else:
            # Unexpected stop reason; try to extract any text
            for block in response.content:
                if hasattr(block, "text"):
                    final_answer = block.text
            break
    else:
        # Loop exhausted without break — return last text found
        for block in response.content:
            if hasattr(block, "text"):
                final_answer = block.text

    estimated_cost = round((total_input_tokens / 1_000_000) * 3.00 + (total_output_tokens / 1_000_000) * 15.00, 6)
    logger.info(
        "claude_api_call",
        extra={
            "model": "claude-sonnet-4-6",
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "estimated_cost_usd": estimated_cost,
            "caller": "run_agent",
            "iterations": iterations,
        },
    )

    return {
        "query": query,
        "answer": final_answer,
        "tools_called": tools_called,
        "iterations": iterations,
    }
