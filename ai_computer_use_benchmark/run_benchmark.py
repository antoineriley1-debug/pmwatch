"""Launch the AI Computer-Use Intelligence Benchmark dashboard (Windows)."""
import sys


def main() -> None:
    if sys.platform != "win32":
        sys.exit("This prototype targets Windows. The reasoning layer is platform-independent; "
                 "add a controller under benchmark/controller/ for other platforms.")
    from benchmark.controller.windows import WindowsController, enable_dpi_awareness
    from benchmark.ui.dashboard import Dashboard

    enable_dpi_awareness()
    Dashboard(controller_factory=WindowsController).run()


if __name__ == "__main__":
    main()
