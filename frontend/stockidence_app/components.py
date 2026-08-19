from __future__ import annotations

import reflex as rx

from .state import RatingState

ADVICE_LABELS = {
    "STRONG_BUY": "Strong Buy",
    "BUY": "Buy",
    "HOLD": "Hold",
    "SELL": "Sell",
    "STRONG_SELL": "Strong Sell",
}

HOLDING_LABELS = {
    "long_term_hold": "Long-term hold",
    "swing_trade": "Swing trade",
    "day_trade": "Day trade",
}

ADVICE_COLOR_SCHEMES = {
    "STRONG_BUY": "green",
    "BUY": "teal",
    "HOLD": "amber",
    "SELL": "orange",
    "STRONG_SELL": "red",
}

ADVICE_COLORS = {
    "STRONG_BUY": rx.color("green", 9),
    "BUY": rx.color("teal", 9),
    "HOLD": rx.color("amber", 9),
    "SELL": rx.color("orange", 9),
    "STRONG_SELL": rx.color("red", 9),
}

ADVICE_FILLS = {
    "STRONG_BUY": rx.color("green", 8),
    "BUY": rx.color("teal", 8),
    "HOLD": rx.color("amber", 8),
    "SELL": rx.color("orange", 8),
    "STRONG_SELL": rx.color("red", 8),
}


def _advice_color_scheme() -> rx.Var:
    return rx.match(
        RatingState.advice,
        *[
            (key, scheme)
            for key, scheme in ADVICE_COLOR_SCHEMES.items()
        ],
        "gray",
    )


def _advice_color() -> rx.Var:
    return rx.match(
        RatingState.advice,
        *[
            (key, color)
            for key, color in ADVICE_COLORS.items()
        ],
        rx.color("slate", 9),
    )


def _advice_fill_color() -> rx.Var:
    return rx.match(
        RatingState.advice,
        *[
            (key, color)
            for key, color in ADVICE_FILLS.items()
        ],
        rx.color("slate", 8),
    )


def _advice_label() -> rx.Var:
    return rx.match(
        RatingState.advice,
        *[
            (key, label)
            for key, label in ADVICE_LABELS.items()
        ],
        RatingState.advice,
    )


BODY_CARD_PADDING = "5"


def top_nav() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.link(
                rx.hstack(
                    rx.image(
                        src="/bull_logo.svg",
                        alt="Stockidence bull",
                        width="26px",
                        height="26px",
                    ),
                    rx.heading(
                        "Stockidence",
                        size="4",
                        weight="bold",
                        color=rx.color("iris", 9),
                    ),
                    spacing="3",
                ),
                href="/",
                underline="none",
                flex_shrink="0",
            ),
            rx.hstack(
                rx.link(
                    "Discover",
                    href="/discover",
                    size="2",
                    weight="medium",
                    underline="none",
                    color=rx.color("slate", 11),
                    _hover={"color": rx.color("iris", 9)},
                ),
                rx.link(
                    "Documentation",
                    href="/documentation",
                    size="2",
                    weight="medium",
                    underline="none",
                    color=rx.color("slate", 11),
                    _hover={"color": rx.color("iris", 9)},
                ),
                spacing="4",
                flex_shrink="0",
            ),
            search_form(),
            width="100%",
            justify="between",
            align="center",
            padding_y="3",
        ),
        rx.separator(width="100%"),
        width="100%",
    )


