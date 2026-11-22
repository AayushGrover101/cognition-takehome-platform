"""Personal Google Drive. Exists so the Blocked group has something in it; no app may use it."""
from . import tool


@tool("gdrive.upload_file", kind="write", returns=["file_id"], inputs={"name": "str", "content": "str"},
      description="Upload a file to the signed-in person's Drive.")
def upload_file(args, ctx):
    return {"file_id": "never-runs"}
