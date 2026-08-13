# Model Overview

## Categories

| Category   | Description                                                                                                                      |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------- |
| Valuation  | Is the stock priced correctly relative to its fundamentals? (DCF/comparables vs. current price)                                  |
| Trend      | Is the stock currently moving up or down, and how strongly? (SMA/EMA/ADX)                                                        |
| Momentum   | Is it overbought/oversold — likely to reverse soon? (RSI/STOCH)                                                                  |
| Sentiment  | Does the market/news currently feel good or bad about it? (News sentiment, analyst recs)                                         |
| Volatility | How risky/unstable is it right now? (ATR/BBANDS — this feeds your separate volatility score, not the buy/sell confidence itself) |

## Philosophy

1. **Valuation is king**: If the stock is overvalued, it doesn't matter if it's trending up or has good sentiment — it's still a bad buy. Conversely, if it's undervalued, it may be a good buy even if it's trending down or has bad sentiment.
2. **Trend and momentum are secondary**: These factors can help you time your entry/exit, but they don't override valuation. A stock can be trending down but still be a strong buy if it's undervalued.
3. **Sentiment is tertiary**: Sentiment can help you gauge market psychology, but it doesn't override valuation or trend. A stock can have bad sentiment but still be a strong buy if it's undervalued and trending up.
4. **Volatility is separate**: Volatility is important for risk management, but it doesn't directly affect the buy/sell confidence rating. Instead, it feeds into a separate volatility score that can help inform your position sizing and stop-loss levels.
5. **The moat**: A strong moat (competitive advantage) can make a stock more resilient to market fluctuations and give it a better long-term outlook.

## Initial Model Weighting

| Category     | Weight |
| ------------ | ------ |
| Valuation    | 50%    |
| Trend        | 18%    |
| Sentiment    | 16%    |
| Momentum     | 8%     |
| Moat         | 8%     |

## Valuation Metrics