def hero() -> rx.Component:
    return rx.vstack(
        rx.badge(
            rx.hstack(
                rx.icon("shield_check", size=12),
                rx.text("Deterministic model — transparent, never a black box", size="1"),
                spacing="1",
            ),
            color_scheme="iris",
            variant="soft",
            radius="full",
        ),
        rx.heading(
            "How confident should you be in that stock?",
            size="7",
            weight="bold",
            letter_spacing="-0.02em",
            text_align="center",
        ),
        rx.text(
            "Stockidence turns messy market data into a single confidence rating for any ticker. "
            "Search from the bar above and get a transparent, rule-based score and advice in seconds.",
            size="3",
            color=rx.color("slate", 10),
            text_align="center",
            max_width="34em",
        ),
        rx.grid(
            rx.vstack(
                rx.heading("Valuation", size="2", weight="bold"),
                rx.text("40% weight", size="1", color=rx.color("slate", 10)),
                align="center",
                spacing="1",
            ),
            rx.vstack(
                rx.heading("Trend", size="2", weight="bold"),
                rx.text("25% weight", size="1", color=rx.color("slate", 10)),
                align="center",
                spacing="1",
            ),
            rx.vstack(
                rx.heading("Momentum", size="2", weight="bold"),
                rx.text("15% weight", size="1", color=rx.color("slate", 10)),
                align="center",
                spacing="1",
            ),
            rx.vstack(
                rx.heading("Sentiment", size="2", weight="bold"),
                rx.text("20% weight", size="1", color=rx.color("slate", 10)),
                align="center",
                spacing="1",
            ),
            columns=rx.breakpoints(initial="2", md="4"),
            spacing="6",
            width="100%",
            padding_y="3",
        ),
        rx.text(
            "Volatility is reported separately — it is never blended into the confidence rating.",
            size="1",
            color=rx.color("slate", 9),
            text_align="center",
        ),
        spacing="3",
        align="center",
        width="100%",
        padding_y="4",
    )


def search_form() -> rx.Component:
    return rx.form(
        rx.hstack(
            rx.input(
                placeholder="Search a ticker (e.g. AAPL)",
                name="ticker",
                size="2",
                width="260px",
                variant="soft",
                radius="full",
                padding="3",
                border=f"1px solid {rx.color('iris', 7)}",
            ),
            rx.button(
                rx.hstack(
                    rx.icon("search", size=14),
                    rx.text("Rate it", size="2", weight="medium"),
                    spacing="1",
                ),
                type="submit",
                size="2",
                variant="solid",
                color_scheme="iris",
                radius="large",
            ),
            width="auto",
            spacing="2",
        ),
        on_submit=RatingState.submit,
        width="auto",
        flex_shrink="0",
    )


def error_callout() -> rx.Component:
    return rx.callout(
        RatingState.error,
        icon="circle_alert",
        color_scheme="red",
        size="3",
        width="100%",
        variant="surface",
    )


def advice_badge() -> rx.Component:
    return rx.badge(
        _advice_label(),
        color_scheme=_advice_color_scheme(),
        size="3",
        radius="full",
        padding_x="4",
        padding_y="2",
        variant="soft",
    )


def source_badge() -> rx.Component:
    return rx.badge(
        rx.match(
            RatingState.source,
            ("warehouse", "Warehouse data"),
            "Demo sample",
        ),
        color_scheme=rx.match(
            RatingState.source,
            ("warehouse", "blue"),
            "amber",
        ),
        size="2",
        variant="soft",
        radius="full",
    )


def stock_header() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.heading(
                RatingState.result_ticker,
                size="7",
                weight="bold",
                letter_spacing="-0.02em",
            ),
            source_badge(),
            rx.button(
                rx.hstack(
                    rx.icon("bookmark_plus", size=14),
                    rx.cond(
                        RatingState.active_list == "",
                        rx.text("Save to a list", size="1"),
                        rx.text(
                            f"Save to {RatingState.active_list}",
                            size="1",
                        ),
                    ),
                    spacing="1",
                ),
                on_click=RatingState.save_result_to_active,
                variant="soft",
                size="2",
                radius="full",
            ),
            spacing="3",
            align="center",
            width="100%",
        ),
        rx.text(RatingState.result_company, size="3", color=rx.color("slate", 10)),
        rx.text(
            f"As of {RatingState.result_as_of}",
            size="1",
            color=rx.color("slate", 9),
        ),
        align="start",
        spacing="1",
    )


def score_panel() -> rx.Component:
    return rx.vstack(
        advice_badge(),
        rx.heading(
            RatingState.confidence_score,
            size="8",
            weight="bold",
            color=_advice_color(),
            letter_spacing="-0.02em",
        ),
        rx.text("Confidence score", size="2", weight="medium", color=rx.color("slate", 10)),
        rx.text("out of 100", size="1", color=rx.color("slate", 9)),
        rx.separator(width="70%"),
        rx.vstack(
            rx.hstack(
                rx.icon("activity", size=16, color=rx.color("purple", 9)),
                rx.text("Volatility", size="2", weight="medium", color=rx.color("slate", 10)),
                spacing="2",
                align="center",
            ),
            rx.heading(
                RatingState.volatility_score,
                size="6",
                weight="bold",
                color=rx.color("purple", 9),
            ),
            rx.text("reported separately", size="1", color=rx.color("slate", 9)),
            align="center",
            spacing="1",
        ),
        align="center",
        width="100%",
        spacing="3",
        padding_y="4",
    )


