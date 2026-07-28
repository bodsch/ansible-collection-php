# notes

PIE (PHP Installer for Extensions) is distributed as a PHAR from the GitHub
releases of the [php/pie](https://github.com/php/pie) project and is the
designated successor of PECL.

- The `bodsch.php.pie_installer` module downloads `pie.phar`, verifies its
  SHA-256 digest against the digest published by the GitHub release API, and
  installs it as an executable into `pie_install_path`.
- The `bodsch.php.pie_packages` module manages PHP extensions via `pie install`
  / `pie uninstall` and uses `pie show` to stay idempotent.
