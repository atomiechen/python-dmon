from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys
import time
from typing import BinaryIO, Callable, Optional, Sequence, TextIO, Tuple

from termcolor import colored

from .types import DmonTaskConfig


FileIdentity = Tuple[int, int]
StopCheck = Callable[[], bool]


@dataclass
class LogCursor:
    task: str
    path: Path
    identity: Optional[FileIdentity] = None
    offset: int = 0
    pending: bytes = b""


def show_stack_logs(
    configs: Sequence[DmonTaskConfig],
    *,
    tail: int = 100,
    follow: bool = False,
    poll_interval: float = 0.2,
    stop_requested: Optional[StopCheck] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    output = stdout or sys.stdout
    errors = stderr or sys.stderr
    cursors = [LogCursor(config.task, Path(config.log_path)) for config in configs]
    width = max((len(cursor.task) for cursor in cursors), default=0)

    for cursor in cursors:
        segments = read_tail(cursor, tail, errors)
        if follow and segments and not line_is_complete(segments[-1]):
            cursor.pending = segments.pop()
        emit_segments(cursor.task, segments, width, output)

    if not follow:
        return 0

    try:
        while True:
            for cursor in cursors:
                read_new(cursor, width, output)
            output.flush()
            if stop_requested is not None and stop_requested():
                break
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        pass
    finally:
        for cursor in cursors:
            if cursor.pending:
                emit_segments(cursor.task, [cursor.pending], width, output)
                cursor.pending = b""
        output.flush()
    return 0


def read_tail(cursor: LogCursor, count: int, errors: TextIO) -> list[bytes]:
    try:
        with cursor.path.open("rb") as stream:
            stat = os.fstat(stream.fileno())
            segments, end = tail_segments(stream, count)
    except FileNotFoundError:
        print(f"Log not found for task '{cursor.task}': {cursor.path}", file=errors)
        return []
    except OSError as error:
        print(f"Cannot read log for task '{cursor.task}': {error}", file=errors)
        return []

    cursor.identity = file_identity(stat)
    cursor.offset = end
    return segments


def tail_segments(stream: BinaryIO, count: int) -> tuple[list[bytes], int]:
    stream.seek(0, os.SEEK_END)
    end = stream.tell()
    if count == 0 or end == 0:
        return [], end

    position = end
    chunks = []
    newlines = 0
    while position > 0 and newlines <= count:
        size = min(8192, position)
        position -= size
        stream.seek(position)
        chunk = stream.read(size)
        chunks.append(chunk)
        newlines += chunk.count(b"\n")
    data = b"".join(reversed(chunks))
    return data.splitlines(keepends=True)[-count:], end


def read_new(cursor: LogCursor, width: int, output: TextIO) -> None:
    try:
        with cursor.path.open("rb") as stream:
            stat = os.fstat(stream.fileno())
            identity = file_identity(stat)
            size = stat.st_size
            replaced = cursor.identity is not None and identity != cursor.identity
            truncated = size < cursor.offset
            if replaced or truncated:
                if replaced:
                    read_rotated_remainder(cursor, width, output)
                if cursor.pending:
                    emit_segments(cursor.task, [cursor.pending], width, output)
                    cursor.pending = b""
                cursor.offset = 0
            stream.seek(cursor.offset)
            data = stream.read()
            cursor.offset = stream.tell()
            cursor.identity = identity
    except FileNotFoundError:
        return
    except OSError:
        return

    if not data:
        return
    consume_data(cursor, data, width, output)


def read_rotated_remainder(cursor: LogCursor, width: int, output: TextIO) -> None:
    previous_identity = cursor.identity
    if previous_identity is None:
        return
    try:
        candidates = cursor.path.parent.glob(f"{cursor.path.name}.*")
        for candidate in candidates:
            try:
                with candidate.open("rb") as stream:
                    stat = os.fstat(stream.fileno())
                    if file_identity(stat) != previous_identity:
                        continue
                    if stat.st_size < cursor.offset:
                        return
                    stream.seek(cursor.offset)
                    consume_data(cursor, stream.read(), width, output)
                    return
            except (FileNotFoundError, OSError):
                continue
    except OSError:
        return


def consume_data(cursor: LogCursor, data: bytes, width: int, output: TextIO) -> None:
    if not data:
        return
    segments = (cursor.pending + data).splitlines(keepends=True)
    cursor.pending = b""
    if segments and not line_is_complete(segments[-1]):
        cursor.pending = segments.pop()
    emit_segments(cursor.task, segments, width, output)


def file_identity(stat: os.stat_result) -> FileIdentity:
    if stat.st_ino:
        return stat.st_dev, stat.st_ino
    return 0, stat.st_ctime_ns


def line_is_complete(segment: bytes) -> bool:
    return segment.endswith((b"\n", b"\r"))


def emit_segments(
    task: str, segments: Sequence[bytes], width: int, output: TextIO
) -> None:
    prefix = colored(f"[{task:<{width}}]", color="cyan", attrs=["bold"])
    for segment in segments:
        text = segment.decode("utf-8", errors="replace")
        output.write(f"{prefix} {text}")
        if not line_is_complete(segment):
            output.write("\n")