def snowflake_chart() -> rx.Component:
    return rx.recharts.responsive_container(
        rx.recharts.radar_chart(
            rx.recharts.polar_grid(stroke=rx.color("slate", 5)),
            rx.recharts.polar_angle_axis(
                data_key="label",
                tick={"font_size": 12, "fill": rx.color("slate", 10)},
            ),
            rx.recharts.radar(
                data_key="score",
                stroke=_advice_color(),
                fill=_advice_fill_color(),
                fill_opacity=0.35,
                stroke_width=2,
            ),
            data=RatingState.snowflake_data,
            cx="50%",
            cy="50%",
            outer_radius="80%",
        ),
        width="100%",
        height=340,
    )


def the_big_picture() -> rx.Component:
    return rx.card(
        rx.grid(
            snowflake_chart(),
            rx.vstack(
                rx.text(
                    "THE BIG PICTURE",
                    size="1",
                    weight="bold",
                    color=rx.color("slate", 9),
                    letter_spacing="0.08em",
                ),
                score_panel(),
                align="start",
                width="100%",
                spacing="3",
                padding="4",
            ),
            columns=rx.breakpoints(initial="1", md="2"),
            spacing="8",
            align="center",
            width="100%",
        ),
        width="100%",
        padding="6",
    )


def category_row(item: rx.Var) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.hstack(
                rx.box(
                    width="10px",
                    height="10px",
                    border_radius="full",
                    bg=rx.color("iris", 9),
                ),
                rx.text(item["label"], size="3", weight="medium"),
                spacing="3",
                align="center",
            ),
            rx.text(
                item["score_text"],
                size="2",
                weight="medium",
                color=rx.color("slate", 10),
            ),
            width="100%",
            justify="between",
        ),
        rx.box(
            rx.box(
                width=f"{item['score']}%",
                height="100%",
                bg=rx.color("iris", 9),
                border_radius="full",
            ),
            width="100%",
            height="8px",
            bg=rx.color("slate", 3),
            border_radius="full",
        ),
        width="100%",
        spacing="2",
    )


def breakdown_card() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading("Score breakdown", size="5", weight="bold"),
            rx.foreach(RatingState.category_rows, category_row),
            align="start",
            width="100%",
            spacing="4",
        ),
        width="100%",
        padding=BODY_CARD_PADDING,
    )


def buy_plan_card(plan: rx.Var) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.icon("target", size=18, color=rx.color("iris", 9)),
                rx.heading("Execution plan", size="4", weight="bold"),
                spacing="2",
                width="100%",
            ),
            rx.grid(
                rx.vstack(
                    rx.text("Advised buy price", size="2", color=rx.color("slate", 10)),
                    rx.heading(plan["advised_buy_price"], size="6", weight="bold"),
                    align="start",
                    spacing="1",
                ),
                rx.vstack(
                    rx.text("Stop-loss price", size="2", color=rx.color("slate", 10)),
                    rx.heading(
                        plan["stop_loss_price"],
                        size="6",
                        weight="bold",
                        color=rx.color("tomato", 9),
                    ),
                    align="start",
                    spacing="1",
                ),
                rx.vstack(
                    rx.text("Holding style", size="2", color=rx.color("slate", 10)),
                    rx.heading(
                        rx.match(
                            plan["holding_style"],
                            ("long_term_hold", HOLDING_LABELS["long_term_hold"]),
                            ("swing_trade", HOLDING_LABELS["swing_trade"]),
                            ("day_trade", HOLDING_LABELS["day_trade"]),
                            "Other",
                        ),
                        size="4",
                        weight="bold",
                    ),
                    align="start",
                    spacing="1",
                ),
                columns=rx.breakpoints(initial="1", md="3"),
                spacing="4",
                width="100%",
            ),
            width="100%",
            spacing="3",
        ),
        width="100%",
        padding=BODY_CARD_PADDING,
    )


