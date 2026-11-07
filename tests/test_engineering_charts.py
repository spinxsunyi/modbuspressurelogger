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
def test_live_and_history_tick_positions(window,major,minor):
    from chart_scale import apply_window_time_grid, apply_engineering_grid
    for units, factor in [('seconds',1),('minutes',1/60)]:
        ax=Figure().add_subplot(111)
        assert apply_window_time_grid(ax,window,units=units)
        apply_engineering_grid(ax)
        assert isinstance(ax.xaxis.get_major_locator(),MultipleLocator)
        assert isinstance(ax.xaxis.get_minor_locator(),MultipleLocator)
        assert any(math.isclose(x,major*factor,abs_tol=1e-6)
                   for x in ax.xaxis.get_majorticklocs())
        assert any(math.isclose(x,minor*factor,abs_tol=1e-6)
                   for x in ax.xaxis.get_minorticklocs())


def test_pressure_ticks_keep_manual_bounds():
    from chart_scale import apply_pressure_grid, apply_engineering_grid
    ax=Figure().add_subplot(111)
    ax.set_ylim(0,5000)
    step=apply_pressure_grid(ax,0,5000)
    apply_engineering_grid(ax)
    assert step==1000
    assert ax.get_ylim()==pytest.approx((0,5000))
    assert any(math.isclose(x,200) for x in ax.yaxis.get_minorticklocs())


def test_reduction_preserves_extrema_and_communication_gap():
    from chart_scale import reduce_live_samples
    rows=[dict(ts=float(i),value=1000.,quality='OK') for i in range(12000)]
    rows[124]['value']=5000.
    rows[7000]['value']=0.
    rows[7100]['value']=None
    rows[7100]['quality']='TIMEOUT'
    result=reduce_live_samples(rows,4000)
    assert len(result)<len(rows)
    assert any(r['value']==5000 for r in result)
    assert any(r['value']==0 for r in result)
    assert any(r['quality']=='TIMEOUT' for r in result)
    assert len(rows)==12000
    assert rows[124]['value']==5000


def test_export_charts_use_same_axis_policy(tmp_path):
    from report_page import report_figures,graph_figure
    st=Store(tmp_path/'report.sqlite')
    sid=st.start(DEFAULTS,1000)
    for i in range(97):
        st.add_sample(sid,dict(ts=1000+i*30,elapsed=i*30,value=5000 if i==42 else 1000,
                               quality='OK',raw=None,status=None,latency=0))
    st.finish(sid)
    interval=(1000,1000+48*60)
    pages=report_figures(st,sid,time_range=interval)
    jpg=graph_figure(st,sid,time_range=interval)
    charts=[next(ax for ax in page.axes if ax.get_ylabel().startswith('Pressure'))
            for page in pages if any(ax.get_ylabel().startswith('Pressure') for ax in page.axes)]
    charts.append(jpg.axes[0])
    for ax in charts:
        assert ax.get_xlim()==pytest.approx((0,50))
        assert isinstance(ax.xaxis.get_major_locator(),MultipleLocator)
        assert isinstance(ax.xaxis.get_minor_locator(),MultipleLocator)
        assert any(math.isclose(x,10) for x in ax.xaxis.get_majorticklocs())
        assert any(math.isclose(x,2) for x in ax.xaxis.get_minorticklocs())
    assert len(st.plot_rows(sid))==97


def test_manual_limits_survive_grid_configuration():
    from chart_scale import apply_window_time_grid,apply_engineering_grid,apply_pressure_grid
    ax=Figure().add_subplot(111)
    ax.set_xlim(3.25,33.25)
    ax.set_ylim(200,5200)
    apply_window_time_grid(ax,'30 min',units='minutes')
    apply_pressure_grid(ax,200,5200)
    apply_engineering_grid(ax)
    assert ax.get_xlim()==pytest.approx((3.25,33.25))
    assert ax.get_ylim()==pytest.approx((200,5200))


def test_timestamp_formatter_across_midnight():
    from exports import stamp
    from datetime import datetime,timezone
    ts=datetime(2026,11,7,15,58,20,tzinfo=timezone.utc).timestamp()
    assert stamp(ts,8)[11:19]=='23:58:20'
    assert stamp(ts+5*60,8)[11:19]=='00:03:20'
    assert stamp(ts,0)[11:19]=='15:58:20'


def test_reduction_keeps_consecutive_invalid_samples():
    from chart_scale import reduce_live_samples
    rows=[dict(ts=float(i),value=float(i%100),quality='OK') for i in range(12000)]
    for i in range(4000,4040):
        rows[i]['value']=None
        rows[i]['quality']='TIMEOUT'
    reduced=reduce_live_samples(rows)
    assert [r['ts'] for r in reduced if r['quality']=='TIMEOUT']==[float(i) for i in range(4000,4040)]
    assert len(rows)==12000
