import time
import unittest
import unittest.mock

from websockets.exceptions import ConcurrencyError
from websockets.frames import OP_BINARY, OP_CONT, OP_TEXT, Frame
from websockets.sync.messages import *

from ..utils import MS
from .utils import ThreadTestCase


class AssemblerTests(ThreadTestCase):
    def setUp(self):
        self.pause = unittest.mock.Mock()
        self.resume = unittest.mock.Mock()
        self.assembler = Assembler(high=2, low=1, pause=self.pause, resume=self.resume)

    # Test get

    def test_get_text_message_already_received(self):
        """get returns a text message that is already received."""
        self.assembler.put(Frame(OP_TEXT, b"caf\xc3\xa9"))
        message = self.assembler.get()
        self.assertEqual(message, "café")

    def test_get_binary_message_already_received(self):
        """get returns a binary message that is already received."""
        self.assembler.put(Frame(OP_BINARY, b"tea"))
        message = self.assembler.get()
        self.assertEqual(message, b"tea")

    def test_get_text_message_not_received_yet(self):
        """get returns a text message when it is received."""
        message = None

        def getter():
            nonlocal message
            message = self.assembler.get()

        with self.run_in_thread(getter):
            self.assembler.put(Frame(OP_TEXT, b"caf\xc3\xa9"))

        self.assertEqual(message, "café")

    def test_get_binary_message_not_received_yet(self):
        """get returns a binary message when it is received."""
        message = None

        def getter():
            nonlocal message
            message = self.assembler.get()

        with self.run_in_thread(getter):
            self.assembler.put(Frame(OP_BINARY, b"tea"))

        self.assertEqual(message, b"tea")

    def test_get_fragmented_text_message_already_received(self):
        """get reassembles a fragmented a text message that is already received."""
        self.assembler.put(Frame(OP_TEXT, b"ca", fin=False))
        self.assembler.put(Frame(OP_CONT, b"f\xc3", fin=False))
        self.assembler.put(Frame(OP_CONT, b"\xa9"))
        message = self.assembler.get()
        self.assertEqual(message, "café")

    def test_get_fragmented_binary_message_already_received(self):
        """get reassembles a fragmented binary message that is already received."""
        self.assembler.put(Frame(OP_BINARY, b"t", fin=False))
        self.assembler.put(Frame(OP_CONT, b"e", fin=False))
        self.assembler.put(Frame(OP_CONT, b"a"))
        message = self.assembler.get()
        self.assertEqual(message, b"tea")

    def test_get_fragmented_text_message_not_received_yet(self):
        """get reassembles a fragmented text message when it is received."""
        message = None

        def getter():
            nonlocal message
            message = self.assembler.get()

        with self.run_in_thread(getter):
            self.assembler.put(Frame(OP_TEXT, b"ca", fin=False))
            self.assembler.put(Frame(OP_CONT, b"f\xc3", fin=False))
            self.assembler.put(Frame(OP_CONT, b"\xa9"))

        self.assertEqual(message, "café")

    def test_get_fragmented_binary_message_not_received_yet(self):
        """get reassembles a fragmented binary message when it is received."""
        message = None

        def getter():
            nonlocal message
            message = self.assembler.get()

        with self.run_in_thread(getter):
            self.assembler.put(Frame(OP_BINARY, b"t", fin=False))
            self.assembler.put(Frame(OP_CONT, b"e", fin=False))
            self.assembler.put(Frame(OP_CONT, b"a"))

        self.assertEqual(message, b"tea")

    def test_get_fragmented_text_message_being_received(self):
        """get reassembles a fragmented text message that is partially received."""
        message = None

        def getter():
            nonlocal message
            message = self.assembler.get()

        self.assembler.put(Frame(OP_TEXT, b"ca", fin=False))
        with self.run_in_thread(getter):
            self.assembler.put(Frame(OP_CONT, b"f\xc3", fin=False))
            self.assembler.put(Frame(OP_CONT, b"\xa9"))

        self.assertEqual(message, "café")

    def test_get_fragmented_binary_message_being_received(self):
        """get reassembles a fragmented binary message that is partially received."""
        message = None

        def getter():
            nonlocal message
            message = self.assembler.get()

        self.assembler.put(Frame(OP_BINARY, b"t", fin=False))
        with self.run_in_thread(getter):
            self.assembler.put(Frame(OP_CONT, b"e", fin=False))
            self.assembler.put(Frame(OP_CONT, b"a"))

        self.assertEqual(message, b"tea")

    def test_get_encoded_text_message(self):
        """get returns a text message without UTF-8 decoding."""
        self.assembler.put(Frame(OP_TEXT, b"caf\xc3\xa9"))
        message = self.assembler.get(decode=False)
        self.assertEqual(message, b"caf\xc3\xa9")

    def test_get_decoded_binary_message(self):
        """get returns a binary message with UTF-8 decoding."""
        self.assembler.put(Frame(OP_BINARY, b"tea"))
        message = self.assembler.get(decode=True)
        self.assertEqual(message, "tea")

    def test_get_resumes_reading(self):
        """get resumes reading when queue goes below the high-water mark."""
        self.assembler.put(Frame(OP_TEXT, b"caf\xc3\xa9"))
        self.assembler.put(Frame(OP_TEXT, b"more caf\xc3\xa9"))
        self.assembler.put(Frame(OP_TEXT, b"water"))

        # queue is above the low-water mark
        self.assembler.get()
        self.resume.assert_not_called()

        # queue is at the low-water mark
        self.assembler.get()
        self.resume.assert_called_once_with()

        # queue is below the low-water mark
        self.assembler.get()
        self.resume.assert_called_once_with()

    def test_get_timeout_before_first_frame(self):
        """get times out before reading the first frame."""
        with self.assertRaises(TimeoutError):
            self.assembler.get(timeout=MS)

        self.assembler.put(Frame(OP_TEXT, b"caf\xc3\xa9"))

        message = self.assembler.get()
        self.assertEqual(message, "café")

    def test_get_timeout_after_first_frame(self):
        """get times out after reading the first frame."""
        self.assembler.put(Frame(OP_TEXT, b"ca", fin=False))

        with self.assertRaises(TimeoutError):
            self.assembler.get(timeout=MS)

        self.assembler.put(Frame(OP_CONT, b"f\xc3", fin=False))
        self.assembler.put(Frame(OP_CONT, b"\xa9"))

        message = self.assembler.get()
        self.assertEqual(message, "café")

    # Test get_iter

    def test_get_iter_text_message_already_received(self):
        """get_iter yields a text message that is already received."""
        self.assembler.put(Frame(OP_TEXT, b"caf\xc3\xa9"))
        fragments = list(self.assembler.get_iter())
        self.assertEqual(fragments, ["café"])

    def test_get_iter_binary_message_already_received(self):
        """get_iter yields a binary message that is already received."""
        self.assembler.put(Frame(OP_BINARY, b"tea"))
        fragments = list(self.assembler.get_iter())
        self.assertEqual(fragments, [b"tea"])

    def test_get_iter_text_message_not_received_yet(self):
        """get_iter yields a text message when it is received."""
        fragments = []

        def getter():
            nonlocal fragments
            for fragment in self.assembler.get_iter():
                fragments.append(fragment)

        with self.run_in_thread(getter):
            self.assembler.put(Frame(OP_TEXT, b"caf\xc3\xa9"))

        self.assertEqual(fragments, ["café"])

    def test_get_iter_binary_message_not_received_yet(self):
        """get_iter yields a binary message when it is received."""
        fragments = []

        def getter():
            nonlocal fragments
            for fragment in self.assembler.get_iter():
                fragments.append(fragment)

        with self.run_in_thread(getter):
            self.assembler.put(Frame(OP_BINARY, b"tea"))

        self.assertEqual(fragments, [b"tea"])

    def test_get_iter_fragmented_text_message_already_received(self):
        """get_iter yields a fragmented text message that is already received."""
        self.assembler.put(Frame(OP_TEXT, b"ca", fin=False))
        self.assembler.put(Frame(OP_CONT, b"f\xc3", fin=False))
        self.assembler.put(Frame(OP_CONT, b"\xa9"))
        fragments = list(self.assembler.get_iter())
        self.assertEqual(fragments, ["ca", "f", "é"])

    def test_get_iter_fragmented_binary_message_already_received(self):
        """get_iter yields a fragmented binary message that is already received."""
        self.assembler.put(Frame(OP_BINARY, b"t", fin=False))
        self.assembler.put(Frame(OP_CONT, b"e", fin=False))
        self.assembler.put(Frame(OP_CONT, b"a"))
        fragments = list(self.assembler.get_iter())
        self.assertEqual(fragments, [b"t", b"e", b"a"])

    def test_get_iter_fragmented_text_message_not_received_yet(self):
        """get_iter yields a fragmented text message when it is received."""
        iterator = self.assembler.get_iter()
        self.assembler.put(Frame(OP_TEXT, b"ca", fin=False))
        self.assertEqual(next(iterator), "ca")
        self.assembler.put(Frame(OP_CONT, b"f\xc3", fin=False))
        self.assertEqual(next(iterator), "f")
        self.assembler.put(Frame(OP_CONT, b"\xa9"))
        self.assertEqual(next(iterator), "é")

    def test_get_iter_fragmented_binary_message_not_received_yet(self):
        """get_iter yields a fragmented binary message when it is received."""
        iterator = self.assembler.get_iter()
        self.assembler.put(Frame(OP_BINARY, b"t", fin=False))
        self.assertEqual(next(iterator), b"t")
        self.assembler.put(Frame(OP_CONT, b"e", fin=False))
        self.assertEqual(next(iterator), b"e")
        self.assembler.put(Frame(OP_CONT, b"a"))
        self.assertEqual(next(iterator), b"a")

    def test_get_iter_fragmented_text_message_being_received(self):
        """get_iter yields a fragmented text message that is partially received."""
        self.assembler.put(Frame(OP_TEXT, b"ca", fin=False))
        iterator = self.assembler.get_iter()
        self.assertEqual(next(iterator), "ca")
        self.assembler.put(Frame(OP_CONT, b"f\xc3", fin=False))
        self.assertEqual(next(iterator), "f")
        self.assembler.put(Frame(OP_CONT, b"\xa9"))
        self.assertEqual(next(iterator), "é")

    def test_get_iter_fragmented_binary_message_being_received(self):
        """get_iter yields a fragmented binary message that is partially received."""
        self.assembler.put(Frame(OP_BINARY, b"t", fin=False))
        iterator = self.assembler.get_iter()
        self.assertEqual(next(iterator), b"t")
        self.assembler.put(Frame(OP_CONT, b"e", fin=False))
        self.assertEqual(next(iterator), b"e")
        self.assembler.put(Frame(OP_CONT, b"a"))
        self.assertEqual(next(iterator), b"a")

    def test_get_iter_encoded_text_message(self):
        """get_iter yields a text message without UTF-8 decoding."""
        self.assembler.put(Frame(OP_TEXT, b"ca", fin=False))
        self.assembler.put(Frame(OP_CONT, b"f\xc3", fin=False))
        self.assembler.put(Frame(OP_CONT, b"\xa9"))
        fragments = list(self.assembler.get_iter(decode=False))
        self.assertEqual(fragments, [b"ca", b"f\xc3", b"\xa9"])

    def test_get_iter_decoded_binary_message(self):
        """get_iter yields a binary message with UTF-8 decoding."""
        self.assembler.put(Frame(OP_BINARY, b"t", fin=False))
        self.assembler.put(Frame(OP_CONT, b"e", fin=False))
        self.assembler.put(Frame(OP_CONT, b"a"))
        fragments = list(self.assembler.get_iter(decode=True))
        self.assertEqual(fragments, ["t", "e", "a"])

    def test_get_iter_resumes_reading(self):
        """get_iter resumes reading when queue goes below the high-water mark."""
        self.assembler.put(Frame(OP_BINARY, b"t", fin=False))
        self.assembler.put(Frame(OP_CONT, b"e", fin=False))
        self.assembler.put(Frame(OP_CONT, b"a"))

        iterator = self.assembler.get_iter()

        # queue is above the low-water mark
        next(iterator)
        self.resume.assert_not_called()

        # queue is at the low-water mark
        next(iterator)
        self.resume.assert_called_once_with()

        # queue is below the low-water mark
        next(iterator)
        self.resume.assert_called_once_with()

    # Test put

    def test_put_pauses_reading(self):
        """put pauses reading when queue goes above the high-water mark."""
        # queue is below the high-water mark
        self.assembler.put(Frame(OP_TEXT, b"caf\xc3\xa9"))
        self.assembler.put(Frame(OP_BINARY, b"t", fin=False))
        self.pause.assert_not_called()

        # queue is at the high-water mark
        self.assembler.put(Frame(OP_CONT, b"e", fin=False))
        self.pause.assert_called_once_with()

        # queue is above the high-water mark
        self.assembler.put(Frame(OP_CONT, b"a"))
        self.pause.assert_called_once_with()

    # Test termination

    def test_get_fails_when_interrupted_by_close(self):
        """get raises EOFError when close is called."""

        def closer():
            time.sleep(2 * MS)
            self.assembler.close()

        with self.run_in_thread(closer):
            with self.assertRaises(EOFError):
                self.assembler.get()

    def test_get_iter_fails_when_interrupted_by_close(self):
        """get_iter raises EOFError when close is called."""

        def closer():
            time.sleep(2 * MS)
            self.assembler.close()

        with self.run_in_thread(closer):
            with self.assertRaises(EOFError):
                for _ in self.assembler.get_iter():
                    self.fail("no fragment expected")

    def test_get_fails_after_close(self):
        """get raises EOFError after close is called."""
        self.assembler.close()
        with self.assertRaises(EOFError):
            self.assembler.get()

    def test_get_iter_fails_after_close(self):
        """get_iter raises EOFError after close is called."""
        self.assembler.close()
        with self.assertRaises(EOFError):
            for _ in self.assembler.get_iter():
                self.fail("no fragment expected")

    def test_put_fails_after_close(self):
        """put raises EOFError after close is called."""
        self.assembler.close()
        with self.assertRaises(EOFError):
            self.assembler.put(Frame(OP_TEXT, b"caf\xc3\xa9"))

    def test_close_is_idempotent(self):
        """close can be called multiple times safely."""
        self.assembler.close()
        self.assembler.close()

    # Test (non-)concurrency

    def test_get_fails_when_get_is_running(self):
        """get cannot be called concurrently."""
        with self.run_in_thread(self.assembler.get):
            with self.assertRaises(ConcurrencyError):
                self.assembler.get()
            self.assembler.put(Frame(OP_TEXT, b""))  # unlock other thread

    def test_get_fails_when_get_iter_is_running(self):
        """get cannot be called concurrently with get_iter."""
        with self.run_in_thread(lambda: list(self.assembler.get_iter())):
            with self.assertRaises(ConcurrencyError):
                self.assembler.get()
            self.assembler.put(Frame(OP_TEXT, b""))  # unlock other thread

    def test_get_iter_fails_when_get_is_running(self):
        """get_iter cannot be called concurrently with get."""
        with self.run_in_thread(self.assembler.get):
            with self.assertRaises(ConcurrencyError):
                list(self.assembler.get_iter())
            self.assembler.put(Frame(OP_TEXT, b""))  # unlock other thread

    def test_get_iter_fails_when_get_iter_is_running(self):
        """get_iter cannot be called concurrently."""
        with self.run_in_thread(lambda: list(self.assembler.get_iter())):
            with self.assertRaises(ConcurrencyError):
                list(self.assembler.get_iter())
            self.assembler.put(Frame(OP_TEXT, b""))  # unlock other thread

    # Test setting limits

    def test_set_high_water_mark(self):
        """high sets the high-water mark."""
        assembler = Assembler(high=10)
        self.assertEqual(assembler.high, 10)

    def test_set_high_and_low_water_mark(self):
        """high sets the high-water mark and low-water mark."""
        assembler = Assembler(high=10, low=5)
        self.assertEqual(assembler.high, 10)
        self.assertEqual(assembler.low, 5)

    def test_set_invalid_high_water_mark(self):
        """high must be a non-negative integer."""
        with self.assertRaises(ValueError):
            Assembler(high=-1)

    def test_set_invalid_low_water_mark(self):
        """low must be higher than high."""
        with self.assertRaises(ValueError):
            Assembler(low=10, high=5)