def result_section() -> rx.Component:
    return rx.vstack(
        stock_header(),
        the_big_picture(),
        rx.grid(
            breakdown_card(),
            rx.cond(
                RatingState.is_buy,
                buy_plan_card(RatingState.buy_plan),
                rx.card(
                    rx.vstack(
                        rx.icon("volleyball", size=18, color=rx.color("slate", 9)),
                        rx.text(
                            "Volatility is reported as a separate score and is not blended into the confidence rating.",
                            size="2",
                            color=rx.color("slate", 10),
                        ),
                        align="center",
                        spacing="2",
                    ),
                    width="100%",
                    padding=BODY_CARD_PADDING,
                ),
            ),
            columns=rx.breakpoints(initial="1", md="2"),
            spacing="4",
            align="start",
            width="100%",
        ),
        width="100%",
        spacing="4",
        align="start",
    )


def new_list_form() -> rx.Component:
    return rx.cond(
        RatingState.show_new_list,
        rx.form(
            rx.hstack(
                rx.input(
                    placeholder="List name",
                    name="list_name",
                    size="2",
                    variant="soft",
                    width="100%",
                ),
                rx.icon_button(
                    "plus",
                    size="2",
                    variant="solid",
                    color_scheme="iris",
                    type="submit",
                ),
                spacing="2",
                width="100%",
            ),
            on_submit=RatingState.create_list,
            width="100%",
        ),
        rx.button(
            rx.hstack(
                rx.icon("list_plus", size=14),
                rx.text("New list", size="2"),
                spacing="2",
            ),
            on_click=RatingState.toggle_new_list,
            variant="soft",
            size="2",
            width="100%",
            justify="center",
        ),
    )


def ticker_chip(ticker: rx.Var) -> rx.Component:
    return rx.hstack(
        rx.badge(
            rx.hstack(
                rx.icon("search", size=10),
                rx.text(ticker, size="1"),
                spacing="1",
            ),
            variant="soft",
            color_scheme="iris",
            radius="full",
            cursor="pointer",
            on_click=RatingState.rate_from_list(ticker),
        ),
        rx.icon_button(
            "x",
            size="1",
            variant="ghost",
            on_click=RatingState.remove_ticker(ticker),
        ),
        spacing="1",
        align="center",
    )


def active_list_panel() -> rx.Component:
    return rx.vstack(
        rx.cond(
            RatingState.active_list_tickers.length() > 0,
            rx.flex(
                rx.foreach(RatingState.active_list_tickers, ticker_chip),
                wrap="wrap",
                width="100%",
                spacing="2",
            ),
        ),
        rx.form(
            rx.hstack(
                rx.input(
                    placeholder="Add a ticker",
                    name="ticker",
                    size="1",
                    variant="soft",
                    width="100%",
                ),
                rx.icon_button(
                    "plus",
                    size="1",
                    variant="solid",
                    color_scheme="iris",
                    type="submit",
                ),
                spacing="2",
                width="100%",
            ),
            on_submit=RatingState.add_ticker_to_active,
            width="100%",
        ),
        align="start",
        spacing="3",
        width="100%",
        padding_left="3",
    )


