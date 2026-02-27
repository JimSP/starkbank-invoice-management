from unittest.mock import MagicMock, patch
from app.scheduler import _job, start_scheduler


class TestJob:
    @patch("app.scheduler.issue_batch")
    def test_success_calls_issue_batch(self, mock_issue):
        _job()
        mock_issue.assert_called_once()


    @patch("app.scheduler.issue_batch", side_effect=Exception("API error"))
    def test_exception_is_swallowed(self, _):
        _job()  # must not raise


class TestStartScheduler:
    @patch("app.scheduler.BackgroundScheduler")
    def test_returns_started_scheduler(self, MockScheduler):
        fake = MagicMock()
        MockScheduler.return_value = fake
        assert start_scheduler() is fake
        fake.start.assert_called_once()


    @patch("app.scheduler.BackgroundScheduler")
    def test_adds_two_jobs(self, MockScheduler):
        fake = MagicMock()
        MockScheduler.return_value = fake
        start_scheduler()
        assert fake.add_job.call_count == 2


    @patch("app.scheduler.BackgroundScheduler")
    def test_immediate_job_id(self, MockScheduler):
        fake = MagicMock()
        MockScheduler.return_value = fake
        start_scheduler()
        ids = [kw.get("id") for _, kw in fake.add_job.call_args_list]
        assert "invoice_batch_initial" in ids


    @patch("app.scheduler.BackgroundScheduler")
    def test_interval_job_id(self, MockScheduler):
        fake = MagicMock()
        MockScheduler.return_value = fake
        start_scheduler()
        ids = [kw.get("id") for _, kw in fake.add_job.call_args_list]
        assert "invoice_batch" in ids
