""" """

from __future__ import annotations

import glob
import os
import re
from typing import Any, Dict, Optional, Sequence, Tuple

# Example php -i output line:
#   extension_dir => /usr/lib/php/20230831 => /usr/lib/php/20230831
_EXT_DIR_RE = re.compile(
    r"^extension_dir\s*=>\s*(?P<configured>.*?)\s*=>",
    re.MULTILINE,
)

_EXTENSION_RE = re.compile(
    r"^(?P<ident>zend_extension|extension)\s*=\s*(?P<extension>[^\s;]+)",
    re.MULTILINE,
)


class PhpExtension:
    """ """

    def __init__(
        self,
        module: Any,
        php_binary: str,
    ) -> None:

        self.module = module
        self.module.log(f"PhpExtension::__init__(php_binary: {php_binary})")

        self.php_binary = php_binary

    def find_extension_dir(self) -> Tuple[Optional[str], Optional[str]]:
        """Determine the configured PHP extension directory.

        Returns:
            A tuple containing the detected extension directory and an optional
            error message.
        """
        self.module.log("PhpExtension::find_extension_dir()")

        if not self.php_binary:
            return None, "PHP does not appear to be installed in the default paths."

        rc, out, err = self.__exec([self.php_binary, "-i"], check_rc=False)
        if rc != 0:
            return None, err or "Unable to determine PHP extension directory."

        match = _EXT_DIR_RE.search(out)
        if not match:
            return None, "Unable to parse the PHP extension directory from 'php -i'."

        return match.group("configured").strip(), None

    def extension_available(
        self, extension_directory: str, module_content: Any
    ) -> bool:
        """Check whether the configured extension is available.

        Args:
            extension_directory: Directory containing PHP extension binaries.
            module_content: Raw INI content for a module.

        Returns:
            C(True) if the extension can be considered available, otherwise
            C(False).
        """
        self.module.log(
            f"PhpExtension::extension_available(extension_directory: {extension_directory}, module_content: {module_content})"
        )

        if not isinstance(module_content, str) or not module_content.strip():
            return False

        match = _EXTENSION_RE.search(module_content)
        if not match:
            return False

        ident = match.group("ident").strip()
        extension = match.group("extension").replace(".so", "").strip()

        self.module.log(f"  - extension: {extension}")

        if ident == "zend_extension":
            return True

        search = glob.glob(os.path.join(extension_directory, f"{extension}.*"))

        if search:
            self.module.log(f"  - found: {search}")
            return True

        return False

    def __exec(
        self,
        args: Sequence[str],
        environ_update: Optional[Dict[str, str]] = None,
        check_rc: bool = True,
    ) -> Tuple[int, str, str]:
        """Execute a prepared command via Ansible's C(run_command()) helper.

        Args:
            args: Full argument vector.
            environ_update: Optional environment variables for the command.
            check_rc: Whether Ansible should fail on non-zero exit codes.

        Returns:
            Tuple of return code, stdout, and stderr.
        """
        rc, out, err = self.module.run_command(
            list(args),
            environ_update=environ_update,
            check_rc=check_rc,
        )

        return rc, out, err
