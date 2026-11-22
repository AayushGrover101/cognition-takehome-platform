"""Slack (an outside service). Messages are kept in memory instead of being sent."""
import time

from . import on_reset, tool

SENT = []


@on_reset
def reset():
    SENT.clear()


@tool("slack.post_message", kind="write", returns=["channel", "text", "sent_at"],
      inputs={"channel": ["#ops-alerts", "#support"], "text": "str"},
      description="Post a message to an approved Slack channel.")
def post_message(args, ctx):
    message = {"channel": args["channel"], "text": args["text"], "sent_at": int(time.time()), "by": ctx["user"]["name"]}
    SENT.append(message)
    return message
