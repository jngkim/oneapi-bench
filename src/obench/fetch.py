"""Downloading workload inputs and application sources.

Downloads happen on the machine where ``obench`` runs (usually a login node),
because compute nodes often have no internet access. Workload data goes to
``<data_root>/<app>/<workload>/``; a ``.obench-ready`` marker records what was
fetched so repeated calls are cheap.
"""

import hashlib
import json
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile
from pathlib import Path

from .config import ConfigError

MARKER = ".obench-ready"


def sha256sum(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url, dest, log=print):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    log("  downloading %s" % url)
    request = urllib.request.Request(url, headers={"User-Agent": "obench"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response, open(tmp, "wb") as out:
            shutil.copyfileobj(response, out, 1 << 20)
    except OSError as exc:
        if tmp.exists():
            tmp.unlink()
        raise ConfigError("download failed for %s: %s\n  If this node has no internet access, "
                          "download the file elsewhere and copy it to %s" % (url, exc, dest))
    tmp.replace(dest)
    return dest


def _is_within(base, target):
    base, target = Path(base).resolve(), Path(target).resolve()
    return target == base or base in target.parents


def extract(archive, dest):
    """Extract tar/zip archives, refusing members that escape ``dest``."""
    archive, dest = Path(archive), Path(dest)
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            for name in zf.namelist():
                if not _is_within(dest, dest / name):
                    raise ConfigError("refusing unsafe path %r in %s" % (name, archive))
            zf.extractall(dest)
        return True
    if tarfile.is_tarfile(archive):
        with tarfile.open(archive) as tf:
            for member in tf.getmembers():
                link_base = dest / Path(member.name).parent if member.issym() else dest
                if (not _is_within(dest, dest / member.name)
                        or (member.issym() or member.islnk())
                        and not _is_within(dest, link_base / member.linkname)):
                    raise ConfigError("refusing unsafe path %r in %s" % (member.name, archive))
            if hasattr(tarfile, "data_filter"):  # Python 3.12+ (and security backports)
                tf.extractall(dest, filter="data")
            else:
                tf.extractall(dest)
        return True
    return False


def _filename(item):
    return item["filename"] or item["url"].rstrip("/").rsplit("/", 1)[-1].split("?")[0]


def input_dir(site, workload):
    return site.path_for("data_root") / workload.app.name / workload.name


def is_ready(site, workload):
    return not workload.data["inputs"] or (input_dir(site, workload) / MARKER).exists()


def fetch_workload(site, workload, force=False, log=print):
    """Make the inputs of ``workload`` available; return the input directory."""
    target = input_dir(site, workload)
    marker = target / MARKER
    if not workload.data["inputs"]:
        return target
    if marker.exists() and not force:
        log("%s: inputs already present in %s" % (workload.id, target))
        return target
    target.mkdir(parents=True, exist_ok=True)
    record = []
    for item in workload.data["inputs"]:
        if item["path"]:  # file shipped inside this repository
            src = workload.app.dir / item["path"]
            if not src.exists():
                raise ConfigError("%s: bundled input %s does not exist" % (workload.path, src))
            dst = target / (item["filename"] or src.name)
            shutil.copy2(src, dst)
            record.append({"path": item["path"], "sha256": sha256sum(dst)})
            continue
        dst = target / _filename(item)
        if force or not dst.exists():
            download(item["url"], dst, log)
        actual = sha256sum(dst)
        if item["sha256"]:
            if actual != item["sha256"].lower():
                raise ConfigError("%s: checksum mismatch for %s\n  expected %s\n  got      %s\n"
                                  "  The upstream file changed or the download is corrupt."
                                  % (workload.id, dst.name, item["sha256"], actual))
        else:
            log("  WARNING: no sha256 recorded for %s. To pin this input, add\n"
                "    sha256 = \"%s\"\n  to the [[inputs]] entry in %s" % (dst.name, actual, workload.path))
        if item["extract"] and extract(dst, target):
            log("  extracted %s" % dst.name)
        record.append({"url": item["url"], "sha256": actual, "pinned": bool(item["sha256"])})
    marker.write_text(json.dumps(record, indent=2) + "\n")
    log("%s: inputs ready in %s" % (workload.id, target))
    return target


def fetch_source(app, version, site, log=print):
    """Download/clone the application source; return the source directory."""
    src = app.data["source"]
    base = site.path_for("build_root") / "src"
    dest = base / ("%s-%s" % (app.name, version))
    if (dest / MARKER).exists():
        return dest
    base.mkdir(parents=True, exist_ok=True)
    if src["git"]:
        ref = src["ref"].format(version=version)
        if dest.exists():
            shutil.rmtree(dest)
        log("  cloning %s (%s)" % (src["git"], ref))
        result = subprocess.run(["git", "clone", "--depth", "1", "--branch", ref,
                                 "--recurse-submodules", "--shallow-submodules", src["git"], str(dest)])
        if result.returncode != 0:
            raise ConfigError("git clone of %s at '%s' failed" % (src["git"], ref))
    else:
        url = src["url"].format(version=version)
        archive = download(url, base / url.rsplit("/", 1)[-1], log)
        unpack = base / (".unpack-%s-%s" % (app.name, version))
        shutil.rmtree(unpack, ignore_errors=True)
        if not extract(archive, unpack):
            raise ConfigError("%s is not a tar or zip archive" % archive)
        entries = list(unpack.iterdir())
        top = entries[0] if len(entries) == 1 and entries[0].is_dir() else unpack
        if dest.exists():
            shutil.rmtree(dest)
        top.replace(dest)
        shutil.rmtree(unpack, ignore_errors=True)
    (dest / MARKER).write_text(json.dumps({"version": version}) + "\n")
    return dest
