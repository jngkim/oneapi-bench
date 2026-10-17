"""``obench new``: create apps, workloads and sites from ``templates/``."""

import re
import shutil
from pathlib import Path

from .config import ConfigError

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _check_name(name, what):
    if not _NAME.match(name):
        raise ConfigError("invalid %s name '%s' (letters, digits, '-', '_' and '.')" % (what, name))


def _fill(path, **values):
    text = path.read_text()
    for key, value in values.items():
        text = text.replace("@%s@" % key, value)
    path.write_text(text)


def new_app(root, name):
    _check_name(name, "application")
    dest = Path(root) / "apps" / name
    if dest.exists():
        raise ConfigError("%s already exists" % dest)
    shutil.copytree(Path(root) / "templates" / "app", dest)
    for path in dest.rglob("*"):
        if path.is_file():
            _fill(path, APP=name)
    (dest / "build.sh").chmod(0o755)
    return dest


def new_workload(registry, ident):
    if "/" not in ident:
        raise ConfigError("name the workload as APP/NAME, e.g. gromacs/my-system")
    app_name, name = ident.split("/", 1)
    _check_name(name, "workload")
    app = registry.app(app_name)
    dest = app.dir / "workloads" / ("%s.toml" % name)
    if dest.exists():
        raise ConfigError("%s already exists" % dest)
    dest.parent.mkdir(exist_ok=True)
    shutil.copy2(Path(registry.root) / "templates" / "workload.toml", dest)
    _fill(dest, APP=app_name, NAME=name)
    return dest


def new_site(root, name):
    _check_name(name, "site")
    dest = Path(root) / "sites" / ("%s.toml" % name)
    if dest.exists():
        raise ConfigError("%s already exists" % dest)
    shutil.copy2(Path(root) / "templates" / "site.toml", dest)
    _fill(dest, NAME=name)
    return dest
