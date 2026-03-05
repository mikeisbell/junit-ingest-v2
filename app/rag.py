import anthropic

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 512

_NO_FAILURES_MESSAGE = "No relevant failures found for this query."


def analyze_failures(query: str, failures: list[dict]) -> str:
    """Build a prompt from retrieved failures and call Claude for analysis."""
    if not failures:
        return _NO_FAILURES_MESSAGE

    failure_blocks = "\n\n".join(
        f"Test: {f['name']}\nFailure: {f['failure_message']}" for f in failures
    )

    prompt = (
        f'You are a test failure analyst. A user has asked the following question about test failures:\n\n'
        f'"{query}"\n\n'
        f"Here are the most relevant test failures retrieved from the test results database:\n\n"
        f"{failure_blocks}\n\n"
        f"Based only on the failures above, provide a concise analysis that answers the user's question. "
        f"If the failures do not contain enough information to answer the question, say so clearly."
    )

    client = anthropic.Anthropic()
    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text
