"""Output parsing and validation for @APP@. See obench/hookutil.py for helpers."""

from obench.hookutil import NUMBER, check, last_match, read, threshold


def parse(rep_dir, ctx):
    """Return metrics for one repetition; include the workload's primary metric."""
    text = read(rep_dir, "stdout.log")
    return {
        # TODO: adapt the pattern to the application's output.
        "time_s": last_match(r"Total time:\s*(%s)" % NUMBER, text),
    }


def checks(metrics, rep_dir, ctx):
    """Return (name, ok, detail) tuples. Every check must pass for a valid result."""
    text = read(rep_dir, "stdout.log")
    return [
        # TODO: prove that the GPU was used and the answer is correct.
        check("gpu-used", "GPU" in text, "GPU mentioned in output", "no evidence of GPU execution"),
    ]
