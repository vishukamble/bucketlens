import os
import sys
import socket
import webbrowser
import threading
import time


def find_free_port(start=8080, max_attempts=10):
    for port in range(start, start + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free port found in range 8080-8089")


def main():
    # Import app — handle both installed and dev modes
    try:
        from bucketlens.app import app
    except ImportError:
        from app import app

    explicit_port = os.environ.get("BucketLens_PORT")
    if explicit_port is not None:
        # User explicitly set a port — try it and fail clearly if unavailable
        port = int(explicit_port)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                raise SystemExit(f"Error: port {port} is already in use. Unset BucketLens_PORT to auto-select.")
    else:
        requested_port = 8080
        port = find_free_port(requested_port)
        if port != requested_port:
            print(f"\n⚠️  Port {requested_port} is already in use.")
            if sys.platform == "win32":
                print(f"   To see what's using it: netstat -ano | findstr :{requested_port}")
            else:
                print(f"   To see what's using it: lsof -i :{requested_port}")
            print(f"   Starting on port {port} instead.\n")

    url = f"http://127.0.0.1:{port}"

    def open_browser():
        time.sleep(1.2)
        webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()
    print(f"\n☁️  BucketLens running at {url}\n")
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
