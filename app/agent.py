"""
This module implements the autonomous tool-use agent pattern (Layer 7).

Unlike the deterministic investigator in investigator.py, Claude decides which tools
to call and in what order based on the user's query. Each tool result is fed back into
the conversation and Claude continues calling tools until it has enough information to
produce a final answer.

This pattern trades predictability for flexibility in open-ended analysis queries where
the set of required data cannot be determined in advance. It is more expensive than the
investigator pattern because every tool result is appended to the message history,
growing the context—and therefore token cost—with each iteration.
"""
import json
import logging
import os

import anthropic
from sqlalchemy.orm import Session

from .agent_tools import TOOL_DEFINITIONS, execute_tool
from .logging_config import configure_logging

configure_logging()

logger = logging.getLogger(__name__)

# The system prompt instructs Claude to use tools before answering and to base its
# analysis only on tool-returned data. This prevents hallucinated statistics while
# steering the model toward the tool-use loop rather than drawing on prior knowledge.
# "Be concise" discourages long-winded narrative that inflates output token costs.
SYSTEM_PROMPT = """You are a test failure analyst with access to a test results database. 
Use the available tools to gather relevant data before answering. 
Always use at least one tool before providing your final answer.
Base your analysis only on data returned by the tools.
Be concise and specific in your analysis."""


def run_agent(query: str, db: Session) -> dict:
    """Run an agentic tool-use loop to answer an open-ended analysis query.

    The loop works as follows:
        1. Send the user's query to Claude with the available tool definitions.
        2. If Claude responds with stop_reason="tool_use", execute each requested
           tool, append the results to the message history, and call Claude again.
        3. Repeat until Claude responds with stop_reason="end_turn" (final answer)
           or the iteration cap is reached.

    Termination conditions:
        - stop_reason="end_turn": Claude has produced a text answer; exit normally.
        - stop_reason="tool_use" after 10 iterations: cap exceeded; return last text.
        - Any other stop_reason: extract available text and exit defensively.

    Args:
        query: Natural-language question about test failures or suite statistics.
        db:    SQLAlchemy session passed through to tool implementations.

    Returns:
        A dict with keys: query, answer, tools_called, and iterations.
    """
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
    # Each tool result is appended to the message history before the next Claude
    # call, so the context—and token cost—grows with every iteration. This makes
    # the tool-use pattern more expensive than the investigator, where all data
    # is gathered by Python and sent in a single bounded prompt.
    total_input_tokens += response.usage.input_tokens
    total_output_tokens += response.usage.output_tokens

    # Cap iterations at 10 to bound token spend and prevent infinite loops if
    # Claude enters a state where it keeps requesting tools without converging
    # on a final answer (e.g. due to a model bug or a pathological query).
    for _ in range(10):
        iterations += 1

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    final_answer = block.text
            break

        if response.stop_reason == "tool_use":
            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

            # Tool-use loop: Claude requests one or more tools; Python executes them
            # and appends the results as a "user" message so the next Claude call
            # has both the tool call and its output in context. This back-and-forth
            # continues until Claude decides it has enough data to produce an answer.
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

    # Choose this pattern over the investigator when the analysis question is
    # open-ended (e.g. "why is the payment service so flaky?") and the optimal
    # set of data-gathering steps cannot be specified in advance. For recurring,
    # well-defined pipelines such as CI webhook failure reports, prefer the fixed
    # workflow in investigator.py for lower cost and easier observability.
    return {
        "query": query,
        "answer": final_answer,
        "tools_called": tools_called,
        "iterations": iterations,
    }
