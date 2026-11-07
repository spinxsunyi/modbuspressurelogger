"""Regression checks for engineering time axes and chart data integrity."""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from matplotlib.figure import Figure
from matplotlib.ticker import MultipleLocator
from report_page import engineering_time_scale, apply_report_time_scale, engineering_grid
from core import Store, DEFAULTS


@pytest.mark.parametrize("duration,expected", [
    (7, 10), (18, 20), (27, 30), (48, 50),
    (73, 80), (118, 120),
])
def test_rounded_chart_window(duration, expected):
    left, right, major, minor = engineering_time_scale(0, duration)
    assert left == 0
    assert right == expected
    assert right >= duration
    assert major > 0
    assert minor == pytest.approx(major / 5)


def test_48_minute_chart_has_10_minute_major_2_minute_minor():
    fig = Figure()
    ax = fig.add_subplot(111)
    apply_report_time_scale(ax, 0, 48)
    engineering_grid(ax)
    assert ax.get_xlim() == pytest.approx((0, 50))
    assert isinstance(ax.xaxis.get_major_locator(), MultipleLocator)
    assert isinstance(ax.xaxis.get_minor_locator(), MultipleLocator)
    majors = ax.xaxis.get_majorticklocs()
    minors = ax.xaxis.get_minorticklocs()
    assert any(math.isclose(t, 10) for t in majors)
    assert any(math.isclose(t, 2) for t in minors)


def test_chart_scale_does_not_change_selected_samples(tmp_path):
    st = Store(tmp_path / 'recordings.sqlite')
    sid = st.start(DEFAULTS, 1000)
    for i in range(97):
        st.add_sample(sid, dict(ts=1000 + i * 30, elapsed=i * 30,
                                value=5000 if i == 42 else 1000,
                                quality='OK', raw=None, status=None, latency=0))
    st.finish(sid)
    before = st.plot_rows(sid)
    selected = (1000, 1000 + 48 * 60)
    fig = Figure()
    ax = fig.add_subplot(111)
    apply_report_time_scale(ax, 0, (selected[1] - selected[0]) / 60)
    after = st.plot_rows(sid)
    assert after == before
    assert len([r for r in after if selected[0] <= r['ts'] <= selected[1]]) == 97
    assert max(r['value'] for r in after) == 5000


@pytest.mark.parametrize("window,major,minor", [
    ('1 min',10,2), ('5 min',60,12), ('10 min',120,30),
    ('15 min',180,30), ('30 min',300,60), ('1 hour',600,120),
    ('12 hours',3600,900), ('24 hours',7200,1800),
])
def test_live_and_history_time_grid_configuration(window,major,minor):
    # Source check catches accidental divergence between the two UI chart maps.
    source = (Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8')
    assert f"'{window}':({major},{minor})" in source
