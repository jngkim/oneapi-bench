"""Planning experiments and generating SLURM jobs.

An *experiment* is one workload run on one site over a set of node and
device counts. Each (nodes, devices_per_node) pair is a *case* and becomes
one job; the job repeats the measurement ``repetitions`` times so all
repetitions see the same nodes. Layout::

    results/<experiment-id>/
        experiment.json          everything needed to reproduce and analyse
        gpu_bind.sh              copy of the device binding wrapper
        n1-d4/job.sh             one SLURM job per case
        n1-d4/rep1/stdout.log    application output and status.json
"""

import datetime
import json
import shutil
import subprocess
from pathlib import Path

from . import __version__, build, fetch, slurm, template
from .config import ConfigError, env_strings

BIND_SCRIPT = Path(__file__).resolve().parent / "gpu_bind.sh"


class Case:
    def __init__(self, nodes, devices_per_node, site, workload):
        run = workload.run
        self.nodes = nodes
        self.devices_per_node = devices_per_node
        self.total_devices = nodes * devices_per_node
        self.ranks_per_node = devices_per_node * run["ranks_per_device"]
        self.ranks = nodes * self.ranks_per_node
        cores = site.node["cores_per_node"]
        self.cpus_per_rank = max(1, cores // self.ranks_per_node)
        self.threads_per_rank = run["threads_per_rank"] or self.cpus_per_rank
        self.name = "n%d-d%d" % (nodes, devices_per_node)

    def variables(self):
        return {k: getattr(self, k) for k in (
            "nodes", "devices_per_node", "total_devices", "ranks", "ranks_per_node",
            "cpus_per_rank", "threads_per_rank")}


def _int_list(values, site, what):
    out = []
    for value in values:
        if value == "max":
            value = site.devices_per_node
        try:
            out.append(int(value))
        except (TypeError, ValueError):
            raise ConfigError("%s must be integers or 'max', got %r" % (what, value))
    return out


def plan_cases(site, workload, nodes=None, devices=None, log=print):
    run = workload.run
    node_counts = _int_list(nodes or run["nodes"], site, "nodes")
    device_counts = _int_list(devices or run["devices_per_node"], site, "devices per node")
    cases, skipped = [], []
    for n in node_counts:
        for d in device_counts:
            total = n * d
            if d < 1 or n < 1:
                skipped.append("n%d-d%d (counts must be positive)" % (n, d))
            elif d > site.devices_per_node:
                skipped.append("n%d-d%d (site has %d devices per node)" % (n, d, site.devices_per_node))
            elif total < run["min_devices"]:
                skipped.append("n%d-d%d (workload needs >= %d devices)" % (n, d, run["min_devices"]))
            elif run["max_devices"] and total > run["max_devices"]:
                skipped.append("n%d-d%d (workload allows <= %d devices)" % (n, d, run["max_devices"]))
            else:
                cases.append(Case(n, d, site, workload))
    for s in skipped:
        log("  skipping %s" % s)
    if not cases:
        raise ConfigError("%s: no valid node/device combinations to run" % workload.id)
    return cases


def base_variables(site, workload, version, info):
    app = workload.app
    prefix = Path(info["prefix"]) if info else build.prefix_for(site, app, version)
    exe = app.data["run"]["executable"]
    return {
        "app": app.name, "workload": workload.name, "version": version,
        "site": site.name, "toolchain": site.toolchain_tag,
        "prefix": str(prefix),
        "src_dir": info["src_dir"] if info else str(
            site.path_for("build_root") / "src" / ("%s-%s" % (app.name, version))),
        "exe": str(prefix / exe) if exe else "",
        "app_dir": str(app.dir),
        "input_dir": str(fetch.input_dir(site, workload)),
        "gpus_per_node": site.node["gpus_per_node"],
        "tiles_per_gpu": site.node["tiles_per_gpu"],
        "gpu_mode": site.node["gpu_mode"],
        "ranks_per_device": workload.run["ranks_per_device"],
        "mpi_gpu_aware": int(site.data["mpi"]["gpu_aware"]),
    }


def case_context(site, workload, case, base, param_overrides):
    """All template variables for one case, after parameters and hooks."""
    variables = dict(base)
    variables.update(case.variables())
    params = dict(workload.params)
    for key, value in param_overrides.items():
        if key not in params:
            raise ConfigError("--set %s: workload %s has no parameter '%s'\n  parameters: %s"
                              % (key, workload.id, key, ", ".join(params) or "(none)"))
        params[key] = value
    rendered = template.render_params(params, variables, "%s [params]" % workload.id)
    variables.update(rendered)
    hook = getattr(workload.app.hooks, "context", None)
    if hook:
        extra = hook(dict(variables)) or {}
        variables.update(extra)
        rendered.update(extra)  # recorded with the case so reports can use them
    return variables, rendered


def render_case(site, workload, case, base, param_overrides):
    """Return (params, command, prepare commands, launcher) for one case."""
    variables, rendered = case_context(site, workload, case, base, param_overrides)
    where = "%s [run]" % workload.id
    command = template.substitute(workload.run["command"], variables, where + " command")
    prep = [template.substitute(p, variables, where + " prepare") for p in workload.run["prepare"]]
    launch = template.substitute(slurm.launcher_template(site), variables, "site mpi.launcher")
    return rendered, command, prep, launch


def run_env(site, workload, overrides):
    env = env_strings(site.data["env"])
    env.update(env_strings(site.data["mpi"]["env"]))
    env.update(env_strings(workload.app.data["run"]["env"]))
    env.update(env_strings(site.app_settings(workload.app.name).get("run_env", {})))
    env.update(env_strings(workload.run["env"]))
    env.update(overrides)
    return env


def _git_revision(root):
    try:
        out = subprocess.run(["git", "-C", str(root), "describe", "--always", "--dirty"],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def prepare(registry, site, workload, nodes=None, devices=None, reps=None, params=None,
            env=None, version=None, dry_run=False, label=None, log=print):
    app = workload.app
    version = app.version_for(site, version)
    info = build.build_info(site, app, version)
    if info is None:
        msg = ("%s %s is not built for site %s (toolchain %s).\n  Build it first: obench build %s --site %s"
               % (app.name, version, site.name, site.toolchain_tag, app.name, site.name))
        if not dry_run:
            raise ConfigError(msg)
        log("  note: " + msg.replace("\n", "\n  "))
    if not dry_run:
        fetch.fetch_workload(site, workload, log=log)
    elif not fetch.is_ready(site, workload):
        log("  note: inputs not downloaded yet (obench fetch %s)" % workload.id)

    cases = plan_cases(site, workload, nodes, devices, log)
    reps = reps or workload.run["repetitions"]
    base = base_variables(site, workload, version, info)
    environment = run_env(site, workload, env or {})

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    exp_id = "%s_%s_%s_%s" % (stamp, app.name, workload.name, site.name)
    if label:
        exp_id += "_" + label
    exp_dir = site.path_for("results_root") / exp_id
    suffix = 1
    while exp_dir.exists():  # same workload started twice within one second
        suffix += 1
        exp_dir = site.path_for("results_root") / ("%s-%d" % (exp_id, suffix))
    exp_id = exp_dir.name
    exp_dir.mkdir(parents=True)
    bind = exp_dir / "gpu_bind.sh"
    shutil.copy2(BIND_SCRIPT, bind)
    bind.chmod(0o755)

    experiment = {
        "id": exp_id,
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "obench": {"version": __version__, "revision": _git_revision(registry.root)},
        "site": {"name": site.name, "config": site.data, "devices_per_node": site.devices_per_node},
        "app": {"name": app.name, "version": version, "config": app.data, "build": info},
        "workload": {"name": workload.name, "id": workload.id, "config": workload.data},
        "overrides": {"params": params or {}, "env": env or {}},
        "repetitions": reps,
        "environment": environment,
        "cases": [],
    }
    for case in cases:
        rendered, command, prep, launch = render_case(site, workload, case, base, params or {})
        case_dir = exp_dir / case.name
        case_dir.mkdir()
        script = case_dir / "job.sh"
        script.write_text(render_job(site, workload, case, case_dir, bind, environment,
                                     launch, command, prep, reps))
        script.chmod(0o755)
        (case_dir / "command.txt").write_text(" ".join(filter(None, [launch, str(bind), command])) + "\n")
        record = case.variables()
        record.update(name=case.name, params=rendered, command=command, prepare=prep,
                      launcher=launch, job_id=None)
        experiment["cases"].append(record)
    write_experiment(exp_dir, experiment)
    return exp_dir, experiment


def write_experiment(exp_dir, experiment):
    (Path(exp_dir) / "experiment.json").write_text(json.dumps(experiment, indent=2, default=str) + "\n")


def load_experiment(exp_dir):
    path = Path(exp_dir) / "experiment.json"
    if not path.exists():
        raise ConfigError("%s is not an experiment directory (no experiment.json)" % exp_dir)
    return json.loads(path.read_text())


def submit_experiment(site, exp_dir, experiment, log=print):
    for record in experiment["cases"]:
        record["job_id"] = slurm.submit(Path(exp_dir) / record["name"] / "job.sh", site, log)
        write_experiment(exp_dir, experiment)


def _seconds(text):
    """SLURM time 'MM', 'MM:SS', 'HH:MM:SS' or 'D-HH:MM:SS' -> seconds."""
    days, _, rest = text.rpartition("-")
    try:
        parts = [int(p) for p in rest.split(":")]
        if len(parts) == 1:
            parts = [0, parts[0], 0]
        elif len(parts) == 2:
            parts = [0] + parts
        hours, minutes, seconds = parts
        return ((int(days or 0) * 24 + hours) * 60 + minutes) * 60 + seconds
    except ValueError:
        raise ConfigError("invalid time limit '%s' (use HH:MM:SS)" % text)


def job_time_limit(per_repetition, reps):
    """Whole-job limit: every repetition gets the workload's time_limit, plus 10 minutes."""
    total = _seconds(per_repetition) * reps + 600
    return "%d:%02d:%02d" % (total // 3600, total % 3600 // 60, total % 60)


def render_job(site, workload, case, case_dir, bind, environment, launch, command, prepare, reps):
    node = site.node
    obench_env = {
        "OBENCH_GPU_MODE": node["gpu_mode"],
        "OBENCH_TILES_PER_GPU": str(node["tiles_per_gpu"]),
        "OBENCH_DEVICES_PER_NODE": str(case.devices_per_node),
        "OBENCH_RANKS_PER_DEVICE": str(workload.run["ranks_per_device"]),
        "OMP_NUM_THREADS": str(case.threads_per_rank),
    }
    if prepare:
        prep = "( set -e\n%s\n    ) > prepare.log 2>&1 || { RC=$?; STAGE=prepare; }" % "\n".join(
            "      " + p for p in prepare)
    else:
        prep = "# (no prepare commands)"
    header = slurm.sbatch_header(site, "obench-%s-%s-%s" % (workload.app.name, workload.name, case.name),
                                 case.nodes, job_time_limit(workload.run["time_limit"], reps),
                                 case_dir / "slurm-%j.out")
    return JOB_TEMPLATE.format(
        header=header, workload=workload.id, site=site.name, case=case.name,
        case_dir=slurm.quote(case_dir), bind=slurm.quote(bind),
        setup="\n".join(site.setup_lines) or "# (no toolchain setup lines in the site file)",
        env=slurm.export_lines(environment) or "# (no extra environment)",
        obench_env=slurm.export_lines(obench_env),
        helpers=slurm.SHELL_HELPERS, reps=reps, prepare=prep,
        launch=(launch + " ") if launch else "", command=command,
    )


JOB_TEMPLATE = """#!/bin/bash
{header}
# Generated by obench: {workload} case {case} on site {site}.
# To re-run this case alone: sbatch job.sh  (or: bash job.sh inside an allocation)
{helpers}
CASE_DIR={case_dir}
OBENCH_BIND={bind}
cd "$CASE_DIR"

# --- toolchain (site file: [toolchain] setup) ---
{setup}
set -u

# --- environment (site, app and workload [env] tables) ---
{env}

# --- device binding and threading ---
{obench_env}

# --- provenance: where and with what this job ran ---
{{ echo "start: $(obench_date)"; echo "job: ${{SLURM_JOB_ID:-none}}"; }} > job-info.txt
(scontrol show hostnames "${{SLURM_JOB_NODELIST:-}}" 2>/dev/null || hostname) > nodes.txt
env | sort > env.txt
(sycl-ls 2>&1 || echo "sycl-ls not available") > sycl-ls.txt

for REP in $(seq 1 {reps}); do
  REP_DIR="$CASE_DIR/rep$REP"
  mkdir -p "$REP_DIR" && cd "$REP_DIR"
  RC=0; STAGE=run
  START=$(obench_now)
  {prepare}
  if [ "$STAGE" = run ]; then
    {launch}"$OBENCH_BIND" {command} > stdout.log 2> stderr.log
    RC=$?
  fi
  END=$(obench_now)
  printf '{{"rep": %d, "stage": "%s", "exit_code": %d, "start": %s, "end": %s}}\\n' \\
    "$REP" "$STAGE" "$RC" "$START" "$END" > status.json
  echo "obench: rep $REP finished with exit code $RC ($STAGE)"
  cd "$CASE_DIR"
done
echo "end: $(obench_date)" >> job-info.txt
"""
