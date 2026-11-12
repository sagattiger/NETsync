"""Example NETsync container plugin: one read tool, one write tool (needs approval), and a call back into NETsync."""

from netsync_plugin import NetsyncPlugin

plugin = NetsyncPlugin("hello", version="1.0.0", description="Example container plugin",
                       permissions=["tools", "call:read"])


@plugin.tool("greet", "Say hello to someone (example read tool).",
             {"type": "object", "properties": {"name": {"type": "string", "maxLength": 64}}})
async def greet(args, call):
    return {"text": f"Hello {args.get('name') or 'world'}!", "asked_by": call.get("actor")}


@plugin.tool("problem_count", "How many open problems NETsync has right now (example of calling NETsync back).")
async def problem_count(args, call):
    answer = await plugin.call_tool("netsync__list_problems", {"limit": 1})
    return {"open_problems": (answer.get("result") or {}).get("count")}


@plugin.tool("write_note", "Pretend to change something (example write tool: runs only after approval).",
             {"type": "object", "properties": {"note": {"type": "string", "maxLength": 200}}, "required": ["note"]},
             risk="write")
async def write_note(args, call):
    return {"written": args["note"], "approved_call": call.get("call_id")}


app = plugin.app()
