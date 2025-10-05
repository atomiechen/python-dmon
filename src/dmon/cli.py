import argparse
import sys

from .config import get_command_config
from .control import list_processes, restart, start, stop, status
from .constants import DEFAULT_META_DIR, LOG_PATH_TEMPLATE, META_PATH_TEMPLATE


def main():
    parser = argparse.ArgumentParser(
        prog="dmon",
        description="Minimal cross-platform daemon manager",
        # formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # start subcommand
    sp_start = subparsers.add_parser(
        "start",
        help="Start a background command",
        # formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sp_start.add_argument(
        "name",
        help="Configured command name (default: the only command if there's just one)",
        nargs="?",
    )
    sp_start.add_argument(
        "--meta-file",
        help=f"Path to meta file (default: {META_PATH_TEMPLATE})",
    )
    sp_start.add_argument(
        "--log-file",
        help=f"Path to log file (default: command configured or {LOG_PATH_TEMPLATE})",
    )

    # stop subcommand
    sp_stop = subparsers.add_parser(
        "stop",
        help="Stop background process",
        # formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sp_stop.add_argument(
        "name",
        help="Configured command name (default: the only command if there's just one)",
        nargs="?",
    )
    sp_stop.add_argument("--meta-file", help="Path to meta file")

    # restart subcommand
    sp_restart = subparsers.add_parser(
        "restart",
        help="Restart background command",
        # formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sp_restart.add_argument(
        "name",
        help="Configured command name (default: the only command if there's just one)",
        nargs="?",
    )
    sp_restart.add_argument(
        "--meta-file",
        help=f"Path to meta file (default: {META_PATH_TEMPLATE})",
    )
    sp_restart.add_argument(
        "--log-file",
        help=f"Path to log file (default: command configured or {LOG_PATH_TEMPLATE})",
    )

    # status subcommand
    sp_status = subparsers.add_parser(
        "status",
        help="Check process status",
        # formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sp_status.add_argument(
        "name",
        help="Configured command name (default: the only command if there's just one)",
        nargs="?",
    )
    sp_status.add_argument(
        "--meta-file",
        help=f"Path to meta file (default: {META_PATH_TEMPLATE})",
    )

    # list subcommand
    sp_list = subparsers.add_parser(
        "list",
        help="List all running processes",
        # formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sp_list.add_argument(
        "dir",
        help=f"Directory to look for meta files (default: {DEFAULT_META_DIR})",
        nargs="?",
    )

    args = parser.parse_args()

    if args.command in ["start", "restart"]:
        try:
            name, cmd_cfg = get_command_config(args.name)
        except Exception as e:
            parser.error(str(e))

        meta_path = args.meta_file or META_PATH_TEMPLATE.format(name=name)
        log_path = (
            args.log_file
            or cmd_cfg.get("log_path")
            or LOG_PATH_TEMPLATE.format(name=name)
        )
        if args.command == "start":
            sys.exit(start(cmd_cfg["cmd"], meta_path, log_path))
        else:
            sys.exit(restart(cmd_cfg["cmd"], meta_path, log_path))
    elif args.command in ["stop", "status"]:
        if args.meta_file:
            meta_path = args.meta_file
        else:
            if args.name:
                name = args.name
            else:
                try:
                    name, _ = get_command_config(args.name)
                except Exception as e:
                    parser.error(str(e))
            meta_path = META_PATH_TEMPLATE.format(name=name)
        if args.command == "stop":
            sys.exit(stop(meta_path))
        else:
            sys.exit(status(meta_path))
    elif args.command == "list":
        dir = args.dir or DEFAULT_META_DIR
        sys.exit(list_processes(dir))


if __name__ == "__main__":
    main()
