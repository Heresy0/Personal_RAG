import json
from pathlib import Path

from .config import ROOT, validate_space


def codex_config(connection: Path, *, enabled=True):
    # JSON basic strings are valid TOML basic strings for these paths.
    command = str(ROOT / ".venv/Scripts/python.exe")
    if not Path(command).exists():
        command = str(ROOT / ".venv/bin/python")
    args = [str(ROOT / "scripts/run_mcp.py"), "--connection", str(connection.resolve())]
    return ("[mcp_servers.personal_memory]\n" + f"command = {json.dumps(command)}\n" +
            f"args = {json.dumps(args)}\n" + f"enabled = {str(enabled).lower()}\n" +
            "startup_timeout_sec = 20\ntool_timeout_sec = 120\n")


def create_connection(name: str, *, write=False):
    validate_space(name)
    directory = ROOT / "config/connections"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.toml"
    mode = "readwrite" if write else "read"
    read_spaces = json.dumps(['general', f'project-{name}'])
    write_spaces = read_spaces if write else '[]'
    with path.open("x", encoding="utf-8") as stream:
        stream.write(f'name = "{name}"\nread_spaces = {read_spaces}\nwrite_spaces = {write_spaces}\nmaximum_mode = "{mode}"\ninitial_mode = "off"\nadmin = false\n')
    snippet = ROOT / "connections" / f"{name}.codex.toml"
    snippet.parent.mkdir(parents=True, exist_ok=True)
    snippet.write_text(codex_config(path), encoding="utf-8")
    return {"connection": str(path), "codex_config": str(snippet),
            "instructions": "将配置合并到目标可信项目 .codex/config.toml；连接默认off，在新会话明确开启。"}
