"""GROMACS: mdrun options per case, md.log parsing and validation."""

import re

from obench.hookutil import NUMBER, check, last_match, read


def context(v):
    """Derive mdrun flags that depend on the rank count."""
    npme = str(v.get("npme", "auto"))
    if npme == "auto":
        # One dedicated PME rank when PME runs on the GPU with several ranks; more PME
        # ranks need GMX_GPU_PME_DECOMPOSITION=1 and a heFFTe-enabled build.
        npme_flag = "-npme 1" if v["ranks"] > 1 and v.get("pme") == "gpu" else ""
    else:
        npme_flag = "-npme %s" % npme
    return {
        "npme_flag": npme_flag,
        "ntomp": min(v["threads_per_rank"], int(v.get("max_threads", 16))),
    }


def parse(rep_dir, ctx):
    log = read(rep_dir, "md.log")
    m = re.search(r"^\s*Performance:\s+(%s)\s+(%s)" % (NUMBER, NUMBER), log, re.MULTILINE)
    return {
        "ns_per_day": float(m.group(1)) if m else None,
        "hours_per_ns": float(m.group(2)) if m else None,
        # "Time:  <core s>  <wall s>  <%>" (timing covers the second half with -resethway)
        "mdrun_wall_s": last_match(r"^\s*Time:\s+%s\s+(%s)" % (NUMBER, NUMBER), log),
        "gpus_selected": last_match(r"(\d+) GPUs? selected for this run", log, cast=int),
    }


def checks(metrics, rep_dir, ctx):
    log = read(rep_dir, "md.log")
    gpu_tasks = re.search(r"Mapping of GPU IDs to the \d+ GPU tasks? in the \d+ ranks?", log)
    result = [
        check("finished", "Finished mdrun" in log, "mdrun finished",
              "md.log has no 'Finished mdrun' (crash or time limit?)"),
        check("gpu-tasks", gpu_tasks, "GPU tasks assigned",
              "md.log shows no GPU task assignment: the run did not use the GPU"),
    ]
    if ctx.get("pme") == "gpu":
        result.append(check("pme-gpu", "PME tasks will do all aspects on the GPU" in log
                            or "PME tasks will do only spread and gather on the GPU" in log,
                            "PME on GPU", "PME was requested on the GPU but md.log does not confirm it"))
    return result
