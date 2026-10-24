import json

from netdiag.tools import Tool, ToolRegistry, build_default_registry
from netdiag.tracing import CallTracer


def test_tracer_records_and_writes_jsonl(tmp_path):
    log = tmp_path / "sub" / "t.jsonl"
    t = CallTracer(str(log), "s1")
    t.note("thinking")
    with t.span("ping", {"host": "x"}, "why") as e:
        e.result_summary = "ok!"
    lines = [json.loads(line) for line in log.read_text().splitlines()]
    assert [x["step"] for x in lines] == [1, 2]
    assert lines[1]["tool"] == "ping" and lines[1]["result_summary"] == "ok!"
    assert "ping(host=x)" in t.format() and "why" in t.format()


def test_tracer_records_exceptions():
    t = CallTracer()
    try:
        with t.span("bad"):
            raise ValueError("nope")
    except ValueError:
        pass
    assert t.entries[0].status == "error" and t.entries[0].error == "nope"


def test_tracer_unwritable_log_does_not_crash(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    t = CallTracer(str(blocker / "child.jsonl"))
    t.note("still works")
    assert len(t.entries) == 1


def test_registry_execute_never_raises():
    reg = ToolRegistry()
    reg.register(Tool("boom", "d", {"type": "object"}, lambda: 1 / 0))
    reg.register(Tool("echo", "d", {"type": "object"}, lambda x: {"x": x}, lambda r: f"x={r['x']}"))
    t = CallTracer()
    assert "failed" in reg.execute("boom", {}, t)["error"]
    assert "bad arguments" in reg.execute("echo", {"y": 1}, t)["error"]
    assert "unknown tool" in reg.execute("nope", {}, t)["error"]
    assert reg.execute("echo", {"x": 5}, t) == {"x": 5}
    assert [e.status for e in t.entries] == ["error", "error", "error", "ok"]


def test_new_tool_is_exposed_to_llms_without_other_changes():
    reg = build_default_registry()
    reg.register(Tool("speed_test", "Measure throughput", {"type": "object"}, lambda: {"mbps": 1}))
    assert "speed_test" in [s["name"] for s in reg.specs()]


def test_default_registry_tools():
    assert set(build_default_registry().names()) == {
        "get_default_gateway", "ping_endpoints", "ping_host", "run_traceroute"}


def test_ping_endpoints_rejects_bad_gateway():
    assert "invalid gateway" in build_default_registry().execute("ping_endpoints", {"gateway": "-f"})["error"]
