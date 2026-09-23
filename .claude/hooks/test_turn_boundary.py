"""_turn_boundary: the turn starts at the user, not at a skill body or a hook block."""
import json

import _turn_boundary as tb


def u(text):
    return json.dumps({"type": "user", "message": {"role": "user", "content": text}})


def u_blocks(blocks, **extra):
    e = {"type": "user", "message": {"role": "user", "content": blocks}}
    e.update(extra)
    return json.dumps(e)


def a(text="x"):
    return json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}})


SKILL_BODY = u_blocks([{"type": "text", "text": "Base directory for this skill: C:/x\n# QA\n..."}],
                      isMeta=True, sourceToolUseID="toolu_1")
TOOL_RESULT = u_blocks([{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}])
HOOK_FEEDBACK = u("Stop hook feedback:\nWORK VERIFICATION: QA REPORT block produced ...")


def test_a_plain_user_message_is_the_boundary():
    lines = [u("build it"), a()]
    assert tb.real_turn_start(lines) == 0


def test_a_text_block_user_message_is_the_boundary():
    lines = [u("old"), a(), u_blocks([{"type": "text", "text": "continue"}]), a()]
    assert tb.real_turn_start(lines) == 2


def test_a_tool_result_wrapper_is_not_the_boundary():
    lines = [u("build it"), a(), TOOL_RESULT, a()]
    assert tb.real_turn_start(lines) == 0


def test_the_skill_body_is_not_the_boundary():
    """The real shape from session 7a74290c line 1702: a user entry with a text
    block, isMeta true and a sourceToolUseID."""
    lines = [u("build it"), a("TASK TYPE: Build"), a(), TOOL_RESULT, SKILL_BODY, a()]
    assert tb.real_turn_start(lines) == 0
    assert tb.user_entry_kind(json.loads(SKILL_BODY)) == "skill-body"


def test_hook_feedback_is_not_the_boundary():
    lines = [u("build it"), a("TASK TYPE: Build"), a("QA REPORT"), HOOK_FEEDBACK, a("QA REPORT")]
    assert tb.real_turn_start(lines) == 0
    assert tb.user_entry_kind(json.loads(HOOK_FEEDBACK)) == "hook-feedback"


def test_hook_feedback_as_a_text_block_is_not_the_boundary():
    lines = [u("go"), a(), u_blocks([{"type": "text", "text": "  Stop hook feedback:\nDISPATCH COMPLIANCE: ..."}]), a()]
    assert tb.real_turn_start(lines) == 0


def test_a_user_message_after_the_skill_body_is_the_boundary():
    lines = [u("build it"), SKILL_BODY, a(), u("now verify"), a()]
    assert tb.real_turn_start(lines) == 3


def test_blank_and_malformed_lines_are_skipped():
    lines = ["", "not json", u("go"), "{", a(), ""]
    assert tb.real_turn_start(lines) == 2


def test_no_user_message_gives_minus_one():
    assert tb.real_turn_start([a(), TOOL_RESULT]) == -1


def test_boundary_kind_names_what_the_naive_rule_would_have_chosen():
    assert tb.boundary_kind([u("go"), a(), SKILL_BODY, a()]) == "skill-body"
    assert tb.boundary_kind([u("go"), a(), HOOK_FEEDBACK, a()]) == "hook-feedback"
    assert tb.boundary_kind([u("go"), a(), TOOL_RESULT, a()]) == "user"


def test_the_tail_grows_past_a_large_tool_result(tmp_path):
    """Silent-failure review item 1: a single tool_result over the 200 KB window
    hid the classification and every dispatch."""
    big = u_blocks([{"type": "tool_result", "tool_use_id": "t1", "content": "x" * 300_000}])
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join([u("build it"), a("TASK TYPE: Build"), big, a("done")]) + "\n", encoding="utf-8")
    lines, info = tb.tail_to_turn_start(str(p))
    assert info["turn_start"] >= 0 and not info["capped"]
    assert info["window_bytes"] > 204800
    assert json.loads(lines[info["turn_start"]])["message"]["content"] == "build it"


def test_a_small_transcript_is_read_whole(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join([u("go"), a("x")]) + "\n", encoding="utf-8")
    lines, info = tb.tail_to_turn_start(str(p))
    assert info["window_bytes"] == info["file_size"] and info["turn_start"] == 0


def test_the_cap_is_reported_when_no_user_entry_fits(tmp_path):
    big = u_blocks([{"type": "tool_result", "tool_use_id": "t1", "content": "x" * 50_000}])
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join([u("go"), big, a("x")]) + "\n", encoding="utf-8")
    lines, info = tb.tail_to_turn_start(str(p), start_bytes=1000, cap_bytes=4000)
    assert info["turn_start"] == -1 and info["capped"]


def test_a_mid_file_window_drops_its_first_fragment(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join([u("old"), a("x" * 500), u("go"), a("y")]) + "\n", encoding="utf-8")
    lines, info = tb.tail_to_turn_start(str(p), start_bytes=300, cap_bytes=300)
    assert all(tb._entry(l) is not None for l in lines if l.strip())
