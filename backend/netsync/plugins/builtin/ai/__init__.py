"""AI assistant: a local LLM (Ollama) explains warning and critical events and syslog messages.

* Automatic comments on WARN/CRIT state changes (and optionally severe syslog), rate limited.
* "Ask AI" buttons next to Acknowledge, on events and on syslog lines.
* Results are posted as AI comments on the event, so they show in the event thread and hover card.
"""

from netsync.plugins.base import Plugin
from netsync.plugins.builtin.ai.api import router
from netsync.plugins.builtin.ai.service import AIService, on_state_change, on_syslog

SETTINGS = [
    {"key": "base_url", "label": "Ollama URL", "type": "text", "section": "Connection",
     "help": "Where Ollama listens, e.g. http://10.128.100.50:11434. Use http://host.docker.internal:11434 if it runs on the NETsync host."},
    {"key": "api_key", "label": "API key (optional)", "type": "secret", "section": "Connection",
     "help": "Only needed when Ollama sits behind a proxy that requires a bearer token (e.g. Open WebUI)."},
    {"key": "model", "label": "Model", "type": "model", "section": "Connection",
     "help": "Models installed in Ollama. 7-14B instruct models (llama3.1, qwen2.5, mistral) work well."},

    {"key": "auto_events", "label": "Comment automatically on events", "type": "bool", "section": "Automatic comments",
     "help": "Analyse every state change into WARNING or CRITICAL and post the explanation as a comment."},
    {"key": "event_min_state", "label": "Event severity", "type": "select", "section": "Automatic comments",
     "options": [["1", "Warning and critical"], ["2", "Critical only"]]},
    {"key": "auto_syslog", "label": "Comment automatically on syslog", "type": "bool", "section": "Automatic comments",
     "help": "Also analyse severe syslog messages. Off by default: busy devices log a lot."},
    {"key": "syslog_min_severity", "label": "Syslog severity", "type": "select", "section": "Automatic comments",
     "options": [["4", "Warning and worse"], ["3", "Error and worse"], ["2", "Critical and worse"]]},
    {"key": "cooldown_minutes", "label": "Cooldown per service (minutes)", "type": "number", "min": 0, "max": 1440,
     "section": "Automatic comments", "help": "Skip automatic analyses of the same service (or device, for syslog) within this time."},
    {"key": "max_auto_per_hour", "label": "Max automatic analyses per hour", "type": "number", "min": 0, "max": 1000,
     "section": "Automatic comments"},

    {"key": "language", "label": "Answer language", "type": "text", "section": "Answers"},
    {"key": "max_words", "label": "Max words per answer", "type": "number", "min": 50, "max": 2000, "section": "Answers"},
    {"key": "extra_instructions", "label": "Site context for the AI", "type": "textarea", "section": "Answers",
     "help": "Facts about your network the AI should know, e.g. \"Core routers are MikroTik RouterOS 7, servers run on Proxmox LXC\"."},
    {"key": "hide_thinking", "label": "Hide reasoning (<think>) of reasoning models", "type": "bool", "section": "Answers"},

    {"key": "temperature", "label": "Temperature", "type": "number", "min": 0, "max": 2, "float": True, "section": "Advanced"},
    {"key": "num_ctx", "label": "Context window (tokens)", "type": "number", "min": 2048, "max": 131072, "section": "Advanced"},
    {"key": "timeout_seconds", "label": "Timeout (seconds)", "type": "number", "min": 10, "max": 900, "section": "Advanced"},
    {"key": "concurrency", "label": "Parallel requests", "type": "number", "min": 1, "max": 8, "section": "Advanced"},
]

DEFAULTS = {
    "base_url": "http://host.docker.internal:11434",
    "api_key": "",
    "model": "",
    "auto_events": True,
    "event_min_state": "1",
    "auto_syslog": False,
    "syslog_min_severity": "3",
    "cooldown_minutes": 30,
    "max_auto_per_hour": 20,
    "language": "English",
    "max_words": 250,
    "extra_instructions": "",
    "hide_thinking": True,
    "temperature": 0.2,
    "num_ctx": 8192,
    "timeout_seconds": 180,
    "concurrency": 1,
}

plugin = Plugin(
    name="ai",
    label="AI assistant",
    version="0.1.0",
    description="Local LLM (Ollama) explains warning and critical events and syslog, and suggests fixes",
    services=[AIService()],
    router=router,
    settings=SETTINGS,
    defaults=DEFAULTS,
    enabled_by_default=False,
    actions=[{"id": "test", "label": "Test connection", "method": "POST", "path": "/test"}],
    hooks={"state_change": [on_state_change], "syslog": [on_syslog]},
    builtin=True,
)
