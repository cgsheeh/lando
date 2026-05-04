LOG_OUTPUT_HEAD_LIMIT = 500
LOG_OUTPUT_TAIL_LIMIT = 200


def truncate_output(output: str) -> str:
    """Trim long command output to its head and tail.

    Keeps log volume bounded for commands like `hg export` or `git format-patch`
    that emit an entire patch, while preserving the most diagnostically useful
    portions (commit metadata at the start, summary or error trailer at the end).
    """
    total = len(output)
    if total <= LOG_OUTPUT_HEAD_LIMIT + LOG_OUTPUT_TAIL_LIMIT:
        return output

    head = output[:LOG_OUTPUT_HEAD_LIMIT]
    tail = output[-LOG_OUTPUT_TAIL_LIMIT:]
    omitted = total - LOG_OUTPUT_HEAD_LIMIT - LOG_OUTPUT_TAIL_LIMIT
    return f"{head}\n...[{omitted} bytes omitted]...\n{tail}"
