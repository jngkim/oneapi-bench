import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from obench.config import Registry  # noqa: E402

TOY_APP = """
[app]
title = "Toy"
default_version = "1.0"
[source]
url = "https://example.invalid/toy-{version}.tar.gz"
[build]
check = []
[run]
executable = "bin/toy"
[run.env]
TOY_ENV = "from-app"
"""

TOY_WORKLOAD = """
[workload]
title = "Toy throughput"
kind = "custom"
scaling = "{scaling}"
[run]
nodes = [1]
devices_per_node = [1, 2]
repetitions = 2
prepare = ["echo prepared > prepared.txt"]
command = "{{exe}} {{size}} {{total_devices}}"
[params]
base = 10
size = "=2 * {{base}} * {{total_devices}}"
[metrics]
primary = "rate"
higher_is_better = true
unit = "items/s"
[validate]
min_rate = 1
"""

TOY_HOOKS = '''
from obench.hookutil import NUMBER, check, last_match, read, threshold

def context(v):
    return {"flag": "-x" if v["ranks"] > 1 else ""}

def parse(rep_dir, ctx):
    text = read(rep_dir, "stdout.log")
    return {"rate": last_match(r"rate=(%s)" % NUMBER, text)}

def checks(metrics, rep_dir, ctx):
    rate = metrics.get("rate") or 0
    return [check("rate", rate >= threshold(ctx, "min_rate", 0), "ok", "rate too low")]
'''

# A fake executable: prints a rate proportional to the device count.
TOY_EXE = """#!/bin/bash
echo "toy size=$1 devices=$2 mask=${ZE_AFFINITY_MASK:-unset} env=${TOY_ENV:-unset}"
echo "rate=$(( 100 * $2 ))"
"""

SITE = """
[site]
scheduler = "local"
[node]
gpus_per_node = 2
tiles_per_gpu = 2
gpu_mode = "{mode}"
cores_per_node = 8
[toolchain]
tag = "test"
[mpi]
launcher = "none"
[paths]
install_root = "{tmp}/install"
build_root = "{tmp}/build"
data_root = "{tmp}/data"
results_root = "{tmp}/results"
"""


@pytest.fixture
def toy_repo(tmp_path):
    """A repository root with the real templates, a toy app and a test site."""
    root = tmp_path / "repo"
    (root / "apps" / "toy" / "workloads").mkdir(parents=True)
    (root / "sites").mkdir()
    shutil.copytree(REPO / "templates", root / "templates")
    app = root / "apps" / "toy"
    (app / "app.toml").write_text(TOY_APP)
    (app / "build.sh").write_text("#!/bin/bash\n")
    (app / "hooks.py").write_text(TOY_HOOKS)
    (app / "workloads" / "strong.toml").write_text(TOY_WORKLOAD.format(scaling="strong"))
    (root / "sites" / "test.toml").write_text(SITE.format(tmp=tmp_path, mode="gpu"))
    (root / "sites" / "tiles.toml").write_text(SITE.format(tmp=tmp_path, mode="tile"))
    return root


@pytest.fixture
def toy_built(toy_repo, tmp_path):
    """Pretend the toy app was built: install the fake executable and a manifest."""
    reg = Registry(toy_repo)
    site = reg.site("test")
    from obench import build
    prefix = build.prefix_for(site, reg.app("toy"), "1.0")
    (prefix / "bin").mkdir(parents=True)
    exe = prefix / "bin" / "toy"
    exe.write_text(TOY_EXE)
    exe.chmod(0o755)
    (prefix / build.MANIFEST).write_text(
        '{"prefix": "%s", "src_dir": "%s/src"}' % (prefix, tmp_path))
    return reg


@pytest.fixture
def registry():
    return Registry(REPO)
