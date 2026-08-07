import argparse
import json
import os
from pathlib import Path
import shlex
import sys
from typing import Optional, Tuple

from colorama import just_fix_windows_console

from .config import (
    check_name_in_config,
    fill_default_paths,
    get_stack_config,
    get_task_config,
    load_config,
    resolve_stack,
)
from .control import (
    execute,
    get_meta_paths,
    list_processes,
    restart,
    start,
    stop,
    status,
)
from .constants import (
    DEFAULT_META_DIR,
    DEFAULT_RUN_NAME,
    LOG_PATH_TEMPLATE,
    META_PATH_TEMPLATE,
    META_SUFFIX,
    ROTATE_LOG_PATH_TEMPLATE,
    STACK_LOG_PATH_TEMPLATE,
    STACK_META_SUFFIX,
    STACK_META_PATH_TEMPLATE,
)
from .logs import show_stack_logs
from .inspection import inspect_stack, inspect_task
from .serialization import stack_result_data, task_result_data
from .supervisor import (
    list_stacks,
    start_detached_stack,
    start_foreground_stack,
    status_stack,
    stop_stack,
)
from .types import DmonStackMeta, DmonTaskConfig


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
        nargs="*",
    )
    sp_start.add_argument(
        "--meta-file",
        help=f"Path to meta file (default: {META_PATH_TEMPLATE})",
    )
    sp_start.add_argument(
        "--log-file",
        help=f"Path to log file (default: task configured or {LOG_PATH_TEMPLATE})",
    )
    sp_start.add_argument("--all", action="store_true", help="Start all processes")

    # stop subcommand
    sp_stop = subparsers.add_parser(
        "stop",
        help="Stop background process(es)",
        description="Stop background process(es) given name or meta file",
        # formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sp_stop.add_argument(
        "task",
        help="Configured task name (default: the only task if there's just one)",
        nargs="*",
    )
    sp_stop.add_argument("--meta-file", help="Path to meta file")
    sp_stop.add_argument(
        "--all",
        action="store_true",
        help=f"Stop all processes in meta dir ({DEFAULT_META_DIR})",
    )

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
        nargs="*",
    )
    sp_restart.add_argument(
        "--meta-file",
        help=f"Path to meta file (default: {META_PATH_TEMPLATE})",
    )
    sp_restart.add_argument(
        "--log-file",
        help=f"Path to log file (default: task configured or {LOG_PATH_TEMPLATE})",
    )
    sp_restart.add_argument("--all", action="store_true", help="Restart all processes")

    # status subcommand
    sp_status = subparsers.add_parser(
        "status",
        help="Check status of background process(es)",
        description="Check status of background process(es) given name or meta file",
        # formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sp_status.add_argument(
        "task",
        help="Configured task name (default: the only task if there's just one)",
        nargs="*",
    )
    sp_status.add_argument("--format", choices=("human", "json"), default="human")
    sp_status.add_argument(
        "--meta-file",
        help=f"Path to meta file (default: {META_PATH_TEMPLATE})",
    )
    sp_status.add_argument(
        "-a",
        "--all",
        action="store_true",
        help=f"Check status of all processes in meta dir ({DEFAULT_META_DIR})",
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
    sp_list.add_argument("--format", choices=("human", "json"), default="human")
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
        metavar="COMMAND",
        nargs=argparse.REMAINDER,
        help="Command and arguments to run; '--' is an optional separator",
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

    sp_stack = subparsers.add_parser(
        "stack",
        help="Manage a supervised stack of related tasks",
        description="Start, inspect, stop, and view logs for supervised task stacks",
    )
    stack_subparsers = sp_stack.add_subparsers(dest="stack_command", required=True)

    sp_stack_up = stack_subparsers.add_parser(
        "up",
        help="Start and supervise a configured stack",
        description="Start a stack atomically and supervise it in the foreground or background",
    )
    sp_stack_up.add_argument(
        "stack",
        help="Configured stack name (default: default_stack or the only stack)",
        nargs="?",
    )
    sp_stack_up.add_argument(
        "-d",
        "--detach",
        action="store_true",
        help="Run the stack under a background supervisor",
    )
    sp_stack_up.add_argument(
        "--abort-on-exit",
        action="store_true",
        help="Stop the remaining tasks when any task exits after startup",
    )

    sp_stack_down = stack_subparsers.add_parser(
        "down",
        help="Stop an active stack",
        description="Stop a foreground or detached stack and all tasks owned by it",
    )
    sp_stack_down.add_argument(
        "stack",
        help="Configured stack name (default: default_stack or the only stack)",
        nargs="?",
    )

    sp_stack_restart = stack_subparsers.add_parser(
        "restart",
        help="Restart a detached stack",
        description="Cleanly stop and start an active detached stack",
    )
    sp_stack_restart.add_argument(
        "stack",
        help="Configured stack name (default: default_stack or the only stack)",
        nargs="?",
    )

    sp_stack_status = stack_subparsers.add_parser(
        "status",
        help="Show stack and member task status",
        description="Show an active stack and every task process it owns",
    )
    sp_stack_status.add_argument(
        "stack",
        help="Configured stack name (default: default_stack or the only stack)",
        nargs="?",
    )
    sp_stack_status.add_argument("--format", choices=("human", "json"), default="human")

    sp_stack_logs = stack_subparsers.add_parser(
        "logs",
        help="Show output from every task in a configured stack",
        description="Show or follow task logs without changing running processes",
    )
    sp_stack_logs.add_argument(
        "stack",
        help="Configured stack name (default: default_stack or the only stack)",
        nargs="?",
    )
    sp_stack_logs.add_argument(
        "-f",
        "--follow",
        action="store_true",
        help="Keep displaying new log output",
    )
    sp_stack_logs.add_argument(
        "--tail",
        type=non_negative_int,
        default=100,
        metavar="LINES",
        help="Number of existing lines per task to show (default: 100)",
    )

    sp_stack_list = stack_subparsers.add_parser(
        "list",
        help="List all recorded stacks",
        description="List all recorded stack metadata in the project",
    )
    sp_stack_list.add_argument("--format", choices=("human", "json"), default="human")

    # add custom config file option
    for sp in [
        sp_start,
        sp_stop,
        sp_restart,
        sp_status,
        sp_exec,
    ]:
        sp.add_argument(
            "-c",
            "--config",
            metavar="PATH",
            help="Path to config file or the directory containing it (default: search from current directory upwards)",
        )
    for sp in [
        sp_stack_up,
        sp_stack_down,
        sp_stack_restart,
        sp_stack_status,
        sp_stack_logs,
        sp_stack_list,
    ]:
        sp.add_argument(
            "-c",
            "--config",
            metavar="PATH",
            help="Path to config file or project directory (default: search from current directory upwards)",
        )

    args = parser.parse_args()

    if args.command == "stack":
        sp = {
            "up": sp_stack_up,
            "down": sp_stack_down,
            "restart": sp_stack_restart,
            "status": sp_stack_status,
            "logs": sp_stack_logs,
            "list": sp_stack_list,
        }[args.stack_command]
        if args.stack_command == "up":
            try:
                stack, task_cfgs, cfg_path = get_stack_config(args.stack, args.config)
                os.chdir(cfg_path.parent)
                fill_default_paths(task_cfgs)
                if args.detach:
                    exit_code = start_detached_stack(
                        stack,
                        task_cfgs,
                        cfg_path,
                        Path(STACK_META_PATH_TEMPLATE.format(stack=stack)),
                        Path(STACK_LOG_PATH_TEMPLATE.format(stack=stack)),
                        abort_on_exit=args.abort_on_exit,
                    )
                else:
                    exit_code = start_foreground_stack(
                        stack,
                        task_cfgs,
                        cfg_path,
                        Path(STACK_META_PATH_TEMPLATE.format(stack=stack)),
                        Path(STACK_LOG_PATH_TEMPLATE.format(stack=stack)),
                        abort_on_exit=args.abort_on_exit,
                    )
            except Exception as error:
                print(f"Stack supervision failed: {error}", file=sys.stderr)
                exit_code = 1
            sp.exit(exit_code)
        if args.stack_command == "logs":
            try:
                _, task_cfgs, cfg_path = get_stack_config(args.stack, args.config)
                os.chdir(cfg_path.parent)
                fill_default_paths(task_cfgs)
            except Exception as error:
                sp.error(str(error))
            sp.exit(show_stack_logs(task_cfgs, tail=args.tail, follow=args.follow))
        if args.stack_command == "list":
            try:
                directory = resolve_project_directory(args.config)
                os.chdir(directory)
            except Exception as error:
                sp.error(str(error))
            if args.format == "json":
                sp.exit(json_stack_list(DEFAULT_META_DIR))
            sp.exit(list_stacks(DEFAULT_META_DIR))

        if args.stack_command == "restart":
            try:
                stack, task_cfgs, cfg_path = get_stack_config(args.stack, args.config)
                os.chdir(cfg_path.parent)
                fill_default_paths(task_cfgs)
                meta_path = Path(STACK_META_PATH_TEMPLATE.format(stack=stack))
                current = DmonStackMeta.load(meta_path)
            except Exception as error:
                sp.error(str(error))
            if current is None:
                sp.error(f"Stack '{stack}' is not running")
            if current.mode == "foreground":
                sp.error(
                    f"Foreground stack '{stack}' cannot be restarted from another "
                    "terminal; stop it with 'dmon stack down' and start it again."
                )
            if stop_stack(meta_path):
                sp.exit(1)
            sp.exit(
                start_detached_stack(
                    stack,
                    task_cfgs,
                    cfg_path,
                    meta_path,
                    Path(STACK_LOG_PATH_TEMPLATE.format(stack=stack)),
                    abort_on_exit=current.abort_on_exit,
                )
            )

        try:
            stack, directory = resolve_stack_target(args.stack, args.config)
            os.chdir(directory)
            meta_path = Path(STACK_META_PATH_TEMPLATE.format(stack=stack))
        except Exception as error:
            sp.error(str(error))
        if args.stack_command == "down":
            sp.exit(stop_stack(meta_path))
        if args.stack_command == "status":
            if args.format == "json":
                sp.exit(json_stack_status(stack, meta_path))
            sp.exit(status_stack(meta_path))
    elif args.command in ["start", "restart"]:
        sp = sp_start if args.command == "start" else sp_restart
        try:
            tasks, task_cfgs, cfg_path = get_task_config(
                args.task, args.config, args.all
            )
            os.chdir(cfg_path.parent)
        except Exception as e:
            sp.error(str(e))

        # check if meta_file or log_file path is provided;
        # if so, only one task should be specified
        if args.meta_file or args.log_file:
            if len(tasks) == 1:
                task_cfgs[0].meta_path = args.meta_file or task_cfgs[0].meta_path
                task_cfgs[0].log_path = args.log_file or task_cfgs[0].log_path
            else:
                sp.error(
                    f"'--meta-file' and '--log-file' can only be specified when {args.command}ing a single task"
                )
        fill_default_paths(task_cfgs)
        if args.command == "start":
            sp.exit(start(task_cfgs))
        else:
            sp.exit(restart(task_cfgs))
    elif args.command == "exec":
        try:
            _, task_cfgs, cfg_path = get_task_config(args.task, args.config)
            os.chdir(cfg_path.parent)
        except Exception as e:
            sp_exec.error(str(e))
        sp_exec.exit(execute(task_cfgs[0]))
    elif args.command in ["stop", "status"]:
        sp = sp_stop if args.command == "stop" else sp_status
        meta_paths = []

        tasks = args.task
        if args.task:
            try:
                tasks, _, cfg_path = get_task_config(args.task, args.config)
                os.chdir(cfg_path.parent)
            except Exception as e:
                sp.error(str(e))
        elif args.config:
            try:
                _, cfg_path = load_config(args.config)
                os.chdir(cfg_path.parent)
            except Exception as e:
                sp.error(str(e))

        # Collect meta paths from --all
        if args.all:
            meta_paths.extend(get_meta_paths(DEFAULT_META_DIR))

        # Collect meta paths from --meta-file
        if args.meta_file:
            meta_paths.append(args.meta_file)

        # Collect meta paths from task names
        if len(tasks) > 0:
            meta_paths.extend([META_PATH_TEMPLATE.format(task=task) for task in tasks])

        # If no meta paths collected, use default task
        if len(meta_paths) == 0:
            try:
                tasks, _, cfg_path = get_task_config(args.task, args.config)
                os.chdir(cfg_path.parent)
            except Exception as e:
                sp.error(str(e))
            meta_paths.extend([META_PATH_TEMPLATE.format(task=task) for task in tasks])

        # Remove duplicates
        unique_meta_paths = sorted(set(Path(p).resolve() for p in meta_paths))

        if args.command == "stop":
            sp.exit(stop(unique_meta_paths))
        else:
            if args.format == "json":
                sp.exit(json_task_status(unique_meta_paths))
            sp.exit(status(unique_meta_paths))
    elif args.command == "list":
        dir = args.dir or DEFAULT_META_DIR
        if args.format == "json":
            sp_list.exit(json_task_list(Path(dir)))
        sp_list.exit(list_processes(dir, args.full))
    elif args.command == "run":
        command_list = args.command_list
        if command_list and command_list[0] == "--":
            command_list = command_list[1:]
        if not command_list:
            sp_run.error("Please provide a command to run.")
        if not args.name:
            sp_run.error("Please provide a non-empty name for the task.")
        elif check_name_in_config(args.name):
            sp_run.error(
                f"Task '{args.name}' already exists in config. Please choose another name."
            )

        task_cfg = DmonTaskConfig(
            task=args.name,
            cmd=shlex.join(command_list) if args.shell else command_list,
            cwd=args.cwd,
            meta_path=args.meta_file or META_PATH_TEMPLATE.format(task=args.name),
            log_path=args.log_file or LOG_PATH_TEMPLATE.format(task=args.name),
            log_rotate=args.log_rotate,
            rotate_log_path=args.rotate_log_path
            or ROTATE_LOG_PATH_TEMPLATE.format(task=args.name),
        )
        sp_run.exit(start([task_cfg]))
    else:
        parser.print_help()
        parser.exit(1)


def resolve_stack_target(
    name: Optional[str], config_path: Optional[str]
) -> Tuple[str, Path]:
    if name is None:
        stack, _, path = resolve_stack(None, config_path)
        return stack, path.parent
    if not name:
        raise ValueError("Stack name must not be empty")
    return name.lower(), resolve_project_directory(config_path)


def resolve_project_directory(config_path: Optional[str]) -> Path:
    if config_path:
        path = Path(config_path).resolve()
        return path if path.is_dir() else path.parent
    try:
        _, path = load_config()
        return path.parent
    except FileNotFoundError:
        return Path.cwd()


def non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def json_task_status(meta_paths) -> int:
    results = [
        inspect_task(
            metadata_name(Path(path), META_SUFFIX),
            Path(path),
            require_running=True,
        )
        for path in meta_paths
    ]
    return print_json_results("tasks", results, task_result_data)


def metadata_name(path: Path, suffix: str) -> str:
    return path.name[: -len(suffix)] if path.name.endswith(suffix) else path.stem


def json_task_list(meta_dir: Path) -> int:
    target = meta_dir.resolve()
    paths = sorted(target.glob(f"*{META_SUFFIX}")) if target.is_dir() else []
    results = [
        inspect_task(path.name[: -len(META_SUFFIX)], path, require_running=False)
        for path in paths
    ]
    return print_json_results("tasks", results, task_result_data)


def json_stack_status(name: str, meta_path: Path) -> int:
    result = inspect_stack(name, meta_path, require_running=True)
    return print_json_results("stacks", [result], stack_result_data)


def json_stack_list(meta_dir: Path) -> int:
    target = meta_dir.resolve()
    paths = sorted(target.glob(f"*{STACK_META_SUFFIX}")) if target.is_dir() else []
    results = [
        inspect_stack(path.name[: -len(STACK_META_SUFFIX)], path, require_running=False)
        for path in paths
    ]
    return print_json_results("stacks", results, stack_result_data)


def print_json_results(key, results, serializer) -> int:
    ok = all(result.ok for result in results)
    print(
        json.dumps(
            {"ok": ok, key: [serializer(result) for result in results]},
            ensure_ascii=False,
            indent=2,
        )
    )
    for result in results:
        if result.error:
            print(f"{result.name}: {result.error}", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    main()
