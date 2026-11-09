"""In-memory /priority: phones register as priority residents; /evacuees carries it."""

from __future__ import annotations

import time
import unittest

from fastapi import Response

from backend.api import main as api


def _evacuee(eid: str) -> None:
    api.evacuees[eid] = {
        "lat": 53.52,
        "lon": -113.61,
        "route_id": None,
        "route_status": None,
        "shelter_id": None,
        "updated_sim_time": 0,
        "last_seen": time.time(),
    }


def _post(**kw):
    body = {"id": "ev_aaaaaaaaaaaa", "id_type": "dats", "id_last4": "1234", "needs": ["mobility"]}
    body.update(kw)
    return api.post_priority(api.PriorityIn(**body), Response())


class PriorityTests(unittest.TestCase):
    def setUp(self) -> None:
        api.evacuees.clear()
        api.priority_residents.clear()

    tearDown = setUp

    def test_register_shows_on_evacuee_without_full_id(self):
        _evacuee("ev_aaaaaaaaaaaa")
        _evacuee("ev_bbbbbbbbbbbb")
        self.assertEqual(_post(note="  Uses a power wheelchair  "), {"id": "ev_aaaaaaaaaaaa", "priority": True})
        props = {f["id"]: f["properties"] for f in api.evacuee_features()}
        a = props["ev_aaaaaaaaaaaa"]
        self.assertTrue(a["priority"])
        self.assertEqual(a["priority_id_type"], "dats")
        self.assertEqual(a["priority_needs"], ["mobility"])
        self.assertEqual(a["priority_note"], "Uses a power wheelchair")
        self.assertNotIn("1234", str(a))  # responders never get the ID digits
        self.assertFalse(props["ev_bbbbbbbbbbbb"]["priority"])

    def test_remove(self):
        _evacuee("ev_aaaaaaaaaaaa")
        _post()
        api.delete_priority("ev_aaaaaaaaaaaa")
        self.assertFalse(api.evacuee_features()[0]["properties"]["priority"])

    def test_rejects_bad_input(self):
        for kw in ({"id_type": "passport"}, {"id_last4": "12"}, {"id_last4": "12-4"}, {"needs": ["flying"]}, {"id": "x"}):
            self.assertEqual(_post(**kw).status_code, 422, kw)
        self.assertEqual(api.priority_residents, {})


if __name__ == "__main__":
    unittest.main()
