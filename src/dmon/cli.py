import argparse
import shlex
import sys

from colorama import just_fix_windows_console

from .config import check_name_in_config, get_task_config
from .control import execute, list_processes, restart, start, stop, status
from .constants import (
    DEFAULT_META_DIR,
    DEFAULT_RUN_NAME,
    LOG_PATH_TEMPLATE,
    META_PATH_TEMPLATE,
    ROTATE_LOG_PATH_TEMPLATE,
)
from .types import DmonTaskConfig


def get_version():
    # if python 3.8 or later, use importlib.metadata
    import importlib.metadata

    return importlib.metadata.version("python-dmon")


def main():
    just_fix_windows_console()

    parser = argparse.ArgumentParser(
        prog="dmon",
        description=f"dmon v{get_version()} - Lightweight cross-platform daemon manager",
        # formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=get_version(),
    )

    subparsers = parser.add_subparsers(dest="command")

    # start subcommand
    sp_start = subparsers.add_parser(
        "start",
        help="Start a configured task as a background process",
        description="Start a configured task as a background process",
        # formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sp_start.add_argument(
        "task",
        help="Configured task name (default: the only task if there's just one)",
        nargs="?",
    )
    sp_start.add_argument(
        "--meta-file",
        help=f"Path to meta file (default: {META_PATH_TEMPLATE})",
    )
    sp_start.add_argument(
        "--log-file",
        help=f"Path to log file (default: task configured or {LOG_PATH_TEMPLATE})",
    )

    # stop subcommand
    sp_stop = subparsers.add_parser(
        "stop",
        help="Stop a background process",
        description="Stop a background process given name or meta file",
        # formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sp_stop.add_argument(
        "task",
        help="Configured task name (default: the only task if there's just one)",
        nargs="?",
    )
    sp_stop.add_argument("--meta-file", help="Path to meta file")

    # restart subcommand
    sp_restart = subparsers.add_parser(
        "restart",
        help="Restart a configured task as a background process",
        description="Restart a configured task as a background process",
        # formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sp_restart.add_argument(
        "task",
        help="Configured task name (default: the only task if there's just one)",
        nargs="?",
    )
    sp_restart.add_argument(
        "--meta-file",
        help=f"Path to meta file (default: {META_PATH_TEMPLATE})",
    )
    sp_restart.add_argument(
        "--log-file",
        help=f"Path to log file (default: task configured or {LOG_PATH_TEMPLATE})",
    )

    # status subcommand
    sp_status = subparsers.add_parser(
        "status",
        help="Check process status",
        description="Check status of a background process given name or meta file",
        # formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sp_status.add_argument(
        "task",
        help="Configured task name (default: the only task if there's just one)",
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
    sp_list.add_argument(
        "--full",
        action="store_true",
        help="Show full width without truncating column (default: False)",
    )

    # run subcommand
    sp_run = subparsers.add_parser(
        "run",
        help="Run a custom task (not in config) as a background process",
        description="Run a custom task (not in config) as a background process",
        # formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sp_run.add_argument(
        "--name",
        "-n",
        default=DEFAULT_RUN_NAME,
        help=f"Name for this task (default: {DEFAULT_RUN_NAME})",
    )
    sp_run.add_argument(
        "--cwd",
        help="Working directory to run the command in (default: current directory)",
        default="",
    )
    sp_run.add_argument(
        "--shell", action="store_true", help="Run task in shell (default: False)"
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
        "--log-rotate",
        action="store_true",
        help="Whether to rotate log file (default: False)",
    )
    sp_run.add_argument(
        "--rotate-log-path",
        help=f"Path to rotation log file (default: {ROTATE_LOG_PATH_TEMPLATE})",
    )
    sp_run.add_argument(
        "command_list",
        metavar="command",
        nargs=argparse.ONE_OR_MORE,
        help="Command (with args) to run",
    )

    sp_exec = subparsers.add_parser(
        "exec",
        help="Execute a configured task in the foreground",
        description="Execute a configured task in the foreground",
    )
    sp_exec.add_argument(
        "task",
        help="Configured task name (default: the only task if there's just one)",
        nargs="?",
    )

    # add custom config file option
    for sp in [sp_start, sp_stop, sp_restart, sp_status, sp_exec]:
        sp.add_argument(
            "--config",
            help="Path to config file (YAML or TOML) (default: search from current directory upwards)",
        )

    args = parser.parse_args()

    if args.command in ["start", "restart"]:
        sp = sp_start if args.command == "start" else sp_restart
        try:
            task, task_cfg = get_task_config(args.task, args.config)
        except Exception as e:
            sp.error(str(e))

        task_cfg.meta_path = (
            args.meta_file or task_cfg.meta_path or META_PATH_TEMPLATE.format(task=task)
        )
        task_cfg.log_path = (
            args.log_file or task_cfg.log_path or LOG_PATH_TEMPLATE.format(task=task)
        )
        task_cfg.rotate_log_path = (
            task_cfg.rotate_log_path or ROTATE_LOG_PATH_TEMPLATE.format(task=task)
        )
        if args.command == "start":
            sys.exit(start(task_cfg))
        else:
            sys.exit(restart(task_cfg))
    elif args.command == "exec":
        try:
            task, task_cfg = get_task_config(args.task, args.config)
        except Exception as e:
            sp_exec.error(str(e))
        sys.exit(execute(task_cfg))
    elif args.command in ["stop", "status"]:
        sp = sp_stop if args.command == "stop" else sp_status
        if args.meta_file:
            meta_path = args.meta_file
        else:
            if args.task:
                task = args.task
            else:
                try:
                    task, _ = get_task_config(args.task, args.config)
                except Exception as e:
                    sp.error(str(e))
            meta_path = META_PATH_TEMPLATE.format(task=task)
        if args.command == "stop":
            sys.exit(stop(meta_path))
        else:
            sys.exit(status(meta_path))
    elif args.command == "list":
        dir = args.dir or DEFAULT_META_DIR
        sys.exit(list_processes(dir, args.full))
    elif args.command == "run":
        if not args.name:
            sp_run.error("Please provide a non-empty name for the task.")
        elif check_name_in_config(args.name):
            sp_run.error(
                f"Task '{args.name}' already exists in config. Please choose another name."
            )

        task_cfg = DmonTaskConfig(
            task=args.name,
            cmd=shlex.join(args.command_list) if args.shell else args.command_list,
            cwd=args.cwd,
            meta_path=args.meta_file or META_PATH_TEMPLATE.format(task=args.name),
            log_path=args.log_file or LOG_PATH_TEMPLATE.format(task=args.name),
            log_rotate=args.log_rotate,
            rotate_log_path=args.rotate_log_path
            or ROTATE_LOG_PATH_TEMPLATE.format(task=args.name),
        )
        sys.exit(start(task_cfg))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
