import argparse
import json
import sys
from pathlib import Path

from .config import Policy, ROOT, Settings
from .connections import codex_config, create_connection
from .db import Database
from .service import MemoryService


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Personal_RAG 知识库管理")
    parser.add_argument("--connection", type=Path, default=ROOT / "config/connections/manager.toml")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("status")
    sync = sub.add_parser("sync")
    sync.add_argument("--prune", action="store_true")
    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--space")
    search.add_argument("--start")
    search.add_argument("--end")
    read = sub.add_parser("read")
    read.add_argument("note_id")
    audit = sub.add_parser("audit")
    audit.add_argument("--note-id")
    audit.add_argument("--operation-id")
    audit.add_argument("--outcome")
    audit.add_argument("--limit", type=int, default=50)
    audit.add_argument("--offset", type=int, default=0)
    version = sub.add_parser("version")
    version.add_argument("note_id")
    version.add_argument("revision", type=int)
    capture = sub.add_parser("capture")
    capture.add_argument("--title", required=True)
    capture.add_argument("--body", required=True)
    capture.add_argument("--space", required=True)
    capture.add_argument("--date")
    capture.add_argument("--request-id")
    connect = sub.add_parser("connect")
    connect.add_argument("name")
    connect.add_argument("--write", action="store_true")
    sub.add_parser("manager-config")
    sub.add_parser("mcp")
    args = parser.parse_args()
    try:
        if args.command == "connect":
            result = create_connection(args.name, write=args.write)
        elif args.command == "manager-config":
            path = ROOT / "knowledge_workspace/.codex/config.toml"
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                raise ValueError("已有管理项目配置，未覆盖")
            path.write_text(codex_config(ROOT / "config/connections/manager.toml"), encoding="utf-8")
            result = {"path": str(path)}
        else:
            settings = Settings.load()
            if args.command == "init":
                Database(settings).initialize()
                result = {"initialized": True}
            else:
                service = MemoryService(settings, Policy.load(args.connection))
                if args.command == "mcp":
                    from .mcp_server import create_server
                    create_server(service).run(transport="stdio")
                    return
                if args.command == "status":
                    result = service.status()
                elif args.command == "sync":
                    result = service.sync(prune=args.prune)
                elif args.command == "search":
                    result = service.search(args.query, space=args.space, start=args.start, end=args.end)
                elif args.command == "read":
                    result = service.read(args.note_id)
                elif args.command == "audit":
                    result = service.list_audit(note_id=args.note_id, operation_id=args.operation_id,
                        outcome=args.outcome, limit=args.limit, offset=args.offset)
                elif args.command == "version":
                    result = service.read_version(args.note_id, args.revision)
                elif args.command == "capture":
                    result = service.capture(args.title, args.body, args.space,
                        event_date=args.date, request_id=args.request_id)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    except (ValueError, PermissionError, LookupError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
    except Exception as error:
        print(f"操作失败（{type(error).__name__}），请检查本地数据库及模型配置。", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
