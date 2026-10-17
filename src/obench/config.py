"""Loading and validating site, application and workload files.

Everything a user edits is TOML. Each file kind has a schema below; unknown
keys are reported with a "did you mean" hint so that typos fail early instead
of being silently ignored.
"""

import difflib
import importlib.util
import os
from pathlib import Path

try:  # Python 3.11+
    import tomllib as _tomllib
except ImportError:  # pragma: no cover - depends on interpreter
    try:
        import tomli as _tomllib
    except ImportError:
        from . import _toml as _tomllib


class ConfigError(Exception):
    """A user-facing configuration problem."""


def load_toml(path):
    path = Path(path)
    try:
        return _tomllib.loads(path.read_text())
    except FileNotFoundError:
        raise ConfigError("file not found: %s" % path)
    except ValueError as exc:  # TOMLDecodeError subclasses ValueError
        raise ConfigError("%s: invalid TOML: %s" % (path, exc))


# ---------------------------------------------------------------------------
# Schemas: {key: (type, default)}; REQUIRED marks mandatory keys. A nested dict
# is a sub-table schema; TABLE is a free-form table (environment variables,
# parameters); [schema] is an array of tables.
# ---------------------------------------------------------------------------
REQUIRED = object()
TABLE = "table"

SITE_SCHEMA = {
    "site": {
        "description": (str, ""),
        "scheduler": (str, "slurm"),
    },
    "node": {
        "gpus_per_node": (int, REQUIRED),
        "tiles_per_gpu": (int, 1),
        "gpu_mode": (str, "gpu"),
        "cores_per_node": (int, REQUIRED),
    },
    "toolchain": {
        "tag": (str, REQUIRED),
        "setup": (list, []),
    },
    "slurm": {
        "partition": (str, ""),
        "account": (str, ""),
        "qos": (str, ""),
        "constraint": (str, ""),
        "directives": (list, []),
    },
    "mpi": {
        "launcher": (str, "srun"),
        "gpu_aware": (bool, False),
        "env": (TABLE, {}),
    },
    "env": (TABLE, {}),
    "paths": {
        "install_root": (str, "~/obench/install"),
        "build_root": (str, "~/obench/build"),
        "data_root": (str, "~/obench/data"),
        "results_root": (str, "results"),
    },
    "apps": (TABLE, {}),
}

APP_SCHEMA = {
    "app": {
        "title": (str, REQUIRED),
        "description": (str, ""),
        "homepage": (str, ""),
        "license": (str, ""),
        "default_version": (str, REQUIRED),
    },
    "source": {
        "url": (str, ""),
        "git": (str, ""),
        "ref": (str, "{version}"),
    },
    "build": {
        "script": (str, "build.sh"),
        "env": (TABLE, {}),
        "check": (list, []),
        "jobs": (int, 16),
        "time_limit": (str, "02:00:00"),
    },
    "run": {
        "executable": (str, ""),
        "env": (TABLE, {}),
    },
}

SITE_APP_SCHEMA = {
    "version": (str, ""),
    "build_env": (TABLE, {}),
    "run_env": (TABLE, {}),
}

WORKLOAD_KINDS = ("bundled", "published", "custom")
SCALING_MODES = ("strong", "weak", "throughput")
SIZES = ("tiny", "small", "medium", "large", "xlarge")
STATUSES = ("draft", "unvalidated", "validated")

WORKLOAD_SCHEMA = {
    "workload": {
        "title": (str, REQUIRED),
        "kind": (str, REQUIRED),
        "publisher": (str, ""),
        "reference": (str, ""),
        "description": (str, ""),
        "size": (str, "medium"),
        "scaling": (str, "strong"),
        "status": (str, "unvalidated"),
        "tags": (list, []),
        "notes": (str, ""),
    },
    "inputs": ([{
        "url": (str, ""),
        "path": (str, ""),
        "filename": (str, ""),
        "sha256": (str, ""),
        "extract": (bool, True),
    }], []),
    "run": {
        "command": (str, REQUIRED),
        "nodes": (list, [1]),
        "devices_per_node": (list, ["max"]),
        "ranks_per_device": (int, 1),
        "threads_per_rank": (int, 0),
        "min_devices": (int, 1),
        "max_devices": (int, 0),
        "repetitions": (int, 3),
        "time_limit": (str, "00:30:00"),   # per repetition
        "prepare": (list, []),
        "env": (TABLE, {}),
    },
    "params": (TABLE, {}),
    "metrics": {
        "primary": (str, REQUIRED),
        "higher_is_better": (bool, True),
        "unit": (str, ""),
    },
    "validate": (TABLE, {}),
}


