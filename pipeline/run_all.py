"""Run the CardPulse pipeline in order without Airflow."""

import os
import sqlite3
import subprocess
import sys
import time

import config
import runlog
from steps import STEPS, Step


def run_step(step: Step, run_id: str) -> tuple[int, str]:
    """Run and log one step, returning its exit code and stderr tail."""
    runlog.start_step(run_id, step.name)
    stderr_tail = ""
    try:
        if step.skip_if is not None and step.skip_if():
            runlog.finish_step(run_id, step.name, "skipped")
            return 0, ""

        env = {**os.environ, "CARDPULSE_RUN_ID": run_id}
        # Inherit stdout and tee stderr so the console and the run log both get errors.
        with subprocess.Popen(
            [sys.executable, step.script, *step.args],
            cwd=config.ROOT,
            env=env,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
        ) as process:
            try:
                for line in process.stderr:
                    print(line, end="", file=sys.stderr, flush=True)
                    stderr_tail = (stderr_tail + line)[-500:]
                exit_code = process.wait()
            except BaseException:
                process.kill()
                raise
    except OSError as exc:
        print(f"{step.name}: {exc}", file=sys.stderr)
        exit_code, stderr_tail = 1, str(exc)[-500:]
    except BaseException as exc:
        runlog.finish_step(run_id, step.name, "failed", stderr_tail or type(exc).__name__)
        raise

    runlog.finish_step(
        run_id, step.name, "failed" if exit_code else "success", stderr_tail if exit_code else None
    )
    return exit_code, stderr_tail


def main() -> int:
    try:
        run_id = runlog.start_run("run_all")
        print(f"Pipeline run {run_id}", flush=True)
        status = "failed"
        durations = []
        try:
            for step in STEPS:
                started = time.monotonic()
                exit_code, _ = run_step(step, run_id)
                if exit_code:
                    return exit_code if exit_code > 0 else 128 - exit_code
                durations.append((step.name, time.monotonic() - started))
            status = "success"
        finally:
            runlog.finish_run(run_id, status)
    except (OSError, sqlite3.Error) as exc:
        print(f"Pipeline error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130

    print(f"{'Step':<20} {'Seconds':>9}")
    for name, seconds in durations:
        print(f"{name:<20} {seconds:9.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
