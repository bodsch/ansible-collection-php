"""
Temporary file helper that keeps the file path usable during the context
lifetime and optionally removes the file afterwards.

This is useful on Windows, where `tempfile.NamedTemporaryFile` can cause
permission problems when the same file must be reopened by path while
still inside the context block.
"""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from types import TracebackType
from typing import IO, Any

PathLike = str | os.PathLike[str]


class WritableTempFile:
    """
    Context manager for a writable temporary file with optional cleanup.

    The created file remains addressable by its path during the whole
    context lifetime. This is useful for APIs that require a filesystem
    path instead of an already opened file object.
    """

    def __init__(
        self,
        mode: str = "w",
        *,
        encoding: str | None = "utf-8",
        suffix: str | None = None,
        directory: PathLike | None = None,
        delete_on_exit: bool = True,
    ) -> None:
        """
        Initialize the temporary file context manager.

        Args:
            mode:
                File open mode.
            encoding:
                Encoding for text mode. Must be ``None`` for binary mode.
            suffix:
                Optional filename suffix.
            directory:
                Optional target directory for the temporary file.
            delete_on_exit:
                If ``True``, delete the temporary file when leaving the
                context. If ``False``, only close the file and leave
                cleanup to the caller.

        Raises:
            ValueError:
                If binary mode is used together with a non-None encoding.
        """
        if "b" in mode and encoding is not None:
            raise ValueError("encoding must be None when using binary mode")

        self.mode = mode
        self.encoding = encoding
        self.suffix = suffix
        self.directory = self._normalize_directory(directory)
        self.delete_on_exit = delete_on_exit
        self.temp_file: IO[Any] | None = None

    def __enter__(self) -> IO[Any]:
        """
        Create and return the temporary file object.

        Returns:
            The opened temporary file object.
        """
        kwargs: dict[str, Any] = {
            "mode": self.mode,
            "suffix": self.suffix,
            "delete": False,
            "dir": self.directory,
        }

        if "b" not in self.mode:
            kwargs["encoding"] = self.encoding

        self.temp_file = NamedTemporaryFile(**kwargs)
        return self.temp_file

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        """
        Close the temporary file and optionally remove it.

        Cleanup errors are only raised if no exception is already active.

        Returns:
            Always ``False`` so that exceptions from the with-block are
            propagated to the caller.
        """
        cleanup_error: BaseException | None = None

        if self.temp_file is not None:
            try:
                self.temp_file.close()
            except OSError as exc:
                cleanup_error = exc

            if self.delete_on_exit:
                try:
                    os.unlink(self.temp_file.name)
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    if cleanup_error is None:
                        cleanup_error = exc

        if cleanup_error is not None and exc_type is None:
            raise cleanup_error

        return False

    @staticmethod
    def _normalize_directory(directory: PathLike | None) -> str | None:
        """
        Normalize the optional directory argument to a string path.

        Args:
            directory:
                Directory as string, ``Path``, or other path-like object.

        Returns:
            A normalized string path or ``None``.
        """
        if directory is None:
            return None
        return os.fspath(Path(directory))
