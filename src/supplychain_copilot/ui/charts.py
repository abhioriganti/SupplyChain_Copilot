"""Plotly figures for the dashboard. Pure functions: DataFrame in, Figure out (unit-testable)."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

MARKET_COLORS = {
    "Africa": "#E07A5F",
    "Europe": "#3D5A80",
    "LATAM": "#81B29A",
    "Pacific Asia": "#F2CC8F",
    "USCA": "#6D597A",
}
_LAYOUT = dict(margin=dict(l=10, r=10, t=50, b=10), legend_title_text="Market", font=dict(size=12))


def late_rate_by_region(df: pd.DataFrame, top_n: int = 23) -> go.Figure:
    d = df.sort_values("LATE_DELIVERY_RATE", ascending=True).tail(top_n)
    fig = px.bar(
        d,
        x="LATE_DELIVERY_RATE",
        y="ORDER_REGION",
        color="MARKET",
        orientation="h",
        color_discrete_map=MARKET_COLORS,
        custom_data=["LATE_SHIPMENTS", "ELIGIBLE_SHIPMENTS", "MARKET"],
        title="Late-delivery rate by destination region",
    )
    fig.update_traces(
        hovertemplate="<b>%{y}</b> (%{customdata[2]})<br>Late rate %{x:.1%}<br>"
        "%{customdata[0]:,} late of %{customdata[1]:,} eligible shipments<extra></extra>",
        texttemplate="%{x:.1%}",
        textposition="outside",
    )
    lo = float(d["LATE_DELIVERY_RATE"].min()) if not d.empty else 0.0
    fig.update_layout(
        **_LAYOUT,
        xaxis=dict(tickformat=".0%", range=[max(0.0, lo - 0.08), 0.66], title="Late-delivery rate"),
        yaxis=dict(title=None, categoryorder="total ascending"),
        height=620,
    )
    return fig


def shipping_mode_performance(df: pd.DataFrame) -> go.Figure:
    d = df.sort_values("SCHEDULED_SHIPPING_DAYS")
    labels = [
        f"{m}<br>(scheduled {int(s)} d)"
        for m, s in zip(d["SHIPPING_MODE"], d["SCHEDULED_SHIPPING_DAYS"], strict=False)
    ]
    fig = go.Figure()
    fig.add_bar(
        x=labels,
        y=d["ON_TIME_DELIVERY_RATE"],
        name="On-time rate",
        marker_color="#3D5A80",
        text=[f"{v:.1%}" for v in d["ON_TIME_DELIVERY_RATE"]],
        textposition="outside",
        customdata=list(zip(d["AVG_ACTUAL_SHIPPING_DAYS"], d["ELIGIBLE_SHIPMENTS"], strict=False)),
        hovertemplate="%{x}<br>On-time %{y:.1%}<br>Avg actual %{customdata[0]:.2f} days<br>"
        "%{customdata[1]:,} eligible shipments<extra></extra>",
    )
    fig.update_layout(
        **{**_LAYOUT, "legend_title_text": None},
        title="On-time delivery rate by shipping mode",
        yaxis=dict(tickformat=".0%", range=[0, 1.05], title="On-time rate"),
        showlegend=False,
        height=420,
    )
    return fig


def monthly_late_rate(df: pd.DataFrame, min_shipments: int = 100) -> go.Figure:
    """Market-months with fewer than `min_shipments` eligible shipments (the hand-over months where a
    market contributes only a few orders) are hidden: their rates are noise, not trend."""
    df = df[df["ELIGIBLE_SHIPMENTS"] >= min_shipments]
    # Put every market on the full monthly grid so months where a market is absent are NaN; Plotly then
    # breaks the line instead of drawing a diagonal across the months the market wasn't in the data.
    if not df.empty:
        months = pd.date_range(df["ORDER_MONTH"].min(), df["ORDER_MONTH"].max(), freq="MS")
        grid = pd.MultiIndex.from_product(
            [months, sorted(df["MARKET"].unique())], names=["ORDER_MONTH", "MARKET"]
        )
        df = df.set_index(["ORDER_MONTH", "MARKET"]).reindex(grid).reset_index()
    fig = px.line(
        df,
        x="ORDER_MONTH",
        y="LATE_DELIVERY_RATE",
        color="MARKET",
        markers=True,
        color_discrete_map=MARKET_COLORS,
        custom_data=["ELIGIBLE_SHIPMENTS"],
        title="Monthly late-delivery rate, by market",
    )
    fig.update_traces(connectgaps=False)
    fig.update_traces(
        hovertemplate="%{x|%b %Y}<br>Late rate %{y:.1%}<br>%{customdata[0]:,} eligible shipments<extra></extra>"
    )
    fig.update_layout(
        **_LAYOUT,
        yaxis=dict(tickformat=".0%", title="Late-delivery rate"),
        xaxis=dict(title=None),
        height=420,
    )
    return fig
