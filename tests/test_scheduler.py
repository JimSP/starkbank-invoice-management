from unittest.mock import MagicMock, patch
from app.scheduler import _job, start_scheduler


class TestJob:
    @patch("app.scheduler.issue_batch")
    def test_success_calls_issue_batch(self, mock_issue):
        _job()
        mock_issue.assert_called_once()


    @patch("app.scheduler.issue_batch", side_effect=Exception("API error"))
    def test_exception_is_swallowed(self, _):
        _job()


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
    def test_invoice_batch_job_id(self, MockScheduler):
        fake = MagicMock()
        MockScheduler.return_value = fake
        start_scheduler()
        ids = [kw.get("id") for _, kw in fake.add_job.call_args_list]
        assert "invoice_batch" in ids


    @patch("app.scheduler.BackgroundScheduler")
    def test_reconciliation_job_id(self, MockScheduler):
        fake = MagicMock()
        MockScheduler.return_value = fake
        start_scheduler()
        ids = [kw.get("id") for _, kw in fake.add_job.call_args_list]
        assert "invoice_reconciliation" in ids


    @patch("app.scheduler.BackgroundScheduler")
    def test_invoice_batch_fires_immediately(self, MockScheduler):
        """next_run_time deve ser definido para disparo imediato no startup."""
        fake = MagicMock()
        MockScheduler.return_value = fake
        start_scheduler()
        batch_kwargs = next(
            kw for _, kw in fake.add_job.call_args_list
            if kw.get("id") == "invoice_batch"
        )
        assert batch_kwargs.get("next_run_time") is not None


    @patch("app.scheduler.BackgroundScheduler")
    def test_reconciliation_job_has_delayed_start(self, MockScheduler):
        """Reconciliation não deve disparar imediatamente no startup."""
        fake = MagicMock()
        MockScheduler.return_value = fake
        start_scheduler()
        recon_kwargs = next(
            kw for _, kw in fake.add_job.call_args_list
            if kw.get("id") == "invoice_reconciliation"
        )
        assert recon_kwargs.get("next_run_time") is not None