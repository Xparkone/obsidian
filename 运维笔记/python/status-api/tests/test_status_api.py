import unittest

from status_api.collectors import summarize_pods
from status_api.http_api import aggregate


class StatusAPITest(unittest.TestCase):
    def test_pod_summary(self):
        summary = {"total": 0, "running": 0, "pending": 0, "failed": 0, "succeeded": 0, "unknown": 0, "unhealthy": [], "status": "healthy"}
        summarize_pods(summary, [{"metadata": {"namespace": "prod", "name": "api"}, "status": {"phase": "Running", "containerStatuses": [{"ready": False, "restartCount": 3, "state": {"waiting": {"reason": "CrashLoopBackOff"}}}]}}])
        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["status"], "degraded")
        self.assertEqual(summary["unhealthy"][0]["reason"], "CrashLoopBackOff")

    def test_aggregate(self):
        data = {"host": {"status": "healthy"}, "kubernetes": {"status": "healthy"}, "pods": {"status": "healthy"}, "middlewares": [{"status": "unhealthy"}]}
        self.assertEqual(aggregate(data), "unhealthy")


if __name__ == "__main__":
    unittest.main()
