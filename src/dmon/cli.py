import argparse
import sys

from colorama import just_fix_windows_console

from .config import check_name_in_config, get_command_config
from .control import list_processes, restart, start, stop, status
from .constants import (
    DEFAULT_META_DIR,
    DEFAULT_RUN_NAME,
    LOG_PATH_TEMPLATE,
    META_PATH_TEMPLATE,
)
from .types import DmonCommandConfig


def main():
    just_fix_windows_console()

    parser = argparse.ArgumentParser(
        prog="dmon",
        description="Minimal cross-platform daemon manager",
        # formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command")

    # start subcommand
    sp_start = subparsers.add_parser(
        "start",
        help="Start a configured command as a background process",
        description="Start a configured command as a background process",
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
        help="Stop a background process",
        description="Stop a background process given name or meta file",
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
        help="Restart a configured command as a background process",
        description="Restart a configured command as a background process",
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
        description="Check status of a background process given name or meta file",
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
        help="List all processes and their status",
        description="List all processes and their status managed by dmon in the given directory",
        # formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sp_list.add_argument(
        "dir",
        help=f"Directory to look for meta files (default: {DEFAULT_META_DIR})",
        nargs="?",
    )

    # run subcommand
    sp_run = subparsers.add_parser(
        "run",
        help="Run a custom command (not in config) as a background process",
        description="Run a custom command (not in config) as a background process",
        # formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sp_run.add_argument(
        "--name",
        "-n",
        default=DEFAULT_RUN_NAME,
        help=f"Name for this command (default: {DEFAULT_RUN_NAME})",
    )
    sp_run.add_argument(
        "--shell", action="store_true", help="Run command in shell (default: False)"
    )
    sp_run.add_argument(
        "--meta-file",
        help=f"Path to meta file (default: {META_PATH_TEMPLATE})",
    )
    sp_run.add_argument(
        "--log-file",
        help=f"Path to log file (default: {LOG_PATH_TEMPLATE})",
    )
    sp_run.add_argument(
        "command_list",
        metavar="command",
        nargs=argparse.ONE_OR_MORE,
        help="Command to run",
    )

    args = parser.parse_args()

    if args.command in ["start", "restart"]:
        try:
            name, cmd_cfg = get_command_config(args.name)
        except Exception as e:
            parser.error(str(e))

        cmd_cfg["meta_path"] = args.meta_file or META_PATH_TEMPLATE.format(name=name)
        cmd_cfg["log_path"] = (
            args.log_file
            or cmd_cfg.get("log_path")
            or LOG_PATH_TEMPLATE.format(name=name)
        )
        if args.command == "start":
            sys.exit(start(cmd_cfg))
        else:
            sys.exit(restart(cmd_cfg))
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
    elif args.command == "run":
        if not args.name:
            parser.error("Please provide a non-empty name for the command.")
        elif check_name_in_config(args.name):
            parser.error(
                f"Name '{args.name}' already exists in config. Please choose another name."
            )

        cmd_cfg: DmonCommandConfig = {
            "name": args.name,
            "cmd": " ".join(args.command_list) if args.shell else args.command_list,
            "cwd": "",
            "env": {},
            "override_env": False,
            "meta_path": args.meta_file or META_PATH_TEMPLATE.format(name=args.name),
            "log_path": args.log_file or LOG_PATH_TEMPLATE.format(name=args.name),
        }
        sys.exit(start(cmd_cfg))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
