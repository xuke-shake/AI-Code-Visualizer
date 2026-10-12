from auth import validate

REQUIRED = 123


def target(username, password):
    if validate(username, password):
        return REQUIRED
    return None


class Outer:
    class Inner:
        def run(self):
            return 1

    def outer(self):
        return True


ENTRY = target