def list_item(item: rx.Var) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.cond(
                RatingState.renaming_list == item,
                rx.form(
                    rx.hstack(
                        rx.input(
                            placeholder="List name",
                            name="new_name",
                            default_value=item,
                            size="2",
                            variant="soft",
                            width="100%",
                        ),
                        rx.icon_button(
                            "check",
                            size="1",
                            variant="solid",
                            color_scheme="iris",
                            type="submit",
                        ),
                        rx.icon_button(
                            "x",
                            size="1",
                            variant="ghost",
                            on_click=RatingState.cancel_rename,
                        ),
                        spacing="2",
                        width="100%",
                    ),
                    on_submit=RatingState.submit_rename,
                    width="100%",
                ),
                rx.button(
                    rx.hstack(
                        rx.icon(
                            "folder_closed",
                            size=14,
                            color=rx.color("iris", 9),
                        ),
                        rx.text(item, size="2", weight="medium"),
                        spacing="2",
                    ),
                    on_click=RatingState.toggle_active_list(item),
                    variant="ghost",
                    size="2",
                    flex_grow="1",
                    justify="start",
                    border_radius="medium",
                    padding_x="2",
                ),
            ),
            rx.icon_button(
                "pencil",
                title="Rename list",
                size="1",
                variant="ghost",
                on_click=RatingState.start_rename(item),
            ),
            rx.icon_button(
                "trash_2",
                title="Delete list",
                size="1",
                variant="ghost",
                color_scheme="red",
                on_click=RatingState.delete_list(item),
            ),
            align="center",
            justify="start",
            width="100%",
            spacing="1",
        ),
        rx.cond(
            RatingState.active_list == item,
            active_list_panel(),
        ),
        align="stretch",
        spacing="1",
        width="100%",
        padding="1",
        padding_y="2",
        border_radius="medium",
        bg=rx.cond(
            RatingState.active_list == item,
            rx.color("slate", 3),
            "transparent",
        ),
        _hover={"bg": rx.color("slate", 3)},
    )


def saved_lists() -> rx.Component:
    return rx.cond(
        RatingState.has_lists,
        rx.vstack(
            rx.foreach(RatingState.list_names, list_item),
            spacing="2",
            width="100%",
            align="stretch",
        ),
        rx.text(
            "Lists you create will appear here. Click a ticker to rate it instantly.",
            size="1",
            color=rx.color("slate", 9),
            align="left",
            width="100%",
        ),
    )


def side_panel() -> rx.Component:
    return rx.flex(
        rx.cond(
            RatingState.sidebar_collapsed,
            rx.card(
                rx.vstack(
                    rx.icon_button(
                        rx.icon("panel_left_open", size=16),
                        title="Expand sidebar",
                        variant="soft",
                        color_scheme="iris",
                        size="2",
                        on_click=RatingState.toggle_sidebar,
                    ),
                    align="center",
                    width="100%",
                    padding_top="1",
                ),
                width="52px",
                variant="surface",
                position="sticky",
                top="6",
                align_self="start",
            ),
            rx.card(
                rx.vstack(
                    rx.hstack(
                        rx.icon("bookmark", size=16, color=rx.color("iris", 9)),
                        rx.heading("My Lists", size="3", weight="bold"),
                        rx.spacer(),
                        rx.icon_button(
                            rx.icon("panel_left_close", size=16),
                            title="Collapse sidebar",
                            variant="ghost",
                            size="2",
                            on_click=RatingState.toggle_sidebar,
                        ),
                        spacing="2",
                        align="center",
                        width="100%",
                    ),
                    new_list_form(),
                    rx.separator(width="100%"),
                    saved_lists(),
                    align="stretch",
                    spacing="3",
                    width="100%",
                ),
                width="300px",
                padding="4",
                position="sticky",
                top="6",
                max_height="85vh",
                style={"overflow_y": "auto"},
            ),
        ),
        width="100%",
    )


def main_panel() -> rx.Component:
    return rx.vstack(
        hero(),
        macro_metrics_section(),
        rx.cond(
            RatingState.error != "",
            error_callout(),
        ),
        spacing="5",
        align="center",
        width="100%",
    )


def profile_panel() -> rx.Component:
    return rx.vstack(
        rx.link(
            rx.hstack(
                rx.icon("arrow_left", size=14),
                rx.text("Back to general info", size="2", weight="medium"),
                spacing="2",
            ),
            href="/",
            underline="none",
            color=rx.color("slate", 11),
            _hover={"color": rx.color("iris", 9)},
        ),
        rx.cond(
            RatingState.has_result,
            result_section(),
            rx.cond(
                RatingState.error != "",
                error_callout(),
                rx.vstack(
                    rx.heading(
                        f"Analyzing {RatingState.ticker}…",
                        size="6",
                        weight="bold",
                        letter_spacing="-0.02em",
                    ),
                    rx.text(
                        "Pulling ratings inputs from the warehouse mart.",
                        size="2",
                        color=rx.color("slate", 10),
                    ),
                    rx.hstack(
                        rx.spinner(
                            size="3",
                            color=rx.color("iris", 9),
                        ),
                        rx.text(
                            "Scoring valuation, trend, momentum, sentiment",
                            size="2",
                            color=rx.color("slate", 9),
                        ),
                        spacing="2",
                        align="center",
                    ),
                    align="start",
                    spacing="3",
                    width="100%",
                ),
            ),
        ),
        spacing="4",
        align="start",
        width="100%",
    )