def _type_name(t):
    return {str: "a string", int: "an integer", bool: "true/false",
            list: "a list", float: "a number"}.get(t, str(t))


def apply_schema(data, schema, where):
    """Validate ``data`` against ``schema`` and fill in defaults (in place)."""
    errors = []
    for key in data:
        if key not in schema:
            hint = difflib.get_close_matches(key, list(schema), n=1)
            errors.append("%s: unknown key '%s'%s" % (
                where, key, " (did you mean '%s'?)" % hint[0] if hint else ""))
    for key, spec in schema.items():
        sub = "%s.%s" % (where, key) if where else key
        if isinstance(spec, dict):  # sub-table
            value = data.setdefault(key, {})
            if not isinstance(value, dict):
                errors.append("%s must be a table" % sub)
                continue
            errors += apply_schema(value, spec, sub)
            continue
        typ, default = spec
        if key not in data:
            if default is REQUIRED:
                errors.append("%s is required" % sub)
            else:
                data[key] = _copy(default)
            continue
        value = data[key]
        if typ == TABLE:
            if not isinstance(value, dict):
                errors.append("%s must be a table" % sub)
        elif isinstance(typ, list):  # array of tables
            if not isinstance(value, list):
                errors.append("%s must be an array of tables ([[%s]])" % (sub, key))
                continue
            for n, item in enumerate(value):
                errors += apply_schema(item, typ[0], "%s[%d]" % (sub, n))
        elif typ is int and (isinstance(value, bool) or not isinstance(value, int)):
            errors.append("%s must be %s, got %r" % (sub, _type_name(typ), value))
        elif typ is not int and not isinstance(value, typ):
            errors.append("%s must be %s, got %r" % (sub, _type_name(typ), value))
    return errors


def _copy(value):
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list):
        return list(value)
    return value


def _choice(errors, where, value, choices):
    if value not in choices:
        errors.append("%s must be one of %s, got %r" % (where, ", ".join(choices), value))


def expand_path(value, root):
    path = Path(os.path.expandvars(os.path.expanduser(value)))
    return path if path.is_absolute() else Path(root) / path


def env_strings(table):
    """Environment tables may hold numbers/bools; the shell needs strings."""
    out = {}
    for key, value in table.items():
        if isinstance(value, bool):
            value = "1" if value else "0"
        out[key] = str(value)
    return out


# ---------------------------------------------------------------------------
# Objects
# ---------------------------------------------------------------------------
class Site:
    def __init__(self, name, path, data, root):
        self.name = name
        self.path = Path(path)
        self.data = data
        self.root = Path(root)

    @property
    def scheduler(self):
        return self.data["site"]["scheduler"]

    @property
    def node(self):
        return self.data["node"]

    @property
    def devices_per_node(self):
        """Devices visible to the application on one node.

        In "tile" mode each GPU tile (stack) is exposed as its own device
        (Level Zero FLAT hierarchy); in "gpu" mode each card is one device.
        """
        n = self.node
        return n["gpus_per_node"] * (n["tiles_per_gpu"] if n["gpu_mode"] == "tile" else 1)

    @property
    def toolchain_tag(self):
        return self.data["toolchain"]["tag"]

    @property
    def setup_lines(self):
        return list(self.data["toolchain"]["setup"])

    def path_for(self, key):
        return expand_path(self.data["paths"][key], self.root)

    def app_settings(self, app_name):
        return self.data["apps"].get(app_name, {})


class Workload:
    def __init__(self, app, name, path, data):
        self.app = app
        self.name = name
        self.path = Path(path)
        self.data = data

    @property
    def id(self):
        return "%s/%s" % (self.app.name, self.name)

    @property
    def meta(self):
        return self.data["workload"]

    @property
    def run(self):
        return self.data["run"]

    @property
    def params(self):
        return self.data["params"]

    @property
    def metrics(self):
        return self.data["metrics"]


