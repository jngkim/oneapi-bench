"""Job-script pieces shared by builds and runs, plus submission/status.

``site.scheduler = "slurm"`` submits with ``sbatch``. ``"local"`` runs the
same script directly with bash, which is useful inside an interactive
allocation (``salloc``) or for testing on a workstation.
"""

import shlex
import shutil
import subprocess

from .config import ConfigError

# MPI launch presets. A site may instead give a full template string.
LAUNCHERS = {
    "srun": ("srun --nodes={nodes} --ntasks={ranks} --ntasks-per-node={ranks_per_node} "
             "--cpus-per-task={cpus_per_rank} --cpu-bind=cores"),
    # Hydra-based mpiexec (Intel MPI, MPICH) inside a SLURM allocation.
    "mpiexec": "mpiexec -n {ranks} -ppn {ranks_per_node}",
    # Single process, no MPI launcher.
    "none": "",
}

# Portable timestamp helpers used inside generated scripts.
SHELL_HELPERS = r'''obench_now() { if [ -n "${EPOCHREALTIME:-}" ]; then echo "${EPOCHREALTIME/,/.}"; else date +%s; fi; }
obench_date() { date -u +%Y-%m-%dT%H:%M:%SZ; }'''


def launcher_template(site):
    value = site.data["mpi"]["launcher"]
    return LAUNCHERS.get(value, value)


def sbatch_header(site, job_name, nodes, time_limit, output):
    if site.scheduler != "slurm":
        return ""
    slurm = site.data["slurm"]
    lines = [
        "#SBATCH --job-name=%s" % job_name[:64],
        "#SBATCH --nodes=%d" % nodes,
        "#SBATCH --time=%s" % time_limit,
        "#SBATCH --output=%s" % output,
    ]
    for key in ("partition", "account", "qos", "constraint"):
        if slurm[key]:
            lines.append("#SBATCH --%s=%s" % (key, slurm[key]))
    lines += ["#SBATCH %s" % d for d in slurm["directives"]]
    return "\n".join(lines)


def export_lines(env):
    """``export`` statements. Values may use shell expansion such as $HOME."""
    out = []
    for key, value in env.items():
        escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`")
        out.append('export %s="%s"' % (key, escaped))
    return "\n".join(out)


def quote(path):
    return shlex.quote(str(path))


def submit(script, site, log=print):
    """Submit (slurm) or execute (local) ``script``; return a job id or exit code."""
    if site.scheduler == "local":
        log("  running %s locally" % script)
        return "local:%d" % subprocess.run(["bash", str(script)], cwd=str(script.parent)).returncode
    if not shutil.which("sbatch"):
        raise ConfigError("sbatch not found. Run on a SLURM login node, use --dry-run, "
                          "or set scheduler = \"local\" in the site file.")
    result = subprocess.run(["sbatch", "--parsable", str(script)], cwd=str(script.parent),
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise ConfigError("sbatch failed for %s:\n%s" % (script, result.stderr.strip()))
    job_id = result.stdout.strip().split(";")[0]
    log("  submitted %s as job %s" % (script, job_id))
    return job_id


def job_states(job_ids):
    """Map SLURM job id -> state (PENDING, RUNNING, COMPLETED, ...)."""
    ids = [j for j in job_ids if j and not j.startswith("local")]
    if not ids or not shutil.which("sacct"):
        return {}
    result = subprocess.run(["sacct", "-n", "-P", "-X", "--format=JobID,State", "-j", ",".join(ids)],
                            capture_output=True, text=True)
    states = {}
    for line in result.stdout.splitlines():
        parts = line.split("|")
        if len(parts) >= 2:
            states[parts[0]] = parts[1].split()[0]
    return states