def macro_metric_chart(item: rx.Var) -> rx.Component:
    return rx.recharts.responsive_container(
        rx.recharts.line_chart(
            rx.recharts.line(
                data_key="value",
                stroke=rx.color("iris", 8),
                dot=False,
                stroke_width=2,
            ),
            data=item["series"],
            margin={"top": 4, "right": 4, "bottom": 4, "left": 4},
        ),
        width="100%",
        height=46,
    )


def macro_metric_card(item: rx.Var) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.text(item["label"], size="2", weight="medium"),
                rx.text(
                    item["as_of"],
                    size="1",
                    color=rx.color("slate", 9),
                ),
                width="100%",
                justify="between",
            ),
            rx.heading(
                item["value"],
                size="5",
                weight="bold",
                color=rx.color("slate", 12),
            ),
            rx.text(
                f"{item['unit']} · {item['detail']}",
                size="1",
                color=rx.color("slate", 10),
            ),
            macro_metric_chart(item),
            align="start",
            width="100%",
            spacing="2",
        ),
        width="100%",
        padding="4",
    )


def commodity_card(item: rx.Var) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.box(
                    width="10px",
                    height="10px",
                    border_radius="full",
                    bg=rx.color("amber", 9),
                ),
                rx.text(item["label"], size="2", weight="medium"),
                spacing="2",
                align="center",
            ),
            rx.hstack(
                rx.heading(item["price"], size="6", weight="bold"),
                rx.text(item["unit"], size="1", color=rx.color("slate", 9)),
                spacing="2",
                align="end",
            ),
            rx.text(
                f"as of {item['timestamp']}",
                size="1",
                color=rx.color("slate", 10),
            ),
            align="start",
            width="100%",
            spacing="2",
        ),
        width="100%",
        padding="4",
    )


def section_header(icon: str, title: str, subtitle: str | None = None) -> rx.Component:
    children = [
        rx.hstack(
            rx.icon(icon, size=18, color=rx.color("iris", 9)),
            rx.heading(title, size="5", weight="bold"),
            spacing="2",
            align="center",
        ),
        rx.text(
            subtitle,
            size="1",
            color=rx.color("slate", 9),
        ) if subtitle else None,
    ]
    return rx.vstack(
        [child for child in children if child is not None],
        align="start",
        width="100%",
        spacing="1",
    )


def macro_metrics_section() -> rx.Component:
    return rx.vstack(
        section_header(
            "gauge",
            "Market snapshot",
            "Headline macro indicators feeding the model context. Data is demo placeholder until the pipeline ingests these endpoints.",
        ),
        rx.grid(
            rx.foreach(RatingState.macro_metrics, macro_metric_card),
            columns=rx.breakpoints(initial="1", sm="2", md="3"),
            spacing="4",
            width="100%",
        ),
        rx.grid(
            rx.foreach(RatingState.commodities, commodity_card),
            columns=rx.breakpoints(initial="1", sm="2"),
            spacing="4",
            width="100%",
        ),
        align="stretch",
        width="100%",
        spacing="4",
        padding_y="2",
    )


def mover_row(item: rx.Var) -> rx.Component:
    return rx.table.row(
        rx.table.cell(
            rx.text(item["ticker"], size="2", weight="medium"),
        ),
        rx.table.cell(
            rx.text(f"${item['price']}", size="2"),
        ),
        rx.table.cell(
            rx.text(
                item["change_display"],
                size="2",
                color=rx.cond(
                    item["is_gain"],
                    rx.color("green", 9),
                    rx.color("red", 9),
                ),
            ),
        ),
        rx.table.cell(
            rx.text(item["volume_display"], size="2", color=rx.color("slate", 10)),
        ),
        _hover={"bg": rx.color("slate", 3)},
    )


