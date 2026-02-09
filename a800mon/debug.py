DEBUGLOG = []


def log(txt):
    DEBUGLOG.append(txt)


def print_log():
    for item in DEBUGLOG:
        print(item)
