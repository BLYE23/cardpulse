"""Schedule the shared CardPulse pipeline in Airflow."""

from datetime import timedelta
import os
from pathlib import Path
import sys

from airflow import DAG
from airflow.exceptions import AirflowException
from airflow.operators.python import PythonOperator
import pendulum

CARDPULSE_HOME = Path(os.environ.get("CARDPULSE_HOME", "/opt/cardpulse"))
sys.path.insert(0, str(CARDPULSE_HOME / "pipeline"))

import runlog
import steps
from run_all import run_step


def start_run(**context):
    runlog.start_run("airflow", run_id=context["run_id"])


def execute_step(step, **context):
    exit_code, stderr_tail = run_step(step, context["run_id"])
    if exit_code:
        raise AirflowException(f"{step.name} exited {exit_code}: {stderr_tail}")


def finish_run(**context):
    tasks = context["dag_run"].get_task_instances()
    failed = any(task.state in {"failed", "upstream_failed"} for task in tasks)
    runlog.finish_run(context["run_id"], "failed" if failed else "success")
    # This all_done leaf must fail too so Airflow reports the DAG run as failed.
    if failed:
        raise AirflowException("A CardPulse task failed")


with DAG(
    dag_id="cardpulse_daily",
    schedule="30 21 * * *",
    start_date=pendulum.datetime(2026, 11, 20, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=10), "owner": "cardpulse"},
    tags=["cardpulse"],
) as dag:
    previous = PythonOperator(task_id="start_run", python_callable=start_run)
    for step in steps.STEPS:
        task = PythonOperator(
            task_id=step.name, python_callable=execute_step, op_kwargs={"step": step}
        )
        previous >> task
        previous = task
    previous >> PythonOperator(
        task_id="finish_run", python_callable=finish_run, trigger_rule="all_done"
    )
