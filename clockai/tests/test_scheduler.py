from datetime import datetime
from clockai.models import Task


def make_task(time="08:00", period="daily", last_run=None, enabled=True):
    return Task(
        id="test-id",
        prompt="test prompt",
        time=time,
        period=period,
        last_run=last_run,
        enabled=enabled,
    )


class TestDaily:
    def test_should_run_at_exact_time(self):
        t = make_task(time="08:00", period="daily")
        assert t.should_run(datetime(2026, 7, 19, 8, 0)) is True

    def test_should_run_within_60s_window(self):
        t = make_task(time="08:00", period="daily")
        assert t.should_run(datetime(2026, 7, 19, 8, 0, 30)) is True

    def test_should_not_run_before_time(self):
        t = make_task(time="08:00", period="daily")
        assert t.should_run(datetime(2026, 7, 19, 7, 59)) is False

    def test_should_not_run_past_60s(self):
        t = make_task(time="08:00", period="daily")
        assert t.should_run(datetime(2026, 7, 19, 8, 1, 1)) is False

    def test_skip_if_already_run_today(self):
        t = make_task(time="08:00", period="daily", last_run="2026-07-19T08:00:00")
        assert t.should_run(datetime(2026, 7, 19, 8, 0, 30)) is False

    def test_run_next_day(self):
        t = make_task(time="08:00", period="daily", last_run="2026-07-18T08:00:00")
        assert t.should_run(datetime(2026, 7, 19, 8, 0)) is True


class TestHourly:
    def test_should_run_at_exact_minute(self):
        assert make_task(time="08:30", period="hourly").should_run(datetime(2026, 7, 19, 10, 30)) is True

    def test_should_not_run_before_minute(self):
        assert make_task(time="08:30", period="hourly").should_run(datetime(2026, 7, 19, 10, 29)) is False

    def test_skip_if_already_run_this_hour(self):
        t = make_task(time="08:30", period="hourly", last_run="2026-07-19T10:30:00")
        assert t.should_run(datetime(2026, 7, 19, 10, 30, 30)) is False

    def test_run_next_hour(self):
        t = make_task(time="08:30", period="hourly", last_run="2026-07-19T09:30:00")
        assert t.should_run(datetime(2026, 7, 19, 10, 30)) is True


class TestInterval:
    def test_initial_run_within_window(self):
        assert make_task(time="08:00", period="interval:10").should_run(datetime(2026, 7, 19, 8, 0)) is True

    def test_run_after_interval_elapsed(self):
        t = make_task(time="08:00", period="interval:10", last_run="2026-07-19T08:00:00")
        assert t.should_run(datetime(2026, 7, 19, 8, 10)) is True

    def test_not_run_before_interval(self):
        t = make_task(time="08:00", period="interval:10", last_run="2026-07-19T08:00:00")
        assert t.should_run(datetime(2026, 7, 19, 8, 9)) is False

    def test_invalid_interval_zero(self):
        assert make_task(time="08:00", period="interval:0").should_run(datetime(2026, 7, 19, 8, 0)) is False

    def test_invalid_interval_format(self):
        assert make_task(time="08:00", period="interval:").should_run(datetime(2026, 7, 19, 8, 0)) is False


class TestDisabled:
    def test_disabled_task_never_runs_daily(self):
        assert make_task(enabled=False).should_run(datetime(2026, 7, 19, 8, 0)) is False

    def test_disabled_task_never_runs_interval(self):
        t = make_task(period="interval:10", enabled=False)
        assert t.should_run(datetime(2026, 7, 19, 8, 0)) is False


class TestEdgeCases:
    def test_invalid_time_string(self):
        assert make_task(time="abc", period="daily").should_run(datetime(2026, 7, 19, 8, 0)) is False

    def test_empty_time(self):
        assert make_task(time="", period="daily").should_run(datetime(2026, 7, 19, 8, 0)) is False

    def test_unknown_period(self):
        assert make_task(period="weekly").should_run(datetime(2026, 7, 19, 8, 0)) is False

    def test_last_run_prevents_rerun(self):
        t = make_task()
        now = datetime(2026, 7, 19, 8, 0)
        assert t.should_run(now) is True
        t.last_run = now.isoformat()
        assert t.should_run(now) is False

    def test_interval_after_last_run_update(self):
        t = make_task(period="interval:5")
        now = datetime(2026, 7, 19, 8, 0)
        assert t.should_run(now) is True
        t.last_run = now.isoformat()
        assert t.should_run(datetime(2026, 7, 19, 8, 4)) is False
        assert t.should_run(datetime(2026, 7, 19, 8, 5)) is True
