"""News summaries: story cards, the daily paragraph and the weekly article,
written by a local model from the picked stories' article text.

NEWS_SUMMARIES.md is the governing spec. Code chooses, plans and checks;
the model only turns the facts it is given into sentences.

    model.py    the Ollama client and Qwen's token counter
    prompts.py  every prompt, with PROMPT_VERSION
    checks.py   numbers, tickers, length and advice checks
    stories.py  the picked stories, and how digests' stories join up
    cards.py    one fact card per story (mart.news_story_cards)
    plan.py     the weekly article's sections, by rule
    writing.py  the daily paragraph and the weekly sections and overview
                (mart.news_summaries)
    store.py    warehouse reads and writes, kept apart from the model calls
    run.py      the two model steps the digest jobs run
"""
