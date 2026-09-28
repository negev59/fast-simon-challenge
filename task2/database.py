"""The key-value database: SET, GET, UNSET, NUMEQUALTO, UNDO, REDO and END.

Data model (each namespace holds its own copy):

  Kind        Key          Fields                          Purpose
  Variable    name         value                           the variables
  ValueCount  value        count                           how many variables hold a value
  Command     1, 2, 3 ...  name, old_value, new_value      history of SET/UNSET
  State       "state"      cursor, top                     cursor: commands currently applied
                                                           top: last command that can be redone

UNDO moves the cursor back and restores old_value; REDO moves it forward and
re-applies new_value. A new SET/UNSET is written at cursor + 1 and sets
top = cursor, which drops any pending redos without deleting anything.

Every command except END touches a fixed number of entities by key, so it's
O(1). Each change runs in a transaction so the four kinds stay consistent.
"""

VARIABLE = "Variable"
VALUE_COUNT = "ValueCount"
COMMAND = "Command"
STATE = "State"
ALL_KINDS = (VARIABLE, VALUE_COUNT, COMMAND, STATE)

STATE_KEY = "state"


class KeyValueDB:
    def __init__(self, store):
        self._store = store

    def get(self, name):
        """Return the variable's value, or None if it isn't set."""
        return _value(self._store.get(VARIABLE, name))

    def set(self, name, value):
        """Set name to value (None unsets it) and record it for UNDO."""
        with self._store.transaction():
            state, variable = self._store.get_many([(STATE, STATE_KEY), (VARIABLE, name)])
            state = state or {"cursor": 0, "top": 0}
            old_value = _value(variable)
            self._record_command(state, name, old_value, value)
            self._change_variable(name, old_value, value)
        return name, value

    def unset(self, name):
        return self.set(name, None)

    def num_equal_to(self, value):
        counter = self._store.get(VALUE_COUNT, value)
        return counter["count"] if counter else 0

    # Commands 1..cursor are exactly the ones applied, so the variable of
    # command #cursor still holds its new_value, and the variable of command
    # #cursor+1 still holds its old_value. UNDO and REDO rely on this, so they
    # don't need to read the variable itself.

    def undo(self):
        """Revert the latest applied command; None if there is nothing to undo."""
        with self._store.transaction():
            state = self._load_state()
            if state["cursor"] == 0:
                return None
            command = self._store.get(COMMAND, state["cursor"])
            state["cursor"] -= 1
            self._store.put(STATE, STATE_KEY, state)
            self._change_variable(command["name"], command["new_value"], command["old_value"])
        return command["name"], command["old_value"]

    def redo(self):
        """Re-apply the latest undone command; None if there is nothing to redo."""
        with self._store.transaction():
            state = self._load_state()
            if state["cursor"] == state["top"]:
                return None
            state["cursor"] += 1
            command = self._store.get(COMMAND, state["cursor"])
            self._store.put(STATE, STATE_KEY, state)
            self._change_variable(command["name"], command["old_value"], command["new_value"])
        return command["name"], command["new_value"]

    def end(self):
        """Delete every entity in this namespace. O(n), as the task allows."""
        self._store.delete_all(ALL_KINDS)

    def _load_state(self):
        return self._store.get(STATE, STATE_KEY) or {"cursor": 0, "top": 0}

    def _record_command(self, state, name, old_value, new_value):
        """Append a command to the history, discarding anything that could be redone."""
        state["cursor"] += 1
        state["top"] = state["cursor"]
        self._store.put(COMMAND, state["cursor"], {
            "name": name, "old_value": old_value, "new_value": new_value,
        })
        self._store.put(STATE, STATE_KEY, state)

    def _change_variable(self, name, old_value, new_value):
        """Move name from old_value to new_value, keeping the counters in sync."""
        if old_value == new_value:
            return
        if new_value is None:
            self._store.delete(VARIABLE, name)
        else:
            self._store.put(VARIABLE, name, {"value": new_value})

        # old_value != new_value, so these are two different counters and
        # neither is written twice in the transaction.
        deltas = {value: delta for value, delta in ((old_value, -1), (new_value, +1))
                  if value is not None}
        counters = self._store.get_many([(VALUE_COUNT, value) for value in deltas])
        for (value, delta), counter in zip(deltas.items(), counters):
            count = (counter["count"] if counter else 0) + delta
            if count > 0:
                self._store.put(VALUE_COUNT, value, {"count": count})
            else:
                self._store.delete(VALUE_COUNT, value)


def _value(variable):
    return variable["value"] if variable else None
