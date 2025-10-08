import argparse
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
import os
import signal
import subprocess
import sys


logger = logging.getLogger("dmon.runner")


class FixedSizeRotatingFileHandler(RotatingFileHandler):
    """
    Custom RotatingFileHandler that renames the old log file with a timestamp suffix
    instead of deleting it.
    """

    def __init__(self, filename, maxBytes):
        super().__init__(filename, maxBytes=maxBytes)

    def doRollover(self):
        if self.stream:
            self.stream.close()
        # Create timestamped filename for the rollover logs
        current_time = datetime.now().strftime(".%Y%m%d-%H:%M:%S")
        self.rotate(self.baseFilename, self.baseFilename + current_time)
        self.stream = self._open()


def get_file_dir(file_path):
    return os.path.dirname(file_path)


def make_dir(dir):
    dir = os.path.abspath(dir)
    if not os.path.exists(dir):
        os.makedirs(dir, exist_ok=True)


def make_file_dir(file_path):
    par_dir = get_file_dir(file_path)
    make_dir(par_dir)


def need_rotate(log_path, max_log_size):
    return os.path.getsize(log_path) >= max_log_size and max_log_size > 0


def rotate_log(log_path):
    current_time = datetime.now().strftime(".%Y%m%d-%H%M%S")
    new_name = log_path + current_time
    logger.info(f"Rotating {log_path} to {new_name}")
    if os.path.exists(new_name):
        logger.warning(f"{new_name} already exists, skip renaming")
    else:
        make_file_dir(new_name)
        os.rename(log_path, new_name)


def loop_to_log(bin_fd, log_path, max_log_size):
    while True:  # loop once whenever need to rotate
        with open(log_path, "ab") as log_file:
            while True:
                try:
                    # read byte by byte in binary mode to avoid decoding
                    # error caused by utf8 character truncation
                    byte = bin_fd.read(1)
                    if byte:
                        log_file.write(byte)
                        log_file.flush()  # immediately write the content to the file
                        # When a newline character is read, check if
                        # rotation is needed; if so, break the loop
                        if byte == b"\n" and need_rotate(log_path, max_log_size):
                            break
                    else:
                        logger.info("Read EOF, now closing...")
                        return
                except Exception as e:
                    logger.exception(f"Exception in while loop: {e}")
        rotate_log(log_path)  # rotate log file


def catch_exception(func):
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.exception(f"Exception in {func.__name__}: {e}")

    return wrapper


@catch_exception
def main(
    cmd,
    log_path,
    max_log_size,
    rotate_log_path,
    max_rotate_log_size,
):
    # Configure logging
    rh = None
    if rotate_log_path:
        rh = FixedSizeRotatingFileHandler(rotate_log_path, maxBytes=max_rotate_log_size)
    logging.basicConfig(
        format="%(asctime)s.%(msecs)03d - %(process)d - %(levelname)s - %(message)s",
        level=logging.INFO,
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[rh] if rh else None,
    )

    logger.info(
        f"Prepare for rotating logs: {log_path=} {max_log_size=} {rotate_log_path=} {max_rotate_log_size=}"
    )

    shell = isinstance(cmd, str)

    # register signal handler to terminate the child process
    def signal_handler(signum: int, frame):
        logger.info(f"Received signal {signum}, forwarding to child process...")
        if sys.platform.startswith("win") and signum == signal.SIGINT:
            signum = signal.SIGTERM
            logger.info(f"On Windows, convert SIGINT to SIGTERM ({signum})")
        # proc.terminate()
        proc.send_signal(signum)
        logger.info("Waiting for child process to exit...")
        proc.wait()
        logger.info("Child process exited, all done.")
        sys.exit(0)

    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start the child process with stdout/stderr redirected to the log
    # env will be inherited from parent process
    # cwd will be inherited from parent process
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=shell,
        text=False,  # binary mode
        bufsize=0,  # unbuffered
    )

    logger.info(f"Started process {proc.pid} with command: {cmd} (shell={shell})")

    make_file_dir(log_path)
    loop_to_log(proc.stdout, log_path, max_log_size)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Dmon task runner with log rotation utility",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "command",
        nargs=argparse.ONE_OR_MORE,
        help="Command with arguments to run",
    )
    parser.add_argument("--shell", action="store_true", help="Run command in shell")
    parser.add_argument("--log-path", help="Log file path", required=True)
    parser.add_argument(
        "--max-log-size",
        help="Max log file size (MB); 0 for no rotation",
        type=int,
        default=5,
    )
    parser.add_argument(
        "--rotate-log-path",
        help="Path of the log output of this rotation process; if not provided, output to stdout",
        default=None,
    )
    parser.add_argument(
        "--max-rotate-log-size",
        help="Max file size (MB) for this rotation log; 0 for no rotation",
        type=int,
        default=5,
    )
    args = parser.parse_args()
    main(
        " ".join(args.command) if args.shell else args.command,
        args.log_path,
        args.max_log_size * 1024 * 1024,
        args.rotate_log_path,
        args.max_rotate_log_size * 1024 * 1024,
    )
    logger.info("Process finished.")
