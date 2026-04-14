#!/usr/bin/env python3
"""UserPromptSubmit hook - context bar from real API usage data + task-classifier enforcement."""
import json
import sys
import os
import re

def main():
    try:
        raw = sys.stdin.read()
    except Exception:
        raw = None

    ctx_line = ""
    classifier_reminder = ""
    classifier_seen = False
    pct = 0

    if raw:
        try:
            data = json.loads(raw)
            transcript_path = data.get("transcript_path", "")

            model_label = "?"
            limit_k = 200
            total_tokens = 0
            tail = ""

            if transcript_path and os.path.exists(transcript_path):
                try:
                    file_size = os.path.getsize(transcript_path)
                    tail_size = min(100000, file_size)
                    with open(transcript_path, "rb") as f:
                        f.seek(-tail_size, 2)
                        tail = f.read().decode("utf-8", errors="replace")

                    # Model detection - last "model":"claude-..." in transcript
                    model_matches = list(re.finditer(r'"model"\s*:\s*"(claude-[^"]+)"', tail))
                    if model_matches:
                        model_id = model_matches[-1].group(1)
                        model_label = re.sub(r'^claude-', '', model_id)
                        model_label = re.sub(r'-\d{8}$', '', model_label)
                        if 'opus' in model_id:
                            limit_k = 1000
                        else:
                            limit_k = 200

                    # Token parsing - find last occurrence of each field
                    in_matches = list(re.finditer(r'"input_tokens":(\d+)', tail))
                    cc_matches = list(re.finditer(r'"cache_creation_input_tokens":(\d+)', tail))
                    cr_matches = list(re.finditer(r'"cache_read_input_tokens":(\d+)', tail))

                    inp = int(in_matches[-1].group(1)) if in_matches else 0
                    cc = int(cc_matches[-1].group(1)) if cc_matches else 0
                    cr = int(cr_matches[-1].group(1)) if cr_matches else 0
                    total_tokens = inp + cc + cr

                    # Check if task-classifier was invoked in recent context
                    tc_matches = re.findall(r'"skill"\s*:\s*"task-classifier"', tail)
                    classifier_seen = len(tc_matches) > 0
                except Exception:
                    pass

            # Build bar
            est_k = round(total_tokens / 1000)
            pct = min(99, round(total_tokens / (limit_k * 1000) * 100)) if limit_k > 0 else 0

            filled = min(10, pct // 10)
            empty = 10 - filled
            bar = "\u25B0" * filled + "\u25B1" * empty

            warn = ""
            if pct >= 70:
                warn = " | /compact recommended"
            elif pct >= 50:
                warn = " | /save recommended"

            ctx_line = f"CTX {bar} {pct}% | {est_k}K/{limit_k}K | {model_label}{warn}"
        except Exception:
            pass

    # Task-classifier enforcement
    classifier_reminder = (
        "MANDATORY: Invoke the task-classifier skill before responding to EVERY message. "
        "No exceptions. Quick tasks are classified as Quick and handled inline. "
        "ALL fields required: IMPLIES, TASK TYPE, APPROACH, MISSED (non-Quick only). "
        "Missing fields = incomplete classification."
    )

    try:
        is_subagent = False
        prompt_text = None
        if raw:
            data2 = json.loads(raw)
            prompt_text = data2.get("prompt")
            is_subagent = bool(data2.get("agent_id") or data2.get("agent_type"))

        # At 50%+ context, add save enforcement
        if pct >= 50 and not is_subagent:
            classifier_reminder = (
                f"SAVE ENFORCEMENT: Context is at {pct}%. You MUST invoke /save before "
                "your next substantive response if you haven't saved recently. "
                f"Do not wait until 85% auto-compact. | {classifier_reminder}"
            )

        if is_subagent:
            classifier_reminder = ""
        elif prompt_text:
            p_lower = prompt_text.strip().lower()
            skip_list = [
                "yes", "no", "ok", "okay", "proceed", "continue", "done",
                "go ahead", "go", "sure", "hi", "hello", "hey", "thanks",
                "thank you", "got it", "sounds good", "confirmed", "nice",
                "great", "perfect"
            ]
            if p_lower in skip_list:
                classifier_reminder = ""
        # S1/M1 fix (2026-04-13): Depth-signal detection.
        # If user message contains depth signals, inject stronger warning.
        # Placed AFTER skip_list (trivial prompts suppress depth check).
        DEPTH_SIGNALS = [
            (r'\bare you sure\b', "follow-up directive -- inherits or escalates, NEVER Quick"),
            (r'\bthink deeper\b', "explicit request for deeper reasoning -- NEVER Quick"),
            (r'\bwhy did\b', "causal investigation -- requires tracing causes, not lookup"),
            (r'\bthought experiment\b', "architectural reasoning -- NEVER Quick"),
            (r'\bi\'ve noticed\b', "pattern observation -- invites investigation"),
            (r'\banalyze this\b', "explicit analysis request -- NEVER Quick"),
            (r'\bthink about this\b', "explicit reasoning request -- NEVER Quick"),
            (r'\bbefore deciding\b', "deliberation request -- NEVER Quick"),
            (r'\bwas it always\b', "timeline investigation -- requires evidence"),
        ]
        if prompt_text and not is_subagent and classifier_reminder:
            for pattern, reason in DEPTH_SIGNALS:
                if re.search(pattern, prompt_text.lower()):
                    classifier_reminder = (
                        f"DEPTH SIGNAL DETECTED: This prompt matches a depth pattern "
                        f"({reason}). Quick is NOT available for this message. "
                        f"You MUST classify as Research, Analysis, or the appropriate "
                        f"non-Quick type. | {classifier_reminder}"
                    )
                    break

    except Exception:
        pass

    # Build output
    display = f'DISPLAY RULE: Begin every response with this exact line in a code block on its own, no changes: `{ctx_line}`' if ctx_line else ""

    if display and classifier_reminder:
        combined = f"{display} | {classifier_reminder}"
    elif display:
        combined = display
    elif classifier_reminder:
        combined = classifier_reminder
    else:
        combined = ""

    msg = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": combined
        }
    }
    print(json.dumps(msg))

if __name__ == "__main__":
    main()
