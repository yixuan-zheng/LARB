"""Start the pilot server with a one-time diagnostic for slow imports."""

import faulthandler


def main():
    print("Importing LARB server", flush=True)
    faulthandler.dump_traceback_later(90)

    from larb_scaled import server

    print("LARB server imported; starting tokenizer, engine, and HTTP service", flush=True)
    server.main()


if __name__ == "__main__":
    main()
