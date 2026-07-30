#!/usr/bin/env python3
"""Turn a sweep's results into a report.

    python tools/benchmark/harness/report.py tmp/run/results.json -o tmp/run/report.pdf

Writes a PDF, and an HTML twin beside it unless --no-html. The HTML is one
self-contained file, which is the easier thing to read on screen and to send to
someone; the PDF is the one to attach.

The report keeps four signals apart on purpose:

  solved      did the agent finish at all
  losses      how many attempts it died in before it did
  efficiency  how far it wandered relative to the gold path
  friction    how often its JSON was rejected as unparseable

A level nobody solves is hard. A level nobody solves *and* everyone racks up
schema rejections on is not hard, it is badly documented, and conflating the two
is how a benchmark ends up measuring its own rules text.

With a transcript present (sweep.py writes one per session) the report also says
*where* a run went wrong: per-attempt totals, every obstacle in order, and the
moves the agent thought longest about.
"""
from __future__ import annotations

import argparse
import html
import io
import json
import statistics
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.enums import TA_LEFT  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
    Table, TableStyle,
)

import sys  # noqa: E402

_HARNESS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _HARNESS_DIR.parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.benchmark.harness import timeline  # noqa: E402

INK = colors.HexColor("#1a1a1a")
MUTED = colors.HexColor("#6b7280")
RULE = colors.HexColor("#e5e7eb")
BAND = colors.HexColor("#f8f9fb")

TIER_COLOUR = {
    "trivial": colors.HexColor("#15803d"),
    "borderline": colors.HexColor("#b45309"),
    "hard": colors.HexColor("#b91c1c"),
    "friction": colors.HexColor("#6d28d9"),
    "error": colors.HexColor("#475569"),
}
TIER_HEX = {k: "#" + v.hexval()[2:] for k, v in TIER_COLOUR.items()}

_OUTCOME_HEX = {"lost": "#b91c1c", "solved": "#15803d", "ended": "#6b7280"}


def attempt_outcomes(detail: dict) -> list[str]:
    """What actually became of each attempt.

    Three outcomes, not two. An attempt that was neither lost nor winning —
    abandoned with give_up, or cut off when the run's shared action budget ran
    out — is "ended". Calling those "solved" because they did not lose put the
    word solved on the chart of a run that failed.
    """
    rows = detail["attempts"]
    solved = bool(detail["run"].get("solved"))
    outcomes = []
    for i, row in enumerate(rows):
        if row["lost"]:
            outcomes.append("lost")
        elif solved and i == len(rows) - 1:
            outcomes.append("solved")
        else:
            outcomes.append("ended")
    return outcomes


TIER_MEANING = {
    "trivial": "solved on the first attempt without wandering",
    "borderline": "solved, but needed more than one attempt or well over the gold path",
    "hard": "not solved",
    "friction": "the agent's JSON kept being rejected — a rules-text problem, not a difficulty one",
    "error": "the session failed to run at all",
}


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _fmt(value, spec: str = "", dash: str = "—") -> str:
    if value is None:
        return dash
    return format(value, spec) if spec else str(value)


def summarize(runs: list[dict]) -> list[dict]:
    """Collapse repeats into one row per level."""
    by_level: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for run in runs:
        by_level[(run["pack_id"], run["level_id"])].append(run)

    rows = []
    for (pack, level), group in sorted(by_level.items()):
        solved = [r for r in group if r.get("solved")]
        effs = [r["efficiency"] for r in solved
                if isinstance(r.get("efficiency"), (int, float))]
        rows.append({
            "pack": pack,
            "level": level,
            "runs": len(group),
            "solved": len(solved),
            "solve_rate": len(solved) / len(group) if group else 0.0,
            "gold": next((r.get("gold_path_length") for r in group
                          if r.get("gold_path_length")), None),
            # Averaged over solved runs only. Including failures would mix in
            # runs that stopped at the action budget, making a level the agent
            # never solved look efficient.
            "efficiency": _mean(effs),
            "losses": _mean([r.get("losses", 0) or 0 for r in group]),
            "attempts": _mean([r.get("attempts", 0) or 0 for r in group]),
            "actions": _mean([r.get("actions_total", 0) or 0 for r in group]),
            "schema": _mean([r.get("rejected_schema", 0) or 0 for r in group]),
            "illegal": _mean([r.get("rejected_illegal", 0) or 0 for r in group]),
            "cost": sum(r.get("cost_usd", 0) or 0 for r in group) or None,
            "seconds": _mean([r.get("wall_seconds", 0) or 0 for r in group]),
            "tiers": [r.get("tier", "?") for r in group],
            "errors": [r["error"] for r in group if r.get("error")],
            "group": group,
        })
    return rows


