"""Task II: a simple key-value database on Google App Engine.

Every command is an HTTP GET request and answers in plain text. Any command
also accepts an optional `db` parameter that selects an isolated database
(a Datastore namespace), e.g. /set?name=a&value=10&db=alice. Without it the
app behaves exactly as the task describes.
"""
import functools
import logging
import re

from flask import Flask, request
from google.cloud import datastore
from werkzeug.exceptions import HTTPException

from database import KeyValueDB
from storage import DatastoreStore

# Datastore reserves key names like __foo__, and indexes at most 1500 bytes.
MAX_TOKEN_BYTES = 500
RESERVED_NAME = re.compile(r"__.*__")
DB_NAME = re.compile(r"[0-9A-Za-z._-]{1,100}")

USAGE = """Simple database - available commands:
  /set?name={name}&value={value}
  /get?name={name}
  /unset?name={name}
  /numequalto?value={value}
  /undo
  /redo
  /end
Add &db={db_name} (letters, digits, . _ -) to any command to work in your own isolated database.
"""


class InvalidInput(Exception):
    """Raised for a bad request; the message is shown to the user."""


def text(body, status=200):
    return body, status, {"Content-Type": "text/plain; charset=utf-8"}


def token_param(param):
    """A required variable name or value: non-empty and without spaces."""
    token = request.args.get(param)
    if token is None or token == "":
        raise InvalidInput(f"missing required parameter '{param}'")
    if any(char.isspace() for char in token):
        raise InvalidInput(f"'{param}' must not contain spaces")
    if len(token.encode("utf-8")) > MAX_TOKEN_BYTES:
        raise InvalidInput(f"'{param}' is longer than {MAX_TOKEN_BYTES} bytes")
    if RESERVED_NAME.fullmatch(token):
        raise InvalidInput(f"'{param}' must not start and end with '__'")
    return token


def db_param():
    """The optional database name, or None for the default database."""
    db_name = request.args.get("db")
    if db_name is None:
        return None
    if not DB_NAME.fullmatch(db_name) or db_name.startswith("__"):
        raise InvalidInput(
            "'db' must be 1-100 letters, digits, '.', '_' or '-', "
            "and must not start with '__'")
    return db_name


def change_result(result):
    """Format the outcome of UNDO / REDO."""
    if result is None:
        return "NO COMMANDS"
    name, value = result
    return f"{name} = {value}"


def create_app(store_factory):
    """Build the app; store_factory(namespace) returns the storage to use."""
    app = Flask(__name__)

    def database():
        return KeyValueDB(store_factory(db_param()))

    @app.route("/")
    def usage():
        return text(USAGE)

    @app.route("/set")
    def set_command():
        name, value = token_param("name"), token_param("value")
        database().set(name, value)
        return text(f"{name} = {value}")

    @app.route("/get")
    def get_command():
        return text(str(database().get(token_param("name"))))

    @app.route("/unset")
    def unset_command():
        name = token_param("name")
        database().unset(name)
        return text(f"{name} = None")

    @app.route("/numequalto")
    def numequalto_command():
        return text(str(database().num_equal_to(token_param("value"))))

    @app.route("/undo")
    def undo_command():
        return text(change_result(database().undo()))

    @app.route("/redo")
    def redo_command():
        return text(change_result(database().redo()))

    @app.route("/end")
    def end_command():
        database().end()
        return text("CLEANED")

    @app.errorhandler(InvalidInput)
    def invalid_input(error):
        return text(f"ERROR: {error}\n\n{USAGE}", 400)

    @app.errorhandler(404)
    def unknown_command(error):
        return text(f"ERROR: unknown command '{request.path}'\n\n{USAGE}", 404)

    @app.errorhandler(405)
    def wrong_method(error):
        return text(f"ERROR: use GET requests\n\n{USAGE}", 405)

    @app.errorhandler(Exception)
    def internal_error(error):
        if isinstance(error, HTTPException):
            return text(f"ERROR: {error.description}", error.code)
        logging.exception("Unhandled error on %s", request.full_path)
        return text("ERROR: something went wrong on our side, please try again", 500)

    return app


@functools.cache
def datastore_client():
    # Created lazily, so importing this module needs no Google credentials.
    return datastore.Client()


def datastore_store(namespace):
    return DatastoreStore(datastore_client(), namespace)


app = create_app(datastore_store)

if __name__ == "__main__":
    # Used only when running locally. On App Engine, gunicorn serves the app.
    app.run(host="127.0.0.1", port=8080, debug=True)
