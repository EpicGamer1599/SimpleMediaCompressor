import argparse
import os
import sys


def main():
    parser = argparse.ArgumentParser(description="SimpleMediaCompressure desktop application")
    parser.add_argument("files", nargs="*", help="Media files to stage on launch")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--request", help=argparse.SUPPRESS)
    parser.add_argument("--events", help=argparse.SUPPRESS)
    parser.add_argument("--picker", nargs=2, help=argparse.SUPPRESS)
    parser.add_argument(
        "--screenshot",
        metavar="PATH",
        help="Save a UI screenshot and exit (for visual QA)",
    )
    parser.add_argument(
        "--page",
        default="Dashboard",
        choices=["Dashboard", "Compress", "Queue", "History", "Settings", "About"],
    )
    parser.add_argument("--size", default="1280x860", help="Window dimensions, e.g. 1280x860")
    args = parser.parse_args()
    if args.picker:
        import json
        from pathlib import Path

        from .dialogs import pick

        request, response = (Path(path) for path in args.picker)
        try:
            payload = json.loads(request.read_text(encoding="utf-8"))
            result = {"value": pick(**payload)}
        except Exception as error:
            result = {"error": str(error)}
        response.write_text(json.dumps(result), encoding="utf-8")
        return
    if args.worker:
        from .worker import main as worker_main

        worker_main(args.request, args.events)
        return
    os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
    from .app import App
    from .storage import data_directory, setup_logging

    try:
        directory = data_directory()
        setup_logging(directory)
        App(directory, args).run()
    except Exception as error:
        import logging

        logging.exception("Application startup failed")
        message = f"SimpleMediaCompressure could not start:\n{error}\n\nCheck your application data directory permissions and installed dependencies."
        if sys.stderr:
            print(message, file=sys.stderr)
        try:
            if os.name == "nt":
                import ctypes

                ctypes.windll.user32.MessageBoxW(None, message, "SimpleMediaCompressure", 0x10)
            else:
                import tkinter as tk
                from tkinter import messagebox

                root = tk.Tk()
                root.withdraw()
                messagebox.showerror("SimpleMediaCompressure", message)
                root.destroy()
        except Exception:
            pass
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