def _dominant_tier(tiers: list[str]) -> str:
    """The tier a level is reported as when repeats disagree.

    Worst-case rather than most-common: a level that friction-failed even once
    has a problem worth looking at, and averaging that away is how it stays
    unnoticed.
    """
    for tier in ("error", "friction", "hard", "borderline", "trivial"):
        if tier in tiers:
            return tier
    return "?"


def session_details(runs: list[dict]) -> list[dict]:
    """Per-session transcript analysis, for runs that recorded one."""
    details = []
    for run in runs:
        path = run.get("transcript")
        if not path:
            continue
        summary = timeline.summarize(Path(path))
        if summary:
            details.append({**summary, "run": run})
    return details


# ── charts ────────────────────────────────────────────────────────────────

def _style_axes(ax):
    ax.grid(axis="y", alpha=0.25, linewidth=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#cbd5e1")
    ax.tick_params(colors="#475569", labelsize=7.5)
    ax.yaxis.label.set_color("#334155")
    ax.yaxis.label.set_size(8.5)


def _chart(rows: list[dict]) -> io.BytesIO:
    fig, axes = plt.subplots(3, 1, figsize=(7.2, 6.6), sharex=True)
    labels = [r["level"] for r in rows]
    x = range(len(rows))

    axes[0].bar(x, [r["solve_rate"] * 100 for r in rows], width=0.62,
                color=[TIER_HEX.get(_dominant_tier(r["tiers"]), "#94a3b8")
                       for r in rows])
    axes[0].set_ylabel("solved %")
    axes[0].set_ylim(0, 105)

    axes[1].bar(x, [r["losses"] or 0 for r in rows], width=0.62, color="#dc2626")
    axes[1].set_ylabel("losses (mean)")

    solved_x = [i for i, r in enumerate(rows) if r["efficiency"] is not None]
    solved_y = [rows[i]["efficiency"] for i in solved_x]
    axes[2].axhline(1.0, color="#15803d", linestyle="--", linewidth=1.1,
                    label="gold path")
    if solved_x:
        axes[2].plot(solved_x, solved_y, "o-", color="#2563eb", markersize=4.5,
                     linewidth=1.4)
    axes[2].set_ylabel("actions / gold")
    axes[2].legend(loc="upper left", fontsize=7.5, frameon=False)

    axes[2].set_xticks(list(x))
    axes[2].set_xticklabels(labels, rotation=90, fontsize=7)
    for ax in axes:
        _style_axes(ax)
    fig.tight_layout(h_pad=1.4)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=170, facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def _attempt_chart(detail: dict) -> io.BytesIO | None:
    """Actions per attempt against the level's own cap.

    The cap is per attempt, so a run's total can exceed it without any single
    attempt doing so — the single most confusing number in a multi-attempt run,
    and the reason this chart exists.
    """
    rows = detail["attempts"]
    if len(rows) < 2:
        return None
    outcomes = attempt_outcomes(detail)
    fig, ax = plt.subplots(figsize=(7.0, 1.9))
    labels = [f"attempt {r['attempt']}" for r in rows]
    values = [r["actions"] for r in rows]
    bars = ax.barh(labels, values, height=0.55,
                   color=[_OUTCOME_HEX[o] for o in outcomes])
    gold = detail["run"].get("gold_path_length")
    if gold:
        ax.axvline(gold, color="#15803d", linestyle="--", linewidth=1.1)
        ax.text(gold, -0.75, f" gold {gold}", color="#15803d", fontsize=7.5)
    for bar, outcome in zip(bars, outcomes):
        ax.text(bar.get_width() + 0.35, bar.get_y() + bar.get_height() / 2,
                outcome, va="center", fontsize=7.5,
                color=_OUTCOME_HEX[outcome])
    ax.set_xlabel("actions used", fontsize=8.5, color="#334155")
    ax.invert_yaxis()
    _style_axes(ax)
    ax.grid(axis="y", alpha=0)
    ax.grid(axis="x", alpha=0.25, linewidth=0.6)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=170, facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


# ── PDF ───────────────────────────────────────────────────────────────────

def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontSize=19,
                                leading=23, textColor=INK, alignment=TA_LEFT,
                                spaceAfter=2),
        "sub": ParagraphStyle("s", parent=base["Normal"], fontSize=9.5,
                              leading=13, textColor=MUTED),
        "h1": ParagraphStyle("h1", parent=base["Heading1"], fontSize=13.5,
                             leading=17, textColor=INK, spaceBefore=2,
                             spaceAfter=5),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontSize=10.5,
                             leading=14, textColor=INK, spaceBefore=8,
                             spaceAfter=3),
        "body": ParagraphStyle("b", parent=base["Normal"], fontSize=8.6,
                               leading=12, textColor=INK),
        "small": ParagraphStyle("sm", parent=base["Normal"], fontSize=7.8,
                                leading=10.5, textColor=MUTED),
        "quote": ParagraphStyle("q", parent=base["Normal"], fontSize=7.8,
                                leading=10.5, textColor=colors.HexColor("#334155"),
                                leftIndent=7, borderPadding=0),
        "mono": ParagraphStyle("m", parent=base["Normal"], fontSize=7.6,
                               leading=10, fontName="Courier", textColor=INK),
    }


