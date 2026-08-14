import argparse
import sys
from datetime import datetime

from .models import Task
from . import storage
from .scheduler import run_scheduler, run_once, execute_task


def cmd_run(args):
    task = Task.create(prompt=args.prompt, time="00:00", period="daily")
    execute_task(task)


def cmd_add(args):
    task = Task.create(prompt=args.prompt, time=args.time, period=args.period)
    storage.add_task(task)
    print(f"Task created: id={task.id}, time={task.time}, period={task.period}, prompt={task.prompt}")


def cmd_list(args):
    tasks = storage.load_tasks()
    if not tasks:
        print("No tasks configured.")
        return

    print(f"{'ID':<14} {'Time':<8} {'Period':<14} {'Enabled':<9} {'Last Run':<22} {'Result':<30} Prompt")
    print("-" * 120)
    for t in tasks:
        last = t.last_run or "-"
        enabled = "yes" if t.enabled else "no"
        prompt_preview = t.prompt[:50] + "..." if len(t.prompt) > 50 else t.prompt
        result_preview = (t.last_result or "-")[:30]
        print(f"{t.id:<14} {t.time:<8} {t.period:<14} {enabled:<9} {last:<22} {result_preview:<30} {prompt_preview}")


def cmd_delete(args):
    if storage.delete_task(args.id):
        print(f"Task {args.id} deleted.")
    else:
        print(f"Task {args.id} not found.", file=sys.stderr)
        sys.exit(1)


def cmd_enable(args):
    task = storage.find_task(args.id)
    if not task:
        print(f"Task {args.id} not found.", file=sys.stderr)
        sys.exit(1)
    task.enabled = True
    storage.update_task(task)
    print(f"Task {args.id} enabled.")


def cmd_disable(args):
    task = storage.find_task(args.id)
    if not task:
        print(f"Task {args.id} not found.", file=sys.stderr)
        sys.exit(1)
    task.enabled = False
    storage.update_task(task)
    print(f"Task {args.id} disabled.")


def cmd_gui(args):
    from .gui import main as gui_main
    gui_main()


def cmd_start(args):
    if args.once:
        run_once()
    else:
        run_scheduler(daemon=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="clockai", description="AI scheduled task manager")

    sub = parser.add_subparsers(dest="command", help="Available commands")

    p_add = sub.add_parser("add", help="Create a new scheduled task")
    p_add.add_argument("--time", "-t", required=True, help="Time in HH:MM format (24h)")
    p_add.add_argument("--period", "-p", required=True,
                       help="Schedule period: daily, hourly, or interval:N (N in minutes)")
    p_add.add_argument("--prompt", "-m", required=True, help="Prompt text to send to aim")
    p_add.set_defaults(func=cmd_add)

    p_gui = sub.add_parser("gui", help="Launch GTK3 graphical interface")
    p_gui.set_defaults(func=cmd_gui)

    p_list = sub.add_parser("list", help="List all tasks")
    p_list.set_defaults(func=cmd_list)

    p_run = sub.add_parser("run", help="Run a prompt immediately with aim")
    p_run.add_argument("prompt", help="Prompt text to send to aim")
    p_run.set_defaults(func=cmd_run)

    p_del = sub.add_parser("delete", help="Delete a task")
    p_del.add_argument("id", help="Task ID")
    p_del.set_defaults(func=cmd_delete)

    p_enable = sub.add_parser("enable", help="Enable a task")
    p_enable.add_argument("id", help="Task ID")
    p_enable.set_defaults(func=cmd_enable)

    p_disable = sub.add_parser("disable", help="Disable a task")
    p_disable.add_argument("id", help="Task ID")
    p_disable.set_defaults(func=cmd_disable)

    p_start = sub.add_parser("start", help="Start the scheduler")
    p_start.add_argument("--once", action="store_true", help="Run due tasks once and exit")
    p_start.set_defaults(func=cmd_start)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
