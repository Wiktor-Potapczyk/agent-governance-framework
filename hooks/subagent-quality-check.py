#!/usr/bin/env python3
"""SubagentStop Hook - L2 exit gate: structural quality check on agent output."""
import json
import sys
import os
import re
from datetime import datetime

def main():
    try:
        raw = sys.stdin.read()
    except Exception:
        return

    if not raw:
        return

    try:
        payload = json.loads(raw)
    except Exception:
        return

    # Prevent infinite loops
    if payload.get("stop_hook_active") is True:
        return

    agent_type = payload.get("agent_type", "unknown")
    agent_id = payload.get("agent_id", "unknown")
    message = payload.get("last_assistant_message", "")
    message_len = len(message)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "subagent-quality.log")

    def log_and_block(result, check_failed, reason):
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"{timestamp} | agent={agent_type} | id={agent_id} | len={message_len} | result={result} | failed={check_failed}\n")
        except Exception:
            pass
        # Also log to governance-log.jsonl
        try:
            gov_log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "governance-log.jsonl")
            entry = json.dumps({"ts": timestamp, "event": "block", "hook": "subagent-quality-check", "agent_type": agent_type, "agent_id": agent_id, "message_len": message_len, "check_failed": check_failed})
            with open(gov_log_path, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
        except Exception:
            pass
        response = {"decision": "block", "reason": reason}
        print(json.dumps(response))
        sys.exit(0)

    # CHECK 1: Truly empty output
    if message_len < 5:
        log_and_block("BLOCK", "check_1_empty",
                       f"Agent output is empty ({message_len} chars). Produce a substantive response.")

    # CHECK 2: Pure error/failure output (very short + error keywords)
    if message_len < 100:
        error_patterns = [
            "unable to complete",
            "i cannot",
            "i can't",
            "i don't have access",
            "i apologize"
        ]
        lower_msg = message.lower()
        for pattern in error_patterns:
            if pattern in lower_msg:
                log_and_block("BLOCK", "check_2_error_refusal",
                               f"Agent output appears to be an error or refusal ({message_len} chars, matched: '{pattern}'). Retry the task or report what specifically failed.")

    # CHECK 3: Substantial output without structure
    if message_len > 500:
        has_headers = bool(re.search(r'(?m)^#{1,4}\s', message))
        has_bullets = bool(re.search(r'(?m)^[\s]*[-*]\s', message))
        has_tables = bool(re.search(r'\|.*\|', message))
        has_code_blocks = '```' in message
        has_numbered_list = bool(re.search(r'(?m)^\s*\d+[.)]\s', message))

        if not (has_headers or has_bullets or has_tables or has_code_blocks or has_numbered_list):
            log_and_block("BLOCK", "check_3_no_structure",
                           f"Agent produced {message_len} chars with no structure (no headers, bullets, tables, or code blocks). Structure your output with clear sections and formatting.")

    # All checks passed
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{timestamp} | agent={agent_type} | id={agent_id} | len={message_len} | result=PASS\n")
    except Exception:
        pass

if __name__ == "__main__":
    main()