def _kv_table(pairs: list[tuple[str, str]]) -> Table:
    table = Table([[k, v] for k, v in pairs], colWidths=[52 * mm, 108 * mm])
    table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), MUTED),
        ("TEXTCOLOR", (1, 0), (1, -1), INK),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE),
    ]))
    return table


def _truncate(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _reply_lines(entry: dict, turn: dict, limit: int = 2) -> list[str]:
    """What to print under one ./play call in the appendix.

    Not the reply itself. A `state` call answers with the whole board, and
    seventy-odd boards is how an appendix stops being read. What earns the
    space is the moment the game disagreed with the agent — a rejection, a
    reset, the end of the run — plus a one-line receipt for the moves that
    simply worked, so the action count stays visible without printing a grid
    to carry it.
    """
    if not turn:
        return []
    notable = (turn.get("rejected_schema") or turn.get("rejected_illegal")
               or turn.get("lost_attempt") or turn.get("terminal"))
    if notable:
        lines = [ln for ln in (turn.get("response") or "").splitlines() if ln.strip()]
        return [_truncate(ln, 150) for ln in lines[:limit]]
    if entry.get("verb") == "move":
        return [f"-> accepted, attempt {turn.get('attempt', '?')}, "
                f"action {turn.get('actions_total', '?')}"]
    return []


def _obstacle_rows(detail: dict, st: dict, limit: int = 12) -> list:
    flow = []
    for ob in detail["obstacles"][:limit]:
        kinds = ", ".join(ob["kinds"])
        colour = "#b91c1c" if ob.get("lost_attempt") else "#b45309"
        head = (f'<font color="{colour}"><b>{html.escape(kinds)}</b></font> '
                f'&nbsp;·&nbsp; attempt {ob.get("attempt", "?")}, '
                f'action {ob.get("actions_total", "?")}, '
                f'{ob.get("elapsed", 0):.0f}s in')
        flow.append(Paragraph(head, st["body"]))
        sent = " ".join(ob.get("args") or [])
        if sent:
            flow.append(Paragraph(f"sent: {html.escape(_truncate(sent, 150))}",
                                  st["mono"]))
        reply = (ob.get("response") or "").splitlines()
        if reply:
            flow.append(Paragraph(f"reply: {html.escape(_truncate(reply[0], 150))}",
                                  st["mono"]))
        if ob.get("reasoning"):
            # Say whose words these are. A quote lifted from an earlier turn
            # explains that turn, not this one, and presenting it unlabelled
            # would attribute a reason to a move the agent made in silence.
            label = ("" if ob.get("reasoning_fresh")
                     else " <font color='#94a3b8'>(no narration for this move; "
                          "carried forward from an earlier turn)</font>")
            flow.append(Paragraph(
                f'<i>“{html.escape(_truncate(ob["reasoning"], 320))}”</i>{label}',
                st["quote"]))
        flow.append(Spacer(1, 3.5 * mm))
    if len(detail["obstacles"]) > limit:
        flow.append(Paragraph(
            f"…and {len(detail['obstacles']) - limit} more; the full record is "
            f"in the transcript.", st["small"]))
    return flow


def build(payload: dict, out_path: Path) -> Path:
    meta = payload.get("meta", {})
    runs = payload.get("runs", [])
    rows = summarize(runs)
    details = session_details(runs)
    st = _styles()

    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=16 * mm, rightMargin=16 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title="GridPonder agent benchmark", author="GridPonder",
    )
    story = []

    agent_label = meta.get("agent", "?")
    if meta.get("model"):
        agent_label += f" · {meta['model']}"
    story.append(Paragraph("GridPonder agent benchmark", st["title"]))
    story.append(Paragraph(
        f"{html.escape(agent_label)} &nbsp;·&nbsp; "
        f"{meta.get('levels', len(rows))} level(s) × {meta.get('repeats', 1)} "
        f"repeat(s) &nbsp;·&nbsp; "
        f"{'anonymous' if meta.get('anon') else 'clear'} mode", st["sub"]))
    story.append(Spacer(1, 6 * mm))

    solved_runs = sum(1 for r in runs if r.get("solved"))
    total_cost = sum(r.get("cost_usd", 0) or 0 for r in runs)
    isolation_mode = meta.get("isolation", "?")
    story.append(_kv_table([
        ("Sessions", str(len(runs))),
        ("Solved", f"{solved_runs}/{len(runs)}"
                   + (f"  ({solved_runs / len(runs) * 100:.0f}%)" if runs else "")),
        ("Levels never solved", str(sum(1 for r in rows if r["solved"] == 0))),
        ("Total losses", str(sum(r.get("losses", 0) or 0 for r in runs))),
        ("Attempts allowed per run", str(meta.get("max_attempts", "—"))),
        ("Isolation", isolation_mode),
        ("Wall clock", f"{meta.get('wall_seconds', 0):.0f}s"),
        ("Cost", f"${total_cost:.4f}" if total_cost else "—"),
    ]))
    story.append(Spacer(1, 6 * mm))

    if isolation_mode == "none":
        story.append(Paragraph(
            '<font color="#b91c1c"><b>These numbers are not verified.</b></font> '
            "The sweep ran without filesystem confinement, so the agent could "
            "read the pack and its gold path directly. Re-run with isolation "
            "before quoting any of this.", st["body"]))
        story.append(Spacer(1, 5 * mm))

    story.append(Paragraph("How to read this", st["h2"]))
    for tier, meaning in TIER_MEANING.items():
        story.append(Paragraph(
            f'<font color="{TIER_HEX[tier]}"><b>{tier}</b></font> — {meaning}',
            st["body"]))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(
        "Rejections are split on purpose. <b>schema</b> means the agent could "
        "not express what it meant, and counts against the level's rules text. "
        "<b>illegal</b> means it expressed itself fine and the board said no, "
        "which is ordinary probing and never counts against a level.",
        st["small"]))
    story.append(Spacer(1, 2.5 * mm))
    story.append(Paragraph(
        "A level's action cap is <b>per attempt</b>, so a run's total actions "
        "can exceed it without any single attempt having done so.", st["small"]))

    if rows:
        story.append(PageBreak())
        story.append(Paragraph("Per level", st["h1"]))
        story.append(Image(_chart(rows), width=168 * mm, height=154 * mm))

    story.append(PageBreak())
    story.append(Paragraph("Results", st["h1"]))
    header = ["Level", "Tier", "Solved", "Gold", "Actions", "Eff.",
              "Att.", "Loss", "Schema", "Illegal", "Sec"]
    data = [header]
    for row in rows:
        data.append([
            row["level"], _dominant_tier(row["tiers"]),
            f"{row['solved']}/{row['runs']}",
            _fmt(row["gold"]), _fmt(row["actions"], ".0f"),
            _fmt(row["efficiency"], ".2f"), _fmt(row["attempts"], ".1f"),
            _fmt(row["losses"], ".1f"), _fmt(row["schema"], ".1f"),
            _fmt(row["illegal"], ".1f"), _fmt(row["seconds"], ".0f"),
        ])
    results = Table(data, repeatRows=1, hAlign="LEFT")
    style = [
        ("FONTSIZE", (0, 0), (-1, -1), 7.6),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f5")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (-1, 0), INK),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.35, RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for i, row in enumerate(rows, start=1):
        style.append(("TEXTCOLOR", (1, i), (1, i),
                      TIER_COLOUR.get(_dominant_tier(row["tiers"]), INK)))
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), BAND))
    results.setStyle(TableStyle(style))
    story.append(results)

    for detail in details:
        run = detail["run"]
        story.append(PageBreak())
        story.append(Paragraph(
            f"Session: {run['pack_id']}/{run['level_id']}", st["h1"]))
        story.append(Paragraph(
            f"{detail['turns']} ./play calls — {detail['moves']} moves, "
            f"{detail['looks']} looks at the board — over "
            f"{run.get('wall_seconds', 0):.0f}s", st["sub"]))
        story.append(Spacer(1, 4 * mm))

        attempt_data = [["Attempt", "Actions", "Schema", "Illegal", "Outcome"]]
        for a, outcome in zip(detail["attempts"], attempt_outcomes(detail)):
            attempt_data.append([
                str(a["attempt"]), str(a["actions"]),
                str(a["rejected_schema"]), str(a["rejected_illegal"]), outcome,
            ])
        table = Table(attempt_data, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f5")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.35, RULE),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(table)

        chart = _attempt_chart(detail)
        if chart is not None:
            story.append(Spacer(1, 4 * mm))
            story.append(Image(chart, width=165 * mm, height=45 * mm))

        story.append(Paragraph("Where it got stuck", st["h2"]))
        if detail["obstacles"]:
            story.extend(_obstacle_rows(detail, st))
        else:
            story.append(Paragraph(
                "No rejections and no lost attempts. Every command the agent "
                "sent was well-formed and legal.", st["body"]))

        if detail["slowest"]:
            story.append(Paragraph("Longest deliberations", st["h2"]))
            story.append(Paragraph(
                "Time from the previous reply going out to this request "
                "arriving — for a hosted model, the time it spent deciding.",
                st["small"]))
            story.append(Spacer(1, 2 * mm))
            slow = [["Thought", "At", "Attempt", "Command"]]
            for turn in detail["slowest"]:
                slow.append([
                    f"{turn.get('thought_for', 0):.0f}s",
                    f"{turn.get('elapsed', 0):.0f}s",
                    str(turn.get("attempt", "?")),
                    _truncate(f"{turn['verb']} {' '.join(turn.get('args') or [])}", 62),
                ])
            table = Table(slow, hAlign="LEFT",
                          colWidths=[16 * mm, 16 * mm, 18 * mm, 118 * mm])
            table.setStyle(TableStyle([
                ("FONTSIZE", (0, 0), (-1, -1), 7.4),
                ("FONTNAME", (3, 1), (3, -1), "Courier"),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f5")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.35, RULE),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            story.append(table)

    for detail in details:
        if not detail.get("dialogue"):
            continue
        run = detail["run"]
        cov = detail.get("coverage") or {}
        story.append(PageBreak())
        story.append(Paragraph(
            f"Appendix: {run['pack_id']}/{run['level_id']} — the run as a "
            f"conversation", st["h1"]))
        story.append(Paragraph(
            "The agent's reasoning, the command it produced, and what the game "
            "said back, in order. Both halves are here because tripping is a "
            "disagreement between the two — a plan that looked sound against a "
            "board that did something else."
            + (f" {cov['explained']} of {cov['calls']} commands arrived with "
               f"their own reasoning ({cov['ratio']:.0%}); the rest the agent "
               f"sent in silence." if cov.get("calls") else ""),
            st["small"]))
        story.append(Spacer(1, 4 * mm))
        for entry in detail["dialogue"]:
            if entry["kind"] == "thought":
                # A reason the agent handed to ./play is set apart from one
                # scraped out of its output stream: the first was written for
                # the move below it, the second merely preceded it.
                style, text = ((st["quote"], f'<i>why: {html.escape(entry["text"])}</i>')
                               if entry.get("stated")
                               else (st["body"],
                                     html.escape(entry["text"]).replace("\n", "<br/>")))
                story.append(KeepTogether([
                    Paragraph(text, style), Spacer(1, 2 * mm)]))
                continue
            turn = entry.get("turn") or {}
            flow = [Paragraph(
                f"&nbsp;&nbsp;./play {html.escape(_truncate(entry['call'], 130))}",
                st["mono"])]
            reply = _reply_lines(entry, turn)
            if reply:
                flow.append(Paragraph(
                    "&nbsp;&nbsp;&nbsp;&nbsp;" + "<br/>".join(
                        html.escape(line) for line in reply), st["mono"]))
            flow.append(Spacer(1, 3 * mm))
            story.append(KeepTogether(flow))

    errors = [(r, e) for r in rows for e in r["errors"]]
    if errors:
        story.append(PageBreak())
        story.append(Paragraph("Sessions that failed to run", st["h1"]))
        story.append(Paragraph(
            "Harness failures, not agent results. Listed because they were "
            "still counted as unsolved runs above.", st["small"]))
        story.append(Spacer(1, 3 * mm))
        for row, err in errors[:20]:
            story.append(KeepTogether([
                Paragraph(f"<b>{row['pack']}/{row['level']}</b>", st["body"]),
                Paragraph(html.escape(err[:500]), st["mono"]),
                Spacer(1, 3 * mm),
            ]))

    doc.build(story)
    return out_path


# ── HTML ──────────────────────────────────────────────────────────────────

_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { margin: 0; padding: 2.5rem 1.25rem 5rem; font: 15px/1.6 -apple-system,
  BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  color: #17181c; background: #fff; }
main { max-width: 62rem; margin: 0 auto; }
h1 { font-size: 1.75rem; margin: 0 0 .2rem; letter-spacing: -.02em; }
h2 { font-size: 1.1rem; margin: 2.6rem 0 .7rem; letter-spacing: -.01em; }
h3 { font-size: .95rem; margin: 1.6rem 0 .5rem; }
.sub { color: #6b7280; margin: 0 0 2rem; }
.facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(9.5rem, 1fr));
  gap: .75rem; margin: 0 0 2rem; }
.fact { border: 1px solid #e5e7eb; border-radius: .6rem; padding: .7rem .85rem; }
.fact dt { color: #6b7280; font-size: .72rem; text-transform: uppercase;
  letter-spacing: .06em; margin: 0 0 .25rem; }
.fact dd { margin: 0; font-size: 1.25rem; font-weight: 650; }
.warn { border-left: 3px solid #b91c1c; background: #fef2f2; padding: .8rem 1rem;
  border-radius: .35rem; margin: 0 0 1.5rem; }
.tablewrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: .84rem; }
th { text-align: left; background: #eef1f5; font-weight: 650; }
th, td { padding: .45rem .6rem; border-bottom: 1px solid #e5e7eb;
  white-space: nowrap; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
tbody tr:nth-child(even) { background: #f8f9fb; }
.tier { font-weight: 650; }
.legend li { margin: .25rem 0; }
.ob { border-left: 3px solid #e5e7eb; padding: .1rem 0 .1rem .9rem;
  margin: 0 0 1.2rem; }
.ob.lost { border-left-color: #b91c1c; }
.ob.rej { border-left-color: #b45309; }
.ob .when { color: #6b7280; font-size: .8rem; }
.ob code, code { display: block; font-size: .78rem; background: #f5f6f8;
  padding: .3rem .5rem; border-radius: .3rem; margin: .3rem 0;
  overflow-x: auto; white-space: pre; }
/* The game's half of the appendix dialogue: indented and quieter than the
   command above it, so a page of the two reads as call and response. */
code.reply { background: none; color: #6b7280; margin: 0 0 .3rem 1.4rem;
  padding: .1rem 0; }
blockquote { margin: .45rem 0 0; padding: 0 0 0 .8rem;
  border-left: 2px solid #d1d5db; color: #4b5563; font-size: .86rem; }
img { max-width: 100%; height: auto; display: block; margin: 1rem 0; }
footer { margin-top: 3.5rem; padding-top: 1rem; border-top: 1px solid #e5e7eb;
  color: #6b7280; font-size: .8rem; }
@media (prefers-color-scheme: dark) {
  body { background: #101114; color: #e6e7ea; }
  .fact, th, td, footer, blockquote { border-color: #2a2c33; }
  .fact { border-color: #2a2c33; }
  th { background: #1a1c21; }
  tbody tr:nth-child(even) { background: #16181c; }
  .ob code, code { background: #1a1c21; }
  code.reply { background: none; color: #9aa0aa; }
  .warn { background: #2a1416; }
  .sub, .ob .when, footer { color: #9aa0aa; }
}
"""


def _html_table(header: list[str], rows: list[list[str]],
                tier_col: int | None = None) -> str:
    head = "".join(
        f'<th class="num">{html.escape(h)}</th>' if i >= 2 else f"<th>{html.escape(h)}</th>"
        for i, h in enumerate(header))
    body = []
    for row in rows:
        cells = []
        for i, cell in enumerate(row):
            text = html.escape(str(cell))
            if i == tier_col:
                text = (f'<span class="tier" style="color:'
                        f'{TIER_HEX.get(cell, "#475569")}">{text}</span>')
            cells.append(f'<td class="num">{text}</td>' if i >= 2 else f"<td>{text}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (f'<div class="tablewrap"><table><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def build_html(payload: dict, out_path: Path) -> Path:
    import base64

    meta = payload.get("meta", {})
    runs = payload.get("runs", [])
    rows = summarize(runs)
    details = session_details(runs)

    solved_runs = sum(1 for r in runs if r.get("solved"))
    total_cost = sum(r.get("cost_usd", 0) or 0 for r in runs)
    isolation_mode = meta.get("isolation", "?")

    agent_label = meta.get("agent", "?")
    if meta.get("model"):
        agent_label += f" · {meta['model']}"

    facts = [
        ("Sessions", str(len(runs))),
        ("Solved", f"{solved_runs}/{len(runs)}"),
        ("Never solved", str(sum(1 for r in rows if r["solved"] == 0))),
        ("Total losses", str(sum(r.get("losses", 0) or 0 for r in runs))),
        ("Attempts allowed", str(meta.get("max_attempts", "—"))),
        ("Isolation", isolation_mode),
        ("Wall clock", f"{meta.get('wall_seconds', 0):.0f}s"),
        ("Cost", f"${total_cost:.4f}" if total_cost else "—"),
    ]
    parts = [
        "<main>",
        "<h1>GridPonder agent benchmark</h1>",
        f'<p class="sub">{html.escape(agent_label)} · '
        f'{meta.get("levels", len(rows))} level(s) × {meta.get("repeats", 1)} '
        f'repeat(s) · {"anonymous" if meta.get("anon") else "clear"} mode</p>',
        '<dl class="facts">'
        + "".join(f'<div class="fact"><dt>{html.escape(k)}</dt>'
                  f"<dd>{html.escape(v)}</dd></div>" for k, v in facts)
        + "</dl>",
    ]
    if isolation_mode == "none":
        parts.append(
            '<div class="warn"><b>These numbers are not verified.</b> The sweep '
            "ran without filesystem confinement, so the agent could read the "
            "pack and its gold path directly.</div>")

    parts.append("<h2>How to read this</h2><ul class=\"legend\">")
    for tier, meaning in TIER_MEANING.items():
        parts.append(f'<li><b style="color:{TIER_HEX[tier]}">{tier}</b> — '
                     f"{html.escape(meaning)}</li>")
    parts.append("</ul>")
    parts.append(
        "<p><b>schema</b> rejections mean the agent could not express what it "
        "meant, and count against the level's rules text. <b>illegal</b> ones "
        "mean it expressed itself fine and the board said no — ordinary "
        "probing, never held against a level. A level's action cap is "
        "<b>per attempt</b>, so a run's total can exceed it without any single "
        "attempt having done so.</p>")

    if rows:
        png = base64.b64encode(_chart(rows).read()).decode("ascii")
        parts.append("<h2>Per level</h2>")
        parts.append(f'<img alt="per level charts" src="data:image/png;base64,{png}">')

    parts.append("<h2>Results</h2>")
    parts.append(_html_table(
        ["Level", "Tier", "Solved", "Gold", "Actions", "Eff.", "Att.", "Loss",
         "Schema", "Illegal", "Sec"],
        [[r["level"], _dominant_tier(r["tiers"]), f"{r['solved']}/{r['runs']}",
          _fmt(r["gold"]), _fmt(r["actions"], ".0f"), _fmt(r["efficiency"], ".2f"),
          _fmt(r["attempts"], ".1f"), _fmt(r["losses"], ".1f"),
          _fmt(r["schema"], ".1f"), _fmt(r["illegal"], ".1f"),
          _fmt(r["seconds"], ".0f")] for r in rows],
        tier_col=1))

    for detail in details:
        run = detail["run"]
        parts.append(f'<h2>Session: {html.escape(run["pack_id"])}/'
                     f'{html.escape(run["level_id"])}</h2>')
        parts.append(
            f'<p class="sub">{detail["turns"]} ./play calls — '
            f'{detail["moves"]} moves, {detail["looks"]} looks at the board — '
            f'over {run.get("wall_seconds", 0):.0f}s</p>')
        attempt_rows = [
            [str(a["attempt"]), outcome, str(a["actions"]),
             str(a["rejected_schema"]), str(a["rejected_illegal"])]
            for a, outcome in zip(detail["attempts"], attempt_outcomes(detail))
        ]
        parts.append(_html_table(
            ["Attempt", "Outcome", "Actions", "Schema", "Illegal"], attempt_rows))

        chart = _attempt_chart(detail)
        if chart is not None:
            png = base64.b64encode(chart.read()).decode("ascii")
            parts.append(f'<img alt="actions per attempt" '
                         f'src="data:image/png;base64,{png}">')

        parts.append("<h3>Where it got stuck</h3>")
        if not detail["obstacles"]:
            parts.append("<p>No rejections and no lost attempts. Every command "
                         "the agent sent was well-formed and legal.</p>")
        for ob in detail["obstacles"][:40]:
            css = "lost" if ob.get("lost_attempt") else "rej"
            parts.append(f'<div class="ob {css}">')
            parts.append(
                f'<div class="when"><b>{html.escape(", ".join(ob["kinds"]))}</b>'
                f' · attempt {ob.get("attempt", "?")}, action '
                f'{ob.get("actions_total", "?")}, {ob.get("elapsed", 0):.0f}s in</div>')
            sent = " ".join(ob.get("args") or [])
            if sent:
                parts.append(f"<code>{html.escape(_truncate(sent, 400))}</code>")
            reply = (ob.get("response") or "").splitlines()
            if reply:
                parts.append(f"<code>{html.escape(_truncate(reply[0], 400))}</code>")
            if ob.get("reasoning"):
                label = ("" if ob.get("reasoning_fresh")
                         else '<span class="sub"> (no narration for this move; '
                              "carried forward from an earlier turn)</span>")
                parts.append(
                    f"<blockquote>{html.escape(_truncate(ob['reasoning'], 900))}"
                    f"{label}</blockquote>")
            parts.append("</div>")

        if detail["slowest"]:
            parts.append("<h3>Longest deliberations</h3>")
            parts.append('<p class="sub">Time from the previous reply going out '
                         "to this request arriving — for a hosted model, the "
                         "time it spent deciding.</p>")
            parts.append(_html_table(
                ["Command", "Attempt", "Thought", "At"],
                [[_truncate(f"{t['verb']} {' '.join(t.get('args') or [])}", 90),
                  str(t.get("attempt", "?")), f"{t.get('thought_for', 0):.0f}s",
                  f"{t.get('elapsed', 0):.0f}s"] for t in detail["slowest"]]))

    for detail in details:
        if not detail.get("dialogue"):
            continue
        run = detail["run"]
        cov = detail.get("coverage") or {}
        parts.append(f'<h2>Appendix: {html.escape(run["pack_id"])}/'
                     f'{html.escape(run["level_id"])} — the run as a '
                     "conversation</h2>")
        parts.append(
            '<p class="sub">The agent\'s reasoning, the command it produced, '
            "and what the game said back, in order. Both halves are here "
            "because tripping is a disagreement between the two."
            + (f" {cov['explained']} of {cov['calls']} commands arrived with "
               f"their own reasoning ({cov['ratio']:.0%}); the rest the agent "
               f"sent in silence." if cov.get("calls") else "")
            + "</p>")
        for entry in detail["dialogue"]:
            if entry["kind"] == "thought":
                if entry.get("stated"):
                    parts.append("<blockquote>why: "
                                 + html.escape(entry["text"]) + "</blockquote>")
                else:
                    parts.append('<div class="ob"><p>'
                                 + html.escape(entry["text"]).replace("\n", "<br>")
                                 + "</p></div>")
                continue
            turn = entry.get("turn") or {}
            parts.append(f'<code>./play {html.escape(entry["call"])}</code>')
            for line in _reply_lines(entry, turn):
                parts.append(f'<code class="reply">{html.escape(line)}</code>')

    errors = [(r, e) for r in rows for e in r["errors"]]
    if errors:
        parts.append("<h2>Sessions that failed to run</h2>")
        parts.append('<p class="sub">Harness failures, not agent results.</p>')
        for row, err in errors[:20]:
            parts.append(f'<div class="ob"><div class="when"><b>{row["pack"]}/'
                         f'{row["level"]}</b></div>'
                         f"<code>{html.escape(err[:800])}</code></div>")

    parts.append(
        '<footer>Generated by tools/benchmark/harness/report.py. Counters come '
        "from the run results; the per-session sections come from the "
        "transcripts written alongside them.</footer></main>")

    out_path.write_text(
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>GridPonder agent benchmark</title>"
        f"<style>{_CSS}</style></head><body>" + "".join(parts) + "</body></html>",
        encoding="utf-8",
    )
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Report for a harness sweep")
    parser.add_argument("results", help="results.json written by sweep.py")
    parser.add_argument("-o", "--out", default=None, help="Output PDF path")
    parser.add_argument("--no-html", action="store_true", default=False,
                        help="Skip the HTML twin")
    args = parser.parse_args()

    results_path = Path(args.results)
    payload = json.loads(results_path.read_text())
    out_path = Path(args.out) if args.out else results_path.with_suffix(".pdf")
    build(payload, out_path)
    print(f"wrote {out_path}")
    if not args.no_html:
        html_path = build_html(payload, out_path.with_suffix(".html"))
        print(f"wrote {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
