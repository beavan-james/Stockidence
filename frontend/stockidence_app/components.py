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

CATEGORY_COLORS = {
    "valuation": rx.color("iris", 9),
    "trend": rx.color("sky", 9),
    "sentiment": rx.color("amber", 9),
    "moat": rx.color("violet", 9),
    "volatility": rx.color("tomato", 9),
}

CATEGORY_SCHEMES = {
    "valuation": "iris",
    "trend": "sky",
    "sentiment": "amber",
    "moat": "violet",
    "volatility": "tomato",
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


def _weight_tile(item: rx.Var) -> rx.Component:
    return rx.vstack(
        rx.heading(item["label"], size="2", weight="bold"),
        rx.text(item["weight_text"], size="1", color=rx.color("slate", 10)),
        align="center",
        spacing="1",
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
            rx.foreach(RatingState.model_weight_rows, _weight_tile),
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


def suggestion_row(item: rx.Var) -> rx.Component:
    return rx.button(
        rx.hstack(
            rx.text(item["symbol"], size="2", weight="bold", font_family="monospace"),
            rx.text(item["description"], size="1", color=rx.color("slate", 10)),
            width="100%",
            spacing="2",
            align="center",
        ),
        on_click=RatingState.select_ticker(item["symbol"]),
        variant="ghost",
        color_scheme="gray",
        width="100%",
        border_radius="6px",
        padding_x="3",
        padding_y="2",
    )


def search_form() -> rx.Component:
    return rx.form(
        rx.box(
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
                    value=RatingState.ticker_search,
                    on_change=RatingState.update_ticker_search,
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
            rx.cond(
                RatingState.ticker_suggestions.length() > 0,
                rx.box(
                    rx.foreach(RatingState.ticker_suggestions, suggestion_row),
                    position="absolute",
                    top="100%",
                    left="0",
                    margin_top="2",
                    padding_y="1",
                    background=rx.color("slate", 2),
                    border=f"1px solid {rx.color('slate', 6)}",
                    border_radius="12px",
                    box_shadow="lg",
                    min_width="340px",
                    max_height="320px",
                    overflow_y="auto",
                    z_index="50",
                ),
            ),
            position="relative",
            width="auto",
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


def failure_row(item: rx.Var) -> rx.Component:
    return rx.hstack(
        rx.badge(
            item["job_name"],
            color_scheme="red",
            variant="soft",
            radius="full",
            size="1",
            flex_shrink="0",
        ),
        rx.text(
            item["failed_at_display"],
            size="1",
            color=rx.color("slate", 9),
            flex_shrink="0",
        ),
        rx.text(
            item["error"],
            size="1",
            color=rx.color("slate", 10),
            overflow="hidden",
            text_overflow="ellipsis",
            white_space="nowrap",
            flex_grow="1",
        ),
        spacing="3",
        align="center",
        width="100%",
    )


def pipeline_health_strip() -> rx.Component:
    """Compact ops strip: green when no recent failures, red list otherwise."""
    return rx.cond(
        RatingState.pipeline_failures.length() == 0,
        rx.callout(
            rx.text("All pipelines operational (no failed runs in the last 7 days)", size="2"),
            icon="circle_check",
            color_scheme="grass",
            size="1",
            width="100%",
            variant="surface",
        ),
        rx.card(
            rx.vstack(
                section_header(
                    "triangle_alert",
                    "Pipeline failures (last 7 days)",
                    "Recorded by the Dagster failure sensor into control.pipeline_failures. Check the webserver for full run logs.",
                ),
                rx.foreach(RatingState.pipeline_failures, failure_row),
                spacing="3",
                width="100%",
            ),
            width="100%",
            padding="4",
        ),
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
        rx.hstack(
            rx.cond(
                RatingState.source == "refreshing",
                rx.spinner(size="1", color=rx.match(RatingState.source, ("refreshing", "blue"), "blue")),
            ),
            rx.text(
                rx.match(
                    RatingState.source,
                    ("warehouse", "Warehouse data"),
                    ("pending", "Computing…"),
                    ("refreshing", "Refreshing…"),
                    "Demo sample",
                ),
                size="1",
                weight="medium",
            ),
            spacing="1",
            align="center",
        ),
        color_scheme=rx.match(
            RatingState.source,
            ("warehouse", "blue"),
            ("pending", "violet"),
            ("refreshing", "violet"),
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
            ),            source_badge(),
            rx.cond(
                RatingState.quote["price"] != None,
                rx.badge(
                    rx.hstack(
                        rx.icon("banknote", size=12),
                        rx.text(
                            RatingState.quote["price_text"],
                            size="2",
                            weight="bold",
                        ),
                        rx.cond(
                            RatingState.quote["change_pct_text"] != None,
                            rx.text(
                                RatingState.quote["change_pct_text"],
                                size="1",
                                color=RatingState.quote["change_color"],
                            ),
                        ),
                        spacing="2",
                        align="center",
                    ),
                    color_scheme="gray",
                    variant="soft",
                    radius="full",
                ),
            ),
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
        class_name="sk-fade",
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


def snowflake_vertex(item: rx.Var) -> rx.Component:
    return rx.el.svg.circle(
        cx=item["cx"],
        cy=item["cy"],
        r=6,
        fill=item["color"],
        stroke="white",
        stroke_width=1.5,
    )


def snowflake_label(item: rx.Var) -> rx.Component:
    return rx.fragment(
        rx.el.svg.text(
            item["label"],
            x=item["lx"],
            y=item["ly"],
            fill=rx.color("slate", 10),
            font_size=12,
            font_weight=600,
            text_anchor="middle",
        ),
        rx.el.svg.text(
            item["score_text"],
            x=item["lx"],
            y=item["ly2"],
            fill=item["color"],
            font_size=13,
            font_weight=700,
            text_anchor="middle",
        ),
        rx.el.svg.circle(
            cx=item["lx2"],
            cy=item["ly3"],
            r=3,
            fill=item["color"],
        ),
    )


def score_badge() -> rx.Component:
    """Composite confidence score at the diamond's center, advice-colored."""
    return rx.el.svg.g(
        rx.el.svg.circle(
            cx=170,
            cy=170,
            r=30,
            fill=_advice_color(),
            opacity=0.9,
        ),
        rx.el.svg.text(
            RatingState.confidence_score_text,
            x=170,
            y=167,
            fill="white",
            font_size=22,
            font_weight=800,
            text_anchor="middle",
        ),
        rx.el.svg.text(
            "CONFIDENCE",
            x=170,
            y=183,
            fill="white",
            font_size=8,
            font_weight=600,
            letter_spacing="0.12em",
            text_anchor="middle",
        ),
    )


def snowflake_chart() -> rx.Component:
    return rx.el.svg(
        rx.el.svg.polygon(
            points=RatingState.snowflake_points,
            fill=_advice_color(),
            fill_opacity=0.15,
            stroke=_advice_color(),
            stroke_width=1.5,
        ),
        rx.foreach(RatingState.snowflake_data, snowflake_vertex),
        rx.foreach(RatingState.snowflake_data, snowflake_label),
        score_badge(),
        class_name="sk-pop",
        view_box="0 0 340 340",
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
        class_name="sk-fade",
    )


def _category_fill(color: rx.Var) -> rx.Var:
    return rx.match(
        color,
        *[(slug, c) for slug, c in CATEGORY_COLORS.items()],
        rx.color("slate", 9),
    )


def _category_scheme(color: rx.Var) -> rx.Var:
    return rx.match(
        color,
        *[(slug, s) for slug, s in CATEGORY_SCHEMES.items()],
        "gray",
    )


def category_row(item: rx.Var) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.hstack(
                rx.box(
                    width="10px",
                    height="10px",
                    border_radius="full",
                    bg=_category_fill(item["color"]),
                ),
                rx.text(item["label"], size="3", weight="medium"),
                rx.text(
                    item["weight_text"],
                    size="1",
                    font_style="italic",
                    color=rx.color("slate", 9),
                ),
                spacing="3",
                align="center",
            ),
            rx.badge(
                item["score_text"],
                size="1",
                variant="soft",
                radius="full",
                color_scheme=_category_scheme(item["color"]),
            ),
            width="100%",
            justify="between",
        ),
        rx.box(
            rx.box(
                width=f"{item['score']}%",
                height="100%",
                bg=_category_fill(item["color"]),
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
        class_name="sk-fade sk-delay-1",
    )


def sub_score_row(item: rx.Var) -> rx.Component:
    return rx.vstack(
        rx.cond(
            item.show_header,
            rx.hstack(
                rx.box(
                    width="10px",
                    height="10px",
                    border_radius="full",
                    bg=_category_fill(item.color),
                ),
                rx.text(
                    item.category_label,
                    size="1",
                    weight="bold",
                    color=rx.color("slate", 11),
                    text_transform="uppercase",
                    letter_spacing="0.05em",
                ),
                spacing="2",
                align="center",
            ),
        ),
        rx.hstack(
            rx.text(item.label, size="2", weight="medium"),
            rx.badge(
                item.score_text,
                size="1",
                variant="soft",
                radius="full",
                color_scheme=_category_scheme(item.color),
            ),
            spacing="3",
            align="center",
            width="100%",
            justify="between",
        ),
        rx.box(
            rx.box(
                width=f"{item.score}%",
                height="100%",
                bg=_category_fill(item.color),
                border_radius="full",
            ),
            width="100%",
            height="6px",
            bg=rx.color("slate", 3),
            border_radius="full",
        ),
        rx.hstack(
            rx.icon("database", size=12, color=rx.color("slate", 9)),
            rx.text(
                f"{item.sources} · {item.weight_text}",
                size="1",
                color=rx.color("slate", 10),
            ),
            spacing="2",
            align="center",
        ),
        rx.text(
            item.direction,
            size="1",
            font_style="italic",
            color=rx.color("slate", 9),
        ),
        rx.separator(width="100%"),
        align="start",
        width="100%",
        spacing="2",
    )


def sub_score_card() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.vstack(
                    rx.heading("Sub-score detail", size="5", weight="bold"),
                    rx.text(
                        "The sub-scores behind each category. Volatility is reported "
                        "as a separate score and is never blended into the rating.",
                        size="1",
                        color=rx.color("slate", 9),
                    ),
                    align="start",
                    spacing="1",
                ),
                rx.cond(
                    RatingState.sub_scores_open,
                    rx.icon("chevron-up", size=18, color=rx.color("slate", 10)),
                    rx.icon("chevron-down", size=18, color=rx.color("slate", 10)),
                ),
                spacing="3",
                align="start",
                width="100%",
                justify="between",
                cursor_pointer="pointer",
                on_click=RatingState.toggle_sub_scores,
            ),
            rx.cond(
                RatingState.sub_scores_open,
                rx.foreach(RatingState.sub_score_rows, sub_score_row),
            ),
            align="start",
            width="100%",
            spacing="4",
        ),
        width="100%",
        padding=BODY_CARD_PADDING,
        class_name="sk-fade sk-delay-2",
    )


def _holding_style_heading() -> rx.Component:
    return rx.heading(
        rx.match(
            RatingState.buy_plan["holding_style"],
            ("long_term_hold", HOLDING_LABELS["long_term_hold"]),
            ("swing_trade", HOLDING_LABELS["swing_trade"]),
            ("day_trade", HOLDING_LABELS["day_trade"]),
            "Other",
        ),
        size="6",
        weight="bold",
    )


def buy_plan_card() -> rx.Component:
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
                    rx.heading(RatingState.buy_price_text, size="6", weight="bold"),
                    align="start",
                    spacing="1",
                ),
                rx.vstack(
                    rx.text("Stop-loss price", size="2", color=rx.color("slate", 10)),
                    rx.heading(
                        RatingState.stop_loss_text,
                        size="6",
                        weight="bold",
                        color=rx.color("tomato", 9),
                    ),
                    align="start",
                    spacing="1",
                ),
                rx.vstack(
                    rx.text("Holding style", size="2", color=rx.color("slate", 10)),
                    _holding_style_heading(),
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
        class_name="sk-fade sk-delay-2",
    )


def price_reference_card() -> rx.Component:
    return rx.cond(
        RatingState.has_fair_value,
        rx.card(
            rx.vstack(
                rx.hstack(
                    rx.icon("scale", size=18, color=rx.color("iris", 9)),
                    rx.heading("Valuation reference", size="4", weight="bold"),
                    spacing="2",
                    width="100%",
                ),
                rx.text(
                    "Model fair value and the price target implied by it, computed "
                    "for every rating. Buy-rated tickers also get an execution plan.",
                    size="1",
                    color=rx.color("slate", 9),
                ),
                rx.grid(
                    rx.vstack(
                        rx.text("Fair value", size="2", color=rx.color("slate", 10)),
                        rx.heading(RatingState.fair_value_text, size="6", weight="bold"),
                        align="start",
                        spacing="1",
                    ),
                    rx.vstack(
                        rx.text("Target price (12m)", size="2", color=rx.color("slate", 10)),
                        rx.heading(RatingState.target_price_text, size="6", weight="bold"),
                        align="start",
                        spacing="1",
                    ),
                    columns=rx.breakpoints(initial="1", md="2"),
                    spacing="4",
                    width="100%",
                ),
                width="100%",
                spacing="3",
            ),
            width="100%",
            padding=BODY_CARD_PADDING,
            class_name="sk-fade sk-delay-2",
        ),
    )


def result_section() -> rx.Component:
    return rx.vstack(
        stock_header(),
        the_big_picture(),
        price_reference_card(),
        rx.cond(
            RatingState.is_buy & RatingState.has_buy_plan,
            buy_plan_card(),
        ),
        breakdown_card(),
        rx.cond(
            RatingState.has_sub_scores,
            sub_score_card(),
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
        width="100%",
        spacing="4",
        align="start",
    )


def new_list_form() -> rx.Component:
    return rx.cond(
        RatingState.show_new_list,
        rx.form(
            rx.vstack(
                rx.hstack(
                    rx.input(
                        placeholder="List name",
                        name="list_name",
                        size="2",
                        variant="soft",
                        width="100%",
                        required=True,
                    ),
                    rx.icon_button(
                        "plus",
                        size="2",
                        variant="solid",
                        color_scheme="iris",
                        type="submit",
                    ),
                    rx.icon_button(
                        rx.icon("x", size=14),
                        title="Hide new-list form",
                        size="2",
                        variant="ghost",
                        type="button",
                        on_click=RatingState.toggle_new_list,
                    ),
                    spacing="2",
                    width="100%",
                ),
                rx.cond(
                    RatingState.list_form_error,
                    rx.text(
                        RatingState.list_form_error,
                        size="1",
                        color=rx.color("red", 9),
                    ),
                ),
                spacing="1",
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
        pipeline_health_strip(),
        rx.cond(
            RatingState.error != "",
            error_callout(),
        ),
        spacing="5",
        align="center",
        width="100%",
    )


def _computing_gauge() -> rx.Component:
    return rx.html(
        """
        <div class="cg-gauge-wrap">
          <svg viewBox="0 0 200 120" width="210" height="126" aria-hidden="true">
            <defs>
              <linearGradient id="cg-arc" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stop-color="#818cf8"/>
                <stop offset="100%" stop-color="#4f46e5"/>
              </linearGradient>
            </defs>
            <path d="M20 105 A80 80 0 0 1 180 105" fill="none"
                  stroke="url(#cg-arc)" stroke-width="6"
                  stroke-linecap="round" opacity="0.35"/>
            <path d="M30 105 A70 70 0 0 1 170 105" fill="none"
                  stroke="#94a3b8" stroke-width="11" opacity="0.55"
                  stroke-dasharray="1.5 12.62"/>
            <g class="cg-needle">
              <line x1="100" y1="105" x2="100" y2="40"
                    stroke="#4f46e5" stroke-width="3" stroke-linecap="round"/>
            </g>
            <circle cx="100" cy="105" r="5.5" fill="#4f46e5"/>
          </svg>
          <span class="cg-gauge-label">Confidence &middot; calibrating</span>
        </div>
        """,
        width="100%",
    )


def _computing_stage(label: str, idx: int) -> rx.Component:
    return rx.hstack(
        rx.box(class_name=f"cg-stage-dot"),
        rx.text(label, size="1", weight="medium"),
        class_name=f"cg-stage cg-stage-{idx}",
    )


def _computing_tenets() -> rx.Component:
    tenets = [
        "Valuation is king — everything else times the entry.",
        "Volatility is reported separately, never blended into your rating.",
        "Every score is deterministic: same data, same answer.",
        "Slow inputs are normal — fundamentals update quarterly.",
    ]
    return rx.box(
        rx.foreach(tenets, lambda t, i: rx.text(
            t,
            size="2",
            color=rx.color("slate", 10),
            font_style="italic",
            text_align="center",
            width="100%",
            class_name=f"cg-tenet cg-tenet-{i}",
        )),
        class_name="cg-tenets",
        width="100%",
    )


def computing_card() -> rx.Component:
    ticker = RatingState.ticker
    named = rx.cond(
        ticker == "",
        "Computing your first rating",
        f"First rating for {ticker}",
    )
    refreshing = rx.cond(ticker == "", "Refreshing", f"Refreshing {ticker}")
    generic = rx.cond(ticker == "", "Computing a rating", f"Computing a rating for {ticker}")
    headline = rx.match(
        RatingState.source,
        ("pending", named),
        ("refreshing", refreshing),
        generic,
    )
    subtitle = rx.match(
        RatingState.source,
        (
            "pending",
            "Assembling its full history from scratch — this is the slow path.",
        ),
        (
            "refreshing",
            "The stored snapshot is over a day old — updating market inputs.",
        ),
        "The pipeline was queued.",
    )
    stages = [
        "Queued",
        "Fetching market data",
        "Cleaning & staging",
        "Deriving indicators",
        "Scoring",
    ]
    return rx.card(
        rx.vstack(
            rx.heading(headline, size="5", weight="bold", text_align="center",
                       width="100%"),
            rx.text(subtitle, size="1", color=rx.color("slate", 9),
                    text_align="center", width="100%"),
            _computing_gauge(),
            rx.hstack(
                rx.foreach(
                    stages,
                    lambda label, i: rx.fragment(
                        _computing_stage(label, i),
                        rx.cond(i < 4, rx.icon("chevron-right", size=12,
                                               color=rx.color("slate", 8))),
                    ),
                ),
                justify="center",
                wrap="wrap",
                spacing="1",
                width="100%",
            ),
            _computing_tenets(),
            rx.text(
                "Still working — fundamentals are the slow part. "
                "This page updates itself the moment the rating lands.",
                size="1",
                color=rx.color("slate", 10),
                text_align="center",
                width="100%",
                class_name="cg-reassure",
            ),
            align="center",
            width="100%",
            spacing="4",
        ),
        width="100%",
        padding=BODY_CARD_PADDING,
        class_name="sk-fade",
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
            RatingState.has_result & ~RatingState.is_loading,
            result_section(),
            rx.cond(
                RatingState.error != "",
                error_callout(),
                computing_card(),
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
            rx.cond(
                item["fetched"] != "",
                rx.text(
                    f"fetched {item['fetched']}",
                    size="1",
                    color=rx.color("slate", 9),
                ),
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
            "Headline macro indicators feeding the model context, read live from the warehouse. Macro series refresh monthly (inflation derived from CPI YoY), gold and silver on the monthly job.",
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


def movers_table(title: str, data: rx.Var, as_of: rx.Var) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.heading(title, size="4", weight="bold"),
                rx.cond(
                    as_of != "",
                    rx.badge(
                        "Market close · ", as_of,
                        variant="soft",
                        radius="full",
                        color_scheme="gray",
                    ),
                    rx.fragment(),
                ),
                align="center",
                spacing="3",
                width="100%",
            ),
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


def limit_select(
    value: rx.Var,
    on_change,
) -> rx.Component:
    return rx.hstack(
        rx.text("Show", size="1", color=rx.color("slate", 9)),
        rx.select(
            ["5", "10", "15", "25"],
            value=value,
            on_change=on_change,
            size="1",
            width="72px",
        ),
        spacing="1",
        align="center",
    )


def discover_panel() -> rx.Component:
    return rx.vstack(
        section_header(
            "compass",
            "Discover",
            "Market movers, news sentiment, and upcoming listings — each section is capped with a results toggle.",
        ),
        rx.vstack(
            section_header(
                "trending_up",
                "Top gainers / losers",
                "Biggest movers in the last session.",
            ),
            rx.hstack(
                limit_select(RatingState.movers_limit, RatingState.set_movers_limit),
                align="center",
                justify="end",
                width="100%",
            ),
            rx.grid(
                movers_table("Top gainers", RatingState.top_gainers,
                             RatingState.movers_as_of),
                movers_table("Top losers", RatingState.top_losers,
                             RatingState.movers_as_of),
                columns=rx.breakpoints(initial="1", md="2"),
                spacing="4",
                width="100%",
            ),
            align="stretch",
            width="100%",
            spacing="3",
        ),
        rx.vstack(
            section_header(
                "newspaper",
                "News & sentiment",
                "Headlines with Finnhub-style sentiment labels.",
            ),
            rx.hstack(
                rx.input(
                    placeholder="Filter by ticker…",
                    value=RatingState.news_ticker_query,
                    on_change=RatingState.update_news_ticker,
                    size="1",
                    variant="soft",
                    width="180px",
                ),
                rx.hstack(
                    rx.icon_button(
                        rx.icon("chevron_left", size=14),
                        title="Previous page",
                        variant="soft",
                        size="1",
                        disabled=RatingState.news_page <= 1,
                        on_click=RatingState.news_prev_page,
                    ),
                    rx.text(
                        f"Page {RatingState.news_page} / {RatingState.news_page_count}",
                        size="1",
                        color=rx.color("slate", 10),
                    ),
                    rx.icon_button(
                        rx.icon("chevron_right", size=14),
                        title="Next page",
                        variant="soft",
                        size="1",
                        disabled=RatingState.news_page >= RatingState.news_page_count,
                        on_click=RatingState.news_next_page,
                    ),
                    spacing="1",
                    align="center",
                ),
                limit_select(RatingState.news_limit, RatingState.set_news_limit),
                justify="between",
                width="100%",
                align="center",
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
            rx.hstack(
                limit_select(RatingState.calendar_limit, RatingState.set_calendar_limit),
                align="center",
                justify="end",
                width="100%",
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