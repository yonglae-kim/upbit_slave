import unittest
from unittest.mock import patch

import apis


class GroupThrottleTest(unittest.TestCase):
    def test_low_remaining_observation_expires_after_pacing_delay(self):
        class AdvancingClock:
            def __init__(self):
                self.now = 0.0
                self.sleep_calls = []

            def monotonic(self):
                return self.now

            def sleep(self, seconds):
                self.sleep_calls.append(seconds)
                if len(self.sleep_calls) > 32:
                    raise AssertionError(
                        "low Remaining-Req observation kept throttle waiting"
                    )
                self.now += seconds

        clock = AdvancingClock()
        throttle = apis.GroupThrottle({"candles": 8})
        throttle.update_remaining(
            "candles", {"group": "candles", "sec": 2}, observed_at=0.0
        )

        with patch("apis.time.monotonic", side_effect=clock.monotonic):
            with patch("apis.time.sleep", side_effect=clock.sleep):
                throttle.wait("candles")

        self.assertEqual(clock.sleep_calls, [0.12])


if __name__ == "__main__":
    unittest.main()
