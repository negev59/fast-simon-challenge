"""Run the HTTP-level tests against the deployed app.

Usage:  python smoke_test.py https://db-dot-negev-fast-simon.ew.r.appspot.com

Warning: it calls /end, which wipes the default database of that app.
"""
import ssl
import sys
import urllib.error
import urllib.request

from tests import test_app

try:  # python.org builds on macOS ship without CA certificates
    import certifi
    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CONTEXT = None

# Tests that don't need to look inside the in-memory store.
LIVE_TESTS = [
    test_app.test_sequence_1,
    test_app.test_sequence_2,
    test_app.test_sequence_3,
    test_app.test_undo_and_redo_on_empty_history,
    test_app.test_redo_is_dropped_after_a_new_command,
    test_app.test_reads_do_not_drop_redo,
    test_app.test_counts_follow_undo_and_redo,
    test_app.test_setting_the_same_value_twice,
    test_app.test_unset_of_a_missing_variable,
    test_app.test_unknown_command,
    test_app.test_wrong_method,
    test_app.test_invalid_input_does_not_change_data,
    test_app.test_databases_are_isolated,
]


class LiveResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def get_data(self, as_text=False):
        return self._body


class LiveClient:
    """Mimics the parts of Flask's test client that the tests use."""

    def __init__(self, base_url):
        self._base_url = base_url.rstrip("/")

    def get(self, path):
        return self._send(path, "GET")

    def post(self, path):
        return self._send(path, "POST")

    def _send(self, path, method):
        url = self._base_url + path.replace(" ", "%20")
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, method=method), context=SSL_CONTEXT) as response:
                return LiveResponse(response.status, response.read().decode())
        except urllib.error.HTTPError as error:
            return LiveResponse(error.code, error.read().decode())


def main(base_url):
    client = LiveClient(base_url)
    failures = 0
    for test in LIVE_TESTS:
        client.get("/end")
        client.get("/end?db=alice")
        client.get("/end?db=bob")
        try:
            test(client)
            print(f"PASS  {test.__name__}")
        except AssertionError as error:
            failures += 1
            print(f"FAIL  {test.__name__}: {error}")
    client.get("/end")
    print(f"\n{len(LIVE_TESTS) - failures}/{len(LIVE_TESTS)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
