"""Tests run against an in-memory store, so they need no Google Cloud access.

Run from the task2 directory:  python -m pytest
"""
import pytest

from main import create_app
from storage import MemoryBackend


@pytest.fixture
def backend():
    return MemoryBackend()


@pytest.fixture
def client(backend):
    return create_app(backend).test_client()


def run(client, steps):
    """Send each (url, expected output) pair and compare the responses."""
    for url, expected in steps:
        response = client.get(url)
        assert (url, response.get_data(as_text=True)) == (url, expected)


def test_sequence_1(client):
    run(client, [
        ("/set?name=ex&value=10", "ex = 10"),
        ("/get?name=ex", "10"),
        ("/unset?name=ex", "ex = None"),
        ("/get?name=ex", "None"),
        ("/end", "CLEANED"),
    ])


def test_sequence_2(client):
    run(client, [
        ("/set?name=a&value=10", "a = 10"),
        ("/set?name=b&value=10", "b = 10"),
        ("/numequalto?value=10", "2"),
        ("/numequalto?value=20", "0"),
        ("/set?name=b&value=30", "b = 30"),
        ("/numequalto?value=10", "1"),
        ("/end", "CLEANED"),
    ])


def test_sequence_3(client):
    run(client, [
        ("/set?name=a&value=10", "a = 10"),
        ("/set?name=b&value=20", "b = 20"),
        ("/get?name=a", "10"),
        ("/get?name=b", "20"),
        ("/undo", "b = None"),
        ("/get?name=a", "10"),
        ("/get?name=b", "None"),
        ("/set?name=a&value=40", "a = 40"),
        ("/get?name=a", "40"),
        ("/undo", "a = 10"),
        ("/get?name=a", "10"),
        ("/undo", "a = None"),
        ("/get?name=a", "None"),
        ("/undo", "NO COMMANDS"),
        ("/redo", "a = 10"),
        ("/redo", "a = 40"),
        ("/end", "CLEANED"),
    ])


def test_end_removes_every_entity(client, backend):
    run(client, [
        ("/set?name=a&value=1", "a = 1"),
        ("/undo", "a = None"),
    ])
    assert backend.namespaces[None]
    run(client, [("/end", "CLEANED")])
    assert backend.namespaces[None] == {}


def test_undo_and_redo_on_empty_history(client):
    run(client, [
        ("/undo", "NO COMMANDS"),
        ("/redo", "NO COMMANDS"),
    ])


def test_redo_is_dropped_after_a_new_command(client):
    run(client, [
        ("/set?name=a&value=1", "a = 1"),
        ("/set?name=b&value=2", "b = 2"),
        ("/undo", "b = None"),
        ("/unset?name=a", "a = None"),
        ("/redo", "NO COMMANDS"),
        ("/undo", "a = 1"),
        ("/undo", "a = None"),
        ("/redo", "a = 1"),
        ("/redo", "a = None"),
        ("/redo", "NO COMMANDS"),
    ])


def test_reads_do_not_drop_redo(client):
    run(client, [
        ("/set?name=a&value=1", "a = 1"),
        ("/undo", "a = None"),
        ("/get?name=a", "None"),
        ("/numequalto?value=1", "0"),
        ("/redo", "a = 1"),
    ])


def test_counts_follow_undo_and_redo(client):
    run(client, [
        ("/set?name=a&value=5", "a = 5"),
        ("/set?name=b&value=5", "b = 5"),
        ("/set?name=a&value=7", "a = 7"),
        ("/numequalto?value=5", "1"),
        ("/numequalto?value=7", "1"),
        ("/undo", "a = 5"),
        ("/numequalto?value=5", "2"),
        ("/numequalto?value=7", "0"),
        ("/redo", "a = 7"),
        ("/numequalto?value=5", "1"),
        ("/unset?name=b", "b = None"),
        ("/numequalto?value=5", "0"),
    ])


def test_setting_the_same_value_twice(client):
    run(client, [
        ("/set?name=a&value=1", "a = 1"),
        ("/set?name=a&value=1", "a = 1"),
        ("/numequalto?value=1", "1"),
        ("/undo", "a = 1"),
        ("/numequalto?value=1", "1"),
        ("/undo", "a = None"),
        ("/numequalto?value=1", "0"),
    ])


def test_unset_of_a_missing_variable(client):
    run(client, [
        ("/unset?name=ghost", "ghost = None"),
        ("/get?name=ghost", "None"),
        ("/undo", "ghost = None"),
        ("/undo", "NO COMMANDS"),
    ])


@pytest.mark.parametrize("url", [
    "/set?name=a",
    "/set?value=1",
    "/set?name=&value=1",
    "/set?name=a b&value=1",
    "/set?name=__key__&value=1",
    "/set?name=a&value=" + "x" * 501,
    "/get",
    "/unset",
    "/numequalto",
    "/get?name=a&db=bad name",
    "/get?name=a&db=__secret",
])
def test_invalid_input_is_rejected(client, url):
    response = client.get(url)
    assert response.status_code == 400
    assert response.get_data(as_text=True).startswith("ERROR:")


def test_unknown_command(client):
    response = client.get("/delete?name=a")
    assert response.status_code == 404
    assert "unknown command" in response.get_data(as_text=True)


def test_wrong_method(client):
    assert client.post("/set?name=a&value=1").status_code == 405


def test_invalid_input_does_not_change_data(client):
    run(client, [
        ("/set?name=a&value=1", "a = 1"),
    ])
    client.get("/set?name=a")
    run(client, [
        ("/get?name=a", "1"),
        ("/undo", "a = None"),
        ("/undo", "NO COMMANDS"),
    ])


def test_databases_are_isolated(client):
    run(client, [
        ("/set?name=a&value=1", "a = 1"),
        ("/set?name=a&value=2&db=alice", "a = 2"),
        ("/get?name=a", "1"),
        ("/get?name=a&db=alice", "2"),
        ("/get?name=a&db=bob", "None"),
        ("/numequalto?value=2", "0"),
        ("/numequalto?value=2&db=alice", "1"),
        ("/undo?db=bob", "NO COMMANDS"),
        ("/end?db=alice", "CLEANED"),
        ("/get?name=a&db=alice", "None"),
        ("/get?name=a", "1"),
        ("/undo", "a = None"),
    ])
