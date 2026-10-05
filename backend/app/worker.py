import argparse
import time
from .config import Settings
from .db import make_engine, session_factory
from .agent import work_once
from .tracing import start_uploader


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    factory = session_factory(make_engine(settings.database_url))
    start_uploader(settings)
    if args.once:
        work_once(factory, settings)
        return
    print("SPD worker ready; database-backed queue; Ctrl+C to stop", flush=True)
    try:
        while True:
            if not work_once(factory, settings):
                time.sleep(.5)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
