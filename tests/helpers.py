import os
import time


def slow_worker(source, options):
    time.sleep(float(options.get("sleep", 30)))
    return "# slow worker finished\n"


def crash_worker(source, options):
    os._exit(1)


class StubSender:
    def __init__(self, fail_send=False, fail_close=False):
        self.sent = []
        self.closed = False
        self.fail_send = fail_send
        self.fail_close = fail_close

    def send(self, msg):
        if self.fail_send:
            raise OSError("pipe send failed")
        self.sent.append(msg)

    def close(self):
        if self.fail_close:
            raise RuntimeError("close failed")
        self.closed = True


class StubReceiver:
    def __init__(self, *, poll_result=True, recv_exc=None, value=("ok", "# stub")):
        self.poll_result = poll_result
        self.recv_exc = recv_exc
        self.value = value
        self.closed = False

    def poll(self, timeout=None):
        return self.poll_result

    def recv(self):
        if self.recv_exc is not None:
            raise self.recv_exc
        return self.value

    def close(self):
        self.closed = True


class StubProc:
    def __init__(self, alive=True, immortal=False):
        self._alive = alive
        self.immortal = immortal
        self.terminated = False
        self.killed = False

    def is_alive(self):
        return self._alive

    def terminate(self):
        self.terminated = True
        if not self.immortal:
            self._alive = False

    def kill(self):
        self.killed = True
        self._alive = False

    def join(self, timeout=None):
        pass


class FakeEngine:
    name = "fake"
    supported_kinds = ()
    requires_process_isolation = False

    def __init__(self, behavior="ok"):
        self.behavior = behavior

    def convert(self, source, options):
        if self.behavior == "keyboard":
            raise KeyboardInterrupt()
        if self.behavior == "boom":
            raise RuntimeError("boom")
        if self.behavior == "slow":
            time.sleep(float(options.get("sleep", 30)))
        return "# fake ok\n"


def make_fake_pytesseract(text="OCR ENGINE TEXT", error=None):
    import types

    module = types.ModuleType("pytesseract")

    class TesseractError(Exception):
        def __init__(self, status=-1, message="tesseract failure"):
            super().__init__(message)
            self.status = status

    module.TesseractError = TesseractError

    def image_to_string(path, lang="eng"):
        if error is not None:
            raise error
        return text

    module.image_to_string = image_to_string
    return module
