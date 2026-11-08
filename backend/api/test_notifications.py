"""In-memory /notifications: dashboard sends, phones read newest first."""

from __future__ import annotations

import unittest

from backend.api import main as api


class NotificationsTests(unittest.TestCase):
    def setUp(self) -> None:
        api.notifications.clear()

    def tearDown(self) -> None:
        api.notifications.clear()

    def test_send_then_list_newest_first(self):
        a = api.post_notification(api.NotificationIn(title="Fire nearby", message="Be ready to leave."))
        b = api.post_notification(
            api.NotificationIn(title="Leave now", message="Go to a shelter.", severity="evacuation", target="zone")
        )
        self.assertEqual(a["severity"], "advisory")
        self.assertEqual(a["target"], "all")
        self.assertNotEqual(a["id"], b["id"])
        self.assertTrue(b["time"].endswith("+00:00"))
        listed = api.get_notifications()["notifications"]
        self.assertEqual([n["id"] for n in listed], [b["id"], a["id"]])

    def test_rejects_blank_and_unknown_severity(self):
        blank = api.post_notification(api.NotificationIn(title="  ", message="x"))
        self.assertEqual(blank.status_code, 422)
        bad = api.post_notification(api.NotificationIn(title="t", message="m", severity="panic"))
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(api.get_notifications()["notifications"], [])


if __name__ == "__main__":
    unittest.main()