class App:
    def __init__(self, name, directory, data):
        self.name = name
        self.dir = Path(directory)
        self.data = data
        self._hooks = None
        self._workloads = None

    @property
    def meta(self):
        return self.data["app"]

    def version_for(self, site=None, override=None):
        if override:
            return override
        if site is not None and site.app_settings(self.name).get("version"):
            return site.app_settings(self.name)["version"]
        return self.meta["default_version"]

    @property
    def hooks(self):
        if self._hooks is None:
            path = self.dir / "hooks.py"
            if not path.exists():
                raise ConfigError("%s: missing hooks.py (needs at least parse())" % self.dir)
            spec = importlib.util.spec_from_file_location("obench_hooks_" + self.name, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if not hasattr(module, "parse"):
                raise ConfigError("%s must define parse(rep_dir, ctx)" % path)
            self._hooks = module
        return self._hooks

    @property
    def workloads(self):
        if self._workloads is None:
            self._workloads = {}
            for path in sorted((self.dir / "workloads").glob("*.toml")):
                data = load_toml(path)
                errors = apply_schema(data, WORKLOAD_SCHEMA, "")
                meta, run = data.get("workload", {}), data.get("run", {})
                _choice(errors, "workload.kind", meta.get("kind"), WORKLOAD_KINDS)
                _choice(errors, "workload.scaling", meta.get("scaling"), SCALING_MODES)
                _choice(errors, "workload.size", meta.get("size"), SIZES)
                _choice(errors, "workload.status", meta.get("status"), STATUSES)
                for n, item in enumerate(data.get("inputs", [])):
                    if bool(item.get("url")) == bool(item.get("path")):
                        errors.append("inputs[%d] needs exactly one of 'url' or 'path'" % n)
                if run.get("repetitions", 1) < 1:
                    errors.append("run.repetitions must be at least 1")
                if errors:
                    raise ConfigError(_format_errors(path, errors))
                self._workloads[path.stem] = Workload(self, path.stem, path, data)
        return self._workloads

    def workload(self, name):
        try:
            return self.workloads[name]
        except KeyError:
            raise ConfigError(_unknown("workload", "%s/%s" % (self.name, name),
                                       ["%s/%s" % (self.name, w) for w in self.workloads]))


def _format_errors(path, errors):
    return "%s:\n  - %s" % (path, "\n  - ".join(errors))


def _unknown(kind, name, known):
    hint = difflib.get_close_matches(name, known, n=1)
    msg = "unknown %s '%s'" % (kind, name)
    if hint:
        msg += " (did you mean '%s'?)" % hint[0]
    if known:
        msg += "\n  available: %s" % ", ".join(sorted(known))
    return msg


class Registry:
    """Discovers apps/<name>/ and sites/<name>.toml below the repository root."""

    def __init__(self, root):
        self.root = Path(root)
        self._apps = None

    @property
    def apps(self):
        if self._apps is None:
            self._apps = {}
            for app_toml in sorted((self.root / "apps").glob("*/app.toml")):
                name = app_toml.parent.name
                data = load_toml(app_toml)
                errors = apply_schema(data, APP_SCHEMA, "")
                if bool(data["source"]["url"]) == bool(data["source"]["git"]):
                    errors.append("source needs exactly one of 'url' or 'git'")
                if errors:
                    raise ConfigError(_format_errors(app_toml, errors))
                self._apps[name] = App(name, app_toml.parent, data)
        return self._apps

    def app(self, name):
        try:
            return self.apps[name]
        except KeyError:
            raise ConfigError(_unknown("application", name, list(self.apps)))

    def workload(self, ident):
        if "/" not in ident:
            raise ConfigError("workloads are named APP/WORKLOAD, e.g. gromacs/benchMEM (got '%s')" % ident)
        app_name, name = ident.split("/", 1)
        return self.app(app_name).workload(name)

    def site_names(self):
        return sorted(p.stem for p in (self.root / "sites").glob("*.toml"))

    def site(self, name):
        if not name:
            name = os.environ.get("OBENCH_SITE", "")
        if not name:
            raise ConfigError("no site given: use --site NAME or export OBENCH_SITE=NAME\n"
                              "  available: %s" % ", ".join(self.site_names()))
        path = Path(name)
        if not path.suffix == ".toml" or not path.exists():
            path = self.root / "sites" / ("%s.toml" % name)
        if not path.exists():
            raise ConfigError(_unknown("site", name, self.site_names()))
        data = load_toml(path)
        errors = apply_schema(data, SITE_SCHEMA, "")
        _choice(errors, "site.scheduler", data["site"].get("scheduler"), ("slurm", "local"))
        _choice(errors, "node.gpu_mode", data["node"].get("gpu_mode"), ("gpu", "tile"))
        for app_name, settings in data.get("apps", {}).items():
            if not isinstance(settings, dict):
                errors.append("apps.%s must be a table" % app_name)
                continue
            errors += apply_schema(settings, SITE_APP_SCHEMA, "apps.%s" % app_name)
        if errors:
            raise ConfigError(_format_errors(path, errors))
        return Site(path.stem, path, data, self.root)