def movers_table(title: str, data: rx.Var) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading(title, size="4", weight="bold"),
            rx.table.root(
                rx.table.header(
                    rx.table.row(
                        rx.table.column_header_cell(
                            "Ticker",
                            color=rx.color("slate", 11),
                            bg=rx.color("slate", 3),
                        ),
                        rx.table.column_header_cell(
                            "Price",
                            color=rx.color("slate", 11),
                            bg=rx.color("slate", 3),
                        ),
                        rx.table.column_header_cell(
                            "Change",
                            color=rx.color("slate", 11),
                            bg=rx.color("slate", 3),
                        ),
                        rx.table.column_header_cell(
                            "Volume",
                            color=rx.color("slate", 11),
                            bg=rx.color("slate", 3),
                        ),
                    ),
                ),
                rx.table.body(
                    rx.foreach(data, mover_row),
                ),
                width="100%",
            ),
            align="stretch",
            width="100%",
            spacing="3",
        ),
        width="100%",
        padding=BODY_CARD_PADDING,
    )


def news_sentiment_badge(label: rx.Var) -> rx.Component:
    return rx.badge(
        label,
        variant="soft",
        radius="full",
        color_scheme=rx.cond(
            label == "Bullish",
            "green",
            rx.cond(
                label == "Somewhat-Bullish",
                "green",
                rx.cond(
                    label == "Bearish",
                    "red",
                    rx.cond(
                        label == "Somewhat-Bearish",
                        "red",
                        "gray",
                    ),
                ),
            ),
        ),
    )


def news_card(item: rx.Var) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(
                news_sentiment_badge(item["overall_sentiment_label"]),
                rx.text(
                    item["source"],
                    size="1",
                    color=rx.color("slate", 10),
                ),
                rx.spacer(),
                rx.text(
                    item["time_published"],
                    size="1",
                    color=rx.color("slate", 9),
                ),
                align="center",
                width="100%",
            ),
            rx.link(
                item["title"],
                href=item["url"],
                weight="bold",
                size="3",
                underline="none",
                target="_blank",
                _hover={"color": rx.color("iris", 9)},
            ),
            rx.text(item["summary"], size="2", color=rx.color("slate", 10)),
            rx.cond(
                item["sentiment_tickers"] != "",
                rx.text(
                    f"Related: {item['sentiment_tickers']}",
                    size="1",
                    color=rx.color("slate", 9),
                ),
            ),
            align="start",
            width="100%",
            spacing="3",
        ),
        width="100%",
        padding=BODY_CARD_PADDING,
    )


def ipo_row(item: rx.Var) -> rx.Component:
    return rx.table.row(
        rx.table.cell(rx.text(item["symbol"], size="2", weight="medium")),
        rx.table.cell(rx.text(item["name"], size="2")),
        rx.table.cell(rx.text(item["exchange"], size="2")),
        rx.table.cell(rx.text(item["date"], size="2")),
        rx.table.cell(rx.text(item["price"], size="2")),
        rx.table.cell(
            rx.badge(
                item["status"],
                variant="soft",
                radius="full",
                color_scheme=rx.cond(
                    item["status"] == "expected",
                    "iris",
                    rx.cond(
                        item["status"] == "priced",
                        "green",
                        rx.cond(item["status"] == "withdrawn", "red", "amber"),
                    ),
                ),
            )
        ),
        _hover={"bg": rx.color("slate", 3)},
    )


def earnings_row(item: rx.Var) -> rx.Component:
    return rx.table.row(
        rx.table.cell(rx.text(item["symbol"], size="2", weight="medium")),
        rx.table.cell(rx.text(item["date"], size="2")),
        rx.table.cell(
            rx.badge(
                rx.match(
                    item["hour"],
                    ("bmo", "BMO"),
                    ("amc", "AMC"),
                    ("dmh", "DMH"),
                    item["hour"],
                ),
                variant="soft",
                radius="full",
                color_scheme="gray",
            )
        ),
        rx.table.cell(
            rx.text(
                f"Q{item['quarter']} {item['year']}",
                size="2",
            )
        ),
        rx.table.cell(
            rx.text(
                item["eps_actual_display"],
                size="2",
                color=rx.cond(
                    item["eps_actual_display"] != None,
                    rx.color("green", 9),
                    rx.color("slate", 9),
                ),
            )
        ),
        rx.table.cell(rx.text(f"${item['eps_estimate']:.2f}", size="2")),
        rx.table.cell(
            rx.text(
                item["revenue_estimate_display"],
                size="2",
                color=rx.color("slate", 10),
            )
        ),
        _hover={"bg": rx.color("slate", 3)},
    )


def discover_panel() -> rx.Component:
    return rx.vstack(
        rx.vstack(
            rx.icon("compass", size=28, color=rx.color("iris", 9)),
            rx.heading(
                "Discover",
                size="7",
                weight="bold",
                letter_spacing="-0.02em",
            ),
            rx.text(
                "Market movers, earnings, IPOs, and the sentiment driving the headlines.",
                size="3",
                color=rx.color("slate", 10),
            ),
            spacing="3",
            align="center",
            padding_y="4",
        ),
        rx.vstack(
            section_header(
                "trending_up",
                "Top gainers / losers",
                "Biggest movers and most active symbols in the last session.",
            ),
            rx.grid(
                movers_table("Top gainers", RatingState.top_gainers),
                movers_table("Top losers", RatingState.top_losers),
                movers_table("Most active", RatingState.most_active),
                columns=rx.breakpoints(initial="1", md="3"),
                spacing="4",
                width="100%",
            ),
            align="stretch",
            width="100%",
            spacing="4",
        ),
        rx.vstack(
            section_header(
                "newspaper",
                "News & sentiment",
                "Headlines with Finnhub-style sentiment labels.",
            ),
            rx.foreach(RatingState.market_news, news_card),
            align="stretch",
            width="100%",
            spacing="3",
        ),
        rx.vstack(
            section_header(
                "calendar_days",
                "Market Calendars",
                "Upcoming IPOs and earnings with consensus estimates.",
            ),
            rx.grid(
                rx.card(
                    rx.vstack(
                        rx.heading("IPO calendar", size="4", weight="bold"),
                        rx.table.root(
                            rx.table.header(
                                rx.table.row(
                                    rx.table.column_header_cell("Symbol", bg=rx.color("slate", 3)),
                                rx.table.column_header_cell("Company", bg=rx.color("slate", 3)),
                                rx.table.column_header_cell("Exchange", bg=rx.color("slate", 3)),
                                rx.table.column_header_cell("Date", bg=rx.color("slate", 3)),
                                rx.table.column_header_cell("Price", bg=rx.color("slate", 3)),
                                rx.table.column_header_cell("Status", bg=rx.color("slate", 3)),
                            ),
                        ),
                        rx.table.body(
                            rx.foreach(RatingState.ipo_calendar, ipo_row),
                        ),
                        width="100%",
                    ),
                    align="stretch",
                    width="100%",
                    spacing="3",
                ),
                width="100%",
                padding=BODY_CARD_PADDING,
            ),
            rx.card(
                rx.vstack(
                    rx.heading("Earnings calendar", size="4", weight="bold"),
                    rx.table.root(
                        rx.table.header(
                            rx.table.row(
                                rx.table.column_header_cell("Symbol", bg=rx.color("slate", 3)),
                                rx.table.column_header_cell("Date", bg=rx.color("slate", 3)),
                                rx.table.column_header_cell("Hour", bg=rx.color("slate", 3)),
                                rx.table.column_header_cell("Period", bg=rx.color("slate", 3)),
                                rx.table.column_header_cell("EPS actual", bg=rx.color("slate", 3)),
                                rx.table.column_header_cell("EPS est.", bg=rx.color("slate", 3)),
                                rx.table.column_header_cell("Rev. est.", bg=rx.color("slate", 3)),
                            ),
                        ),
                        rx.table.body(
                            rx.foreach(RatingState.earnings_calendar, earnings_row),
                        ),
                        width="100%",
                    ),
                    align="stretch",
                    width="100%",
                    spacing="3",
                ),
                width="100%",
                padding=BODY_CARD_PADDING,
            ),
            columns=rx.breakpoints(initial="1", md="2"),
            spacing="4",
            width="100%",
            align="start",
        ),
        align="stretch",
        width="100%",
        spacing="4",
    ),
        align="stretch",
        width="100%",
        spacing="6",
        padding_bottom="4",
    )